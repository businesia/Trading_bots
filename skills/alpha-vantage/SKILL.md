---
name: alpha-vantage
description: Fetch 20+ years of global financial data via Alpha Vantage API — equities, options, forex, crypto, commodities, economic indicators, and 50+ technical indicators. Use when the user needs historical price data, real-time quotes, technical analysis, or macro economic data for any asset class.
---

# Alpha Vantage Data Skill

Access comprehensive global financial data through the Alpha Vantage API covering stocks, options, forex, crypto, commodities, and 50+ technical indicators.

## When to Use This Skill

- Fetching historical OHLCV data for backtesting
- Getting real-time or intraday quotes
- Computing technical indicators (RSI, MACD, Bollinger Bands, etc.)
- Forex and cryptocurrency rate lookups
- Commodity prices (oil, gold, natural gas)
- Economic indicators (GDP, CPI, unemployment, treasury yields)
- Options chain data

## Setup

```bash
# Set API key (free tier: 25 requests/day, premium: unlimited)
export ALPHAVANTAGE_API_KEY="your_key_here"
# Get free key: https://www.alphavantage.co/support/#api-key
```

Install the Python client:
```bash
pip install alpha_vantage requests pandas
```

## Core Data Functions

### Daily OHLCV (Equities)

```python
import requests, os, pandas as pd

def get_daily(symbol: str, outputsize: str = "full") -> pd.DataFrame:
    """Fetch daily adjusted OHLCV. outputsize: 'compact' (100 days) or 'full' (20+ years)."""
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_DAILY_ADJUSTED",
        "symbol": symbol,
        "outputsize": outputsize,
        "apikey": os.environ["ALPHAVANTAGE_API_KEY"],
        "datatype": "json",
    }
    r = requests.get(url, params=params, timeout=30)
    data = r.json().get("Time Series (Daily)", {})
    df = pd.DataFrame(data).T
    df.index = pd.to_datetime(df.index)
    df = df.rename(columns={
        "1. open": "open", "2. high": "high", "3. low": "low",
        "4. close": "close", "5. adjusted close": "adj_close",
        "6. volume": "volume", "7. dividend amount": "dividend",
        "8. split coefficient": "split"
    }).astype(float).sort_index()
    return df
```

### Intraday Data

```python
def get_intraday(symbol: str, interval: str = "5min") -> pd.DataFrame:
    """interval: 1min, 5min, 15min, 30min, 60min"""
    params = {
        "function": "TIME_SERIES_INTRADAY",
        "symbol": symbol,
        "interval": interval,
        "outputsize": "full",
        "extended_hours": "true",
        "apikey": os.environ["ALPHAVANTAGE_API_KEY"],
    }
    r = requests.get("https://www.alphavantage.co/query", params=params, timeout=30)
    data = r.json().get(f"Time Series ({interval})", {})
    df = pd.DataFrame(data).T
    df.index = pd.to_datetime(df.index)
    df = df.rename(columns={"1. open": "open", "2. high": "high", "3. low": "low",
                             "4. close": "close", "5. volume": "volume"}).astype(float).sort_index()
    return df
```

### Forex & Crypto

```python
def get_forex_daily(from_symbol: str, to_symbol: str) -> pd.DataFrame:
    params = {
        "function": "FX_DAILY",
        "from_symbol": from_symbol,
        "to_symbol": to_symbol,
        "outputsize": "full",
        "apikey": os.environ["ALPHAVANTAGE_API_KEY"],
    }
    r = requests.get("https://www.alphavantage.co/query", params=params, timeout=30)
    data = r.json().get("Time Series FX (Daily)", {})
    return pd.DataFrame(data).T.rename(
        columns={"1. open": "open", "2. high": "high", "3. low": "low", "4. close": "close"}
    ).astype(float).sort_index()

def get_crypto_daily(symbol: str, market: str = "USD") -> pd.DataFrame:
    params = {
        "function": "DIGITAL_CURRENCY_DAILY",
        "symbol": symbol,
        "market": market,
        "apikey": os.environ["ALPHAVANTAGE_API_KEY"],
    }
    r = requests.get("https://www.alphavantage.co/query", params=params, timeout=30)
    data = r.json().get("Time Series (Digital Currency Daily)", {})
    df = pd.DataFrame(data).T.astype(float).sort_index()
    return df[[f"1a. open ({market})", f"2a. high ({market})", f"3a. low ({market})", f"4a. close ({market})", "5. volume"]]
```

