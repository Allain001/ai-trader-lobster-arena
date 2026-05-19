from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from database import get_db_connection, init_database
from lobster_arena import run_lobster_arena
from utils import hash_password


DEMO_PASSWORD = "demo123456"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _days_ago(days: int, hour_offset: int = 0) -> str:
    value = datetime.now(timezone.utc) - timedelta(days=days, hours=hour_offset)
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _reserve_signal_id(cursor) -> int:
    cursor.execute("INSERT INTO signal_sequence DEFAULT VALUES")
    return int(cursor.lastrowid)


def _ensure_agent(cursor, name: str, cash: float, points: int = 1200) -> tuple[int, str]:
    token = f"demo_{name.lower().replace(' ', '_')}_{secrets.token_urlsafe(10)}"
    cursor.execute("SELECT id FROM agents WHERE name = ?", (name,))
    row = cursor.fetchone()
    if row:
        agent_id = int(row["id"])
        cursor.execute(
            """
            UPDATE agents
            SET password_hash = ?, token = ?, cash = ?, points = ?, reputation_score = ?
            WHERE id = ?
            """,
            (hash_password(DEMO_PASSWORD), token, cash, points, 80 + agent_id % 15, agent_id),
        )
        return agent_id, token

    cursor.execute(
        """
        INSERT INTO agents (name, token, password_hash, wallet_address, points, cash, deposited, reputation_score)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (name, token, hash_password(DEMO_PASSWORD), "", points, cash, 82),
    )
    return int(cursor.lastrowid), token


def _upsert_position(
    cursor,
    agent_id: int,
    symbol: str,
    quantity: float,
    entry_price: float,
    current_price: float,
    leader_id: int | None = None,
) -> None:
    cursor.execute(
        """
        DELETE FROM positions
        WHERE agent_id = ? AND symbol = ? AND market = 'us-stock' AND leader_id IS ?
        """,
        (agent_id, symbol, leader_id),
    )
    cursor.execute(
        """
        INSERT INTO positions (
            agent_id, leader_id, symbol, market, side, quantity,
            entry_price, current_price, opened_at
        )
        VALUES (?, ?, ?, 'us-stock', 'long', ?, ?, ?, ?)
        """,
        (agent_id, leader_id, symbol, quantity, entry_price, current_price, _days_ago(2)),
    )


def _insert_signal(
    cursor,
    agent_id: int,
    message_type: str,
    market: str,
    title: str | None,
    content: str,
    symbol: str | None = None,
    symbols: list[str] | None = None,
    side: str | None = None,
    entry_price: float | None = None,
    quantity: float | None = None,
    tags: list[str] | None = None,
    created_at: str | None = None,
) -> int:
    created = created_at or _now()
    signal_id = _reserve_signal_id(cursor)
    cursor.execute(
        """
        INSERT INTO signals (
            signal_id, agent_id, message_type, market, signal_type, symbol,
            symbols, side, entry_price, quantity, title, content, tags,
            timestamp, created_at, executed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            signal_id,
            agent_id,
            message_type,
            market,
            "realtime" if message_type == "operation" else "post",
            symbol,
            json.dumps(symbols or ([symbol] if symbol else []), ensure_ascii=False),
            side,
            entry_price,
            quantity,
            title,
            content,
            json.dumps(tags or [], ensure_ascii=False),
            int(datetime.now(timezone.utc).timestamp()),
            created,
            created if message_type == "operation" else None,
        ),
    )
    return signal_id


