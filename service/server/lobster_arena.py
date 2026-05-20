from __future__ import annotations

import json
import os
import random
import statistics
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
DEFAULT_SYMBOLS = ["NVDA", "AAPL", "TSLA", "MSFT", "SPY"]

LOBSTER_AGENT_NAME = "龙虾智能体"
MA_AGENT_NAME = "均线智能体"
CONSERVATIVE_AGENT_NAME = "稳健智能体"
CONTRARIAN_AGENT_NAME = "反向智能体"
RANDOM_AGENT_NAME = "随机基准智能体"
API_AGENT_NAME = "NewAPI 智能体"

DEMO_QUOTES = {
    "NVDA": (220.78, 0.61),
    "AAPL": (294.80, 0.72),
    "TSLA": (433.45, -2.60),
    "MSFT": (407.77, -1.18),
    "SPY": (738.18, -0.15),
}

AGENT_PROFILES: dict[str, dict[str, Any]] = {
    LOBSTER_AGENT_NAME: {
        "role": "动量捕手机器人",
        "style": "进攻型，偏好短期趋势和价格弹性",
        "focus": ["当日涨跌幅", "MA5-MA20 动量", "随机扰动模拟非理性市场"],
        "risk_rule": "单票目标仓位不超过系统上限，信号不足时保持观望。",
    },
    MA_AGENT_NAME: {
        "role": "趋势跟随机器人",
        "style": "规则型，使用短中期均线交叉确认趋势",
        "focus": ["5 日均线", "20 日均线", "均线价差"],
        "risk_rule": "只在均线价差超过阈值时交易，避免频繁换手。",
    },
    CONSERVATIVE_AGENT_NAME: {
        "role": "低波动配置机器人",
        "style": "防守型，只关注核心资产池",
        "focus": ["核心股票池", "20 日均线", "单日跌幅过滤"],
        "risk_rule": "只买 SPY/MSFT/AAPL 等核心资产，仓位更小。",
    },
    CONTRARIAN_AGENT_NAME: {
        "role": "逆向交易机器人",
        "style": "反人性，寻找短期超跌或过热后的回归机会",
        "focus": ["单日大跌", "单日大涨", "已有持仓"],
        "risk_rule": "只在跌幅或涨幅达到阈值时行动。",
    },
    RANDOM_AGENT_NAME: {
        "role": "随机基准组",
        "style": "对照组，用来证明策略不是随机买卖",
        "focus": ["固定随机种子", "低仓位交易"],
        "risk_rule": "仓位很低，只作为基准参照。",
    },
    API_AGENT_NAME: {
        "role": "综合评分机器人",
        "style": "本地规则先决策，LLM 只增强解释",
        "focus": ["当日涨跌幅", "趋势动量", "波动率", "当前持仓"],
        "risk_rule": "LLM 不直接改动作和仓位，所有交易仍受本地风控约束。",
    },
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
    source: str = "yahoo"


@dataclass
class Decision:
    agent: str
    symbol: str
    action: str
    confidence: float
    reason: str
    target_fraction: float = 0.0
    signals: dict[str, Any] = field(default_factory=dict)
    risk_note: str = ""


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
    ) -> dict[str, Any] | None:
        action = decision.action.upper()
        if action not in {"BUY", "SELL"}:
            return None

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
                return {
                    "severity": "info",
                    "agent": self.agent,
                    "symbol": decision.symbol,
                    "message": "买入信号未成交：现金不足或已接近目标仓位。",
                }
            gross_value = shares * price
            fee = gross_value * fee_rate
            self.cash -= gross_value + fee
            self.positions[decision.symbol] = self.positions.get(decision.symbol, 0) + shares
        else:
            owned = self.positions.get(decision.symbol, 0)
            shares = min(owned, max(1, int(owned * max(decision.target_fraction, 0.25)))) if owned else 0
            if shares <= 0:
                return {
                    "severity": "info",
                    "agent": self.agent,
                    "symbol": decision.symbol,
                    "message": "卖出信号未成交：当前没有可卖出的模拟持仓。",
                }
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
        return None