### Technical Indicators (50+ available)

```python
def get_indicator(symbol: str, function: str, interval: str = "daily",
                  time_period: int = 14, series_type: str = "close") -> pd.Series:
    """
    Common functions: RSI, MACD, BBANDS, EMA, SMA, ATR, ADX, STOCH,
    OBV, CCI, WILLR, MOM, ROC, TRIX, ULTOSC, AROON, DX, PLUS_DI, MINUS_DI
    """
    params = {
        "function": function,
        "symbol": symbol,
        "interval": interval,
        "time_period": time_period,
        "series_type": series_type,
        "apikey": os.environ["ALPHAVANTAGE_API_KEY"],
    }
    r = requests.get("https://www.alphavantage.co/query", params=params, timeout=30)
    payload = r.json()
    # Key varies by indicator — find the "Technical Analysis" key
    ta_key = [k for k in payload if "Technical Analysis" in k][0]
    df = pd.DataFrame(payload[ta_key]).T.astype(float).sort_index()
    return df
```

### Economic Indicators

```python
ECONOMIC_FUNCTIONS = {
    "gdp_annual": "REAL_GDP",
    "gdp_quarterly": "REAL_GDP_PER_CAPITA",
    "cpi": "CPI",
    "inflation": "INFLATION",
    "retail_sales": "RETAIL_SALES",
    "unemployment": "UNEMPLOYMENT",
    "fed_funds_rate": "FEDERAL_FUNDS_RATE",
    "treasury_yield_10y": "TREASURY_YIELD",
    "nonfarm_payroll": "NONFARM_PAYROLL",
}

def get_economic(indicator: str, interval: str = "monthly") -> pd.Series:
    params = {
        "function": ECONOMIC_FUNCTIONS[indicator],
        "interval": interval,
        "apikey": os.environ["ALPHAVANTAGE_API_KEY"],
    }
    r = requests.get("https://www.alphavantage.co/query", params=params, timeout=30)
    data = r.json().get("data", [])
    s = pd.Series({d["date"]: float(d["value"]) for d in data if d["value"] != "."})
    return s.sort_index()
```

## Rate Limit Handling

```python
import time

def rate_limited_get(url, params, calls_per_minute=5):
    """Free tier: 25/day, 5/minute. Premium: unlimited."""
    r = requests.get(url, params=params, timeout=30)
    time.sleep(60 / calls_per_minute)
    return r
```

## Available Asset Classes

| Asset Class | Functions |
|-------------|-----------|
| US Equities | TIME_SERIES_DAILY_ADJUSTED, TIME_SERIES_INTRADAY, GLOBAL_QUOTE |
| Options | REALTIME_OPTIONS, HISTORICAL_OPTIONS |
| Forex | FX_INTRADAY, FX_DAILY, FX_WEEKLY, FX_MONTHLY, CURRENCY_EXCHANGE_RATE |
| Crypto | CRYPTO_INTRADAY, DIGITAL_CURRENCY_DAILY, CRYPTO_RATING |
| Commodities | WTI, BRENT, NATURAL_GAS, COPPER, ALUMINUM, WHEAT, CORN, COTTON, SUGAR |
| Economic | REAL_GDP, CPI, INFLATION, UNEMPLOYMENT, FEDERAL_FUNDS_RATE, TREASURY_YIELD |

## Notes

- Free API key from https://www.alphavantage.co/support/#api-key
- Premium plans remove rate limits and add options data, 1-min intraday history
- Data coverage: 20+ years for most US equities; varies by asset class
- Adjusted close accounts for splits and dividends — use for backtesting
