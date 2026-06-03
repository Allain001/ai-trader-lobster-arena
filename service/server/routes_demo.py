from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from database import begin_write_transaction, get_database_status, get_db_connection, init_database, using_postgres
from demo_seed import bootstrap_demo_data
from routes_shared import RouteContext, invalidate_leaderboard_caches, invalidate_signal_read_caches, invalidate_trending_caches


DEMO_EXPORT_TABLES = [
    "agents",
    "agent_messages",
    "signals",
    "signal_replies",
    "subscriptions",
    "positions",
    "profit_history",
    "agent_metric_snapshots",
    "lobster_arena_runs",
    "lobster_arena_backtests",
    "challenges",
    "challenge_participants",
    "challenge_submissions",
    "challenge_trades",
    "challenge_results",
    "team_missions",
    "teams",
    "team_mission_participants",
    "team_members",
    "team_messages",
    "team_submissions",
    "team_contributions",
    "team_results",
    "market_news_snapshots",
    "macro_signal_snapshots",
    "etf_flow_snapshots",
    "stock_analysis_snapshots",
]

DEMO_PRESENT_TABLES = ("agents", "signals", "lobster_arena_runs", "challenges", "team_missions")
DEMO_AUTO_BOOTSTRAP_ENV = "AI_TRADER_DEMO_AUTO_BOOTSTRAP"
DEMO_BOOTSTRAP_MODE_ENV = "AI_TRADER_DEMO_BOOTSTRAP_MODE"
DEMO_SNAPSHOT_PATH_ENV = "AI_TRADER_DEMO_SNAPSHOT_PATH"


def _table_rows(cursor: Any, table: str) -> list[dict[str, Any]]:
    try:
        cursor.execute(f"SELECT * FROM {table}")
    except Exception:
        return []
    return [dict(row) for row in cursor.fetchall()]


def _insert_rows(cursor: Any, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(columns)
    sql = f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})"
    cursor.executemany(sql, [tuple(row.get(column) for column in columns) for row in rows])


def _sync_signal_sequence(cursor: Any) -> None:
    cursor.execute("SELECT COALESCE(MAX(signal_id), 0) AS max_signal_id FROM signals")
    max_signal_id = int(cursor.fetchone()["max_signal_id"] or 0)
    cursor.execute("SELECT COALESCE(MAX(id), 0) AS max_sequence_id FROM signal_sequence")
    max_sequence_id = int(cursor.fetchone()["max_sequence_id"] or 0)
    if max_sequence_id < max_signal_id:
        cursor.executemany("INSERT INTO signal_sequence DEFAULT VALUES", [()] * (max_signal_id - max_sequence_id))


def _sync_postgres_identity_sequences(cursor: Any) -> None:
    if not using_postgres():
        return
    for table in DEMO_EXPORT_TABLES:
        try:
            cursor.execute(f"SELECT COALESCE(MAX(id), 0) AS max_id FROM {table}")
            max_id = int(cursor.fetchone()["max_id"] or 0)
            if max_id > 0:
                cursor.execute("SELECT setval(pg_get_serial_sequence(?, 'id'), ?, true)", (table, max_id))
        except Exception:
            continue


def export_demo_snapshot() -> dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        return {
            "schema": "ai-trader-demo-snapshot",
            "version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "database": get_database_status(),
            "tables": {table: _table_rows(cursor, table) for table in DEMO_EXPORT_TABLES},
        }
    finally:
        conn.close()


def import_demo_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != "ai-trader-demo-snapshot":
        raise HTTPException(status_code=400, detail="Invalid demo snapshot file")
    tables = payload.get("tables")
    if not isinstance(tables, dict):
        raise HTTPException(status_code=400, detail="Missing tables in demo snapshot")

    conn = get_db_connection()
    cursor = conn.cursor()
    restored: dict[str, int] = {}
    try:
        begin_write_transaction(cursor)
        for table in reversed(DEMO_EXPORT_TABLES):
            cursor.execute(f"DELETE FROM {table}")
        for table in DEMO_EXPORT_TABLES:
            rows = tables.get(table) or []
            if not isinstance(rows, list):
                raise HTTPException(status_code=400, detail=f"Invalid rows for {table}")
            _insert_rows(cursor, table, rows)
            restored[table] = len(rows)
        _sync_signal_sequence(cursor)
        _sync_postgres_identity_sequences(cursor)
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to import demo snapshot: {exc}") from exc
    finally:
        conn.close()

    return {
        "ok": True,
        "restored": restored,
        "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def save_demo_snapshot(path: str | os.PathLike[str]) -> dict[str, Any]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    snapshot = export_demo_snapshot()
    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "path": str(target),
        "tables": {table: len(rows) for table, rows in snapshot["tables"].items()},
        "exported_at": snapshot["exported_at"],
    }


