from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException

from database import begin_write_transaction, get_database_status, get_db_connection
from demo_seed import bootstrap_demo_data
from routes_shared import RouteContext, invalidate_leaderboard_caches, invalidate_signal_read_caches, invalidate_trending_caches


DEMO_EXPORT_TABLES = [
    "agents",
    "signals",
    "signal_replies",
    "positions",
    "profit_history",
    "lobster_arena_runs",
    "lobster_arena_backtests",
]


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
