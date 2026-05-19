from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from lobster_agent_runtime import (
    get_lobster_autorun_status,
    get_lobster_run,
    list_lobster_runs,
    run_lobster_agent_cycle,
)
from lobster_arena import DEFAULT_SYMBOLS, LobsterArenaError, run_lobster_arena


class LobsterArenaRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: DEFAULT_SYMBOLS.copy())
    initial_cash: float = Field(default=100000.0, gt=0, le=10000000)
    fee_rate: float = Field(default=0.001, ge=0, le=0.05)
    max_position: float = Field(default=0.3, gt=0, le=1)
    use_llm: bool = False
    use_api_agent: bool = False
    publish_to_platform: bool = False


def register_lobster_arena_routes(app: FastAPI) -> None:
    @app.get("/api/lobster-arena/run")
    async def run_lobster_arena_get(symbols: Optional[str] = None):
        requested_symbols = symbols.split(",") if symbols else DEFAULT_SYMBOLS.copy()
        try:
            return run_lobster_arena(symbols=requested_symbols)
        except LobsterArenaError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/lobster-arena/run")
    async def run_lobster_arena_post(payload: LobsterArenaRequest):
        try:
            return run_lobster_agent_cycle(
                symbols=payload.symbols,
                initial_cash=payload.initial_cash,
                fee_rate=payload.fee_rate,
                max_position=payload.max_position,
                use_llm=payload.use_llm,
                publish_to_platform=payload.publish_to_platform,
                source="manual",
                include_api_agent=payload.use_api_agent,
            )
        except LobsterArenaError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/lobster-arena/autorun/status")
    async def lobster_arena_autorun_status():
        return get_lobster_autorun_status()

    @app.get("/api/lobster-arena/runs")
    async def lobster_arena_runs(limit: int = 20):
        return list_lobster_runs(limit=limit)

    @app.get("/api/lobster-arena/runs/{run_id}")
    async def lobster_arena_run_detail(run_id: str):
        run = get_lobster_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Lobster Arena run not found")
        return run

    @app.post("/api/lobster-arena/autorun/run-once")
    async def lobster_arena_autorun_once(payload: LobsterArenaRequest):
        try:
            return run_lobster_agent_cycle(
                symbols=payload.symbols,
                initial_cash=payload.initial_cash,
                fee_rate=payload.fee_rate,
                max_position=payload.max_position,
                use_llm=payload.use_llm,
                publish_to_platform=payload.publish_to_platform,
                source="run-once",
                include_api_agent=payload.use_api_agent,
            )
        except LobsterArenaError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