def get_agent_profiles(include_api_agent: bool = True) -> dict[str, dict[str, Any]]:
    if include_api_agent:
        return AGENT_PROFILES.copy()
    return {name: profile for name, profile in AGENT_PROFILES.items() if name != API_AGENT_NAME}


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
        source="yahoo",
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
        source="local-fallback",
    )
    return quote, history


def _moving_average(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _technical_snapshot(symbol: str, quote: Quote, history: dict[str, list[float]]) -> dict[str, Any]:
    closes = history.get(symbol) or []
    ma5 = _moving_average(closes, 5)
    ma20 = _moving_average(closes, 20)
    momentum = 0.0 if not ma5 or not ma20 else ((ma5 - ma20) / ma20) * 100
    returns = [
        ((closes[index] - closes[index - 1]) / closes[index - 1]) * 100
        for index in range(1, len(closes))
        if closes[index - 1]
    ]
    volatility = statistics.pstdev(returns[-20:]) if len(returns) >= 2 else 0.0
    return {
        "price": round(quote.price, 4),
        "change_percent": round(quote.change_percent, 4),
        "ma5": round(ma5, 4) if ma5 else None,
        "ma20": round(ma20, 4) if ma20 else None,
        "momentum_percent": round(momentum, 4),
        "volatility_percent": round(volatility, 4),
        "data_source": quote.source,
    }


def _decision_payload(decision: Decision) -> dict[str, Any]:
    return {
        "agent": decision.agent,
        "symbol": decision.symbol,
        "action": decision.action,
        "confidence": round(decision.confidence, 4),
        "reason": decision.reason,
        "target_fraction": round(decision.target_fraction, 4),
        "signals": decision.signals,
        "risk_note": decision.risk_note,
    }


def _lobster_decisions(
    quotes: dict[str, Quote],
    history: dict[str, list[float]],
    portfolio: PaperPortfolio,
) -> list[Decision]:
    rng = random.Random(2026)
    decisions: list[Decision] = []
    for symbol, quote in quotes.items():
        signals = _technical_snapshot(symbol, quote, history)
        momentum = float(signals["momentum_percent"] or 0)
        noise = rng.uniform(-0.9, 0.9)
        score = quote.change_percent * 0.45 + momentum * 0.45 + noise
        signals["lobster_score"] = round(score, 4)
        signals["noise"] = round(noise, 4)
        if score > 0.75 and portfolio.exposure(symbol, quotes) < 0.22:
            decisions.append(
                Decision(
                    LOBSTER_AGENT_NAME,
                    symbol,
                    "BUY",
                    min(1.0, abs(score) / 3),
                    f"龙虾信号偏多：当日涨跌 {quote.change_percent:.2f}%，趋势动量 {momentum:.2f}%，综合分 {score:.2f}。",
                    0.10 + min(abs(score), 2.5) / 25,
                    signals,
                    "进攻型策略，仍受单票最大仓位限制。",
                )
            )
        elif score < -1.1 and portfolio.positions.get(symbol, 0) > 0:
            decisions.append(
                Decision(
                    LOBSTER_AGENT_NAME,
                    symbol,
                    "SELL",
                    min(1.0, abs(score) / 3),
                    f"龙虾撤退：综合风险分 {score:.2f}，选择降低已有仓位。",
                    0.35,
                    signals,
                    "只卖出已有模拟持仓，不允许裸卖空。",
                )
            )
        else:
            decisions.append(
                Decision(
                    LOBSTER_AGENT_NAME,
                    symbol,
                    "HOLD",
                    0.3,
                    f"龙虾观望：综合信号 {score:.2f}，未达到交易阈值。",
                    0.0,
                    signals,
                    "信号不足时不强行交易。",
                )
            )
    return decisions


def _ma_decisions(
    quotes: dict[str, Quote],
    history: dict[str, list[float]],
    portfolio: PaperPortfolio,
) -> list[Decision]:
    decisions: list[Decision] = []
    for symbol, quote in quotes.items():
        signals = _technical_snapshot(symbol, quote, history)
        ma5 = signals["ma5"]
        ma20 = signals["ma20"]
        if not ma5 or not ma20:
            decisions.append(
                Decision(MA_AGENT_NAME, symbol, "HOLD", 0.1, "历史数据不足，暂不生成均线信号。", 0.0, signals)
            )
            continue
        spread = (float(ma5) - float(ma20)) / float(ma20)
        signals["ma_spread_percent"] = round(spread * 100, 4)
        if spread > 0.01 and portfolio.exposure(symbol, quotes) < 0.25:
            decisions.append(
                Decision(
                    MA_AGENT_NAME,
                    symbol,
                    "BUY",
                    min(1.0, abs(spread) * 18),
                    f"5 日均线 {ma5:.2f} 高于 20 日均线 {ma20:.2f}，趋势偏强。",
                    0.18,
                    signals,
                    "趋势确认后小仓位跟随。",
                )
            )
        elif spread < -0.01 and portfolio.positions.get(symbol, 0) > 0:
            decisions.append(
                Decision(
                    MA_AGENT_NAME,
                    symbol,
                    "SELL",
                    min(1.0, abs(spread) * 18),
                    f"5 日均线 {ma5:.2f} 低于 20 日均线 {ma20:.2f}，趋势转弱。",
                    0.5,
                    signals,
                    "仅减持已有仓位。",
                )
            )
        else:
            decisions.append(
                Decision(
                    MA_AGENT_NAME,
                    symbol,
                    "HOLD",
                    0.35,
                    f"均线差值 {spread * 100:.2f}%，处于中性区间。",
                    0.0,
                    signals,
                    "避免均线接近时频繁交易。",
                )
            )
    return decisions


def _conservative_decisions(quotes: dict[str, Quote], history: dict[str, list[float]]) -> list[Decision]:
    preferred = {"SPY", "MSFT", "AAPL"}
    decisions: list[Decision] = []
    for symbol, quote in quotes.items():
        signals = _technical_snapshot(symbol, quote, history)
        if symbol not in preferred:
            decisions.append(
                Decision(CONSERVATIVE_AGENT_NAME, symbol, "HOLD", 0.25, "不在稳健核心股票池中。", 0.0, signals)
            )
            continue
        ma20 = signals["ma20"]
        if ma20 and quote.price >= float(ma20) and quote.change_percent > -1.5:
            decisions.append(
                Decision(
                    CONSERVATIVE_AGENT_NAME,
                    symbol,
                    "BUY",
                    0.65,
                    f"核心资产价格高于 20 日均线 {ma20:.2f}，允许小仓位买入。",
                    0.14,
                    signals,
                    "防守型仓位低于进攻型策略。",
                )
            )
        else:
            decisions.append(
                Decision(CONSERVATIVE_AGENT_NAME, symbol, "HOLD", 0.4, "没有达到稳健买入条件。", 0.0, signals)
            )
    return decisions


def _contrarian_decisions(quotes: dict[str, Quote], history: dict[str, list[float]], portfolio: PaperPortfolio) -> list[Decision]:
    decisions: list[Decision] = []
    for symbol, quote in quotes.items():
        signals = _technical_snapshot(symbol, quote, history)
        if quote.change_percent <= -1.8 and portfolio.exposure(symbol, quotes) < 0.2:
            decisions.append(
                Decision(
                    CONTRARIAN_AGENT_NAME,
                    symbol,
                    "BUY",
                    min(1.0, abs(quote.change_percent) / 4),
                    f"当日下跌 {quote.change_percent:.2f}%，触发低吸策略。",
                    0.12,
                    signals,
                    "逆向策略只做小仓位试探。",
                )
            )
        elif quote.change_percent >= 2.0 and portfolio.positions.get(symbol, 0) > 0:
            decisions.append(
                Decision(
                    CONTRARIAN_AGENT_NAME,
                    symbol,
                    "SELL",
                    min(1.0, quote.change_percent / 4),
                    f"当日上涨 {quote.change_percent:.2f}%，触发止盈减仓。",
                    0.4,
                    signals,
                    "只卖出已有模拟持仓。",
                )
            )
        else:
            decisions.append(
                Decision(CONTRARIAN_AGENT_NAME, symbol, "HOLD", 0.3, "没有明显低吸或止盈信号。", 0.0, signals)
            )
    return decisions


def _random_decisions(quotes: dict[str, Quote], history: dict[str, list[float]], portfolio: PaperPortfolio) -> list[Decision]:
    rng = random.Random(7)
    decisions: list[Decision] = []
    for symbol, quote in quotes.items():
        signals = _technical_snapshot(symbol, quote, history)
        roll = rng.random()
        signals["random_roll"] = round(roll, 4)
        if roll < 0.18 and portfolio.exposure(symbol, quotes) < 0.15:
            decisions.append(
                Decision(RANDOM_AGENT_NAME, symbol, "BUY", 0.2, "随机基准策略触发买入，用作对照组。", 0.08, signals)
            )
        elif roll > 0.88 and portfolio.positions.get(symbol, 0) > 0:
            decisions.append(
                Decision(RANDOM_AGENT_NAME, symbol, "SELL", 0.2, "随机基准策略触发卖出，用作对照组。", 0.5, signals)
            )
        else:
            decisions.append(
                Decision(RANDOM_AGENT_NAME, symbol, "HOLD", 0.2, "随机基准策略保持观望。", 0.0, signals)
            )
    return decisions


def _api_agent_decisions(
    quotes: dict[str, Quote],
    history: dict[str, list[float]],
    portfolio: PaperPortfolio,
    max_position: float,
) -> tuple[list[Decision], dict[str, Any]]:
    decisions: list[Decision] = []
    for symbol, quote in quotes.items():
        signals = _technical_snapshot(symbol, quote, history)
        momentum = float(signals["momentum_percent"] or 0)
        volatility = float(signals["volatility_percent"] or 0)
        score = quote.change_percent * 0.35 + momentum * 0.5 - volatility * 0.08
        signals["composite_score"] = round(score, 4)
        if score > 0.6 and portfolio.exposure(symbol, quotes) < max_position * 0.75:
            action = "BUY"
            target = min(max_position, 0.12 + min(score, 2.4) / 24)
            confidence = min(0.92, 0.45 + abs(score) / 4)
            reason = f"综合评分 {score:.2f} 偏多，趋势动量 {momentum:.2f}%，波动 {volatility:.2f}%，本地策略建议买入。"
        elif score < -0.9 and portfolio.positions.get(symbol, 0) > 0:
            action = "SELL"
            target = 0.35
            confidence = min(0.9, 0.45 + abs(score) / 4)
            reason = f"综合评分 {score:.2f} 偏弱，优先保护已有模拟收益，建议减仓。"
        else:
            action = "HOLD"
            target = 0.0
            confidence = 0.35
            reason = f"综合评分 {score:.2f} 未达到交易阈值，保持观望。"
        decisions.append(
            Decision(
                API_AGENT_NAME,
                symbol,
                action,
                confidence,
                reason,
                target,
                signals,
                "该智能体由本地规则决策；LLM 只允许改写解释，不允许改动作和仓位。",
            )
        )
    return (
        decisions,
        {
            "enabled": True,
            "status": "local_strategy",
            "decision_count": len(decisions),
            "agent_name": API_AGENT_NAME,
            "llm_decision_permission": "disabled",
        },
    )


def build_agent_reports(result: dict[str, Any]) -> list[dict[str, Any]]:
    profiles = result.get("agent_profiles") or AGENT_PROFILES
    decisions = result.get("decisions") or []
    leaderboard_by_agent = {row.get("agent"): row for row in result.get("leaderboard") or []}
    reports: list[dict[str, Any]] = []
    for agent_name, profile in profiles.items():
        agent_decisions = [item for item in decisions if item.get("agent") == agent_name]
        if not agent_decisions and agent_name not in leaderboard_by_agent:
            continue
        counts = {
            "BUY": sum(1 for item in agent_decisions if item.get("action") == "BUY"),
            "SELL": sum(1 for item in agent_decisions if item.get("action") == "SELL"),
            "HOLD": sum(1 for item in agent_decisions if item.get("action") == "HOLD"),
        }
        row = leaderboard_by_agent.get(agent_name, {})
        trades = row.get("trades") or []
        top_reason = next((item.get("reason") for item in agent_decisions if item.get("action") != "HOLD"), None)
        reports.append(
            {
                "agent": agent_name,
                "profile": profile,
                "decision_counts": counts,
                "trade_count": len(trades),
                "return_percent": row.get("return_percent", 0),
                "total_value": row.get("total_value"),
                "positions": row.get("positions", {}),
                "review": top_reason or "本轮未出现足够强的交易信号，策略选择等待更清晰的行情。",
            }
        )
    return reports


def build_risk_events(result: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    max_position = float(result.get("max_position") or 0)
    quote_by_symbol = {item["symbol"]: item for item in result.get("quotes") or []}
    if any(item.get("source") == "local-fallback" for item in quote_by_symbol.values()):
        events.append(
            {
                "severity": "warning",
                "code": "fallback_market_data",
                "message": "部分行情使用本地演示数据兜底，适合课堂演示，不代表实时行情。",
            }
        )
    for row in result.get("leaderboard") or []:
        total_value = float(row.get("total_value") or 0)
        if not total_value:
            continue
        for symbol, quantity in (row.get("positions") or {}).items():
            quote = quote_by_symbol.get(symbol)
            if not quote:
                continue
            exposure = abs(float(quantity or 0) * float(quote.get("price") or 0)) / total_value
            if max_position and exposure > max_position + 0.01:
                events.append(
                    {
                        "severity": "warning",
                        "code": "position_limit",
                        "agent": row.get("agent"),
                        "symbol": symbol,
                        "message": f"{row.get('agent')} 的 {symbol} 仓位 {exposure:.1%} 接近或超过上限 {max_position:.0%}。",
                    }
                )
    if not events:
        events.append(
            {
                "severity": "ok",
                "code": "paper_guardrails_ok",
                "message": "本轮交易均为模拟撮合，未触发实盘下单，仓位约束正常。",
            }
        )
    return events


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

    agent_decision_builders: list[tuple[str, Callable[[PaperPortfolio], list[Decision]]]] = [
        (LOBSTER_AGENT_NAME, lambda p: _lobster_decisions(quotes, history, p)),
        (MA_AGENT_NAME, lambda p: _ma_decisions(quotes, history, p)),
        (CONSERVATIVE_AGENT_NAME, lambda p: _conservative_decisions(quotes, history)),
        (CONTRARIAN_AGENT_NAME, lambda p: _contrarian_decisions(quotes, history, p)),
        (RANDOM_AGENT_NAME, lambda p: _random_decisions(quotes, history, p)),
    ]

    portfolios: list[PaperPortfolio] = []
    decisions_payload: list[dict[str, Any]] = []
    risk_events: list[dict[str, Any]] = []
    api_agent_status: dict[str, Any] = {"enabled": False, "status": "disabled", "decision_count": 0}
    for agent_name, build_decisions in agent_decision_builders:
        portfolio = PaperPortfolio(agent=agent_name, cash=initial_cash)
        decisions = build_decisions(portfolio)
        for decision in decisions:
            event = portfolio.execute(decision, quotes, max_position=max_position, fee_rate=fee_rate)
            if event:
                risk_events.append(event)
            decisions_payload.append(_decision_payload(decision))
        portfolios.append(portfolio)

    if include_api_agent:
        portfolio = PaperPortfolio(agent=API_AGENT_NAME, cash=initial_cash)
        decisions, api_agent_status = _api_agent_decisions(quotes, history, portfolio, max_position)
        for decision in decisions:
            event = portfolio.execute(decision, quotes, max_position=max_position, fee_rate=fee_rate)
            if event:
                risk_events.append(event)
            decisions_payload.append(_decision_payload(decision))
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
    result = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "initial_cash": initial_cash,
        "fee_rate": fee_rate,
        "max_position": max_position,
        "quotes": [quote.__dict__ for quote in quotes.values()],
        "decisions": decisions_payload,
        "leaderboard": leaderboard,
        "api_agent": api_agent_status,
        "agent_profiles": get_agent_profiles(include_api_agent=include_api_agent),
        "risk_events": risk_events,
    }
    result["agent_reports"] = build_agent_reports(result)
    result["risk_events"] = [*risk_events, *build_risk_events(result)]
    return result
