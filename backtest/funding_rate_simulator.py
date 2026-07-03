"""
Funding Rate Arbitrage Simulator
=================================
Гипотеза A: Delta-neutral позиция (Spot Long + Perp Short)
стабильно собирает Funding Rate без зависимости от цены BTC.

Данные: Binance Futures API (бесплатно, без ключей)
Запуск: python funding_rate_simulator.py
"""

import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from datetime import datetime, timezone
import time
import sys

# ── Настройки стратегии ────────────────────────────────────────────────────
CONFIG = {
    "symbol":            "BTCUSDT",       # торговая пара
    "capital":           10_000,          # стартовый капитал ($)
    "fee_entry":         0.0004,          # комиссия на вход (0.04% taker × 2 ноги)
    "fee_exit":          0.0004,          # комиссия на выход
    "stop_threshold":    0.00002,         # 0.002%/8h: оптимум из sensitivity analysis
                                          # (было 0.0003=0.03% — слишком жёстко, 13% активности)
    "stop_consec":       3,               # сколько подряд плохих периодов до выхода
    "reentry_threshold": 0.00005,         # 0.005%/8h: порог для повторного входа
    "reentry_consec":    3,               # сколько подряд хороших периодов до входа
    "history_days":      1460,            # сколько дней истории (4 года)
}

BINANCE_URL = "https://fapi.binance.com/fapi/v1/fundingRate"


