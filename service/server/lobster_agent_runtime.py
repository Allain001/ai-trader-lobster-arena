from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any

import requests

from database import begin_write_transaction, get_database_status, get_db_connection
from fees import TRADE_FEE_RATE
from services import _reserve_signal_id, _update_position_from_signal
from utils import hash_password


AGENT_PASSWORD = "agent123456"
LLM_DECISION_LIMIT = 12
LAST_AUTORUN_STATUS: dict[str, Any] = {
    "enabled": False,
    "running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_error": None,
    "runs": 0,
    "last_result": None,
}


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _timestamp(value: str | None = None) -> int:
    raw = value or _utc_now()
    try:
        return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp())
    except Exception:
        return int(datetime.now(timezone.utc).timestamp())


def _ensure_agent(cursor, name: str, cash: float) -> tuple[int, str]:
    cursor.execute("SELECT id, token FROM agents WHERE name = ?", (name,))
    row = cursor.fetchone()
    if row:
        token = row["token"] or f"lobster_{secrets.token_urlsafe(16)}"
        cursor.execute(
            "UPDATE agents SET token = COALESCE(token, ?), cash = MAX(cash, ?), reputation_score = MAX(reputation_score, 78) WHERE id = ?",
            (token, cash, row["id"]),
        )
        return int(row["id"]), token

    token = f"lobster_{secrets.token_urlsafe(16)}"
    cursor.execute(
        """
        INSERT INTO agents (name, token, password_hash, wallet_address, points, cash, deposited, reputation_score)
        VALUES (?, ?, ?, '', 1500, ?, 0, 80)
        """,
        (name, token, hash_password(AGENT_PASSWORD), cash),
    )
    return int(cursor.lastrowid), token


def _current_quantity(cursor, agent_id: int, symbol: str) -> float:
    cursor.execute(
        """
        SELECT quantity FROM positions
        WHERE agent_id = ? AND market = 'us-stock' AND symbol = ?
        """,
        (agent_id, symbol),
    )
    row = cursor.fetchone()
    return float(row["quantity"]) if row else 0.0


