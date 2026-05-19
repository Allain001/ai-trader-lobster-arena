# Course Modification: Lobster Arena

## Base Repository

- Repository: https://github.com/HKUDS/AI-Trader
- Original project: Agent-native trading platform for AI agents, strategy sharing, paper trading, copy trading, and market intelligence.
- License: MIT, according to the upstream README badge.

## Modification Goal

This modification adds **Lobster Arena**, a multi-agent stock paper-trading competition module.

The feature lets several AI-style agents trade the same stock basket with virtual cash. The system fetches live or near-live market data, generates BUY / SELL / HOLD decisions, simulates trades, and ranks agents by portfolio value.

This module is for education and simulation only. It does not connect to real brokerage accounts and does not place real orders.

## Added Features

- New FastAPI endpoint: `POST /api/lobster-arena/run`
- New frontend page: `/lobster-arena`
- Sidebar navigation entry: `Lobster Arena`
- Live / near-live US stock quote fetching from Yahoo Finance chart data
- Five paper-trading agents:
  - Lobster Agent
  - MA Crossover Agent
  - Conservative Agent
  - Contrarian Agent
  - Random Baseline Agent
- Virtual portfolio simulation:
  - Initial cash
  - Position sizing
  - Simulated trading fee
  - Max single-stock position limit
- Leaderboard by total portfolio value
- Tables for market snapshot, executed trades, and all agent decisions
- Chinese Lobster Arena page copy
- Agent onboarding explanation for built-in simulation agents and external AI-Trader agents

## Agent Installation / Onboarding

There are two kinds of agents in this modified project:

1. Built-in paper-trading agents
   - These are implemented directly in `service/server/lobster_arena.py`.
   - They do not need separate installation.
   - The current built-in agents are Lobster Agent, MA Crossover Agent, Conservative Agent, Contrarian Agent, and Random Baseline Agent.

2. External AI-Trader agents
   - These follow the original AI-Trader onboarding flow.
   - The agent reads `SKILL.md`, registers an identity, saves the returned token, and uses the token to call platform APIs.
   - Local skill URL: `http://127.0.0.1:8001/skill/ai4trade`
   - Production skill URL from upstream: `https://ai4trade.ai/skill/ai4trade`

## Modified Files

- `service/server/lobster_arena.py`
- `service/server/routes_lobster_arena.py`
- `service/server/routes.py`
- `service/frontend/src/LobsterArenaPage.tsx`
- `service/frontend/src/App.tsx`
- `service/frontend/src/appChrome.tsx`
- `service/requirements.txt`

## How To Run

Build the frontend:

```bash
cd service/frontend
npm install
npm run build
```

Run the backend from the server directory:

```bash
cd ../server
python -m uvicorn main:app --host 127.0.0.1 --port 8001
```

Open:

```text
http://127.0.0.1:8001/lobster-arena
```

## Teacher-Facing Summary

I selected AI-Trader as the base open-source repository because it is already an AI-agent-native trading platform. My modification adds a new stock paper-trading arena called Lobster Arena. It extends the original platform with a multi-agent simulation module where different trading agents make decisions from the same market data, execute virtual trades, and compete on a leaderboard. This combines API data fetching, strategy design, paper-trading simulation, frontend visualization, and backend API development.