# ── 1. ЗАГРУЗКА ДАННЫХ ─────────────────────────────────────────────────────
def fetch_funding_rates(symbol: str, days: int) -> pd.DataFrame:
    """
    Загружаем исторические funding rates с Binance.
    Один запрос = 1000 записей (каждые 8h → ~333 дня).
    Пагинируем чтобы получить полную историю.
    """
    print(f"📡 Загружаю funding rates для {symbol}...")
    all_records = []
    end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_time = end_time - days * 24 * 60 * 60 * 1000

    current_end = end_time
    while True:
        params = {
            "symbol": symbol,
            "limit":  1000,
            "endTime": current_end,
        }
        try:
            resp = requests.get(BINANCE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"⚠️  Ошибка API: {e}. Использую синтетические данные.")
            return generate_synthetic_data(days)

        if not data:
            break

        all_records.extend(data)
        oldest = data[0]["fundingTime"]

        if oldest <= start_time or len(data) < 1000:
            break

        current_end = oldest - 1
        time.sleep(0.3)  # rate limit

    if not all_records:
        print("⚠️  Нет данных от API. Использую синтетические данные.")
        return generate_synthetic_data(days)

    df = pd.DataFrame(all_records)
    df["time"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df["rate"] = df["fundingRate"].astype(float)
    df = df[["time", "rate"]].sort_values("time").reset_index(drop=True)
    df = df[df["time"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)]

    print(f"✅ Загружено {len(df)} записей ({df['time'].min().date()} → {df['time'].max().date()})")
    return df


def generate_synthetic_data(days: int) -> pd.DataFrame:
    """
    Синтетические данные с реалистичными режимами рынка
    на случай если Binance API недоступен.
    """
    print("🔄 Генерирую реалистичные синтетические данные...")
    np.random.seed(42)
    periods = days * 3  # 3 периода в день (каждые 8h)
    dates = pd.date_range(
        end=pd.Timestamp.now(tz="UTC"),
        periods=periods,
        freq="8h"
    )
    # Имитируем разные рыночные режимы
    rates = []
    regime_lengths = [300, 250, 400, 200, 310]  # периоды в каждом режиме
    regime_means  = [0.040, -0.005, 0.010, -0.003, 0.035]  # % средние
    regime_stds   = [0.020,  0.010, 0.008,  0.006, 0.018]  # волатильность

    for mean, std, length in zip(regime_means, regime_stds, regime_lengths):
        segment = np.random.normal(mean / 100, std / 100, length)
        rates.extend(segment.tolist())

    rates = rates[:periods]
    return pd.DataFrame({"time": dates[:len(rates)], "rate": rates})


# ── 2. СИМУЛЯТОР СТРАТЕГИИ ─────────────────────────────────────────────────
def simulate(df: pd.DataFrame, cfg: dict, use_stop: bool = True) -> pd.DataFrame:
    """
    Симулирует стратегию Funding Rate Arbitrage.

    Логика:
    - В позиции: собираем funding каждые 8h
    - Правило стопа: если rate < stop_threshold N раз подряд → выходим
    - Правило реентри: если rate > reentry_threshold M раз подряд → входим снова
    """
    capital = cfg["capital"]
    fee_e   = cfg["fee_entry"]
    fee_x   = cfg["fee_exit"]
    thresh  = cfg["stop_threshold"]
    re_thr  = cfg["reentry_threshold"]
    n_stop  = cfg["stop_consec"]
    n_re    = cfg["reentry_consec"]

    in_position  = False
    consec_bad   = 0
    consec_good  = 0
    pnl_history  = []
    status_log   = []

    for _, row in df.iterrows():
        rate = row["rate"]
        period_pnl = 0.0
        action = "hold"

        if not in_position:
            # Проверяем условие для входа
            if rate >= re_thr or not use_stop:
                consec_good += 1
                if consec_good >= n_re or not use_stop:
                    # ВХОД: платим двойную комиссию (спот + фьючерс)
                    period_pnl  = -fee_e * capital
                    capital    += period_pnl
                    in_position = True
                    consec_good = 0
                    consec_bad  = 0
                    action = "enter"
            else:
                consec_good = 0

        else:
            # В позиции: собираем funding
            period_pnl  = rate * capital
            capital    += period_pnl

            if use_stop:
                # Проверяем условие стопа
                if rate < thresh:
                    consec_bad += 1
                    if consec_bad >= n_stop:
                        # ВЫХОД: платим комиссию выхода
                        exit_cost   = -fee_x * capital
                        capital    += exit_cost
                        period_pnl += exit_cost
                        in_position = False
                        consec_bad  = 0
                        action = "exit"
                else:
                    consec_bad = 0

        pnl_history.append({
            "time":        row["time"],
            "rate":        rate * 100,           # в процентах
            "rate_8h_pct": rate * 100,
            "capital":     capital,
            "period_pnl":  period_pnl,
            "in_position": in_position,
            "action":      action,
            "apr_equiv":   rate * 3 * 365 * 100, # аннуализированный эквивалент
        })

    return pd.DataFrame(pnl_history)


# ── 3. МЕТРИКИ ─────────────────────────────────────────────────────────────
def compute_metrics(result: pd.DataFrame, cfg: dict) -> dict:
    cap_series  = result["capital"]
    initial     = cfg["capital"]
    final       = cap_series.iloc[-1]
    total_ret   = (final - initial) / initial * 100

    # Аннуализированная доходность
    n_years = len(result) / (3 * 365)
    annual_ret = ((final / initial) ** (1 / max(n_years, 0.01)) - 1) * 100

    # Max Drawdown
    rolling_max = cap_series.cummax()
    drawdown    = (cap_series - rolling_max) / rolling_max * 100
    max_dd      = drawdown.min()

    # Sharpe (дневная доходность × √365 / std)
    daily_ret = cap_series.pct_change().dropna()
    sharpe    = (daily_ret.mean() / daily_ret.std() * np.sqrt(365)
                 if daily_ret.std() > 0 else 0)

    # % времени в позиции
    pct_active = result["in_position"].mean() * 100

    # Avg funding rate когда в позиции
    in_pos = result[result["in_position"]]
    avg_rate_active = in_pos["rate_8h_pct"].mean() if len(in_pos) > 0 else 0

    # Кол-во входов/выходов
    n_entries = (result["action"] == "enter").sum()
    n_exits   = (result["action"] == "exit").sum()

    return {
        "Начальный капитал":     f"${initial:,.0f}",
        "Конечный капитал":      f"${final:,.2f}",
        "Общая доходность":      f"{total_ret:+.2f}%",
        "Годовая доходность":    f"{annual_ret:+.2f}%",
        "Sharpe Ratio":          f"{sharpe:.2f}",
        "Max Drawdown":          f"{max_dd:.2f}%",
        "% времени в позиции":   f"{pct_active:.1f}%",
        "Ср. Funding (в позиции)": f"{avg_rate_active:.4f}%/8h",
        "Входов / Выходов":      f"{n_entries} / {n_exits}",
    }


# ── 4. ТЕКУЩИЙ FUNDING RATE ────────────────────────────────────────────────
def get_current_rate(symbol: str) -> dict | None:
    try:
        url  = "https://fapi.binance.com/fapi/v1/premiumIndex"
        resp = requests.get(url, params={"symbol": symbol}, timeout=10)
        data = resp.json()
        rate = float(data.get("lastFundingRate", 0))
        next_funding = data.get("nextFundingTime", 0)
        next_dt = datetime.fromtimestamp(next_funding / 1000, tz=timezone.utc)
        return {
            "rate":     rate,
            "rate_pct": rate * 100,
            "apr":      rate * 3 * 365 * 100,
            "next":     next_dt.strftime("%H:%M UTC"),
        }
    except Exception:
        return None


# ── 5. ВИЗУАЛИЗАЦИЯ ────────────────────────────────────────────────────────
def plot_results(df_raw: pd.DataFrame, res_stop: pd.DataFrame,
                 res_no_stop: pd.DataFrame, cfg: dict):

    fig = plt.figure(figsize=(16, 12), facecolor="#0a0e1a")
    fig.suptitle(
        f"Funding Rate Arbitrage — {cfg['symbol']} | "
        f"Капитал: ${cfg['capital']:,} | "
        f"Стоп: {cfg['stop_threshold']*100:.3f}%/8h",
        color="#e2e8f0", fontsize=14, fontweight="bold", y=0.98
    )

    gs   = gridspec.GridSpec(3, 2, figure=fig, hspace=0.4, wspace=0.3)
    ax1  = fig.add_subplot(gs[0, :])   # Funding rate история
    ax2  = fig.add_subplot(gs[1, :])   # P&L сравнение
    ax3  = fig.add_subplot(gs[2, 0])   # Распределение ставок
    ax4  = fig.add_subplot(gs[2, 1])   # Месячная доходность

    colors = {
        "green":   "#00d4aa",
        "red":     "#ff4757",
        "blue":    "#3b82f6",
        "yellow":  "#f59e0b",
        "bg":      "#111827",
        "grid":    "#1e2d4a",
        "text":    "#64748b",
    }

    style = dict(facecolor=colors["bg"], edgecolor=colors["grid"])
    for ax in [ax1, ax2, ax3, ax4]:
        ax.set_facecolor(colors["bg"])
        ax.tick_params(colors=colors["text"], labelsize=9)
        ax.spines[:].set_color(colors["grid"])
        for spine in ax.spines.values():
            spine.set_alpha(0.5)

    # ── График 1: Funding Rate ──
    ax1.set_title("Funding Rate per 8h (%)", color="#e2e8f0", fontsize=11, pad=8)
    rate_pct = df_raw["rate"] * 100
    ax1.fill_between(df_raw["time"], rate_pct, 0,
                     where=rate_pct >= 0, alpha=0.4, color=colors["green"], label="Положительный")
    ax1.fill_between(df_raw["time"], rate_pct, 0,
                     where=rate_pct < 0,  alpha=0.4, color=colors["red"],   label="Отрицательный")
    ax1.plot(df_raw["time"], rate_pct, linewidth=0.7, color=colors["green"], alpha=0.8)
    ax1.axhline(cfg["stop_threshold"] * 100, color=colors["yellow"],
                linestyle="--", linewidth=1.2, label=f"Порог стопа ({cfg['stop_threshold']*100:.3f}%)")
    ax1.axhline(0, color=colors["grid"], linewidth=0.8, alpha=0.7)
    ax1.legend(facecolor=colors["bg"], edgecolor=colors["grid"],
               labelcolor="#e2e8f0", fontsize=8, loc="upper right")
    ax1.set_ylabel("%", color=colors["text"], fontsize=9)

    # ── График 2: P&L сравнение ──
    ax2.set_title("Рост капитала: со стопом vs без стопа", color="#e2e8f0", fontsize=11, pad=8)

    ax2.plot(res_stop["time"],    res_stop["capital"],    linewidth=1.8,
             color=colors["green"], label="Со стопом (наша стратегия)")
    ax2.plot(res_no_stop["time"], res_no_stop["capital"], linewidth=1.4,
             color=colors["red"], linestyle="--", alpha=0.8, label="Без стопа (hold всегда)")
    ax2.axhline(cfg["capital"], color=colors["grid"], linewidth=0.8, linestyle=":", alpha=0.7)

    # Закрашиваем периоды не в позиции
    in_pos = res_stop["in_position"].astype(float)
    ax2.fill_between(res_stop["time"], res_stop["capital"].min(), res_stop["capital"].max(),
                     where=~res_stop["in_position"],
                     alpha=0.07, color=colors["red"], label="Вне позиции")

    ax2.legend(facecolor=colors["bg"], edgecolor=colors["grid"],
               labelcolor="#e2e8f0", fontsize=9)
    ax2.set_ylabel("Капитал ($)", color=colors["text"], fontsize=9)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))

    # ── График 3: Распределение ставок ──
    ax3.set_title("Распределение Funding Rate", color="#e2e8f0", fontsize=11, pad=8)
    rates = df_raw["rate"] * 100
    positive = rates[rates >= 0]
    negative = rates[rates < 0]

    ax3.hist(positive, bins=50, color=colors["green"], alpha=0.7,
             label=f"Позит. ({len(positive)/len(rates)*100:.0f}%)")
    ax3.hist(negative, bins=30, color=colors["red"],   alpha=0.7,
             label=f"Негат. ({len(negative)/len(rates)*100:.0f}%)")
    ax3.axvline(cfg["stop_threshold"] * 100, color=colors["yellow"],
                linestyle="--", linewidth=1.5, label="Порог стопа")
    ax3.axvline(rates.mean(), color=colors["blue"],
                linestyle="-", linewidth=1.2, label=f"Среднее: {rates.mean():.4f}%")
    ax3.legend(facecolor=colors["bg"], edgecolor=colors["grid"],
               labelcolor="#e2e8f0", fontsize=8)
    ax3.set_xlabel("%/8h", color=colors["text"], fontsize=9)
    ax3.set_ylabel("Кол-во периодов", color=colors["text"], fontsize=9)

    # ── График 4: Месячная доходность ──
    ax4.set_title("Месячная доходность (со стопом)", color="#e2e8f0", fontsize=11, pad=8)
    monthly = (res_stop.set_index("time")["capital"]
               .resample("ME").last()
               .pct_change()
               .dropna() * 100)

    bar_colors = [colors["green"] if v >= 0 else colors["red"] for v in monthly.values]
    ax4.bar(range(len(monthly)), monthly.values, color=bar_colors, alpha=0.85, width=0.7)
    ax4.axhline(0, color=colors["grid"], linewidth=0.8)
    ax4.set_xticks(range(len(monthly)))
    ax4.set_xticklabels(
        [d.strftime("%b%y") for d in monthly.index],
        rotation=45, ha="right", fontsize=7
    )
    ax4.set_ylabel("%", color=colors["text"], fontsize=9)

    plt.savefig("funding_rate_results.png", dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    print("📊 График сохранён: funding_rate_results.png")
    plt.show()


# ── 6. ГЛАВНАЯ ФУНКЦИЯ ─────────────────────────────────────────────────────
def main():
    print("\n" + "="*60)
    print("  FUNDING RATE ARBITRAGE SIMULATOR")
    print("  Гипотеза A: Delta-Neutral Крипто-Стратегия")
    print("="*60)

    # Проверяем текущий funding rate
    print("\n📡 Текущий Funding Rate...")
    current = get_current_rate(CONFIG["symbol"])
    if current:
        status = "✅ ВХОДИМ" if current["rate"] >= CONFIG["reentry_threshold"] else "⏸️  ЖДЁМ"
        print(f"   Rate:       {current['rate_pct']:+.4f}%/8h")
        print(f"   APR equiv:  {current['apr']:+.2f}% годовых")
        print(f"   Следующий:  {current['next']}")
        print(f"   Статус:     {status}")
    else:
        print("   ⚠️  Не удалось получить текущую ставку")

    # Загружаем историю
    print()
    df_raw = fetch_funding_rates(CONFIG["symbol"], CONFIG["history_days"])

    if df_raw.empty:
        print("❌ Нет данных. Проверь подключение к интернету.")
        sys.exit(1)

    # Симулируем обе версии
    print("\n⚙️  Симулирую стратегию...")
    res_with_stop    = simulate(df_raw, CONFIG, use_stop=True)
    res_without_stop = simulate(df_raw, CONFIG, use_stop=False)

    # Метрики
    metrics_stop    = compute_metrics(res_with_stop,    CONFIG)
    metrics_no_stop = compute_metrics(res_without_stop, CONFIG)

    print("\n" + "─"*60)
    print(f"  {'Метрика':<30} {'СО СТОПОМ':>12} {'БЕЗ СТОПА':>12}")
    print("─"*60)
    for key in metrics_stop:
        print(f"  {key:<30} {metrics_stop[key]:>12} {metrics_no_stop[key]:>12}")
    print("─"*60)

    # Анализ по годам
    print("\n📅 Разбивка по годам (со стопом):")
    res_with_stop["year"] = res_with_stop["time"].dt.year
    for year, grp in res_with_stop.groupby("year"):
        start = grp["capital"].iloc[0]
        end   = grp["capital"].iloc[-1]
        ret   = (end - start) / start * 100
        avg_r = df_raw[df_raw["time"].dt.year == year]["rate"].mean() * 100
        pct_a = grp["in_position"].mean() * 100
        bar   = "█" * int(abs(ret) / 5) + ("+" if ret > 0 else "-")
        print(f"   {year}: {ret:+7.1f}%  avg_rate={avg_r:.4f}%/8h  "
              f"активен={pct_a:.0f}%  {bar}")

    # Ключевые выводы
    final_stop    = res_with_stop["capital"].iloc[-1]
    final_no_stop = res_without_stop["capital"].iloc[-1]
    saved         = final_stop - final_no_stop

    print("\n" + "─"*60)
    print("  🔍 ВЫВОД ПО ГИПОТЕЗЕ A:")
    print("─"*60)
    neg_pct = (df_raw["rate"] < CONFIG["stop_threshold"]).mean() * 100
    print(f"  • {neg_pct:.1f}% периодов funding ниже порога стопа")
    print(f"  • Правило стопа {'ПОМОГЛО' if saved > 0 else 'НЕ ПОМОГЛО'}: "
          f"{'+'  if saved > 0 else ''}{saved:,.0f}$ разницы")

    m_stop    = compute_metrics(res_with_stop,    CONFIG)
    sharpe_v  = float(m_stop["Sharpe Ratio"])
    annual_v  = float(m_stop["Годовая доходность"].replace("%","").replace("+",""))

    if annual_v > 15 and sharpe_v > 0.8:
        verdict = "✅ ГИПОТЕЗА ПОДТВЕРЖДЕНА — стратегия жизнеспособна"
    elif annual_v > 5:
        verdict = "🟡 ГИПОТЕЗА ЧАСТИЧНО ПОДТВЕРЖДЕНА — доходность есть, но слабая"
    else:
        verdict = "❌ ГИПОТЕЗА ОТКЛОНЕНА — стратегия не даёт приемлемой доходности"

    print(f"\n  {verdict}")
    print(f"  • Годовая доходность:  {m_stop['Годовая доходность']}")
    print(f"  • Sharpe Ratio:        {m_stop['Sharpe Ratio']}")
    print(f"  • Max Drawdown:        {m_stop['Max Drawdown']}")

    # Рекомендации
    print("\n  📋 СЛЕДУЮЩИЙ ШАГ:")
    if annual_v > 15:
        print("  → Запустить paper trading на Binance Testnet с $500")
        print("  → Мониторить 2 недели, сравнить с симуляцией")
        print(f"  → Текущий funding: {'выше' if current and current['rate'] >= CONFIG['reentry_threshold'] else 'ниже'} порога входа")
    else:
        print("  → Проверить ETH/SOL — у них часто выше funding rate")
        print("  → Рассмотреть мультиактивную версию стратегии")
    print()

    # График
    print("📊 Строю визуализацию...")
    plot_results(df_raw, res_with_stop, res_without_stop, CONFIG)


if __name__ == "__main__":
    # Проверка зависимостей
    try:
        import requests, pandas, numpy, matplotlib
    except ImportError as e:
        print(f"❌ Установи зависимости: pip install requests pandas numpy matplotlib")
        print(f"   Не хватает: {e.name}")
        sys.exit(1)

    main()