def _insert_operation_signal(cursor, agent_id: int, trade: dict[str, Any]) -> int | None:
    symbol = str(trade.get("symbol") or "").upper()
    action = str(trade.get("action") or "").lower()
    quantity = float(trade.get("shares") or 0)
    price = float(trade.get("price") or 0)
    if not symbol or action not in {"buy", "sell"} or quantity <= 0 or price <= 0:
        return None

    if action == "sell":
        current_qty = _current_quantity(cursor, agent_id, symbol)
        if current_qty <= 0:
            return None
        quantity = min(quantity, current_qty)

    trade_value = price * quantity
    fee = trade_value * TRADE_FEE_RATE
    if action == "buy":
        cursor.execute("SELECT cash FROM agents WHERE id = ?", (agent_id,))
        row = cursor.fetchone()
        if not row or float(row["cash"] or 0) < trade_value + fee:
            return None

    executed_at = str(trade.get("timestamp") or _utc_now())
    if not executed_at.endswith("Z") and "+00:00" not in executed_at:
        executed_at = executed_at + "Z"
    created_at = _utc_now()
    signal_id = _reserve_signal_id(cursor)
    content = str(trade.get("reason") or "")
    cursor.execute(
        """
        INSERT INTO signals
        (signal_id, agent_id, message_type, market, signal_type, symbol, side, entry_price, quantity, content, timestamp, created_at, executed_at)
        VALUES (?, ?, 'operation', 'us-stock', 'lobster-arena', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            signal_id,
            agent_id,
            symbol,
            action,
            price,
            quantity,
            content,
            _timestamp(executed_at),
            created_at,
            executed_at,
        ),
    )
    _update_position_from_signal(
        agent_id,
        symbol,
        "us-stock",
        action,
        quantity,
        price,
        executed_at,
        cursor=cursor,
    )
    if action == "buy":
        cursor.execute("UPDATE agents SET cash = cash - ? WHERE id = ?", (trade_value + fee, agent_id))
    else:
        cursor.execute("UPDATE agents SET cash = cash + ? WHERE id = ?", (trade_value - fee, agent_id))
    return signal_id


def _action_label(action: str) -> str:
    return {"BUY": "买入", "SELL": "卖出", "HOLD": "观望"}.get(action.upper(), action)


def _agent_voice(agent_name: str) -> dict[str, str]:
    voices = {
        "龙虾智能体": {
            "tone": "我偏短线，先看资金有没有继续追高的意愿。",
            "question": "你们觉得这个动量还能撑几天，还是应该等一次回踩？",
            "risk": "如果明天高开但量能跟不上，我会更倾向于减一点仓。",
        },
        "均线智能体": {
            "tone": "我主要看均线结构，不太追单日情绪。",
            "question": "现在的问题是均线给了方向，但入场点并不算便宜。",
            "risk": "如果 5 日线重新压回 20 日线下方，我会把这轮信号降级。",
        },
        "稳健智能体": {
            "tone": "我更关心组合能不能扛住回撤，而不是单票冲得多快。",
            "question": "这里适合慢慢配，不适合一下子把仓位打满。",
            "risk": "如果大盘一起转弱，先保留现金比追求满仓更重要。",
        },
        "反向智能体": {
            "tone": "我看的是情绪过头后的修复机会，不是盲目抄底。",
            "question": "如果继续跌，我会等更明显的止跌信号，不急着接飞刀。",
            "risk": "反向策略最怕趋势性下跌，所以仓位必须轻。",
        },
        "随机基准智能体": {
            "tone": "我这组主要是对照实验，帮大家判断其他策略有没有真的跑赢随机。",
            "question": "如果规则策略连随机基准都打不过，就要重新检查信号质量。",
            "risk": "我不会把随机结果解释成有效观点，只用于比较。",
        },
        "NewAPI 智能体": {
            "tone": "我把动量、波动和已有持仓合在一起打分，但动作仍受本地风控约束。",
            "question": "这里最值得讨论的是：信号强度够不够覆盖波动风险？",
            "risk": "LLM 只写解释，不会改买卖动作和仓位。",
        },
    }
    return voices.get(
        agent_name,
        {
            "tone": "我会先看信号质量，再看仓位是否值得调整。",
            "question": "这个位置更像观察点，还是已经值得执行？",
            "risk": "所有动作都要先过现金、持仓和最大仓位限制。",
        },
    )


def _build_strategy_post(agent_name: str, decisions: list[dict[str, Any]]) -> tuple[str, str, list[str]]:
    tradable = [item for item in decisions if str(item.get("action") or "").upper() in {"BUY", "SELL"}]
    focus = tradable[:3] or decisions[:3]
    symbols = sorted({str(item.get("symbol") or "").upper() for item in decisions if item.get("symbol")})
    buy_count = sum(1 for item in decisions if str(item.get("action") or "").upper() == "BUY")
    sell_count = sum(1 for item in decisions if str(item.get("action") or "").upper() == "SELL")
    hold_count = sum(1 for item in decisions if str(item.get("action") or "").upper() == "HOLD")
    lead = focus[0] if focus else {}
    lead_symbol = str(lead.get("symbol") or (symbols[0] if symbols else "市场"))
    lead_action = _action_label(str(lead.get("action") or "HOLD"))
    title = f"{agent_name}：{lead_symbol} {lead_action}计划与风控边界"
    lines = [
        "本轮策略结论：先执行高置信度信号，低置信度标的保持观察，不做满仓押注。",
        f"动作分布：买入 {buy_count} 个，卖出 {sell_count} 个，观望 {hold_count} 个。",
        "重点标的：",
    ]
    for item in focus:
        confidence = round(float(item.get("confidence") or 0) * 100)
        target = round(float(item.get("target_fraction") or 0) * 100)
        reason = str(item.get("reason") or "").strip()
        lines.append(
            f"- {item.get('symbol')}：{_action_label(str(item.get('action') or 'HOLD'))}，"
            f"置信度 {confidence}%，目标仓位 {target}%。{reason}"
        )
    lines.extend(
        [
            "执行原则：买入前检查现金和单票仓位上限，卖出前检查已有持仓；没有足够依据时宁可不交易。",
            "风险提示：这是纸上交易策略，不代表真实投资建议。",
        ]
    )
    return title, "\n".join(lines), symbols


def _build_discussion_post(agent_name: str, decisions: list[dict[str, Any]]) -> tuple[str, str, str]:
    voice = _agent_voice(agent_name)
    tradable = [item for item in decisions if str(item.get("action") or "").upper() in {"BUY", "SELL"}]
    focus = (tradable or decisions or [{}])[0]
    symbol = str(focus.get("symbol") or "市场").upper()
    action = _action_label(str(focus.get("action") or "HOLD"))
    confidence = round(float(focus.get("confidence") or 0) * 100)
    reason = str(focus.get("reason") or "").strip()
    title = f"{symbol} 这里要不要跟？{agent_name}的盘中想法"
    content = (
        f"{voice['tone']}\n\n"
        f"我这轮对 {symbol} 的动作是{action}，置信度大约 {confidence}%。"
        f"{' 触发点是：' + reason if reason else ''}\n\n"
        f"{voice['question']}\n"
        f"{voice['risk']}\n\n"
        "欢迎从基本面、技术面或者仓位管理角度反驳，我会把有效回复纳入下一轮模拟复盘。"
    )
    return symbol, title, content


def _insert_agent_posts(cursor, agent_id: int, agent_name: str, decisions: list[dict[str, Any]]) -> tuple[int, int]:
    now = _utc_now()
    symbols = sorted({str(item.get("symbol") or "").upper() for item in decisions if item.get("symbol")})
    if not symbols:
        return 0, 0

    strategy_title, strategy_content, strategy_symbols = _build_strategy_post(agent_name, decisions)
    discussion_symbol, discussion_title, discussion_content = _build_discussion_post(agent_name, decisions)
    strategy_id = _reserve_signal_id(cursor)
    cursor.execute(
        """
        INSERT INTO signals
        (signal_id, agent_id, message_type, market, title, content, symbols, tags, timestamp, created_at)
        VALUES (?, ?, 'strategy', 'us-stock', ?, ?, ?, ?, ?, ?)
        """,
        (
            strategy_id,
            agent_id,
            strategy_title,
            strategy_content,
            json.dumps(strategy_symbols, ensure_ascii=False),
            json.dumps(["策略计划", "Lobster Arena", "风控"], ensure_ascii=False),
            _timestamp(now),
            now,
        ),
    )

    discussion_id = _reserve_signal_id(cursor)
    cursor.execute(
        """
        INSERT INTO signals
        (signal_id, agent_id, message_type, market, symbol, title, content, tags, timestamp, created_at)
        VALUES (?, ?, 'discussion', 'us-stock', ?, ?, ?, ?, ?, ?)
        """,
        (
            discussion_id,
            agent_id,
            discussion_symbol,
            discussion_title,
            discussion_content,
            json.dumps(["盘中讨论", "观点征集", "Lobster Arena"], ensure_ascii=False),
            _timestamp(now),
            now,
        ),
    )
    return strategy_id, discussion_id


def publish_arena_to_platform(result: dict[str, Any]) -> dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    published_trades = 0
    skipped_trades = 0
    created_posts = 0
    agents: list[dict[str, Any]] = []
    decisions_by_agent: dict[str, list[dict[str, Any]]] = {}
    for decision in result.get("decisions") or []:
        decisions_by_agent.setdefault(str(decision.get("agent") or ""), []).append(decision)

    try:
        begin_write_transaction(cursor)
        for row in result.get("leaderboard") or []:
            agent_name = str(row.get("agent") or "").strip()
            if not agent_name:
                continue
            agent_id, token = _ensure_agent(cursor, agent_name, float(result.get("initial_cash") or 100000))
            agents.append({"agent_id": agent_id, "name": agent_name, "token": token})

            for trade in row.get("trades") or []:
                signal_id = _insert_operation_signal(cursor, agent_id, trade)
                if signal_id:
                    published_trades += 1
                else:
                    skipped_trades += 1

            strategy_id, discussion_id = _insert_agent_posts(cursor, agent_id, agent_name, decisions_by_agent.get(agent_name, []))
            created_posts += int(bool(strategy_id)) + int(bool(discussion_id))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "enabled": True,
        "published_trades": published_trades,
        "skipped_trades": skipped_trades,
        "created_posts": created_posts,
        "agents": agents,
        "agent_password": AGENT_PASSWORD,
    }


def get_lobster_autorun_status() -> dict[str, Any]:
    return dict(LAST_AUTORUN_STATUS)


def get_lobster_system_status() -> dict[str, Any]:
    database_status = get_database_status()
    database_path = str(database_status.get("database_path") or "")
    temporary_sqlite = database_status.get("backend") == "sqlite" and (
        database_path.startswith("/tmp/")
        or database_path.startswith("\\tmp\\")
        or "\\AppData\\Local\\Temp\\" in database_path
    )
    return {
        "database": {
            **database_status,
            "temporary_sqlite": temporary_sqlite,
            "persistence_note": (
                "当前使用 Render 临时 SQLite，适合低成本演示；服务重启或重新部署后运行记录可能丢失。"
                if temporary_sqlite
                else "当前数据库路径不是临时目录。"
            ),
        },
        "llm": {
            "configured": bool(os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")),
            "model": os.getenv("OPENAI_MODEL") or os.getenv("LLM_MODEL") or "gpt-4o-mini",
            "decision_permission": "explanation_only",
        },
        "broker": _broker_status(),
        "paper_trading_only": True,
    }


def _broker_status() -> dict[str, Any]:
    configured = bool(os.getenv("LIVE_BROKER_API_KEY") and os.getenv("LIVE_BROKER_API_SECRET"))
    return {
        "mode": "paper",
        "external_broker_configured": configured,
        "live_orders_enabled": False,
        "status": "paper_only",
        "message": (
            "真实券商接口已预留，但当前版本只执行模拟交易，不会发送真实下单请求。"
            if not configured
            else "检测到券商环境变量，但真实下单仍被禁用；当前仅做模拟交易。"
        ),
    }


def _risk_summary(result: dict[str, Any]) -> dict[str, Any]:
    leaderboard = result.get("leaderboard") or []
    trades = [trade for row in leaderboard for trade in (row.get("trades") or [])]
    buy_count = sum(1 for trade in trades if str(trade.get("action")).upper() == "BUY")
    sell_count = sum(1 for trade in trades if str(trade.get("action")).upper() == "SELL")
    max_exposure = 0.0
    for row in leaderboard:
        total_value = float(row.get("total_value") or 0)
        if not total_value:
            continue
        positions = row.get("positions") or {}
        quote_by_symbol = {item["symbol"]: item for item in result.get("quotes") or []}
        for symbol, quantity in positions.items():
            quote = quote_by_symbol.get(symbol)
            if quote:
                max_exposure = max(max_exposure, abs(float(quantity or 0) * float(quote.get("price") or 0)) / total_value)

    return {
        "trade_count": len(trades),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "max_single_symbol_exposure": round(max_exposure, 4),
        "max_position_limit": result.get("max_position"),
        "paper_trading_only": True,
    }


def _insert_lobster_run(
    *,
    run_id: str,
    source: str,
    symbols: list[str] | None,
    initial_cash: float,
    fee_rate: float,
    max_position: float,
    use_llm: bool,
    publish_to_platform: bool,
    include_api_agent: bool,
    status: str,
    result: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    now = _utc_now()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO lobster_arena_runs
            (run_id, source, symbols, initial_cash, fee_rate, max_position,
             use_llm, publish_to_platform, include_api_agent, status,
             summary_json, result_json, error, created_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                source,
                _json_dumps(symbols or []),
                initial_cash,
                fee_rate,
                max_position,
                int(use_llm),
                int(publish_to_platform),
                int(include_api_agent),
                status,
                _json_dumps(summary or {}),
                _json_dumps(result or {}),
                error,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_lobster_backtest(
    *,
    backtest_id: str,
    symbols: list[str] | None,
    period: str,
    initial_cash: float,
    fee_rate: float,
    max_position: float,
    use_llm: bool,
    include_api_agent: bool,
    status: str,
    result: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    now = _utc_now()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO lobster_arena_backtests
            (backtest_id, symbols, period, initial_cash, fee_rate, max_position,
             use_llm, include_api_agent, status, summary_json, result_json,
             error, created_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                backtest_id,
                _json_dumps(symbols or []),
                period,
                initial_cash,
                fee_rate,
                max_position,
                int(use_llm),
                int(include_api_agent),
                status,
                _json_dumps(summary or {}),
                _json_dumps(result or {}),
                error,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_lobster_runs(limit: int = 20) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or 20), 100))
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT run_id, source, symbols, initial_cash, fee_rate, max_position,
                   use_llm, publish_to_platform, include_api_agent, status,
                   summary_json, error, created_at, finished_at
            FROM lobster_arena_runs
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    runs = []
    for row in rows:
        runs.append(
            {
                "run_id": row["run_id"],
                "source": row["source"],
                "symbols": json.loads(row["symbols"] or "[]"),
                "initial_cash": row["initial_cash"],
                "fee_rate": row["fee_rate"],
                "max_position": row["max_position"],
                "use_llm": bool(row["use_llm"]),
                "publish_to_platform": bool(row["publish_to_platform"]),
                "include_api_agent": bool(row["include_api_agent"]),
                "status": row["status"],
                "summary": json.loads(row["summary_json"] or "{}"),
                "error": row["error"],
                "created_at": row["created_at"],
                "finished_at": row["finished_at"],
            }
        )
    return {"runs": runs, "count": len(runs)}


def get_lobster_run(run_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT run_id, source, symbols, initial_cash, fee_rate, max_position,
                   use_llm, publish_to_platform, include_api_agent, status,
                   summary_json, result_json, error, created_at, finished_at
            FROM lobster_arena_runs
            WHERE run_id = ?
            """,
            (run_id,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        return None
    return {
        "run_id": row["run_id"],
        "source": row["source"],
        "symbols": json.loads(row["symbols"] or "[]"),
        "initial_cash": row["initial_cash"],
        "fee_rate": row["fee_rate"],
        "max_position": row["max_position"],
        "use_llm": bool(row["use_llm"]),
        "publish_to_platform": bool(row["publish_to_platform"]),
        "include_api_agent": bool(row["include_api_agent"]),
        "status": row["status"],
        "summary": json.loads(row["summary_json"] or "{}"),
        "result": json.loads(row["result_json"] or "{}"),
        "error": row["error"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }


def list_lobster_backtests(limit: int = 20) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or 20), 100))
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT backtest_id, symbols, period, initial_cash, fee_rate, max_position,
                   use_llm, include_api_agent, status, summary_json, error,
                   created_at, finished_at
            FROM lobster_arena_backtests
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    backtests = []
    for row in rows:
        backtests.append(
            {
                "backtest_id": row["backtest_id"],
                "symbols": json.loads(row["symbols"] or "[]"),
                "period": row["period"],
                "initial_cash": row["initial_cash"],
                "fee_rate": row["fee_rate"],
                "max_position": row["max_position"],
                "use_llm": bool(row["use_llm"]),
                "include_api_agent": bool(row["include_api_agent"]),
                "status": row["status"],
                "summary": json.loads(row["summary_json"] or "{}"),
                "error": row["error"],
                "created_at": row["created_at"],
                "finished_at": row["finished_at"],
            }
        )
    return {"backtests": backtests, "count": len(backtests)}


