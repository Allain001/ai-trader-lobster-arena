from __future__ import annotations

import json
import os
import random
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
DEFAULT_SYMBOLS = ["NVDA", "AAPL", "TSLA", "MSFT", "SPY"]
API_AGENT_NAME = "NewAPI 智能体"
DEMO_QUOTES = {
    "NVDA": (220.78, 0.61),
    "AAPL": (294.80, 0.72),
    "TSLA": (433.45, -2.60),
    "MSFT": (407.77, -1.18),
    "SPY": (738.18, -0.15),
}


class LobsterArenaError(RuntimeError):
    pass


@dataclass
class Quote:
    symbol: str
    price: float
    change_percent: float
    market_time: str
    currency: str = "USD"


@dataclass
class Decision:
    agent: str
    symbol: str
    action: str
    confidence: float
    reason: str
    target_fraction: float = 0.0


@dataclass
class PaperPortfolio:
    agent: str
    cash: float
    positions: dict[str, int] = field(default_factory=dict)
    trades: list[dict[str, Any]] = field(default_factory=list)

    def position_value(self, symbol: str, quotes: dict[str, Quote]) -> float:
        return self.positions.get(symbol, 0) * quotes[symbol].price

    def total_value(self, quotes: dict[str, Quote]) -> float:
        holdings = sum(shares * quotes[symbol].price for symbol, shares in self.positions.items())
        return self.cash + holdings

    def exposure(self, symbol: str, quotes: dict[str, Quote]) -> float:
        total = self.total_value(quotes)
        return self.position_value(symbol, quotes) / total if total else 0.0

    def execute(
        self,
        decision: Decision,
        quotes: dict[str, Quote],
        max_position: float,
        fee_rate: float,
    ) -> None:
        action = decision.action.upper()
        if action not in {"BUY", "SELL"}:
            return

        quote = quotes[decision.symbol]
        price = quote.price
        total_value = self.total_value(quotes)

        if action == "BUY":
            target_fraction = min(decision.target_fraction, max_position)
            target_value = total_value * target_fraction
            current_value = self.position_value(decision.symbol, quotes)
            budget = max(0.0, min(target_value - current_value, self.cash))
            shares = int(budget / (price * (1 + fee_rate)))
            if shares <= 0:
                return
            gross_value = shares * price
            fee = gross_value * fee_rate
            self.cash -= gross_value + fee
            self.positions[decision.symbol] = self.positions.get(decision.symbol, 0) + shares
        else:
            owned = self.positions.get(decision.symbol, 0)
            shares = min(owned, max(1, int(owned * max(decision.target_fraction, 0.25)))) if owned else 0
            if shares <= 0:
                return
            gross_value = shares * price
            fee = gross_value * fee_rate
            self.cash += gross_value - fee
            remaining = owned - shares
            if remaining:
                self.positions[decision.symbol] = remaining
            else:
                self.positions.pop(decision.symbol, None)

        self.trades.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "agent": self.agent,
                "symbol": decision.symbol,
                "action": action,
                "shares": shares,
                "price": round(price, 4),
                "value": round(gross_value, 2),
                "fee": round(fee, 2),
                "reason": decision.reason,
            }
        )


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
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            import json

            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise LobsterArenaError(f"Failed to fetch market data: {exc}") from exc


def _chart_result(symbol: str, range_: str = "3mo", interval: str = "1d") -> dict[str, Any]:
    params = urllib.parse.urlencode({"range": range_, "interval": interval})
    payload = _fetch_json(f"{CHART_URL.format(symbol=symbol)}?{params}")
    result = payload.get("chart", {}).get("result")
    if not result:
        raise LobsterArenaError(f"Missing chart data for {symbol}")
    return result[0]


