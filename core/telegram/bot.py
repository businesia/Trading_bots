"""
core/telegram/bot.py
=====================
Telegram-бот для управления и мониторинга.
Авторизация по chat_id — только ваш аккаунт получает команды.

Команды:
  /status  — P&L, позиции, состояние риск-менеджера
  /pause   — временно остановить торговлю
  /resume  — возобновить торговлю
  /kill    — экстренная остановка (требует рестарта)
  /report  — дневной отчёт
  /help    — список команд
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

if TYPE_CHECKING:
    from core.engine.execution_engine import ExecutionEngine
    from core.engine.position_tracker import PositionTracker
    from core.engine.risk_manager import RiskManager


class TradingBot:
    """
    Telegram-бот для управления ботами.

    Использование:
        tg_bot = TradingBot(
            token=settings.telegram_bot_token,
            allowed_chat_id=settings.telegram_allowed_chat_id,
            bots={"crypto": (risk_mgr, pos_tracker, exec_engine)},
        )
        await tg_bot.start()
    """

    def __init__(
        self,
        token: str,
        allowed_chat_id: int,
        bots: dict[str, tuple["RiskManager", "PositionTracker", "ExecutionEngine"]],
    ) -> None:
        self._token = token
        self._allowed_chat_id = allowed_chat_id
        self._bots = bots
        self._app: Application | None = None

    async def start(self) -> None:
        """Запускает Telegram-бота (неблокирующий polling)."""
        if not self._token:
            logger.warning("TELEGRAM_BOT_TOKEN не задан — Telegram-бот отключён")
            return

        self._app = Application.builder().token(self._token).build()

        # Регистрируем хендлеры
        handlers = [
            CommandHandler("start",  self._cmd_help),
            CommandHandler("help",   self._cmd_help),
            CommandHandler("status", self._cmd_status),
            CommandHandler("pause",  self._cmd_pause),
            CommandHandler("resume", self._cmd_resume),
            CommandHandler("kill",   self._cmd_kill),
            CommandHandler("report", self._cmd_report),
        ]
        for h in handlers:
            self._app.add_handler(h)

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

        logger.info("Telegram-бот запущен")

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            logger.info("Telegram-бот остановлен")

    async def send_alert(self, message: str, parse_mode: str = ParseMode.HTML) -> None:
        """Отправляет уведомление без команды пользователя."""
        if self._app and self._allowed_chat_id:
            try:
                await self._app.bot.send_message(
                    chat_id=self._allowed_chat_id,
                    text=message,
                    parse_mode=parse_mode,
                )
            except Exception as e:
                logger.error(f"Ошибка отправки Telegram алёрта: {e}")

    # ── Авторизация ────────────────────────────────────────────────────────

    def _is_authorized(self, update: Update) -> bool:
        if update.effective_chat is None:
            return False
        authorized = update.effective_chat.id == self._allowed_chat_id
        if not authorized:
            logger.warning(
                f"Неавторизованный доступ с chat_id={update.effective_chat.id}"
            )
        return authorized

    # ── Команды ───────────────────────────────────────────────────────────

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return
        text = (
            "🤖 <b>Trading Bot Commands</b>\n\n"
            "/status — текущий P&L и позиции\n"
            "/pause — приостановить торговлю\n"
            "/resume — возобновить торговлю\n"
            "/kill — 🚨 экстренная остановка (нужен рестарт для отмены)\n"
            "/report — дневной отчёт\n"
            "/help — это сообщение"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return

        lines = ["📊 <b>Статус ботов</b>\n"]

        for bot_name, (risk, tracker, _) in self._bots.items():
            risk_status = risk.get_status()
            pos_summary = await tracker.get_summary()

            trading_icon = "✅" if risk_status["trading_allowed"] else "🔴"
            mode_icon = "📄" if risk_status.get("is_paper", True) else "💰"

            lines.append(f"{trading_icon} <b>{bot_name.upper()}</b> {mode_icon}")
            lines.append(
                f"  Капитал: ${risk_status['capital']:,.2f}\n"
                f"  Дн. P&L: {risk_status['daily_pnl_pct']:+.2f}% "
                f"(${risk_status['daily_pnl']:+.2f})\n"
                f"  Позиций: {pos_summary['open_positions']}\n"
                f"  Unrealized: ${pos_summary['total_unrealized_pnl']:+.2f}\n"
                f"  Exposure: ${pos_summary['total_exposure_usd']:,.0f}"
            )

            if risk_status["kill_switch"]:
                lines.append("  🚨 KILL-SWITCH АКТИВЕН")
            elif risk_status["paused"]:
                lines.append("  ⏸️ На паузе")
            elif risk_status["circuit_breaker"]:
                lines.append("  🔴 Circuit breaker сработал")

            lines.append("")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def _cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return

        for bot_name, (risk, _, _) in self._bots.items():
            await risk.pause_trading(reason="Ручная пауза через Telegram")

        await update.message.reply_text(
            "⏸️ Торговля остановлена на всех ботах.\n"
            "Используй /resume для возобновления."
        )

    async def _cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return

        messages = []
        for bot_name, (risk, _, _) in self._bots.items():
            if risk._kill_switch:
                messages.append(f"❌ {bot_name}: kill-switch активен, нужен рестарт")
            else:
                await risk.resume_trading()
                messages.append(f"▶️ {bot_name}: торговля возобновлена")

        await update.message.reply_text("\n".join(messages))

    async def _cmd_kill(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return

        # Двойное подтверждение в аргументах
        args = context.args or []
        if "confirm" not in args:
            await update.message.reply_text(
                "⚠️ <b>ВНИМАНИЕ!</b> Это остановит ВСЕ боты.\n\n"
                "Для подтверждения: /kill confirm",
                parse_mode=ParseMode.HTML,
            )
            return

        for bot_name, (risk, _, _) in self._bots.items():
            await risk.activate_kill_switch(reason="Kill-switch через Telegram")

        await update.message.reply_text(
            "🚨 <b>KILL-SWITCH АКТИВИРОВАН</b>\n\n"
            "Все боты остановлены.\n"
            "Для возобновления необходим рестарт сервиса.",
            parse_mode=ParseMode.HTML,
        )

    async def _cmd_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return

        lines = ["📈 <b>Дневной отчёт</b>\n"]

        for bot_name, (risk, tracker, _) in self._bots.items():
            risk_status = risk.get_status()
            pos_summary = await tracker.get_summary()

            lines.append(f"<b>{bot_name.upper()}</b>")
            lines.append(f"  Капитал: ${risk_status['capital']:,.2f}")
            lines.append(f"  Дн. P&L: {risk_status['daily_pnl_pct']:+.2f}%")
            lines.append(f"  Лимит убытка: {risk_status['daily_loss_limit_pct']}%")
            lines.append(f"  Открытых позиций: {pos_summary['open_positions']}")

            positions = pos_summary.get("positions", [])
            if positions:
                lines.append("  Позиции:")
                for p in positions:
                    lines.append(
                        f"    {p['symbol']} {p['side']} "
                        f"@ ${p['entry_price']:,.2f} → "
                        f"${p.get('current_price', 0):,.2f} "
                        f"PnL: ${p['unrealized_pnl']:+.2f}"
                    )
            lines.append("")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
