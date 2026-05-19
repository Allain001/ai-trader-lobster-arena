from __future__ import annotations

from fastapi import FastAPI

from demo_seed import bootstrap_demo_data
from routes_shared import RouteContext, invalidate_leaderboard_caches, invalidate_signal_read_caches, invalidate_trending_caches


def register_demo_routes(app: FastAPI, ctx: RouteContext) -> None:
    @app.post("/api/demo/bootstrap")
    @app.get("/api/demo/bootstrap")
    async def bootstrap_complete_local_product():
        payload = bootstrap_demo_data()
        invalidate_signal_read_caches(ctx, refresh_trending=True)
        invalidate_leaderboard_caches(ctx)
        invalidate_trending_caches()
        return payload