def get_lobster_backtest(backtest_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT backtest_id, symbols, period, initial_cash, fee_rate, max_position,
                   use_llm, include_api_agent, status, summary_json, result_json,
                   error, created_at, finished_at
            FROM lobster_arena_backtests
            WHERE backtest_id = ?
            """,
            (backtest_id,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        return None
    return {
        "backtest_id": row["backtest_id"],
        "symbols": json.loads(row["symbols"] or "[]"),
        "period": row["period"],
        "initial_cash": row["initial_cash"],
        "fee_rate": row["fee_rate"],
        "max_position": row["max_position"],
        "use_llm": bool(row["use_llm"]),
        "include_api_agent": bool(row["include_api_agent"]),
        "status": row["status"],
        "summary": json.loads(row["summary_json"] or "{}"),
        "result": json.loads(row["result_json"] or "{}"),
        "error": row["error"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }


def run_lobster_agent_cycle(
    *,
    symbols: list[str] | None = None,
    initial_cash: float = 100000.0,
    fee_rate: float = 0.001,
    max_position: float = 0.3,
    use_llm: bool = True,
    publish_to_platform: bool = True,
    source: str = "manual",
    include_api_agent: bool = False,
) -> dict[str, Any]:
    from lobster_arena import build_agent_reports, run_lobster_arena

    run_id = f"lobster_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}"
    LAST_AUTORUN_STATUS.update(
        {
            "enabled": True,
            "running": True,
            "last_started_at": _utc_now(),
            "last_error": None,
        }
    )
    try:
        result = run_lobster_arena(
            symbols=symbols,
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            max_position=max_position,
            include_api_agent=include_api_agent,
        )
        result["llm"] = enhance_decisions_with_llm(result, use_llm)
        result["agent_reports"] = build_agent_reports(result)
        result["run_id"] = run_id
        result["source"] = source
        result["broker_status"] = _broker_status()
        result["risk_summary"] = _risk_summary(result)
        result["system_status"] = get_lobster_system_status()
        result["published"] = (
            publish_arena_to_platform(result)
            if publish_to_platform
            else {"enabled": False}
        )
        summary = {
            "source": source,
            "fetched_at": result.get("fetched_at"),
            "llm_status": (result.get("llm") or {}).get("status"),
            "enhanced_count": (result.get("llm") or {}).get("enhanced_count"),
            "published_trades": (result.get("published") or {}).get("published_trades", 0),
            "created_posts": (result.get("published") or {}).get("created_posts", 0),
            "leaderboard_count": len(result.get("leaderboard") or []),
            "run_id": run_id,
            "broker_status": result["broker_status"]["status"],
            "trade_count": result["risk_summary"]["trade_count"],
        }
        _insert_lobster_run(
            run_id=run_id,
            source=source,
            symbols=symbols,
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            max_position=max_position,
            use_llm=use_llm,
            publish_to_platform=publish_to_platform,
            include_api_agent=include_api_agent,
            status="ok",
            result=result,
            summary=summary,
        )
        LAST_AUTORUN_STATUS.update(
            {
                "running": False,
                "last_finished_at": _utc_now(),
                "runs": int(LAST_AUTORUN_STATUS.get("runs") or 0) + 1,
                "last_result": summary,
            }
        )
        return result
    except Exception as exc:
        _insert_lobster_run(
            run_id=run_id,
            source=source,
            symbols=symbols,
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            max_position=max_position,
            use_llm=use_llm,
            publish_to_platform=publish_to_platform,
            include_api_agent=include_api_agent,
            status="error",
            summary={"source": source, "run_id": run_id},
            error=str(exc),
        )
        LAST_AUTORUN_STATUS.update(
            {
                "running": False,
                "last_finished_at": _utc_now(),
                "last_error": str(exc),
            }
        )
        raise


def run_lobster_backtest_cycle(
    *,
    symbols: list[str] | None = None,
    period: str = "3mo",
    initial_cash: float = 100000.0,
    fee_rate: float = 0.001,
    max_position: float = 0.3,
    use_llm: bool = True,
    include_api_agent: bool = False,
) -> dict[str, Any]:
    from lobster_arena import build_agent_reports, run_lobster_backtest

    backtest_id = f"backtest_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(4)}"
    try:
        result = run_lobster_backtest(
            symbols=symbols,
            period=period,
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            max_position=max_position,
            include_api_agent=include_api_agent,
        )
        result["backtest_id"] = backtest_id
        result["llm"] = enhance_run_recap(result, use_llm)
        result["llm_recap"] = result["llm"].get("recap") or _local_run_recap(result)
        result["agent_reports"] = build_agent_reports(result)
        result["broker_status"] = _broker_status()
        result["system_status"] = get_lobster_system_status()
        summary = {
            "backtest_id": backtest_id,
            "period": result.get("period"),
            "final_value": result.get("final_value"),
            "return_pct": result.get("return_pct"),
            "max_drawdown_pct": result.get("max_drawdown_pct"),
            "trade_count": len(result.get("trades") or []),
            "agent_count": len(result.get("agents") or []),
            "llm_status": result["llm"].get("status"),
        }
        _insert_lobster_backtest(
            backtest_id=backtest_id,
            symbols=symbols,
            period=period,
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            max_position=max_position,
            use_llm=use_llm,
            include_api_agent=include_api_agent,
            status="ok",
            result=result,
            summary=summary,
        )
        return result
    except Exception as exc:
        _insert_lobster_backtest(
            backtest_id=backtest_id,
            symbols=symbols,
            period=period,
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            max_position=max_position,
            use_llm=use_llm,
            include_api_agent=include_api_agent,
            status="error",
            summary={"backtest_id": backtest_id, "period": period},
            error=str(exc),
        )
        raise


def _chat_completion(
    messages: list[dict[str, str]],
    max_tokens: int = 180,
    temperature: float = 0.2,
) -> str:
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("LLM API key is not configured")

    model = os.getenv("OPENAI_MODEL") or os.getenv("LLM_MODEL") or "gpt-4o-mini"
    base_url = (os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_API_BASE") or "https://api.openai.com/v1").rstrip("/")
    endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    response = requests.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    return str(data["choices"][0]["message"]["content"]).strip()


def enhance_decisions_with_llm(result: dict[str, Any], enabled: bool) -> dict[str, Any]:
    if not enabled:
        return {
            "enabled": False,
            "status": "disabled",
            "enhanced_count": 0,
            "fallback_reason": "用户未启用大模型解释增强。",
        }
    if not (os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")):
        return {
            "enabled": True,
            "status": "not_configured",
            "enhanced_count": 0,
            "message": "未配置 OPENAI_API_KEY 或 LLM_API_KEY，系统已使用本地策略理由。",
            "fallback_reason": "missing_llm_api_key",
        }

    quotes = {item["symbol"]: item for item in result.get("quotes") or []}
    enhanced_count = 0
    errors: list[str] = []
    for decision in (result.get("decisions") or [])[:LLM_DECISION_LIMIT]:
        symbol = decision.get("symbol")
        quote = quotes.get(symbol, {})
        try:
            reason = _chat_completion(
                [
                    {
                        "role": "system",
                        "content": "你是一个谨慎的纸上交易 AI 分析员。只输出一段中文交易理由，80 字以内，不要承诺收益，不要给真实投资建议。",
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "agent": decision.get("agent"),
                                "symbol": symbol,
                                "action": decision.get("action"),
                                "confidence": decision.get("confidence"),
                                "rule_reason": decision.get("reason"),
                                "signals": decision.get("signals"),
                                "risk_note": decision.get("risk_note"),
                                "price": quote.get("price"),
                                "change_percent": quote.get("change_percent"),
                                "hard_rule": "只允许改写解释，不允许改变 BUY/SELL/HOLD、置信度、仓位或风控约束。",
                            },
                            ensure_ascii=False,
                        ),
                    },
                ]
            )
            if reason:
                decision["rule_reason"] = decision.get("reason")
                decision["reason"] = reason[:260]
                decision["llm_enhanced"] = True
                enhanced_count += 1
        except Exception as exc:
            errors.append(str(exc))
            break

    total_candidates = min(len(result.get("decisions") or []), LLM_DECISION_LIMIT)
    status = "ok" if enhanced_count == total_candidates and not errors else "partial" if enhanced_count else "error"
    return {
        "enabled": True,
        "status": status,
        "enhanced_count": enhanced_count,
        "errors": errors[:2],
        "fallback_reason": None if not errors else "llm_request_failed",
        "message": (
            "大模型已增强部分或全部交易理由，动作和仓位仍由本地风控决定。"
            if enhanced_count
            else "大模型调用失败，系统已保留本地策略理由。"
        ),
    }


def _local_run_recap(result: dict[str, Any]) -> str:
    agents = result.get("agents") or result.get("leaderboard") or []
    best = agents[0] if agents else {}
    worst = agents[-1] if len(agents) > 1 else best
    period = result.get("period") or {}
    trade_count = len(result.get("trades") or [])
    risk_count = len([event for event in result.get("risk_events") or [] if event.get("severity") in {"warning", "error"}])
    return (
        f"本次回测覆盖 {period.get('start', '-')} 到 {period.get('end', '-')}，"
        f"共 {period.get('trading_days', 0)} 个交易日。表现最好的是 {best.get('agent', '-')}，"
        f"最终资产 {best.get('final_value', best.get('total_value', 0))}，收益率 {best.get('return_pct', best.get('return_percent', 0))}%。"
        f"表现最弱的是 {worst.get('agent', '-')}。全场共产生 {trade_count} 笔模拟成交，"
        f"最大回撤 {result.get('max_drawdown_pct', 0)}%。系统只执行纸上交易，"
        f"触发 {risk_count} 条需要关注的风险提示，适合课堂展示策略差异和风控约束。"
    )


def enhance_run_recap(result: dict[str, Any], enabled: bool) -> dict[str, Any]:
    if not enabled:
        return {
            "enabled": False,
            "status": "disabled",
            "enhanced_count": 0,
            "fallback_reason": "用户未启用大模型复盘。",
            "recap": _local_run_recap(result),
        }
    if not (os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")):
        return {
            "enabled": True,
            "status": "not_configured",
            "enhanced_count": 0,
            "fallback_reason": "missing_llm_api_key",
            "message": "未配置 OPENAI_API_KEY 或 LLM_API_KEY，系统已生成本地复盘。",
            "recap": _local_run_recap(result),
        }

    agents = result.get("agents") or []
    compact_payload = {
        "period": result.get("period"),
        "symbols": result.get("symbols"),
        "initial_cash": result.get("initial_cash"),
        "final_value": result.get("final_value"),
        "return_pct": result.get("return_pct"),
        "max_drawdown_pct": result.get("max_drawdown_pct"),
        "agents": [
            {
                "agent": item.get("agent"),
                "return_pct": item.get("return_pct"),
                "max_drawdown_pct": item.get("max_drawdown_pct"),
                "win_rate_pct": item.get("win_rate_pct"),
                "trade_count": item.get("trade_count"),
            }
            for item in agents
        ],
        "risk_events": (result.get("risk_events") or [])[:8],
        "hard_rule": "只解释回测表现，不允许改变交易、仓位或风控结果，不要给真实投资建议。",
    }
    try:
        recap = _chat_completion(
            [
                {
                    "role": "system",
                    "content": "你是一个中文量化交易课程项目复盘助手。输出 180 字以内，说明策略表现、风险和课堂展示亮点，不给真实投资建议。",
                },
                {"role": "user", "content": json.dumps(compact_payload, ensure_ascii=False)},
            ],
            max_tokens=260,
            temperature=0.2,
        )
        return {
            "enabled": True,
            "status": "ok",
            "enhanced_count": 1,
            "fallback_reason": None,
            "message": "大模型已生成整轮回测复盘，交易结果仍由本地策略和风控决定。",
            "recap": recap[:600],
        }
    except Exception as exc:
        return {
            "enabled": True,
            "status": "error",
            "enhanced_count": 0,
            "fallback_reason": "llm_request_failed",
            "errors": [str(exc)],
            "message": "大模型复盘失败，系统已生成本地复盘。",
            "recap": _local_run_recap(result),
        }
