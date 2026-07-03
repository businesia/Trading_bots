"""
bots/kalshi/main.py
=====================
Точка входа Kalshi Bot.

Запуск:
    python -m bots.kalshi.main

Docker:
    docker-compose --profile kalshi up kalshi-bot
"""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bots.kalshi.connectors.kalshi_rest import KalshiRestConnector
from bots.kalshi.connectors.kalshi_ws import KalshiWebSocketConnector
from bots.kalshi.strategies.momentum import MomentumStrategy
from bots.kalshi.strategies.whale_follow import WhaleFollowStrategy
from core.config import load_bot_config, settings
from core.logging import setup_logging
from core.storage.database import close_db, init_db
from core.telegram.bot import TradingBot


class KalshiBot:
    """
    Kalshi Prediction Markets Bot.

    Оркестрирует коннекторы, стратегии, Telegram и хранилище.
    Данные о позициях и ордерах пишутся в собственную БД (kalshi.db).

    Примечание: Kalshi использует свою систему ордеров и позиций,
    поэтому OrderManager/ExecutionEngine из core/ здесь адаптированы
    через KalshiOrderAdapter (вместо полного переиспользования).
    """

    BOT_NAME = "kalshi"

    def __init__(self) -> None:
        self._rest: KalshiRestConnector | None = None
        self._ws: KalshiWebSocketConnector | None = None
        self._momentum: MomentumStrategy | None = None
        self._whale_follow: WhaleFollowStrategy | None = None
        self._telegram: TradingBot | None = None
        self._is_running = False

        # Список активных рынков (обновляется каждый цикл)
        self._active_tickers: list[str] = []

    async def start(self) -> None:
        """Инициализирует все компоненты и запускает бот."""

        # ── 1. Логирование ─────────────────────────────────────────────────
        setup_logging(level=settings.log_level.value, bot_name=self.BOT_NAME)
        logger.info("=" * 60)
        logger.info("  KALSHI BOT — СТАРТ")
        logger.info(f"  Режим: {'📄 PAPER' if settings.is_paper_trading else '💰 LIVE'}")
        logger.info(f"  Среда: {settings.kalshi_env}")
        logger.info("=" * 60)

        # ── 2. Конфиг ──────────────────────────────────────────────────────
        bot_config = load_bot_config("kalshi")
        strategies_config = bot_config.get("strategies", {})
        markets_config = bot_config.get("markets", {})

        # ── 3. База данных ─────────────────────────────────────────────────
        await init_db(settings.database_url)

        # ── 4. REST коннектор ──────────────────────────────────────────────
        self._rest = KalshiRestConnector(
            api_key=settings.kalshi_api_key,
            private_key_path=settings.kalshi_private_key_path,
            env=settings.kalshi_env,
        )
        await self._rest.__aenter__()

        # Проверяем баланс
        try:
            balance = await self._rest.get_balance()
            logger.info(f"Kalshi баланс: {balance}")
        except Exception as e:
            logger.warning(f"Не удалось получить баланс Kalshi: {e}")

        # ── 5. Загружаем активные рынки ────────────────────────────────────
        self._active_tickers = await self._load_active_markets(markets_config)
        logger.info(f"Загружено {len(self._active_tickers)} рынков")

        # ── 6. Стратегии ───────────────────────────────────────────────────
        momentum_cfg = strategies_config.get("momentum", {})
        if momentum_cfg.get("enabled", True):
            self._momentum = MomentumStrategy(config=momentum_cfg)
            await self._momentum.on_start()

        whale_cfg = strategies_config.get("whale_follow", {})
        if whale_cfg.get("enabled", True):
            self._whale_follow = WhaleFollowStrategy(config=whale_cfg)
            await self._whale_follow.on_start()

        # ── 7. WebSocket ───────────────────────────────────────────────────
        if self._active_tickers:
            self._ws = KalshiWebSocketConnector(rest=self._rest)

            if self._momentum:
                self._ws.subscribe_ticker(
                    tickers=self._active_tickers,
                    callback=self._on_ticker_update,
                )

            if self._whale_follow:
                self._ws.subscribe_trades(
                    tickers=self._active_tickers,
                    callback=self._on_trade_update,
                )

        # ── 8. Telegram ────────────────────────────────────────────────────
        if settings.telegram_bot_token:
            # Для Kalshi используем упрощённый Telegram (без core/ RiskManager)
            self._telegram = _KalshiTelegramAdapter(
                token=settings.telegram_bot_token,
                allowed_chat_id=settings.telegram_allowed_chat_id,
                bot=self,
            )
            await self._telegram.start()

        # ── 9. Обработчики сигналов ОС ────────────────────────────────────
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        self._is_running = True
        logger.info("✅ Kalshi Bot запущен")

        if self._telegram:
            await self._telegram.send_alert(
                f"🟢 <b>Kalshi Bot запущен</b>\n"
                f"Режим: {'📄 Paper' if settings.is_paper_trading else '💰 Live'}\n"
                f"Рынков: {len(self._active_tickers)}"
            )

        # ── 10. Главный цикл ───────────────────────────────────────────────
        await self._run_main_loop()

    async def _run_main_loop(self) -> None:
        """Запускает фоновые задачи."""
        tasks = []

        # WebSocket стрим
        if self._ws:
            tasks.append(asyncio.create_task(
                self._ws.connect(), name="ws_stream"
            ))

        # Периодическое обновление списка рынков (каждый час)
        tasks.append(asyncio.create_task(
            self._market_refresh_loop(), name="market_refresh"
        ))

        logger.info(f"Запущено {len(tasks)} фоновых задач")

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Kalshi Bot: главный цикл отменён")
        finally:
            for task in tasks:
                task.cancel()

    async def _on_ticker_update(self, ticker: str, data: dict) -> None:
        """WebSocket callback: обновление цены/объёма."""
        if not self._is_running or not self._momentum:
            return

        signal = await self._momentum.generate_signal({
            "ticker": ticker,
            **data,
        })
        await self._handle_kalshi_signal(signal)

    async def _on_trade_update(self, ticker: str, data: dict) -> None:
        """WebSocket callback: публичная сделка."""
        if not self._is_running or not self._whale_follow:
            return

        signal = await self._whale_follow.generate_signal({
            "ticker": ticker,
            **data,
        })
        await self._handle_kalshi_signal(signal)

    async def _handle_kalshi_signal(self, signal) -> None:
        """Обрабатывает сигнал от стратегии (paper или live)."""
        from bots.kalshi.strategies.base import KalshiCloseSignal, KalshiSignal

        if signal is None:
            return

        if settings.is_paper_trading:
            logger.info(f"[Paper] Сигнал: {signal}")
            return

        if isinstance(signal, KalshiSignal):
            try:
                result = await self._rest.place_order(
                    ticker=signal.ticker,
                    side=signal.side.value,
                    action=signal.action.value,
                    count=signal.count,
                    yes_price=signal.yes_price,
                )
                logger.info(f"Ордер размещён: {result}")
                if self._telegram:
                    await self._telegram.send_alert(
                        f"✅ <b>Ордер Kalshi</b>\n"
                        f"{signal.ticker} {signal.action.value} {signal.side.value}\n"
                        f"×{signal.count} @ {signal.yes_price}¢\n"
                        f"Стратегия: {signal.strategy}"
                    )
            except Exception as e:
                logger.error(f"Ошибка размещения ордера Kalshi: {e}")

        elif isinstance(signal, KalshiCloseSignal):
            try:
                result = await self._rest.place_order(
                    ticker=signal.ticker,
                    side=signal.side.value,
                    action="sell",
                    count=signal.count,
                    yes_price=signal.current_yes_price,
                )
                logger.info(f"Позиция закрыта: {result}")
                if self._telegram:
                    await self._telegram.send_alert(
                        f"🔴 <b>Закрытие Kalshi</b>\n"
                        f"{signal.ticker}\nПричина: {signal.reason}"
                    )
            except Exception as e:
                logger.error(f"Ошибка закрытия позиции Kalshi: {e}")

    async def _load_active_markets(self, markets_config: dict) -> list[str]:
        """Загружает список активных рынков по конфигу."""
        categories = markets_config.get("categories", ["crypto"])
        min_liquidity = markets_config.get("min_liquidity", 1000.0)
        max_time_hours = markets_config.get("max_time_to_expiry_hours", 72.0)

        try:
            markets = await self._rest.get_open_markets_by_category(
                categories=categories,
                min_liquidity=min_liquidity,
                max_time_to_expiry_hours=max_time_hours,
            )
            return [m["ticker"] for m in markets]
        except Exception as e:
            logger.error(f"Ошибка загрузки рынков: {e}")
            return []

    async def _market_refresh_loop(self) -> None:
        """Обновляет список рынков каждые 60 минут."""
        bot_config = load_bot_config("kalshi")
        markets_config = bot_config.get("markets", {})

        while self._is_running:
            await asyncio.sleep(3600)
            try:
                new_tickers = await self._load_active_markets(markets_config)
                added = set(new_tickers) - set(self._active_tickers)
                removed = set(self._active_tickers) - set(new_tickers)
                if added or removed:
                    logger.info(
                        f"Рынки обновлены: +{len(added)} -{len(removed)}"
                    )
                    self._active_tickers = new_tickers
            except Exception as e:
                logger.error(f"Ошибка обновления рынков: {e}")

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info("Kalshi Bot: получен сигнал остановки...")
        self._is_running = False

        if self._momentum:
            await self._momentum.on_stop()
        if self._whale_follow:
            await self._whale_follow.on_stop()
        if self._ws:
            await self._ws.disconnect()
        if self._telegram:
            await self._telegram.send_alert("🔴 <b>Kalshi Bot остановлен</b>")
            await self._telegram.stop()
        if self._rest:
            await self._rest.__aexit__(None, None, None)

        await close_db()
        logger.info("✅ Kalshi Bot остановлен")