def import_demo_snapshot_file(path: str | os.PathLike[str]) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Demo snapshot not found: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    result = import_demo_snapshot(payload)
    result["source"] = "snapshot-file"
    result["path"] = str(target)
    return result


def demo_data_present() -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        for table in DEMO_PRESENT_TABLES:
            try:
                cursor.execute(f"SELECT COUNT(*) AS count FROM {table}")
                row = cursor.fetchone()
                if int(row["count"] or 0) > 0:
                    return True
            except Exception:
                continue
        return False
    finally:
        conn.close()


def ensure_demo_data_for_showcase() -> dict[str, Any]:
    enabled = os.getenv(DEMO_AUTO_BOOTSTRAP_ENV, "false").strip().lower() in {"1", "true", "yes", "on"}
    mode = os.getenv(DEMO_BOOTSTRAP_MODE_ENV, "when_empty").strip().lower() or "when_empty"
    snapshot_path = os.getenv(DEMO_SNAPSHOT_PATH_ENV, "").strip()

    if not enabled:
        return {"ok": True, "action": "skipped", "reason": "auto_bootstrap_disabled"}

    init_database()
    has_demo_data = demo_data_present()
    if has_demo_data and mode not in {"always", "force"}:
        return {"ok": True, "action": "skipped", "reason": "demo_data_present"}

    if snapshot_path and Path(snapshot_path).exists():
        result = import_demo_snapshot_file(snapshot_path)
        return {
            "ok": True,
            "action": "imported_snapshot",
            "path": snapshot_path,
            "restored": result.get("restored", {}),
        }

    payload = bootstrap_demo_data()
    return {
        "ok": True,
        "action": "bootstrapped",
        "mode": payload.get("mode"),
        "agents": payload.get("agents", []),
        "pages_ready": payload.get("pages_ready", []),
    }


def register_demo_routes(app: FastAPI, ctx: RouteContext) -> None:
    @app.post("/api/demo/bootstrap")
    @app.get("/api/demo/bootstrap")
    async def bootstrap_complete_local_product():
        payload = bootstrap_demo_data()
        invalidate_signal_read_caches(ctx, refresh_trending=True)
        invalidate_leaderboard_caches(ctx)
        invalidate_trending_caches()
        return payload

    @app.get("/api/demo/export")
    async def export_demo_data():
        return export_demo_snapshot()

    @app.post("/api/demo/import")
    async def import_demo_data(payload: dict[str, Any]):
        result = import_demo_snapshot(payload)
        invalidate_signal_read_caches(ctx, refresh_trending=True)
        invalidate_leaderboard_caches(ctx)
        invalidate_trending_caches()
        return result

    @app.post("/api/demo/snapshot/save")
    async def save_demo_data_snapshot(path: str | None = None):
        target = path or os.getenv(DEMO_SNAPSHOT_PATH_ENV, "").strip()
        if not target:
            raise HTTPException(status_code=400, detail=f"Set {DEMO_SNAPSHOT_PATH_ENV} or pass ?path=")
        return save_demo_snapshot(target)

    @app.post("/api/demo/snapshot/restore")
    async def restore_demo_data_snapshot(path: str | None = None):
        target = path or os.getenv(DEMO_SNAPSHOT_PATH_ENV, "").strip()
        if not target:
            raise HTTPException(status_code=400, detail=f"Set {DEMO_SNAPSHOT_PATH_ENV} or pass ?path=")
        result = import_demo_snapshot_file(target)
        invalidate_signal_read_caches(ctx, refresh_trending=True)
        invalidate_leaderboard_caches(ctx)
        invalidate_trending_caches()
        return result
