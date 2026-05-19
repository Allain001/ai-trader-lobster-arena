from typing import Optional

from fastapi import FastAPI, HTTPException

from market_candles import MarketCandleError, get_market_candles, get_market_watchlist
from market_intel import (
    get_etf_flows_payload,
    get_featured_stock_analysis_payload,
    get_macro_signals_payload,
    get_market_intel_overview,
    get_market_news_payload,
    get_stock_analysis_history_payload,
    get_stock_analysis_latest_payload,
)
from routes_shared import utc_now_iso_z


def register_market_routes(app: FastAPI) -> None:
    @app.get('/health')
    async def health_check():
        return {'status': 'ok', 'timestamp': utc_now_iso_z()}

    @app.get('/api/market-intel/overview')
    async def market_intel_overview():
        return get_market_intel_overview()

    @app.get('/api/market-intel/news')
    async def market_intel_news(category: Optional[str] = None, limit: int = 5):
        safe_limit = max(1, min(limit, 12))
        return get_market_news_payload(category=category, limit=safe_limit)

    @app.get('/api/market-intel/macro-signals')
    async def market_intel_macro_signals():
        return get_macro_signals_payload()

    @app.get('/api/market-intel/etf-flows')
    async def market_intel_etf_flows():
        return get_etf_flows_payload()

    @app.get('/api/market-intel/stocks/featured')
    async def market_intel_featured_stocks(limit: int = 6):
        return get_featured_stock_analysis_payload(limit=max(1, min(limit, 12)))

    @app.get('/api/market-intel/stocks/{symbol}/latest')
    async def market_intel_stock_latest(symbol: str):
        return get_stock_analysis_latest_payload(symbol)

    @app.get('/api/market-intel/stocks/{symbol}/history')
    async def market_intel_stock_history(symbol: str, limit: int = 10):
        return get_stock_analysis_history_payload(symbol, limit=limit)

    @app.get('/api/market/watchlist')
    async def market_watchlist():
        return get_market_watchlist()

    @app.get('/api/market/candles')
    async def market_candles(symbol: str, range: str = "3mo", interval: str = "1d"):
        try:
            return get_market_candles(symbol, range_=range, interval=interval)
        except MarketCandleError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to fetch candles for {symbol}: {exc}") from exc