def _quote_from_chart(symbol: str) -> tuple[Quote, list[float]]:
    result = _chart_result(symbol)
    meta = result.get("meta", {})
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    clean_closes = [float(close) for close in closes if close is not None]
    if not clean_closes and meta.get("regularMarketPrice") is None:
        raise LobsterArenaError(f"Missing price data for {symbol}")

    price = float(meta.get("regularMarketPrice") or clean_closes[-1])
    previous = clean_closes[-2] if len(clean_closes) >= 2 else meta.get("previousClose") or price
    change_percent = ((price - float(previous)) / float(previous)) * 100 if previous else 0.0
    timestamp = meta.get("regularMarketTime")
    market_time = (
        datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")
        if timestamp
        else datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    quote = Quote(
        symbol=symbol,
        price=price,
        change_percent=change_percent,
        market_time=market_time,
        currency=meta.get("currency") or "USD",
    )
    return quote, clean_closes


def _fallback_quote(symbol: str) -> tuple[Quote, list[float]]:
    price, change_percent = DEMO_QUOTES.get(symbol, (100.0, 0.0))
    history = [price * (0.94 + index * 0.003) for index in range(30)]
    history[-1] = price
    quote = Quote(
        symbol=symbol,
        price=price,
        change_percent=change_percent,
        market_time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        currency="USD",
    )
    return quote, history


def _moving_average(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _lobster_decisions(
    quotes: dict[str, Quote],
    history: dict[str, list[float]],
    portfolio: PaperPortfolio,
) -> list[Decision]:
    rng = random.Random(2026)
    decisions: list[Decision] = []
    for symbol, quote in quotes.items():
        ma5 = _moving_average(history[symbol], 5)
        ma20 = _moving_average(history[symbol], 20)
        momentum = 0.0 if not ma5 or not ma20 else ((ma5 - ma20) / ma20) * 100
        noise = rng.uniform(-0.9, 0.9)
        score = quote.change_percent * 0.45 + momentum * 0.45 + noise
        if score > 0.75 and portfolio.exposure(symbol, quotes) < 0.22:
            decisions.append(
                Decision(
                    "龙虾智能体",
                    symbol,
                    "BUY",
                    min(1.0, abs(score) / 3),
                    f"龙虾信号偏多：当日涨跌 {quote.change_percent:.2f}%，趋势动量 {momentum:.2f}%，随机扰动 {noise:.2f}。",
                    0.10 + min(abs(score), 2.5) / 25,
                )
            )
        elif score < -1.1 and portfolio.positions.get(symbol, 0) > 0:
            decisions.append(
                Decision(
                    "龙虾智能体",
                    symbol,
                    "SELL",
                    min(1.0, abs(score) / 3),
                    f"龙虾撤退：综合风险分数 {score:.2f}，选择减仓。",
                    0.35,
                )
            )
        else:
            decisions.append(
                Decision("龙虾智能体", symbol, "HOLD", 0.3, f"龙虾观望：综合信号 {score:.2f}，暂不操作。")
            )
    return decisions


def _ma_decisions(
    quotes: dict[str, Quote],
    history: dict[str, list[float]],
    portfolio: PaperPortfolio,
) -> list[Decision]:
    decisions: list[Decision] = []
    for symbol in quotes:
        ma5 = _moving_average(history[symbol], 5)
        ma20 = _moving_average(history[symbol], 20)
        if not ma5 or not ma20:
            decisions.append(Decision("均线智能体", symbol, "HOLD", 0.1, "历史数据不足，暂不生成均线信号。"))
            continue
        spread = (ma5 - ma20) / ma20
        if spread > 0.01 and portfolio.exposure(symbol, quotes) < 0.25:
            decisions.append(
                Decision(
                    "均线智能体",
                    symbol,
                    "BUY",
                    min(1.0, abs(spread) * 18),
                    f"5 日均线 {ma5:.2f} 高于 20 日均线 {ma20:.2f}，趋势偏强。",
                    0.18,
                )
            )
        elif spread < -0.01 and portfolio.positions.get(symbol, 0) > 0:
            decisions.append(
                Decision(
                    "均线智能体",
                    symbol,
                    "SELL",
                    min(1.0, abs(spread) * 18),
                    f"5 日均线 {ma5:.2f} 低于 20 日均线 {ma20:.2f}，趋势转弱。",
                    0.5,
                )
            )
        else:
            decisions.append(
                Decision("均线智能体", symbol, "HOLD", 0.35, f"均线差值 {spread * 100:.2f}%，处于中性区间。")
            )
    return decisions


def _conservative_decisions(quotes: dict[str, Quote], history: dict[str, list[float]]) -> list[Decision]:
    preferred = {"SPY", "MSFT", "AAPL"}
    decisions: list[Decision] = []
    for symbol, quote in quotes.items():
        if symbol not in preferred:
            decisions.append(Decision("稳健智能体", symbol, "HOLD", 0.25, "不在稳健核心股票池中。"))
            continue
        ma20 = _moving_average(history[symbol], 20)
        if ma20 and quote.price >= ma20 and quote.change_percent > -1.5:
            decisions.append(
                Decision("稳健智能体", symbol, "BUY", 0.65, f"核心资产价格高于 20 日均线 {ma20:.2f}，允许小仓位买入。", 0.14)
            )
        else:
            decisions.append(Decision("稳健智能体", symbol, "HOLD", 0.4, "没有达到稳健买入条件。"))
    return decisions


def _contrarian_decisions(quotes: dict[str, Quote], portfolio: PaperPortfolio) -> list[Decision]:
    decisions: list[Decision] = []
    for symbol, quote in quotes.items():
        if quote.change_percent <= -1.8 and portfolio.exposure(symbol, quotes) < 0.2:
            decisions.append(
                Decision("反向智能体", symbol, "BUY", min(1.0, abs(quote.change_percent) / 4), f"当日下跌 {quote.change_percent:.2f}%，触发低吸策略。", 0.12)
            )
        elif quote.change_percent >= 2.0 and portfolio.positions.get(symbol, 0) > 0:
            decisions.append(
                Decision("反向智能体", symbol, "SELL", min(1.0, quote.change_percent / 4), f"当日上涨 {quote.change_percent:.2f}%，触发止盈减仓。", 0.4)
            )
        else:
            decisions.append(Decision("反向智能体", symbol, "HOLD", 0.3, "没有明显低吸或止盈信号。"))
    return decisions


def _random_decisions(quotes: dict[str, Quote], portfolio: PaperPortfolio) -> list[Decision]:
    rng = random.Random(7)
    decisions: list[Decision] = []
    for symbol in quotes:
        roll = rng.random()
        if roll < 0.18 and portfolio.exposure(symbol, quotes) < 0.15:
            decisions.append(Decision("随机基准智能体", symbol, "BUY", 0.2, "随机基准策略触发买入，用作对照组。", 0.08))
        elif roll > 0.88 and portfolio.positions.get(symbol, 0) > 0:
            decisions.append(Decision("随机基准智能体", symbol, "SELL", 0.2, "随机基准策略触发卖出，用作对照组。", 0.5))
        else:
            decisions.append(Decision("随机基准智能体", symbol, "HOLD", 0.2, "随机基准策略保持观望。"))
    return decisions


def _safe_json_array(raw: str) -> list[Any]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM response did not contain a JSON array")
    payload = cleaned[start : end + 1]
    parsed = json.loads(payload)
    if not isinstance(parsed, list):
        raise ValueError("LLM response JSON was not a list")
    return parsed


def _clamp_float(value: Any, default: float, lower: float, upper: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(lower, min(number, upper))


def _api_agent_decisions(
    quotes: dict[str, Quote],
    history: dict[str, list[float]],
    portfolio: PaperPortfolio,
    max_position: float,
) -> tuple[list[Decision], dict[str, Any]]:
    if not (os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")):
        return (
            [
                Decision(API_AGENT_NAME, symbol, "HOLD", 0.0, "未配置 NewAPI 密钥，API 智能体本轮不参赛。")
                for symbol in quotes
            ],
            {"enabled": True, "status": "not_configured", "decision_count": 0, "agent_name": API_AGENT_NAME},
        )

    market_payload = []
    for symbol, quote in quotes.items():
        ma5 = _moving_average(history[symbol], 5)
        ma20 = _moving_average(history[symbol], 20)
        momentum = 0.0 if not ma5 or not ma20 else ((ma5 - ma20) / ma20) * 100
        market_payload.append(
            {
                "symbol": symbol,
                "price": quote.price,
                "change_percent": quote.change_percent,
                "ma5": ma5,
                "ma20": ma20,
                "momentum_percent": momentum,
                "current_shares": portfolio.positions.get(symbol, 0),
                "current_exposure": round(portfolio.exposure(symbol, quotes), 4),
            }
        )

    try:
        from lobster_agent_runtime import _chat_completion

        content = _chat_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是一个只做纸上模拟交易的股票 Agent。"
                        "你必须根据行情、现金和持仓独立决定每个股票 BUY、SELL 或 HOLD。"
                        "不要承诺收益，不要给真实投资建议。"
                        "只输出 JSON 数组，不要输出 Markdown。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "agent_name": API_AGENT_NAME,
                            "cash": portfolio.cash,
                            "max_position_fraction_per_symbol": max_position,
                            "symbols": market_payload,
                            "output_schema": [
                                {
                                    "symbol": "AAPL",
                                    "action": "BUY|SELL|HOLD",
                                    "confidence": 0.0,
                                    "target_fraction": 0.0,
                                    "reason": "80字以内中文理由",
                                }
                            ],
                            "rules": [
                                "每个输入 symbol 必须返回且只返回一条决策。",
                                "BUY 的 target_fraction 表示目标仓位比例，范围 0 到 max_position_fraction_per_symbol。",
                                "SELL 的 target_fraction 表示卖出已有持仓的比例，范围 0.25 到 1。",
                                "HOLD 的 target_fraction 必须为 0。",
                            ],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            max_tokens=900,
            temperature=0.15,
        )
        rows = _safe_json_array(content)
        by_symbol = {str(row.get("symbol") or "").upper(): row for row in rows if isinstance(row, dict)}
        decisions: list[Decision] = []
        for symbol in quotes:
            row = by_symbol.get(symbol, {})
            action = str(row.get("action") or "HOLD").upper()
            if action not in {"BUY", "SELL", "HOLD"}:
                action = "HOLD"
            confidence = _clamp_float(row.get("confidence"), 0.5, 0.0, 1.0)
            default_fraction = 0.12 if action == "BUY" else 0.35 if action == "SELL" else 0.0
            target_fraction = _clamp_float(row.get("target_fraction"), default_fraction, 0.0, max_position)
            if action == "SELL":
                target_fraction = _clamp_float(row.get("target_fraction"), default_fraction, 0.25, 1.0)
            if action == "HOLD":
                target_fraction = 0.0
            reason = str(row.get("reason") or "NewAPI 智能体根据行情与持仓选择观望。").strip()
            decisions.append(
                Decision(
                    API_AGENT_NAME,
                    symbol,
                    action,
                    confidence,
                    reason[:180],
                    target_fraction,
                )
            )
        return (
            decisions,
            {"enabled": True, "status": "ok", "decision_count": len(decisions), "agent_name": API_AGENT_NAME},
        )
    except Exception as exc:
        return (
            [
                Decision(API_AGENT_NAME, symbol, "HOLD", 0.0, f"NewAPI 智能体调用失败，本轮保守观望：{exc}")
                for symbol in quotes
            ],
            {
                "enabled": True,
                "status": "error",
                "decision_count": 0,
                "agent_name": API_AGENT_NAME,
                "errors": [str(exc)],
            },
        )


def run_lobster_arena(
    symbols: list[str] | None = None,
    initial_cash: float = 100000.0,
    fee_rate: float = 0.001,
    max_position: float = 0.3,
    include_api_agent: bool = False,
) -> dict[str, Any]:
    normalized_symbols = [symbol.strip().upper() for symbol in (symbols or DEFAULT_SYMBOLS) if symbol.strip()]
    if not normalized_symbols:
        raise LobsterArenaError("At least one stock symbol is required.")

    quotes: dict[str, Quote] = {}
    history: dict[str, list[float]] = {}
    for symbol in normalized_symbols:
        try:
            quote, closes = _quote_from_chart(symbol)
        except LobsterArenaError:
            quote, closes = _fallback_quote(symbol)
        quotes[symbol] = quote
        history[symbol] = closes

    agent_decision_builders = [
        ("龙虾智能体", lambda p: _lobster_decisions(quotes, history, p)),
        ("均线智能体", lambda p: _ma_decisions(quotes, history, p)),
        ("稳健智能体", lambda p: _conservative_decisions(quotes, history)),
        ("反向智能体", lambda p: _contrarian_decisions(quotes, p)),
        ("随机基准智能体", lambda p: _random_decisions(quotes, p)),
    ]

    portfolios: list[PaperPortfolio] = []
    decisions_payload: list[dict[str, Any]] = []
    api_agent_status: dict[str, Any] = {"enabled": False, "status": "disabled", "decision_count": 0}
    for agent_name, build_decisions in agent_decision_builders:
        portfolio = PaperPortfolio(agent=agent_name, cash=initial_cash)
        decisions = build_decisions(portfolio)
        for decision in decisions:
            portfolio.execute(decision, quotes, max_position=max_position, fee_rate=fee_rate)
            decisions_payload.append(decision.__dict__)
        portfolios.append(portfolio)

    if include_api_agent:
        portfolio = PaperPortfolio(agent=API_AGENT_NAME, cash=initial_cash)
        decisions, api_agent_status = _api_agent_decisions(quotes, history, portfolio, max_position)
        for decision in decisions:
            portfolio.execute(decision, quotes, max_position=max_position, fee_rate=fee_rate)
            decisions_payload.append(decision.__dict__)
        portfolios.append(portfolio)

    leaderboard = []
    for portfolio in portfolios:
        total_value = portfolio.total_value(quotes)
        profit = total_value - initial_cash
        leaderboard.append(
            {
                "agent": portfolio.agent,
                "cash": round(portfolio.cash, 2),
                "total_value": round(total_value, 2),
                "profit": round(profit, 2),
                "return_percent": round((profit / initial_cash) * 100 if initial_cash else 0.0, 2),
                "positions": dict(sorted(portfolio.positions.items())),
                "trades": portfolio.trades,
            }
        )

    leaderboard.sort(key=lambda item: item["total_value"], reverse=True)
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "initial_cash": initial_cash,
        "fee_rate": fee_rate,
        "max_position": max_position,
        "quotes": [quote.__dict__ for quote in quotes.values()],
        "decisions": decisions_payload,
        "leaderboard": leaderboard,
        "api_agent": api_agent_status,
    }
