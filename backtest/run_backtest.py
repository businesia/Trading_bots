"""
backtest/run_backtest.py
=========================
Единая точка запуска бэктестов.

Использование:
    # Funding Rate (Гипотеза A) — данные уже есть:
    python backtest/run_backtest.py --bot crypto --strategy funding_rate --days 90

    # С кастомными параметрами:
    python backtest/run_backtest.py \\
        --bot crypto --strategy funding_rate --days 180 \\
        --param stop_threshold=0.00003 --param reentry_threshold=0.00006

    # Отчёт в файл:
    python backtest/run_backtest.py --bot crypto --strategy funding_rate \\
        --output backtest/reports/my_run.png
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

# Добавляем корень проекта в путь
sys.path.insert(0, str(Path(__file__).parent.parent))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trading Bots — Backtest Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--bot",
        choices=["crypto", "kalshi"],
        required=True,
        help="Какой бот бэктестить",
    )
    parser.add_argument(
        "--strategy",
        required=True,
        help="Имя стратегии (funding_rate | trend_following | grid | momentum | whale_follow)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Количество дней исторических данных (default: 90)",
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help="Символ для крипто-стратегий (default: BTCUSDT)",
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Переопределить параметр стратегии (можно указывать несколько раз)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Путь для сохранения графика (default: backtest/reports/<strategy>_<date>.png)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=10_000.0,
        help="Начальный капитал в USD (default: 10000)",
    )
    parser.add_argument(
        "--no-plot",
        action="store_true",
        help="Не показывать график, только метрики в консоль",
    )
    return parser.parse_args()


def parse_params(param_list: list[str]) -> dict:
    """Парсит параметры вида KEY=VALUE."""
    params = {}
    for p in param_list:
        if "=" not in p:
            print(f"⚠️  Неверный формат параметра: {p!r} (ожидается KEY=VALUE)")
            continue
        key, value = p.split("=", 1)
        # Пробуем конвертировать в число
        try:
            value = float(value)
        except ValueError:
            pass
        params[key.strip()] = value
    return params


def run_funding_rate(args: argparse.Namespace, params: dict) -> None:
    """Запускает бэктест Funding Rate стратегии через существующий симулятор."""
    from backtest.funding_rate_simulator import run_simulation

    print("=" * 60)
    print("  БЭКТЕСТ: Funding Rate Arbitrage (Гипотеза A)")
    print(f"  Период: {args.days} дней")
    print(f"  Капитал: ${args.capital:,.0f}")
    if params:
        print(f"  Параметры: {params}")
    print("=" * 60)

    # Симулятор имеет свои дефолты, но можно переопределить через params
    output = args.output or f"backtest/reports/funding_rate_{args.days}d.png"
    run_simulation(
        days=args.days,
        initial_capital=args.capital,
        output_path=output,
        show_plot=not args.no_plot,
        **params,
    )


def run_generic(args: argparse.Namespace, params: dict) -> None:
    """
    Заглушка для будущих стратегий.
    При добавлении новой стратегии — реализуй run_<strategy>() выше.
    """
    print(f"⚠️  Бэктест для стратегии '{args.strategy}' ещё не реализован.")
    print()
    print("Чтобы добавить:")
    print(f"  1. Создай функцию run_{args.strategy}() в этом файле")
    print(f"  2. Добавь в STRATEGY_MAP ниже")
    print()
    print("Пример: см. run_funding_rate() выше")
    sys.exit(1)


# Маппинг стратегий → функции запуска
STRATEGY_MAP = {
    "funding_rate": run_funding_rate,
    # Будущие стратегии:
    # "trend_following": run_trend_following,
    # "grid": run_grid,
    # "momentum": run_kalshi_momentum,
    # "whale_follow": run_kalshi_whale_follow,
}


def main() -> None:
    args = parse_args()
    params = parse_params(args.param)

    runner = STRATEGY_MAP.get(args.strategy, run_generic)
    runner(args, params)


if __name__ == "__main__":
    main()