class _KalshiTelegramAdapter:
    """
    Упрощённый Telegram адаптер для Kalshi бота.
    Не использует core/ RiskManager (у Kalshi другая модель рисков).
    """

    def __init__(
        self,
        token: str,
        allowed_chat_id: int,
        bot: KalshiBot,
    ) -> None:
        from telegram.ext import Application, CommandHandler
        self._app = Application.builder().token(token).build()
        self._chat_id = allowed_chat_id
        self._kalshi_bot = bot

        # Команды
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("markets", self._cmd_markets))
        self._app.add_handler(CommandHandler("kill", self._cmd_kill))

    async def start(self) -> None:
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        logger.info("[Kalshi Telegram] Запущен")

    async def stop(self) -> None:
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()

    async def send_alert(self, message: str) -> None:
        try:
            await self._app.bot.send_message(
                chat_id=self._chat_id,
                text=message,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"[Kalshi Telegram] send_alert ошибка: {e}")

    def _is_authorized(self, update) -> bool:
        return update.effective_chat.id == self._chat_id

    async def _cmd_status(self, update, context) -> None:
        if not self._is_authorized(update):
            return
        lines = ["<b>Kalshi Bot — статус</b>"]
        if self._kalshi_bot._momentum:
            st = self._kalshi_bot._momentum.get_status()
            lines.append(f"\nMomentum: {st['open_positions']} позиций")
        if self._kalshi_bot._whale_follow:
            st = self._kalshi_bot._whale_follow.get_status()
            lines.append(f"WhaleFollow: {st['open_positions']} позиций")
        lines.append(f"\nРынков: {len(self._kalshi_bot._active_tickers)}")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def _cmd_markets(self, update, context) -> None:
        if not self._is_authorized(update):
            return
        tickers = self._kalshi_bot._active_tickers[:10]
        text = "<b>Активные рынки (топ-10):</b>\n" + "\n".join(tickers)
        await update.message.reply_text(text, parse_mode="HTML")

    async def _cmd_kill(self, update, context) -> None:
        if not self._is_authorized(update):
            return
        args = context.args or []
        if "confirm" not in args:
            await update.message.reply_text("⚠️ /kill confirm — для подтверждения")
            return
        await update.message.reply_text("🛑 Останавливаем Kalshi Bot...")
        await self._kalshi_bot.stop()


# ── Точка входа ───────────────────────────────────────────────────────────

async def main() -> None:
    bot = KalshiBot()
    try:
        await bot.start()
    except KeyboardInterrupt:
        await bot.stop()
    except Exception as e:
        logger.critical(f"Критическая ошибка Kalshi Bot: {e}", exc_info=True)
        await bot.stop()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
