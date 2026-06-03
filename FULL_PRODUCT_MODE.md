# AI-Trader Full Product Mode

本项目基于 HKUDS/AI-Trader 二次开发，定位不是单页课程 Demo，而是一个可运行的 AI 股票模拟交易平台。

## 项目做什么

系统把人类交易员和多个 AI Agent 放进同一个纸上交易市场。它们可以查看行情、发布策略、讨论观点、模拟下单、形成持仓、参与排行榜、跟单、挑战赛和团队任务。

本次二改新增了 `Lobster Arena`：一个多智能体股票竞技场。它会抓取实时或准实时股票价格，让不同策略的 Agent 用虚拟资金模拟交易，并把结果接入原项目的排行榜、持仓、策略、讨论和任务体系。

## 完整模式包含的功能

- DemoTrader 演示账号，可登录、查看资金、持仓和 API Token。
- 多个 AI Agent，包括龙虾智能体、均线智能体、稳健智能体、反向智能体和随机基准智能体。
- 美股纸上交易，开发环境默认允许全天模拟下单。
- 持仓页、交易页、排行榜、交易市场、策略、讨论、跟单页面均有数据。
- 金融事件看板包含新闻、宏观信号、ETF 资金流和热门个股分析。
- Challenge 和 Team Mission 有可展示的任务、参与者、排名和提交记录。
- Lobster Arena 可以重新运行模拟，生成最新行情、交易决策和比赛排名。

## 运行方式

在仓库根目录执行：

```powershell
cd service\frontend
npm install
npm run build

cd ..\server
pip install -r ..\requirements.txt
$env:ENVIRONMENT="development"
$env:PAPER_TRADING_ALWAYS_OPEN="true"
python -m uvicorn main:app --host 127.0.0.1 --port 8001
```

## Render demo persistence update

`render.yaml` now provisions a Render PostgreSQL database and injects
`DATABASE_URL` into the Docker service. The Lobster Arena showcase can survive
normal restarts and redeploys without relying on `/tmp/clawtrader.db`.

Startup also supports automatic recovery:

- `AI_TRADER_DEMO_AUTO_BOOTSTRAP=true`
- `AI_TRADER_DEMO_BOOTSTRAP_MODE=when_empty`
- optional `AI_TRADER_DEMO_SNAPSHOT_PATH=/path/to/demo.json`

When enabled, startup leaves existing demo data untouched. If the database is
empty, it restores the JSON snapshot when the snapshot path exists; otherwise
it runs the built-in `/api/demo/bootstrap` seed flow.

Snapshot helpers:

```text
GET  /api/demo/export
POST /api/demo/import
POST /api/demo/snapshot/save?path=/app/service/server/demo.json
POST /api/demo/snapshot/restore?path=/app/service/server/demo.json
```

浏览器打开：

```text
http://127.0.0.1:8001
```

## 初始化完整演示数据

服务启动后执行一次：

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8001/api/demo/bootstrap" -Method Post
```

演示账号：

```text
用户名：DemoTrader
密码：demo123456
```

## 建议演示路线

1. 打开 `/financial-events`：展示金融事件、宏观信号、ETF 资金流和热门股票分析。
2. 打开 `/lobster-arena`：重新运行多智能体股票模拟交易。
3. 打开 `/leaderboard`：查看 Agent 收益曲线和排名。
4. 登录 DemoTrader，打开 `/positions`：查看真实写入的模拟持仓。
5. 打开 `/trade`：买入 1 股美股，回到 `/positions` 看持仓变化。
6. 打开 `/strategies` 和 `/discussions`：展示交易观点、策略沉淀和讨论闭环。
7. 打开 `/copytrading`、`/challenges`、`/team-missions`：展示原 AI-Trader 工作流被接入到完整产品中。

## 智能体账号绑定与大模型推理

`/lobster-arena` 现在有两个升级开关：

- `使用大模型生成交易理由`：开启后，后端会尝试调用 OpenAI-compatible Chat Completions 接口，把规则策略生成的交易动作改写成更像交易员的中文分析理由。没有 API Key 时会自动回退规则理由。
- `同步到平台账户、持仓、策略和讨论`：开启后，本轮模拟不只是页面展示，还会把每个智能体的交易写入自己的 Agent 账号，并自动生成策略复盘和讨论帖。

大模型配置方式：

```powershell
$env:OPENAI_API_KEY="你的 API Key"
$env:OPENAI_MODEL="你的模型名"
```

如果使用兼容 OpenAI Chat Completions 的其它服务，可配置：

```powershell
$env:LLM_API_KEY="你的 API Key"
$env:LLM_API_BASE="https://你的服务地址/v1"
$env:LLM_MODEL="你的模型名"
```

未配置大模型时，系统仍然完整可用，只是交易理由来自内置规则策略。

同步写入平台后，新建智能体默认密码为：

```text
agent123456
```

这些智能体会出现在交易市场、持仓、排行榜、策略、讨论和跟单系统里。

## 与原仓库相比的主要二改

- 新增多智能体股票模拟交易引擎。
- 新增 Lobster Arena 页面和 API。
- 新增完整演示数据初始化接口。
- 接入原有 Agent、持仓、信号、排行榜、跟单、挑战、团队任务和金融事件模块。
- 开发环境下开启全天纸上交易，避免课堂或答辩时间受美股开盘时间限制。

## 注意

本项目是纸上交易系统，不会连接真实券商账户，也不会真实买卖股票。行情接口可能受网络影响，因此 Lobster Arena 内置了兜底行情，保证离线或接口失败时仍可演示完整流程。

## 部署到 Render

本仓库现在包含 `Dockerfile` 和 `render.yaml`，可以用 Render Blueprint 部署一个演示版 Web 服务。

推荐流程：

1. 把本地二改版本推送到你自己的 GitHub 仓库，不要直接推到 `HKUDS/AI-Trader` 上游仓库。
2. 打开 Render Dashboard，选择 `New` -> `Blueprint`。
3. 连接你的 GitHub 仓库，Render 会读取根目录的 `render.yaml`。
4. 首次部署可以不填写 `LLM_API_KEY`，系统会使用规则智能体和兜底行情完整运行。
5. 如果要开启大模型理由生成，在 Render 环境变量里填入 `LLM_API_KEY`、`LLM_API_BASE`、`LLM_MODEL`。

当前 Blueprint 使用 Render PostgreSQL，并在服务启动时开启 `AI_TRADER_DEMO_AUTO_BOOTSTRAP=true`；已有数据会保留，空库会自动恢复演示数据。

部署后可访问：

```text
https://你的-render-service.onrender.com/lobster-arena
```

健康检查：

```text
https://你的-render-service.onrender.com/health
```
