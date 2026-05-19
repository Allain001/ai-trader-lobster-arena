from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any


CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
CACHE_TTL_SECONDS = 300
NETWORK_TIMEOUT_SECONDS = 5

STOCK_UNIVERSE: list[dict[str, str]] = [
    {"symbol": "AAPL", "name": "Apple", "sector": "Tech"},
    {"symbol": "MSFT", "name": "Microsoft", "sector": "Tech"},
    {"symbol": "GOOGL", "name": "Alphabet", "sector": "Tech"},
    {"symbol": "META", "name": "Meta", "sector": "Tech"},
    {"symbol": "AMZN", "name": "Amazon", "sector": "Tech"},
    {"symbol": "NFLX", "name": "Netflix", "sector": "Tech"},
    {"symbol": "CRM", "name": "Salesforce", "sector": "Tech"},
    {"symbol": "ORCL", "name": "Oracle", "sector": "Tech"},
    {"symbol": "NVDA", "name": "NVIDIA", "sector": "Chips"},
    {"symbol": "AMD", "name": "AMD", "sector": "Chips"},
    {"symbol": "AVGO", "name": "Broadcom", "sector": "Chips"},
    {"symbol": "TSM", "name": "TSMC", "sector": "Chips"},
    {"symbol": "INTC", "name": "Intel", "sector": "Chips"},
    {"symbol": "QCOM", "name": "Qualcomm", "sector": "Chips"},
    {"symbol": "MU", "name": "Micron", "sector": "Chips"},
    {"symbol": "ASML", "name": "ASML", "sector": "Chips"},
    {"symbol": "TSLA", "name": "Tesla", "sector": "Momentum"},
    {"symbol": "COIN", "name": "Coinbase", "sector": "Momentum"},
    {"symbol": "PLTR", "name": "Palantir", "sector": "Momentum"},
    {"symbol": "RBLX", "name": "Roblox", "sector": "Momentum"},
    {"symbol": "SHOP", "name": "Shopify", "sector": "Momentum"},
    {"symbol": "SPY", "name": "S&P 500 ETF", "sector": "ETF"},
    {"symbol": "QQQ", "name": "Nasdaq 100 ETF", "sector": "ETF"},
    {"symbol": "DIA", "name": "Dow ETF", "sector": "ETF"},
    {"symbol": "IWM", "name": "Russell 2000 ETF", "sector": "ETF"},
    {"symbol": "VOO", "name": "Vanguard S&P 500", "sector": "ETF"},
    {"symbol": "JPM", "name": "JPMorgan", "sector": "Finance"},
    {"symbol": "BAC", "name": "Bank of America", "sector": "Finance"},
    {"symbol": "GS", "name": "Goldman Sachs", "sector": "Finance"},
    {"symbol": "MS", "name": "Morgan Stanley", "sector": "Finance"},
    {"symbol": "V", "name": "Visa", "sector": "Finance"},
    {"symbol": "MA", "name": "Mastercard", "sector": "Finance"},
    {"symbol": "WMT", "name": "Walmart", "sector": "Consumer"},
    {"symbol": "COST", "name": "Costco", "sector": "Consumer"},
    {"symbol": "KO", "name": "Coca-Cola", "sector": "Consumer"},
    {"symbol": "PEP", "name": "PepsiCo", "sector": "Consumer"},
    {"symbol": "MCD", "name": "McDonald's", "sector": "Consumer"},
    {"symbol": "NKE", "name": "Nike", "sector": "Consumer"},
    {"symbol": "JNJ", "name": "Johnson & Johnson", "sector": "Healthcare"},
    {"symbol": "UNH", "name": "UnitedHealth", "sector": "Healthcare"},
    {"symbol": "PFE", "name": "Pfizer", "sector": "Healthcare"},
    {"symbol": "ABBV", "name": "AbbVie", "sector": "Healthcare"},
    {"symbol": "MRK", "name": "Merck", "sector": "Healthcare"},
    {"symbol": "XOM", "name": "Exxon Mobil", "sector": "Energy"},
    {"symbol": "CVX", "name": "Chevron", "sector": "Energy"},
    {"symbol": "COP", "name": "ConocoPhillips", "sector": "Energy"},
    {"symbol": "SLB", "name": "Schlumberger", "sector": "Energy"},
    {"symbol": "BABA", "name": "Alibaba", "sector": "China ADR"},
    {"symbol": "PDD", "name": "PDD", "sector": "China ADR"},
    {"symbol": "JD", "name": "JD.com", "sector": "China ADR"},
]

_WATCHLIST_CACHE: dict[str, Any] = {"expires_at": 0.0, "payload": None}
_CANDLE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


class MarketCandleError(RuntimeError):
    pass


