"""
bots/crypto_futures/main.py
============================
Точка входа Crypto Futures Bot.

Запуск:
    python -m bots.crypto_futures.main

Docker:
    docker-compose up crypto-bot
"""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

from loguru import logger

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bots.crypto_futures.connectors.bybit import BybitFuturesConnector
from bots.crypto_futures.strategies.funding_rate import FundingRateStrategy
from core.api.routes import init_api, router
from core.config import load_bot_config, settings
from core.engine.execution_engine import ExecutionEngine
from core.engine.order_manager import OrderManager
from core.engine.position_tracker import PositionTracker
from core.engine.risk_manager import RiskConfig, RiskManager
from core.logging import setup_logging
from core.storage.database import close_db, init_db
from core.storage.models import BotType
from core.telegram.bot import TradingBot


class CryptoFuturesBot:
    """
    Crypto Futures Bot — главный класс оркестрации.

    Поднимает все компоненты, соединяет их между собой,
    запускает стратегии и обрабатывает сигналы остановки.
    """

    BOT_NAME = "crypto_futures"

    def __init__(self) -> None:
        # Компоненты инициализируются в start()
        self._connector: BybitFuturesConnector | None = None
        self._risk_manager: RiskManager | None = None
        self._order_manager: OrderManager | None = None
        self._position_tracker: PositionTracker | None = None
        self._execution_engine: ExecutionEngine | None = None
        self._funding_rate_strategy: FundingRateStrategy | None = None
        self._telegram: TradingBot | None = None
        self._is_running = False

    async def start(self) -> None:
        """Инициализирует все компоненты и запускает бот."""

        # ── 1. Логирование ─────────────────────────────────────────────────
        setup_logging(
            level=settings.log_level.value,
            bot_name=self.BOT_NAME,
        )
        logger.info("=" * 60)
        logger.info("  CRYPTO FUTURES BOT — СТАРТ")
        logger.info(f"  Режим: {'📄 PAPER TRADING' if settings.is_paper_trading else '💰 LIVE TRADING'}")
        logger.info(f"  Bybit: {'testnet' if settings.bybit_testnet else 'mainnet'}")
        logger.info("=" * 60)

        # ── 2. Конфиг стратегий ────────────────────────────────────────────
        bot_config = load_bot_config("crypto")
        risk_cfg_dict = bot_config.get("risk", {})
        risk_config = RiskConfig(
            daily_loss_limit_pct=risk_cfg_dict.get("daily_loss_limit_pct", 5.0),
            max_position_size_pct=risk_cfg_dict.get("max_position_size_pct", 10.0),
            max_total_exposure_pct=risk_cfg_dict.get("max_total_exposure_pct", 30.0),
            max_leverage=risk_cfg_dict.get("max_leverage", 2.0),
        )

        # ── 3. База данных ─────────────────────────────────────────────────
        await init_db(settings.database_url)

        # ── 4. Bybit коннектор ───────────────────────────────────────────
        self._connector = BybitFuturesConnector(
            api_key=settings.bybit_api_key,
            api_secret=settings.bybit_api_secret,
            testnet=settings.bybit_testnet,
        )
        await self._connector.__aenter__()

        # Получаем стартовый капитал (только в live режиме)
        if not settings.is_paper_trading:
            try:
                balances = await self._connector.get_balance()
                capital = balances.get("USDT", 10_000.0)
                logger.info(f"Баланс Bybit: USDT={capital:,.2f}")
            except Exception as e:
                logger.warning(f"Не удалось получить баланс: {e}. Используем дефолтный $10,000")
                capital = 10_000.0
        else:
            capital = 10_000.0
            logger.info(f"Paper trading режим: используем дефолтный капитал ${capital:,.0f}")

        # ── 5. Риск-менеджер ───────────────────────────────────────────────
        self._risk_manager = RiskManager(
            bot=BotType.CRYPTO_FUTURES,
            config=risk_config,
            capital=capital,
        )
        await self._risk_manager.initialize()

        # ── 6. Order manager ───────────────────────────────────────────────
        self._order_manager = OrderManager(
            bot=BotType.CRYPTO_FUTURES,
            connector=self._connector if not settings.is_paper_trading else None,
            is_paper=settings.is_paper_trading,
        )

        # ── 7. Position tracker ────────────────────────────────────────────
        self._position_tracker = PositionTracker(
            bot=BotType.CRYPTO_FUTURES,
            provider=self._connector if not settings.is_paper_trading else None,
        )
        # Сверяем позиции с биржей при рестарте
        await self._position_tracker.reconcile_with_exchange()

        # ── 8. Execution engine ────────────────────────────────────────────
        self._execution_engine = ExecutionEngine(
            risk_manager=self._risk_manager,
            order_manager=self._order_manager,
            position_tracker=self._position_tracker,
        )

        # ── 9. Стратегии ───────────────────────────────────────────────────
        funding_cfg = bot_config.get("strategies", {}).get("funding_rate", {})
        if funding_cfg.get("enabled", True):
            self._funding_rate_strategy = FundingRateStrategy(
                config=funding_cfg,
                engine=self._execution_engine,
                position_tracker=self._position_tracker,
            )
            self._funding_rate_strategy.update_capital(capital)
            await self._funding_rate_strategy.on_start()

        # ── 10. Telegram ───────────────────────────────────────────────────
        if settings.telegram_bot_token:
            self._telegram = TradingBot(
                token=settings.telegram_bot_token,
                allowed_chat_id=settings.telegram_allowed_chat_id,
                bots={
                    self.BOT_NAME: (
                        self._risk_manager,
                        self._position_tracker,
                        self._execution_engine,
                    )
                },
            )
            await self._telegram.start()

        # ── 11. Обработчики сигналов ОС ────────────────────────────────────
        # На Windows add_signal_handler не поддерживается, используем try/except
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))
        except NotImplementedError:
            # Windows — сигналы обрабатываются через KeyboardInterrupt
            pass

        self._is_running = True
        logger.info("✅ Crypto Futures Bot запущен")

        if self._telegram:
            await self._telegram.send_alert(
                "🟢 <b>Crypto Futures Bot запущен</b>\n"
                f"Режим: {'📄 Paper' if settings.is_paper_trading else '💰 Live'}\n"
                f"Капитал: ${capital:,.0f}"
            )

        # ── 12. Главный цикл ───────────────────────────────────────────────
        await self._run_main_loop()

    async def _run_main_loop(self) -> None:
        """
        Главный цикл бота.
        Запускает WebSocket стрим + задачи мониторинга.
        """
        tasks = []

        # Фоновая очередь ордеров
        tasks.append(asyncio.create_task(
            self._execution_engine.start_queue_processor(),
            name="order_queue",
        ))

        # WebSocket стрим цен (если стратегия активна)
        if self._funding_rate_strategy:
            symbols = self._funding_rate_strategy._symbols
            tasks.append(asyncio.create_task(
                self._connector.stream_mark_prices(
                    symbols=symbols,
                    callback=self._on_price_update,
                ),
                name="ws_stream",
            ))

        # Мониторинг funding rate каждые 8 часов (как резерв если WS отвалился)
        tasks.append(asyncio.create_task(
            self._funding_rate_poller(),
            name="funding_poller",
        ))

        # Обновление unrealized PnL каждые 60 секунд
        tasks.append(asyncio.create_task(
            self._pnl_updater(),
            name="pnl_updater",
        ))

        logger.info(f"Запущено {len(tasks)} фоновых задач")

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Главный цикл отменён — завершаем")
        except Exception as e:
            logger.error(f"Ошибка в главном цикле: {e}", exc_info=True)
            raise
        finally:
            for task in tasks:
                task.cancel()

    async def _on_price_update(
        self,
        symbol: str,
        mark_price: float,
        funding_rate: float,
    ) -> None:
        """WebSocket callback — новая цена и funding rate."""
        if not self._is_running:
            return

        # Обновляем позиции в трекере
        await self._position_tracker.update_prices({symbol: mark_price})

        # Передаём в стратегию
        if self._funding_rate_strategy and self._funding_rate_strategy.is_active:
            signal = await self._funding_rate_strategy.generate_signal({
                "symbol": symbol,
                "rate": funding_rate,
                "mark_price": mark_price,
            })
            await self._handle_signal(signal)

    async def _handle_signal(self, signal) -> None:
        """Обрабатывает сигнал от стратегии."""
        from bots.crypto_futures.strategies.base import CloseSignal, Signal

        if signal is None:
            return

        if isinstance(signal, Signal):
            from core.engine.execution_engine import OrderRequest
            request = OrderRequest(
                symbol=signal.symbol,
                side=signal.direction,
                quantity=signal.suggested_quantity,
                strategy=signal.strategy,
                price=signal.suggested_price,
                size_usd=(signal.suggested_quantity * (signal.suggested_price or 0)),
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                notes=signal.notes,
            )
            result = await self._execution_engine.execute(request)
            if result.success and result.trade:
                self._funding_rate_strategy.on_position_opened(
                    symbol=signal.symbol,
                    position_id=result.trade.id,
                    entry_price=result.trade.fill_price or (signal.suggested_price or 0),
                )
                if self._telegram:
                    await self._telegram.send_alert(
                        f"✅ <b>Позиция открыта</b>\n"
                        f"{signal.symbol} LONG\n"
                        f"Цена: ${signal.suggested_price:,.2f}\n"
                        f"Количество: {signal.suggested_quantity}\n"
                        f"Funding APR: {signal.notes}"
                    )
            elif not result.success:
                logger.warning(f"Сигнал не исполнен: {result.reason}")

        elif isinstance(signal, CloseSignal):
            result = await self._execution_engine.close_position(
                position_id=signal.position_id,
                symbol=signal.symbol,
                side=signal.side,
                quantity=signal.quantity,
                strategy=signal.strategy,
                current_price=signal.current_price,
            )
            if result.success:
                self._funding_rate_strategy.on_position_closed(signal.symbol)
                if self._telegram:
                    await self._telegram.send_alert(
                        f"🔴 <b>Позиция закрыта</b>\n"
                        f"{signal.symbol}\n"
                        f"Причина: {signal.reason}"
                    )

    async def _funding_rate_poller(self) -> None:
        """
        Опрашивает funding rate каждые 8 часов как резерв.
        Основной источник данных — WebSocket.
        """
        POLL_INTERVAL = 8 * 3600  # 8 часов

        while self._is_running:
            try:
                if self._funding_rate_strategy:
                    for symbol in self._funding_rate_strategy._symbols:
                        data = await self._connector.get_funding_rate(symbol)
                        logger.info(
                            f"[Poller] {symbol} rate={data['rate_pct']:.4f}%/8h "
                            f"APR={data['apr']:.2f}% | next={data['next_funding_time']}"
                        )
                        # Генерируем сигнал через стратегию
                        signal = await self._funding_rate_strategy.generate_signal({
                            "symbol": symbol,
                            "rate": data["rate"],
                            "mark_price": data["mark_price"],
                        })
                        await self._handle_signal(signal)
            except Exception as e:
                logger.error(f"Ошибка в funding poller: {e}")

            await asyncio.sleep(POLL_INTERVAL)

    async def _pnl_updater(self) -> None:
        """Обновляет unrealized PnL в риск-менеджере каждые 60 секунд."""
        while self._is_running:
            try:
                summary = await self._position_tracker.get_summary()
                await self._risk_manager.update_open_pnl(summary["total_unrealized_pnl"])
            except Exception as e:
                logger.error(f"Ошибка в pnl updater: {e}")
            await asyncio.sleep(60)

    async def stop(self) -> None:
        """Graceful shutdown всех компонентов."""
        logger.info("Получен сигнал остановки...")
        self._is_running = False

        if self._funding_rate_strategy:
            await self._funding_rate_strategy.on_stop()

        if self._execution_engine:
            await self._execution_engine.stop()

        if self._telegram:
            await self._telegram.send_alert("🔴 <b>Crypto Futures Bot остановлен</b>")
            await self._telegram.stop()

        if self._connector:
            await self._connector.__aexit__(None, None, None)

        await close_db()
        logger.info("✅ Crypto Futures Bot остановлен")


# ── Точка входа ───────────────────────────────────────────────────────────

async def main() -> None:
    bot = CryptoFuturesBot()
    try:
        await bot.start()
    except KeyboardInterrupt:
        await bot.stop()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nException type: {type(e).__name__}")
        print(f"Exception args: {e.args}")
        print(f"Exception str: {str(e)}")
        logger.critical(f"Критическая ошибка: {e}", exc_info=True)
        await bot.stop()
        sys.exit(1)


if __name__ == "__main__":
    import traceback
    try:
        asyncio.run(main())
    except Exception as e:
        traceback.print_exc()
        print(f"\nException type: {type(e).__name__}")
        print(f"Exception args: {e.args}")
        print(f"Exception str: {str(e)}")
        sys.exit(1)