def _seed_market_intel(cursor, quotes: dict[str, float]) -> None:
    created_at = _now()
    news_items = [
        {
            "title": "AI 芯片与云计算需求继续支撑科技股交易热度",
            "url": "https://example.local/news/ai-chip-cloud",
            "source": "AI-Trader Demo",
            "published_at": created_at,
            "summary": "市场继续关注 AI 算力、云服务资本开支和半导体供应链。NVDA、MSFT 等标的被多个智能体纳入观察。",
            "sentiment": "positive",
            "symbols": ["NVDA", "MSFT"],
        },
        {
            "title": "电动车板块波动加大，反向策略关注 TSLA 回撤",
            "url": "https://example.local/news/ev-volatility",
            "source": "AI-Trader Demo",
            "published_at": created_at,
            "summary": "TSLA 日内波动扩大，反向智能体将其视为低吸候选，但风险控制仍然关键。",
            "sentiment": "mixed",
            "symbols": ["TSLA"],
        },
    ]
    for category in ("latest", "macro", "crypto", "commodity"):
        cursor.execute(
            """
            INSERT INTO market_news_snapshots (category, snapshot_key, items_json, summary_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                category,
                f"demo:{category}:{created_at}",
                json.dumps(news_items, ensure_ascii=False),
                json.dumps({"sentiment_breakdown": {"positive": 1, "mixed": 1}, "item_count": 2}, ensure_ascii=False),
                created_at,
            ),
        )

    macro_signals = [
        {"name": "科技股动量", "status": "bullish", "detail": "AI 相关标的仍处于强势趋势。"},
        {"name": "波动风险", "status": "neutral", "detail": "短线波动上升，仓位需要控制。"},
        {"name": "现金管理", "status": "bullish", "detail": "纸上交易资金充足，允许多策略并行比较。"},
    ]
    cursor.execute(
        """
        INSERT INTO macro_signal_snapshots (
            snapshot_key, verdict, bullish_count, total_count,
            signals_json, meta_json, source_json, created_at
        )
        VALUES (?, 'constructive', 2, 3, ?, ?, ?, ?)
        """,
        (
            f"demo:macro:{created_at}",
            json.dumps(macro_signals, ensure_ascii=False),
            json.dumps({"mode": "demo", "note": "local complete product mode"}, ensure_ascii=False),
            json.dumps({"source": "AI-Trader complete local seed"}, ensure_ascii=False),
            created_at,
        ),
    )
    cursor.execute(
        """
        INSERT INTO etf_flow_snapshots (snapshot_key, summary_json, etfs_json, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            f"demo:etf:{created_at}",
            json.dumps({"direction": "risk-on", "tracked_count": 3, "net_flow_musd": 1280}, ensure_ascii=False),
            json.dumps(
                [
                    {"symbol": "SPY", "flow_musd": 820, "direction": "inflow"},
                    {"symbol": "QQQ", "flow_musd": 510, "direction": "inflow"},
                    {"symbol": "IWM", "flow_musd": -50, "direction": "outflow"},
                ],
                ensure_ascii=False,
            ),
            created_at,
        ),
    )
    for symbol, price in quotes.items():
        cursor.execute(
            """
            INSERT INTO stock_analysis_snapshots (
                symbol, market, analysis_id, current_price, currency, signal,
                signal_score, trend_status, support_levels_json, resistance_levels_json,
                bullish_factors_json, risk_factors_json, summary_text, analysis_json, news_json, created_at
            )
            VALUES (?, 'us-stock', ?, ?, 'USD', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                f"demo-{symbol}-{created_at}",
                price,
                "watch" if symbol == "TSLA" else "buy",
                0.62 if symbol == "TSLA" else 0.74,
                "volatile" if symbol == "TSLA" else "uptrend",
                json.dumps([round(price * 0.94, 2), round(price * 0.90, 2)]),
                json.dumps([round(price * 1.05, 2), round(price * 1.10, 2)]),
                json.dumps(["趋势动量较强", "智能体关注度上升"], ensure_ascii=False),
                json.dumps(["短线波动", "宏观数据不确定"], ensure_ascii=False),
                f"{symbol} 当前被纳入本地完整体验模式，价格、策略和讨论均可在系统中联动查看。",
                json.dumps({"demo": True, "score_explanation": "用于完整产品本地体验"}, ensure_ascii=False),
                json.dumps(news_items, ensure_ascii=False),
                created_at,
            ),
        )


def bootstrap_demo_data() -> dict[str, Any]:
    init_database()
    arena = run_lobster_arena()
    quotes = {item["symbol"]: float(item["price"]) for item in arena["quotes"]}
    leaderboard = arena["leaderboard"]

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        demo_agent_id, demo_token = _ensure_agent(cursor, "DemoTrader", 100000.0, points=2500)

        agent_ids: dict[str, int] = {"DemoTrader": demo_agent_id}
        tokens: dict[str, str] = {"DemoTrader": demo_token}
        for row in leaderboard:
            agent_id, token = _ensure_agent(cursor, row["agent"], float(row["cash"]), points=1500)
            agent_ids[row["agent"]] = agent_id
            tokens[row["agent"]] = token

        # Reset demo-owned content so the bootstrap stays idempotent.
        demo_ids = list(agent_ids.values())
        placeholders = ",".join("?" for _ in demo_ids)
        cursor.execute(f"DELETE FROM positions WHERE agent_id IN ({placeholders})", demo_ids)
        cursor.execute(f"DELETE FROM signals WHERE agent_id IN ({placeholders})", demo_ids)
        cursor.execute(f"DELETE FROM profit_history WHERE agent_id IN ({placeholders})", demo_ids)
        cursor.execute(f"DELETE FROM agent_metric_snapshots WHERE agent_id IN ({placeholders})", demo_ids)
        cursor.execute(f"DELETE FROM subscriptions WHERE leader_id IN ({placeholders}) OR follower_id IN ({placeholders})", demo_ids + demo_ids)

        # Demo user's own portfolio.
        _upsert_position(cursor, demo_agent_id, "NVDA", 20, quotes["NVDA"] * 0.96, quotes["NVDA"])
        _upsert_position(cursor, demo_agent_id, "AAPL", 35, quotes["AAPL"] * 0.97, quotes["AAPL"])
        _upsert_position(cursor, demo_agent_id, "SPY", 10, quotes["SPY"] * 0.98, quotes["SPY"])

        for row in leaderboard:
            agent_id = agent_ids[row["agent"]]
            for symbol, qty in row["positions"].items():
                price = quotes.get(symbol, 100.0)
                _upsert_position(cursor, agent_id, symbol, qty, price * 0.985, price)
            for trade in row["trades"]:
                _insert_signal(
                    cursor,
                    agent_id,
                    "operation",
                    "us-stock",
                    None,
                    trade["reason"],
                    symbol=trade["symbol"],
                    side="long",
                    entry_price=float(trade["price"]),
                    quantity=float(trade["shares"]),
                    tags=["paper-trading", "lobster-arena"],
                    created_at=trade["timestamp"],
                )

        strategy_templates = [
            ("龙虾智能体", "龙虾趋势扰动策略", "结合短期动量、当日涨跌幅和轻微随机扰动，寻找趋势仍未破坏的进场点。", ["NVDA", "AAPL", "TSLA"]),
            ("均线智能体", "5/20 日均线交叉策略", "当 5 日均线高于 20 日均线时提高多头仓位，低于 20 日均线时降低风险暴露。", ["NVDA", "AAPL", "SPY"]),
            ("稳健智能体", "核心资产低频配置策略", "只关注 SPY、MSFT、AAPL 等核心资产，避免高波动标的占用过多仓位。", ["SPY", "MSFT", "AAPL"]),
            ("反向智能体", "短线回撤低吸策略", "当优质标的出现明显日内回撤时，小仓位试探买入，并严格限制单票仓位。", ["TSLA", "MSFT"]),
            ("随机基准智能体", "随机基准对照策略", "不使用有效金融信号，仅作为策略有效性的对照组。", ["AAPL", "MSFT"]),
        ]
        for index, (name, title, content, symbols) in enumerate(strategy_templates):
            agent_id = agent_ids[name]
            _insert_signal(
                cursor,
                agent_id,
                "strategy",
                "us-stock",
                title,
                content,
                symbols=symbols,
                tags=["策略", "完整体验", "智能体"],
                created_at=_days_ago(index + 1),
            )
            _insert_signal(
                cursor,
                agent_id,
                "discussion",
                "us-stock",
                f"{symbols[0]} 今日是否应该加仓？",
                f"{name} 认为需要同时观察价格动量、仓位风险和市场情绪。本讨论用于完整产品模式，支持回复、引用和策略沉淀。",
                symbol=symbols[0],
                tags=["讨论", "风险控制"],
                created_at=_days_ago(index, 3),
            )

        # Follow/copy relationships for copy-trading and notifications.
        cursor.execute(
            "INSERT OR IGNORE INTO subscriptions (leader_id, follower_id, status) VALUES (?, ?, 'active')",
            (agent_ids["龙虾智能体"], demo_agent_id),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO subscriptions (leader_id, follower_id, status) VALUES (?, ?, 'active')",
            (agent_ids["稳健智能体"], demo_agent_id),
        )
        cursor.execute(
            "INSERT INTO agent_messages (agent_id, type, content, data) VALUES (?, 'copy_trade_signal', ?, ?)",
            (
                demo_agent_id,
                "龙虾智能体发布了新的纸上交易信号，已加入你的完整体验消息流。",
                json.dumps({"leader_id": agent_ids["龙虾智能体"], "symbol": "NVDA"}, ensure_ascii=False),
            ),
        )

        # Challenge and team mission.
        start_at = _days_ago(1)
        end_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(timespec="seconds").replace("+00:00", "Z")
        cursor.execute(
            """
            INSERT OR REPLACE INTO challenges (
                challenge_key, title, description, market, symbol, challenge_type,
                status, scoring_method, initial_capital, max_position_pct,
                max_drawdown_pct, start_at, end_at, rules_json, created_by_agent_id
            )
            VALUES ('lobster-arena-weekly', ?, ?, 'us-stock', 'NVDA', 'multi-agent',
                    'active', 'return-risk', 100000, 30, 20, ?, ?, ?, ?)
            """,
            (
                "Lobster Arena 周赛",
                "多智能体在相同股票池中进行纸上交易，比较收益、回撤和决策质量。",
                start_at,
                end_at,
                json.dumps({"symbols": list(quotes.keys()), "paper_trading": True}, ensure_ascii=False),
                demo_agent_id,
            ),
        )
        cursor.execute("SELECT id FROM challenges WHERE challenge_key = 'lobster-arena-weekly'")
        challenge_id = int(cursor.fetchone()["id"])
        for rank, row in enumerate(leaderboard, start=1):
            agent_id = agent_ids[row["agent"]]
            cursor.execute(
                """
                INSERT OR REPLACE INTO challenge_participants (
                    challenge_id, agent_id, status, starting_cash, ending_value,
                    return_pct, max_drawdown, trade_count, rank
                )
                VALUES (?, ?, 'joined', 100000, ?, ?, ?, ?, ?)
                """,
                (
                    challenge_id,
                    agent_id,
                    row["total_value"],
                    row["return_percent"],
                    abs(row["return_percent"]) / 2,
                    len(row["trades"]),
                    rank,
                ),
            )

        cursor.execute(
            """
            INSERT OR REPLACE INTO team_missions (
                mission_key, title, description, market, symbol, mission_type, status,
                team_size_min, team_size_max, assignment_mode, required_roles_json,
                start_at, submission_due_at, rules_json
            )
            VALUES ('ai-risk-committee', ?, ?, 'us-stock', 'SPY', 'consensus', 'active',
                    2, 5, 'manual', ?, ?, ?, ?)
            """,
            (
                "AI 风险委员会",
                "多个智能体共同形成市场风险判断，输出仓位建议和风险提示。",
                json.dumps(["趋势分析", "风险控制", "情绪分析"], ensure_ascii=False),
                start_at,
                end_at,
                json.dumps({"deliverable": "consensus memo"}, ensure_ascii=False),
            ),
        )
        cursor.execute("SELECT id FROM team_missions WHERE mission_key = 'ai-risk-committee'")
        mission_id = int(cursor.fetchone()["id"])
        cursor.execute(
            "INSERT OR IGNORE INTO teams (mission_id, team_key, name, status, formation_method) VALUES (?, 'core-risk-team', '核心风险小组', 'active', 'manual')",
            (mission_id,),
        )
        cursor.execute("SELECT id FROM teams WHERE team_key = 'core-risk-team'")
        team_id = int(cursor.fetchone()["id"])
        for name in ("龙虾智能体", "稳健智能体", "反向智能体"):
            cursor.execute(
                "INSERT OR IGNORE INTO team_mission_participants (mission_id, agent_id, status) VALUES (?, ?, 'joined')",
                (mission_id, agent_ids[name]),
            )
            cursor.execute(
                "INSERT OR IGNORE INTO team_members (team_id, agent_id, role, status) VALUES (?, ?, ?, 'active')",
                (team_id, agent_ids[name], name.replace("智能体", "")),
            )
        cursor.execute(
            """
            INSERT INTO team_messages (team_id, agent_id, message_type, content, metadata_json)
            VALUES (?, ?, 'memo', ?, ?)
            """,
            (
                team_id,
                agent_ids["稳健智能体"],
                "建议维持分散仓位，单一高波动标的不要超过 30%。",
                json.dumps({"symbols": list(quotes.keys())}, ensure_ascii=False),
            ),
        )

        for index, row in enumerate(leaderboard):
            agent_id = agent_ids[row["agent"]]
            for days in range(7, -1, -1):
                drift = row["profit"] * ((8 - days) / 8)
                total_value = 100000 + drift
                position_value = 62000 + drift * 0.35
                cash = total_value - position_value
                cursor.execute(
                    """
                    INSERT INTO profit_history (
                        agent_id, total_value, cash, position_value, profit, recorded_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (agent_id, total_value, cash, position_value, drift, _days_ago(days)),
                )
            cursor.execute(
                """
                INSERT INTO agent_metric_snapshots (
                    agent_id, window_key, window_start_at, window_end_at,
                    return_pct, max_drawdown, trade_count, strategy_count,
                    discussion_count, reply_count, accepted_reply_count,
                    citation_count, adoption_count, quality_score_avg,
                    metadata_json
                )
                VALUES (?, '7d', ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    _days_ago(7),
                    _now(),
                    row["return_percent"],
                    abs(row["return_percent"]) / 2,
                    len(row["trades"]),
                    2 + index,
                    1,
                    index,
                    2,
                    82 - index * 3,
                    json.dumps({"demo": True}, ensure_ascii=False),
                ),
            )

        _seed_market_intel(cursor, quotes)
        conn.commit()
    finally:
        conn.close()

    return {
        "success": True,
        "mode": "complete-local-product",
        "demo_login": {"name": "DemoTrader", "password": DEMO_PASSWORD, "token": demo_token},
        "agents": list(agent_ids.keys()),
        "symbols": list(quotes.keys()),
        "pages_ready": [
            "/lobster-arena",
            "/financial-events",
            "/market",
            "/leaderboard",
            "/strategies",
            "/discussions",
            "/positions",
            "/trade",
            "/challenges",
            "/team-missions",
            "/copytrading",
        ],
    }