def _fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _known_stock(symbol: str) -> dict[str, str] | None:
    normalized = symbol.strip().upper()
    return next((item for item in STOCK_UNIVERSE if item["symbol"] == normalized), None)


def _symbol_seed(symbol: str) -> int:
    return sum((index + 1) * ord(char) for index, char in enumerate(symbol.upper()))


def _fallback_quote(stock: dict[str, str], index: int) -> dict[str, Any]:
    seed = _symbol_seed(stock["symbol"])
    base_price = 35.0 + (seed % 320) + index * 0.8
    change = ((seed % 17) - 8) * 0.31
    return {
        **stock,
        "price": round(base_price, 2),
        "change_percent": round(change, 2),
        "market_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "currency": "USD",
        "source": "fallback",
    }


def get_market_watchlist() -> dict[str, Any]:
    now = time.time()
    cached = _WATCHLIST_CACHE.get("payload")
    if cached and now < float(_WATCHLIST_CACHE.get("expires_at") or 0):
        return cached

    quote_by_symbol: dict[str, dict[str, Any]] = {}
    try:
        params = urllib.parse.urlencode({"symbols": ",".join(item["symbol"] for item in STOCK_UNIVERSE)})
        payload = _fetch_json(f"{QUOTE_URL}?{params}")
        for item in payload.get("quoteResponse", {}).get("result", []) or []:
            symbol = str(item.get("symbol") or "").upper()
            price = item.get("regularMarketPrice")
            previous_close = item.get("regularMarketPreviousClose")
            change_percent = item.get("regularMarketChangePercent")
            timestamp = item.get("regularMarketTime")
            if price is None:
                continue
            if change_percent is None and previous_close:
                change_percent = (float(price) - float(previous_close)) / float(previous_close) * 100
            quote_by_symbol[symbol] = {
                "price": round(float(price), 4),
                "change_percent": round(float(change_percent or 0), 4),
                "market_time": (
                    datetime.fromtimestamp(int(timestamp), timezone.utc).isoformat(timespec="seconds")
                    if timestamp
                    else datetime.now(timezone.utc).isoformat(timespec="seconds")
                ),
                "currency": item.get("currency") or "USD",
                "source": "yahoo",
            }
    except Exception:
        quote_by_symbol = {}

    stocks: list[dict[str, Any]] = []
    for index, stock in enumerate(STOCK_UNIVERSE):
        quote = quote_by_symbol.get(stock["symbol"])
        stocks.append({**stock, **quote} if quote else _fallback_quote(stock, index))

    payload = {
        "stocks": stocks,
        "sectors": sorted({item["sector"] for item in STOCK_UNIVERSE}),
        "count": len(stocks),
        "cached_for_seconds": CACHE_TTL_SECONDS,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _WATCHLIST_CACHE["payload"] = payload
    _WATCHLIST_CACHE["expires_at"] = now + CACHE_TTL_SECONDS
    return payload


def _chart_result(symbol: str, range_: str, interval: str) -> dict[str, Any]:
    params = urllib.parse.urlencode({"range": range_, "interval": interval})
    payload = _fetch_json(f"{CHART_URL.format(symbol=symbol)}?{params}")
    result = payload.get("chart", {}).get("result")
    if not result:
        raise MarketCandleError(f"Missing candle data for {symbol}")
    return result[0]


def _moving_average(values: list[float], window: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, _value in enumerate(values):
        if index + 1 < window:
            continue
        window_values = values[index + 1 - window : index + 1]
        result.append({"index": index, "value": round(sum(window_values) / window, 4)})
    return result


def _fallback_candles(stock: dict[str, str], range_: str, interval: str) -> dict[str, Any]:
    days = {"1mo": 23, "3mo": 63, "6mo": 126, "1y": 252}.get(range_, 63)
    seed = _symbol_seed(stock["symbol"])
    base = 45.0 + (seed % 260)
    drift = ((seed % 13) - 5) / 1000
    volatility = 0.014 + (seed % 7) / 1000
    start_date = datetime.now(timezone.utc).date() - timedelta(days=days * 1.45)
    candles: list[dict[str, Any]] = []
    price = base
    day_index = 0

    while len(candles) < days:
        date = start_date + timedelta(days=day_index)
        day_index += 1
        if date.weekday() >= 5:
            continue
        wave = math.sin((len(candles) + seed % 19) / 5) * volatility
        move = drift + wave
        open_price = price
        close_price = max(1.0, open_price * (1 + move))
        high_price = max(open_price, close_price) * (1 + volatility * 0.75)
        low_price = min(open_price, close_price) * (1 - volatility * 0.75)
        volume = int(1_000_000 + (seed % 9) * 350_000 + len(candles) * 12_000)
        candles.append(
            {
                "time": date.strftime("%Y-%m-%d"),
                "open": round(open_price, 4),
                "high": round(high_price, 4),
                "low": round(low_price, 4),
                "close": round(close_price, 4),
                "volume": volume,
            }
        )
        price = close_price

    closes = [float(item["close"]) for item in candles]
    ma5 = [{"time": candles[item["index"]]["time"], "value": item["value"]} for item in _moving_average(closes, 5)]
    ma20 = [{"time": candles[item["index"]]["time"], "value": item["value"]} for item in _moving_average(closes, 20)]
    previous = candles[-2]["close"] if len(candles) > 1 else candles[-1]["close"]
    change_percent = ((candles[-1]["close"] - previous) / previous * 100) if previous else 0.0
    return {
        "symbol": stock["symbol"],
        "name": stock["name"],
        "sector": stock["sector"],
        "range": range_,
        "interval": interval,
        "currency": "USD",
        "price": candles[-1]["close"],
        "change_percent": round(change_percent, 4),
        "candles": candles,
        "ma5": ma5,
        "ma20": ma20,
        "source": "fallback",
        "cached_for_seconds": CACHE_TTL_SECONDS,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def get_market_candles(symbol: str, range_: str = "3mo", interval: str = "1d") -> dict[str, Any]:
    normalized = symbol.strip().upper()
    if not normalized:
        raise MarketCandleError("symbol is required")
    if range_ not in {"1mo", "3mo", "6mo", "1y"}:
        range_ = "3mo"
    if interval not in {"1d", "1h"}:
        interval = "1d"

    cache_key = f"{normalized}:{range_}:{interval}"
    now = time.time()
    cached = _CANDLE_CACHE.get(cache_key)
    if cached and now < cached[0]:
        return cached[1]

    stock = _known_stock(normalized)
    if not stock:
        raise MarketCandleError(f"Unknown stock symbol: {normalized}")

    try:
        chart = _chart_result(normalized, range_, interval)
        payload = _payload_from_chart(stock, chart, range_, interval)
    except Exception:
        payload = _fallback_candles(stock, range_, interval)

    _CANDLE_CACHE[cache_key] = (now + CACHE_TTL_SECONDS, payload)
    return payload


def _payload_from_chart(stock: dict[str, str], chart: dict[str, Any], range_: str, interval: str) -> dict[str, Any]:
    meta = chart.get("meta", {})
    quote = (chart.get("indicators", {}).get("quote") or [{}])[0]
    timestamps = chart.get("timestamp") or []
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    candles: list[dict[str, Any]] = []
    clean_closes: list[float] = []
    close_time_pairs: list[tuple[str, float]] = []
    for index, timestamp in enumerate(timestamps):
        values = [
            opens[index] if index < len(opens) else None,
            highs[index] if index < len(highs) else None,
            lows[index] if index < len(lows) else None,
            closes[index] if index < len(closes) else None,
        ]
        if any(value is None for value in values):
            continue
        date_key = datetime.fromtimestamp(int(timestamp), timezone.utc).strftime("%Y-%m-%d")
        close_value = float(values[3])
        clean_closes.append(close_value)
        close_time_pairs.append((date_key, close_value))
        candles.append(
            {
                "time": date_key,
                "open": round(float(values[0]), 4),
                "high": round(float(values[1]), 4),
                "low": round(float(values[2]), 4),
                "close": round(close_value, 4),
                "volume": int(volumes[index] or 0) if index < len(volumes) and volumes[index] is not None else 0,
            }
        )

    if not candles:
        raise MarketCandleError(f"No usable candle data for {stock['symbol']}")

    ma5 = [
        {"time": close_time_pairs[item["index"]][0], "value": item["value"]}
        for item in _moving_average(clean_closes, 5)
    ]
    ma20 = [
        {"time": close_time_pairs[item["index"]][0], "value": item["value"]}
        for item in _moving_average(clean_closes, 20)
    ]
    last = candles[-1]
    previous_close = float(meta.get("previousClose") or (candles[-2]["close"] if len(candles) > 1 else last["close"]))
    change_percent = ((last["close"] - previous_close) / previous_close * 100) if previous_close else 0.0
    return {
        "symbol": stock["symbol"],
        "name": stock["name"],
        "sector": stock["sector"],
        "range": range_,
        "interval": interval,
        "currency": meta.get("currency") or "USD",
        "price": last["close"],
        "change_percent": round(change_percent, 4),
        "candles": candles,
        "ma5": ma5,
        "ma20": ma20,
        "source": "yahoo",
        "cached_for_seconds": CACHE_TTL_SECONDS,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
