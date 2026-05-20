import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers
} from 'lightweight-charts'

import { API_BASE } from './appShared'

type WatchlistStock = {
  symbol: string
  name: string
  sector: string
  price: number
  change_percent: number
  market_time: string
  currency: string
  source: string
}

type CandlePoint = {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

type LinePoint = {
  time: string
  value: number
}

type CandlePayload = {
  symbol: string
  name: string
  sector: string
  range: ChartRange
  interval: string
  currency: string
  price: number
  change_percent: number
  candles: CandlePoint[]
  ma5: LinePoint[]
  ma20: LinePoint[]
  source: string
  fetched_at: string
}

type Decision = {
  agent: string
  symbol: string
  action: 'BUY' | 'SELL' | 'HOLD'
  confidence: number
  reason: string
  target_fraction: number
  signals?: Record<string, any>
  risk_note?: string
  rule_reason?: string
  llm_enhanced?: boolean
}

type Trade = {
  timestamp: string
  agent: string
  symbol: string
  action: string
  shares: number
  price: number
  value: number
  fee: number
  reason: string
}

type LeaderboardRow = {
  agent: string
  cash: number
  total_value: number
  profit: number
  return_percent: number
  positions: Record<string, number>
  trades: Trade[]
}

type ArenaResult = {
  run_id?: string
  source?: string
  fetched_at: string
  initial_cash: number
  fee_rate: number
  max_position: number
  quotes: Array<{
    symbol: string
    price: number
    change_percent: number
    market_time: string
    currency: string
    source?: string
  }>
  decisions: Decision[]
  leaderboard: LeaderboardRow[]
  agent_profiles?: Record<string, {
    role: string
    style: string
    focus: string[]
    risk_rule: string
  }>
  agent_reports?: Array<{
    agent: string
    profile: {
      role: string
      style: string
      focus: string[]
      risk_rule: string
    }
    decision_counts: Record<'BUY' | 'SELL' | 'HOLD', number>
    trade_count: number
    return_percent: number
    total_value?: number
    positions: Record<string, number>
    review: string
  }>
  risk_events?: Array<{
    severity: 'ok' | 'info' | 'warning' | 'error'
    code?: string
    agent?: string
    symbol?: string
    message: string
  }>
  api_agent?: {
    enabled: boolean
    status: string
    decision_count: number
    agent_name?: string
    llm_decision_permission?: string
    errors?: string[]
  }
  llm?: {
    enabled: boolean
    status: string
    enhanced_count: number
    message?: string
    fallback_reason?: string | null
    errors?: string[]
  }
  published?: {
    enabled: boolean
    published_trades?: number
    skipped_trades?: number
    created_posts?: number
    agent_password?: string
  }
  broker_status?: {
    mode: string
    external_broker_configured: boolean
    live_orders_enabled: boolean
    status: string
    message: string
  }
  risk_summary?: {
    trade_count: number
    buy_count: number
    sell_count: number
    max_single_symbol_exposure: number
    max_position_limit: number
    paper_trading_only: boolean
  }
  system_status?: LobsterSystemStatus
}

type LobsterSystemStatus = {
  database?: {
    backend?: string
    database_path?: string
    temporary_sqlite?: boolean
    persistence_note?: string
  }
  llm?: {
    configured: boolean
    model: string
    decision_permission: string
  }
  broker?: {
    mode: string
    live_orders_enabled: boolean
    message: string
  }
  paper_trading_only?: boolean
}

type LobsterRunSummary = {
  run_id: string
  source: string
  symbols: string[]
  status: string
  created_at: string
  finished_at?: string
  summary?: {
    llm_status?: string
    enhanced_count?: number
    published_trades?: number
    created_posts?: number
    leaderboard_count?: number
    trade_count?: number
    broker_status?: string
  }
}

type ManualMarker = {
  symbol: string
  action: 'BUY' | 'SELL'
  timestamp: string
  shares: number
  price: number
}

type ChartRange = '1mo' | '3mo' | '6mo' | '1y'

const DEFAULT_SYMBOLS =
  'AAPL,MSFT,GOOGL,META,AMZN,NFLX,CRM,ORCL,NVDA,AMD,AVGO,TSM,INTC,QCOM,MU,ASML,TSLA,COIN,PLTR,RBLX,SHOP,SPY,QQQ,DIA,IWM,VOO,JPM,BAC,GS,MS,V,MA,WMT,COST,KO,PEP,MCD,NKE,JNJ,UNH,PFE,ABBV,MRK,XOM,CVX,COP,SLB,BABA,PDD,JD'

const RANGE_OPTIONS: Array<{ value: ChartRange; label: string }> = [
  { value: '1mo', label: '1M' },
  { value: '3mo', label: '3M' },
  { value: '6mo', label: '6M' },
  { value: '1y', label: '1Y' }
]

const RANGE_DAYS: Record<ChartRange, number> = {
  '1mo': 23,
  '3mo': 63,
  '6mo': 126,
  '1y': 252
}

const panelStyle = {
  background: '#071017',
  border: '1px solid rgba(148, 163, 184, 0.18)',
  borderRadius: 8,
  boxShadow: '0 18px 40px rgba(0, 0, 0, 0.24)'
}

function formatMoney(value: number, currency = 'USD') {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    maximumFractionDigits: 2
  }).format(value || 0)
}

function formatSignedPercent(value: number) {
  const number = Number(value || 0)
  return `${number >= 0 ? '+' : ''}${number.toFixed(2)}%`
}

function formatShortDate(value?: string) {
  if (!value) return '暂无'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 16)
  return parsed.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function actionColor(action: string) {
  if (action === 'BUY') return '#16a34a'
  if (action === 'SELL') return '#dc2626'
  return '#94a3b8'
}

function actionLabel(action: string) {
  if (action === 'BUY') return '买入'
  if (action === 'SELL') return '卖出'
  return '持有'
}

function llmStatusLabel(status?: string) {
  if (status === 'ok') return 'LLM 已增强'
  if (status === 'partial') return 'LLM 部分增强'
  if (status === 'not_configured') return '未配置 LLM'
  if (status === 'disabled') return '本地策略'
  if (status === 'error') return 'LLM 回退'
  return '等待运行'
}

function severityColor(severity?: string) {
  if (severity === 'ok') return '#22c55e'
  if (severity === 'warning') return '#f59e0b'
  if (severity === 'error') return '#ef4444'
  return '#38bdf8'
}

function formatPositions(positions: Record<string, number>) {
  const entries = Object.entries(positions)
  if (entries.length === 0) return '-'
  return entries.map(([symbol, shares]) => `${symbol}: ${shares}`).join(', ')
}

function toDateKey(value: string) {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 10)
  return parsed.toISOString().slice(0, 10)
}

function toChartTime(value: string) {
  const [year, month, day] = value.slice(0, 10).split('-').map((item) => Number(item))
  return { year, month, day }
}

function symbolSeed(symbol: string) {
  return symbol.split('').reduce((sum, char, index) => sum + char.charCodeAt(0) * (index + 1), 0)
}

function seededRandom(seed: number) {
  let state = seed % 2147483647
  if (state <= 0) state += 2147483646
  return () => {
    state = (state * 16807) % 2147483647
    return (state - 1) / 2147483646
  }
}

function movingAverage(candles: CandlePoint[], windowSize: number): LinePoint[] {
  const points: LinePoint[] = []
  for (let index = windowSize - 1; index < candles.length; index += 1) {
    const slice = candles.slice(index + 1 - windowSize, index + 1)
    points.push({
      time: candles[index].time,
      value: Number((slice.reduce((sum, item) => sum + item.close, 0) / windowSize).toFixed(4))
    })
  }
  return points
}

function buildLocalCandles(symbol: string, range: ChartRange, stock?: WatchlistStock): CandlePayload {
  const seed = symbolSeed(symbol) + RANGE_DAYS[range]
  const random = seededRandom(seed)
  const days = RANGE_DAYS[range]
  const candles: CandlePoint[] = []
  const anchor = Number(stock?.price || 70 + (seed % 180))
  const start = new Date()
  start.setDate(start.getDate() - Math.ceil(days * 1.55))
  let price = anchor * (0.92 + random() * 0.16)
  let dayCursor = 0
  let trend = (random() - 0.48) * 0.002

  while (candles.length < days) {
    const date = new Date(start)
    date.setDate(start.getDate() + dayCursor)
    dayCursor += 1
    if (date.getDay() === 0 || date.getDay() === 6) continue

    trend = trend * 0.94 + (random() - 0.5) * 0.0014
    const shock = (random() - 0.5) * (0.018 + random() * 0.012)
    const gap = (random() - 0.5) * 0.008
    const open = Math.max(1, price * (1 + gap))
    const close = Math.max(1, open * (1 + trend + shock))
    const spread = 0.006 + random() * 0.018
    const high = Math.max(open, close) * (1 + spread)
    const low = Math.min(open, close) * (1 - spread * (0.75 + random() * 0.45))
    const volumePulse = Math.abs(close - open) / open
    const volume = Math.round(900_000 + random() * 2_400_000 + volumePulse * 85_000_000)

    candles.push({
      time: date.toISOString().slice(0, 10),
      open: Number(open.toFixed(4)),
      high: Number(high.toFixed(4)),
      low: Number(low.toFixed(4)),
      close: Number(close.toFixed(4)),
      volume
    })
    price = close
  }

  const last = candles[candles.length - 1]
  const previous = candles[candles.length - 2] || last
  return {
    symbol,
    name: stock?.name || symbol,
    sector: stock?.sector || 'US Stock',
    range,
    interval: '1d',
    currency: stock?.currency || 'USD',
    price: last.close,
    change_percent: Number((((last.close - previous.close) / previous.close) * 100).toFixed(4)),
    candles,
    ma5: movingAverage(candles, 5),
    ma20: movingAverage(candles, 20),
    source: 'local-fallback',
    fetched_at: new Date().toISOString()
  }
}

function KLineChart({
  data,
  markers,
  loading,
  showMA5,
  showMA20,
  showVolume,
  compact
}: {
  data: CandlePayload | null
  markers: Array<any>
  loading: boolean
  showMA5: boolean
  showMA20: boolean
  showVolume: boolean
  compact: boolean
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartHeight = compact ? 430 : 610

  useEffect(() => {
    if (!containerRef.current || !data?.candles.length || loading) return
    const container = containerRef.current
    const chartWidth = Math.max(320, container.clientWidth || 320)
    const chart = createChart(container, {
      width: chartWidth,
      height: chartHeight,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#8b9aab',
        fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        fontSize: 12
      },
      grid: {
        vertLines: { color: 'rgba(71, 85, 105, 0.16)' },
        horzLines: { color: 'rgba(71, 85, 105, 0.16)' }
      },
      rightPriceScale: {
        borderColor: 'rgba(148, 163, 184, 0.14)',
        scaleMargins: { top: 0.08, bottom: showVolume ? 0.25 : 0.08 },
        entireTextOnly: true
      },
      timeScale: {
        borderColor: 'rgba(148, 163, 184, 0.14)',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 6,
        barSpacing: compact ? 7 : 9,
        fixLeftEdge: true,
        fixRightEdge: false
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: 'rgba(203, 213, 225, 0.38)', width: 1, style: 2 },
        horzLine: { color: 'rgba(203, 213, 225, 0.38)', width: 1, style: 2 }
      },
      handleScroll: true,
      handleScale: true
    })

    const candles = data.candles.map((item) => ({
      ...item,
      time: toChartTime(item.time)
    }))
    const chartMarkers = markers.map((item) => ({
      ...item,
      time: typeof item.time === 'string' ? toChartTime(item.time) : item.time
    }))

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#16a34a',
      downColor: '#dc2626',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#86efac',
      wickDownColor: '#fca5a5',
      priceLineVisible: false
    })
    candleSeries.setData(candles as any)
    candleSeries.createPriceLine({
      price: data.price,
      color: '#fbbf24',
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: '现价'
    } as any)

    if (showMA5) {
      const ma5Series = chart.addSeries(LineSeries, {
        color: '#38bdf8',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false
      })
      ma5Series.setData(data.ma5.map((item) => ({ ...item, time: toChartTime(item.time) })) as any)
    }

    if (showMA20) {
      const ma20Series = chart.addSeries(LineSeries, {
        color: '#f59e0b',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false
      })
      ma20Series.setData(data.ma20.map((item) => ({ ...item, time: toChartTime(item.time) })) as any)
    }

    if (showVolume) {
      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: 'volume' },
        priceScaleId: '',
        lastValueVisible: false,
        priceLineVisible: false
      } as any)
      volumeSeries.setData(
        data.candles.map((item) => ({
          time: toChartTime(item.time),
          value: item.volume,
          color: item.close >= item.open ? 'rgba(22, 163, 74, 0.28)' : 'rgba(220, 38, 38, 0.26)'
        })) as any
      )
      ;(volumeSeries as any).priceScale().applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } })
    }

    if (markers.length > 0) {
      createSeriesMarkers(candleSeries as any, chartMarkers as any)
    }

    chart.timeScale().fitContent()
    const resizeObserver = new ResizeObserver(() => {
      chart.applyOptions({ width: Math.max(320, container.clientWidth || 320) })
    })
    resizeObserver.observe(container)

    return () => {
      resizeObserver.disconnect()
      chart.remove()
    }
  }, [chartHeight, compact, data, loading, markers, showMA5, showMA20, showVolume])

  if (loading) {
    return (
      <div
        style={{
          height: chartHeight,
          borderRadius: 8,
          background: 'linear-gradient(90deg, rgba(15,23,42,.6), rgba(30,41,59,.9), rgba(15,23,42,.6))'
        }}
      />
    )
  }

  if (!data) {
    return (
      <div className="empty-state" style={{ height: chartHeight }}>
        <div className="empty-title">请选择股票查看 K 线</div>
      </div>
    )
  }

  return <div ref={containerRef} style={{ height: chartHeight, width: '100%', minWidth: 0, overflow: 'hidden' }} />
}

function ToggleButton({
  active,
  children,
  onClick
}: {
  active: boolean
  children: React.ReactNode
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        border: `1px solid ${active ? 'rgba(251, 191, 36, 0.7)' : 'rgba(148, 163, 184, 0.18)'}`,
        background: active ? 'rgba(251, 191, 36, 0.16)' : 'rgba(15, 23, 42, 0.72)',
        color: active ? '#fde68a' : '#94a3b8',
        borderRadius: 6,
        padding: '7px 10px',
        fontSize: 12,
        fontWeight: 800,
        cursor: 'pointer'
      }}
    >
      {children}
    </button>
  )
}

export function LobsterArenaPage() {
  const [symbols, setSymbols] = useState(DEFAULT_SYMBOLS)
  const [initialCash, setInitialCash] = useState(100000)
  const [useApiAgent, setUseApiAgent] = useState(true)
  const [useLlm, setUseLlm] = useState(false)
  const [publishToPlatform, setPublishToPlatform] = useState(false)
  const [result, setResult] = useState<ArenaResult | null>(null)
  const [runHistory, setRunHistory] = useState<LobsterRunSummary[]>([])
  const [systemStatus, setSystemStatus] = useState<LobsterSystemStatus | null>(null)
  const [historyLoadingId, setHistoryLoadingId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [watchlist, setWatchlist] = useState<WatchlistStock[]>([])
  const [watchlistLoading, setWatchlistLoading] = useState(true)
  const [selectedSymbol, setSelectedSymbol] = useState('NVDA')
  const [sector, setSector] = useState('全部')
  const [search, setSearch] = useState('')
  const [range, setRange] = useState<ChartRange>('3mo')
  const [showMA5, setShowMA5] = useState(true)
  const [showMA20, setShowMA20] = useState(true)
  const [showVolume, setShowVolume] = useState(true)
  const [candleCache, setCandleCache] = useState<Record<string, CandlePayload>>({})
  const [candleData, setCandleData] = useState<CandlePayload | null>(null)
  const [candleLoading, setCandleLoading] = useState(false)
  const [candleWarning, setCandleWarning] = useState<string | null>(null)
  const [orderSide, setOrderSide] = useState<'BUY' | 'SELL'>('BUY')
  const [orderQuantity, setOrderQuantity] = useState('10')
  const [manualMarkers, setManualMarkers] = useState<ManualMarker[]>([])
  const [isCompact, setIsCompact] = useState(() => (typeof window === 'undefined' ? false : window.innerWidth < 980))
  const candleRequestId = useRef(0)

  const trades = useMemo(() => result?.leaderboard.flatMap((row) => row.trades) || [], [result])
  const selectedStock = useMemo(
    () => watchlist.find((item) => item.symbol === selectedSymbol),
    [selectedSymbol, watchlist]
  )
  const sectors = useMemo(() => ['全部', ...Array.from(new Set(watchlist.map((item) => item.sector)))], [watchlist])
  const filteredWatchlist = useMemo(() => {
    const query = search.trim().toUpperCase()
    return watchlist.filter((item) => {
      const sectorMatched = sector === '全部' || item.sector === sector
      const queryMatched = !query || item.symbol.includes(query) || item.name.toUpperCase().includes(query)
      return sectorMatched && queryMatched
    })
  }, [search, sector, watchlist])
  const selectedDecisions = useMemo(
    () => (result?.decisions || []).filter((item) => item.symbol === selectedSymbol),
    [result, selectedSymbol]
  )
  const selectedTrades = useMemo(
    () => trades.filter((item) => item.symbol === selectedSymbol),
    [trades, selectedSymbol]
  )
  const bestAgent = useMemo(() => result?.leaderboard[0], [result])
  const activeSystemStatus = result?.system_status || systemStatus
  const chartMarkers = useMemo(() => {
    const tradeMarkers = selectedTrades.map((trade) => ({
      time: toDateKey(trade.timestamp),
      position: trade.action === 'BUY' ? 'belowBar' : 'aboveBar',
      color: trade.action === 'BUY' ? '#22c55e' : '#ef4444',
      shape: trade.action === 'BUY' ? 'arrowUp' : 'arrowDown',
      text: `${trade.agent} ${actionLabel(trade.action)}`
    }))
    const manual = manualMarkers
      .filter((item) => item.symbol === selectedSymbol)
      .map((item) => ({
        time: toDateKey(item.timestamp),
        position: item.action === 'BUY' ? 'belowBar' : 'aboveBar',
        color: item.action === 'BUY' ? '#14b8a6' : '#f97316',
        shape: item.action === 'BUY' ? 'arrowUp' : 'arrowDown',
        text: `手动${actionLabel(item.action)} ${item.shares}`
      }))
    return [...tradeMarkers, ...manual]
  }, [manualMarkers, selectedSymbol, selectedTrades])

  const loadWatchlist = async () => {
    setWatchlistLoading(true)
    try {
      const response = await fetch(`${API_BASE}/market/watchlist`)
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'watchlist_load_failed')
      setWatchlist(payload.stocks || [])
    } catch (err) {
      console.error(err)
      setWatchlist([])
    } finally {
      setWatchlistLoading(false)
    }
  }

  const loadRunHistory = async () => {
    try {
      const response = await fetch(`${API_BASE}/lobster-arena/runs?limit=8`)
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'runs_load_failed')
      setRunHistory(payload.runs || [])
    } catch (err) {
      console.error(err)
      setRunHistory([])
    }
  }

  const loadSystemStatus = async () => {
    try {
      const response = await fetch(`${API_BASE}/lobster-arena/status`)
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'status_load_failed')
      setSystemStatus(payload)
    } catch (err) {
      console.error(err)
    }
  }

  const loadRunDetail = async (runId: string) => {
    setHistoryLoadingId(runId)
    setError(null)
    try {
      const response = await fetch(`${API_BASE}/lobster-arena/runs/${encodeURIComponent(runId)}`)
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'run_detail_failed')
      if (payload.result) {
        setResult(payload.result)
      }
    } catch (err: any) {
      setError(err?.message || '历史详情加载失败。')
    } finally {
      setHistoryLoadingId(null)
    }
  }

  const loadCandles = async (symbol: string, nextRange: ChartRange, force = false) => {
    const normalized = symbol.trim().toUpperCase()
    if (!normalized) return
    const cacheKey = `${normalized}:${nextRange}`
    const cached = candleCache[cacheKey]
    const requestId = candleRequestId.current + 1
    candleRequestId.current = requestId
    if (cached && !force) {
      setCandleData(cached)
      setCandleWarning(null)
      return
    }

    const optimisticStock = watchlist.find((item) => item.symbol === normalized)
    setCandleData(buildLocalCandles(normalized, nextRange, optimisticStock))
    setCandleLoading(false)
    setCandleWarning(null)
    const controller = new AbortController()
    const timeoutId = window.setTimeout(() => controller.abort(), 8000)

    try {
      const params = new URLSearchParams({ symbol: normalized, range: nextRange, interval: '1d' })
      const response = await fetch(`${API_BASE}/market/candles?${params.toString()}`, { signal: controller.signal })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'candles_load_failed')
      if (candleRequestId.current !== requestId) return
      setCandleCache((current) => ({ ...current, [cacheKey]: payload }))
      setCandleData(payload)
      setCandleWarning(null)
    } catch (err: any) {
      if (candleRequestId.current !== requestId) return
      setCandleWarning(err?.name === 'AbortError' ? '实时行情响应较慢，当前显示本地模拟 K 线。' : '行情接口暂不可用，当前显示本地模拟 K 线。')
    } finally {
      window.clearTimeout(timeoutId)
      if (candleRequestId.current === requestId) {
        setCandleLoading(false)
      }
    }
  }

  const runArena = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch(`${API_BASE}/lobster-arena/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbols: symbols.split(',').map((symbol) => symbol.trim().toUpperCase()).filter(Boolean),
          initial_cash: initialCash,
          fee_rate: 0.001,
          max_position: 0.3,
          use_api_agent: useApiAgent,
          use_llm: useLlm,
          publish_to_platform: publishToPlatform
        })
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(payload.detail || 'Failed to run Lobster Arena.')
      }
      const payload = await response.json()
      setResult(payload)
      if (payload.system_status) {
        setSystemStatus(payload.system_status)
      }
      loadRunHistory()
    } catch (err: any) {
      setError(err?.message || 'Failed to run Lobster Arena.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadWatchlist()
    loadRunHistory()
    loadSystemStatus()
    runArena()
  }, [])

  useEffect(() => {
    const onResize = () => setIsCompact(window.innerWidth < 980)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  useEffect(() => {
    loadCandles(selectedSymbol, range)
  }, [range, selectedSymbol])

  const handleSelectStock = (symbol: string) => {
    setSelectedSymbol(symbol.toUpperCase())
  }

  const handleRangeChange = (nextRange: ChartRange) => {
    setRange(nextRange)
  }

  const handleAddManualMarker = () => {
    const shares = Number(orderQuantity || 0)
    if (!shares || shares <= 0 || !candleData) return
    setManualMarkers((current) => [
      ...current,
      {
        symbol: selectedSymbol,
        action: orderSide,
        shares,
        price: candleData.price,
        timestamp: new Date().toISOString()
      }
    ])
  }

  const openTradePage = () => {
    window.location.assign(`/trade?market=us-stock&symbol=${encodeURIComponent(selectedSymbol)}&action=${orderSide.toLowerCase()}`)
  }

  const price = candleData?.price || selectedStock?.price || 0
  const changePercent = candleData?.change_percent ?? selectedStock?.change_percent ?? 0
  const isUp = changePercent >= 0
  const shellColumns = isCompact ? '1fr' : 'minmax(250px, 290px) minmax(480px, 1fr) minmax(240px, 300px)'

  return (
    <div
      style={{
        color: '#e5edf6',
        background: 'radial-gradient(circle at 20% 0%, rgba(30, 41, 59, 0.72), transparent 34%), #020617',
        border: '1px solid rgba(148, 163, 184, 0.12)',
        borderRadius: 12,
        padding: isCompact ? 12 : 18,
        minHeight: 'calc(100vh - 48px)'
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'end', marginBottom: 16, flexWrap: 'wrap' }}>
        <div>
          <h1 className="page-title" style={{ marginBottom: 6, color: '#f8fafc' }}>AI 股票模拟交易控制台</h1>
          <p className="page-subtitle" style={{ maxWidth: 780, color: '#94a3b8' }}>
            50 只美股股票池，点击任意股票查看专业 K 线。AI 智能体与人类用户在同一行情和虚拟资金规则下模拟交易，真实券商接口仅预留，不会实际下单。
          </p>
        </div>
        <button className="btn btn-primary" type="button" onClick={runArena} disabled={loading}>
          {loading ? 'AI 正在模拟...' : '运行 AI 模拟交易'}
        </button>
      </div>

      <section style={{ display: 'grid', gridTemplateColumns: isCompact ? '1fr' : 'repeat(6, minmax(0, 1fr))', gap: 12, marginBottom: 12 }}>
        <div style={{ ...panelStyle, padding: 14 }}>
          <div style={{ color: '#64748b', fontSize: 12, fontWeight: 800 }}>最近运行</div>
          <div style={{ color: '#e2e8f0', fontSize: 14, fontWeight: 900, marginTop: 6 }}>{result?.run_id || runHistory[0]?.run_id || '-'}</div>
        </div>
        <div style={{ ...panelStyle, padding: 14 }}>
          <div style={{ color: '#64748b', fontSize: 12, fontWeight: 800 }}>券商模式</div>
          <div style={{ color: '#22c55e', fontSize: 14, fontWeight: 900, marginTop: 6 }}>
            {result?.broker_status?.mode === 'paper' ? '模拟交易，真实下单关闭' : '等待运行'}
          </div>
        </div>
        <div style={{ ...panelStyle, padding: 14 }}>
          <div style={{ color: '#64748b', fontSize: 12, fontWeight: 800 }}>本轮交易</div>
          <div style={{ color: '#e2e8f0', fontSize: 14, fontWeight: 900, marginTop: 6 }}>
            {result?.risk_summary ? `${result.risk_summary.trade_count} 笔 / 买 ${result.risk_summary.buy_count} / 卖 ${result.risk_summary.sell_count}` : '-'}
          </div>
        </div>
        <div style={{ ...panelStyle, padding: 14 }}>
          <div style={{ color: '#64748b', fontSize: 12, fontWeight: 800 }}>历史记录</div>
          <div style={{ color: '#e2e8f0', fontSize: 14, fontWeight: 900, marginTop: 6 }}>
            已保存 {runHistory.length} 次运行
          </div>
        </div>
        <div style={{ ...panelStyle, padding: 14 }}>
          <div style={{ color: '#64748b', fontSize: 12, fontWeight: 800 }}>LLM 状态</div>
          <div style={{ color: result?.llm?.status === 'error' ? '#f59e0b' : '#e2e8f0', fontSize: 14, fontWeight: 900, marginTop: 6 }}>
            {llmStatusLabel(result?.llm?.status)}
          </div>
        </div>
        <div style={{ ...panelStyle, padding: 14 }}>
          <div style={{ color: '#64748b', fontSize: 12, fontWeight: 800 }}>数据持久化</div>
          <div style={{ color: activeSystemStatus?.database?.temporary_sqlite ? '#f59e0b' : '#22c55e', fontSize: 14, fontWeight: 900, marginTop: 6 }}>
            {activeSystemStatus?.database?.temporary_sqlite ? '临时 SQLite' : activeSystemStatus?.database?.backend || 'SQLite'}
          </div>
        </div>
      </section>

      <div style={{ display: 'grid', gridTemplateColumns: shellColumns, gap: 12, alignItems: 'start' }}>
        <aside style={{ ...panelStyle, overflow: 'hidden' }}>
          <div style={{ padding: 14, borderBottom: '1px solid rgba(148, 163, 184, 0.16)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 900 }}>市场列表</div>
                <div style={{ color: '#64748b', fontSize: 12, marginTop: 4 }}>50 stocks · quote first</div>
              </div>
              <div style={{ color: '#f8fafc', fontWeight: 900, fontSize: 20 }}>{watchlist.length || 50}</div>
            </div>
            <input
              className="form-input"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索代码或名称，例如 NVDA"
              style={{ marginTop: 12, background: '#0b1620', borderColor: 'rgba(148, 163, 184, 0.18)' }}
            />
            <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingTop: 10, paddingBottom: 2 }}>
              {sectors.map((item) => (
                <button
                  key={item}
                  type="button"
                  onClick={() => setSector(item)}
                  style={{
                    border: '1px solid rgba(148, 163, 184, 0.18)',
                    background: sector === item ? '#d9a94f' : '#0b1620',
                    color: sector === item ? '#111827' : '#cbd5e1',
                    borderRadius: 6,
                    padding: '6px 10px',
                    whiteSpace: 'nowrap',
                    fontSize: 12,
                    fontWeight: 800,
                    cursor: 'pointer'
                  }}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>

          <div style={{ maxHeight: isCompact ? 360 : 760, overflowY: 'auto' }}>
            {watchlistLoading ? (
              <div className="empty-state"><div className="empty-title">正在加载股票池...</div></div>
            ) : filteredWatchlist.length === 0 ? (
              <div className="empty-state"><div className="empty-title">没有匹配股票</div></div>
            ) : (
              filteredWatchlist.map((stock) => {
                const active = selectedSymbol === stock.symbol
                const stockUp = stock.change_percent >= 0
                return (
                  <button
                    key={stock.symbol}
                    type="button"
                    onClick={() => handleSelectStock(stock.symbol)}
                    style={{
                      width: '100%',
                      border: 'none',
                      borderBottom: '1px solid rgba(148, 163, 184, 0.09)',
                      borderLeft: `3px solid ${active ? '#d9a94f' : 'transparent'}`,
                      padding: '11px 12px',
                      display: 'grid',
                      gridTemplateColumns: 'minmax(0, 1fr) 82px',
                      gap: 8,
                      textAlign: 'left',
                      cursor: 'pointer',
                      background: active ? 'linear-gradient(90deg, rgba(217,169,79,0.18), rgba(15,23,42,0.08))' : 'transparent',
                      color: '#e5edf6'
                    }}
                  >
                    <span style={{ minWidth: 0 }}>
                      <strong style={{ fontSize: 14 }}>{stock.symbol}</strong>
                      <span
                        style={{
                          marginLeft: 8,
                          color: '#8b9aab',
                          fontSize: 12,
                          display: 'inline-block',
                          maxWidth: isCompact ? 82 : 120,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                          verticalAlign: 'bottom'
                        }}
                      >
                        {stock.name}
                      </span>
                      <span style={{ display: 'block', color: '#64748b', fontSize: 12, marginTop: 3 }}>{stock.sector}</span>
                    </span>
                    <span style={{ textAlign: 'right' }}>
                      <strong style={{ fontSize: 13 }}>{formatMoney(stock.price, stock.currency)}</strong>
                      <span style={{ display: 'block', color: stockUp ? '#22c55e' : '#ef4444', fontSize: 12, marginTop: 3 }}>
                        {formatSignedPercent(stock.change_percent)}
                      </span>
                    </span>
                  </button>
                )
              })
            )}
          </div>
        </aside>

        <main style={{ ...panelStyle, overflow: 'hidden' }}>
          <div style={{ padding: '16px 18px 10px', borderBottom: '1px solid rgba(148, 163, 184, 0.13)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', alignItems: 'start' }}>
              <div>
                <div style={{ color: '#64748b', fontSize: 12, fontWeight: 800, textTransform: 'uppercase', letterSpacing: 0 }}>
                  {candleData?.sector || selectedStock?.sector || 'US Stock'} · {candleData?.source === 'yahoo' ? 'Yahoo Finance' : 'Local fallback'}
                </div>
                <div style={{ display: 'flex', gap: 12, alignItems: 'baseline', flexWrap: 'wrap', marginTop: 5 }}>
                  <h2 style={{ margin: 0, fontSize: isCompact ? 26 : 34, lineHeight: 1, fontWeight: 950 }}>
                    {selectedSymbol}
                  </h2>
                  <span style={{ color: '#94a3b8', fontSize: 16, fontWeight: 700 }}>
                    {candleData?.name || selectedStock?.name || ''}
                  </span>
                </div>
              </div>
              <div style={{ textAlign: isCompact ? 'left' : 'right' }}>
                <div style={{ fontSize: isCompact ? 28 : 34, fontWeight: 950, lineHeight: 1 }}>{formatMoney(price, candleData?.currency || selectedStock?.currency || 'USD')}</div>
                <div style={{ color: isUp ? '#22c55e' : '#ef4444', fontWeight: 900, marginTop: 6 }}>
                  {formatSignedPercent(changePercent)}
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', marginTop: 16, flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {RANGE_OPTIONS.map((item) => (
                  <ToggleButton key={item.value} active={range === item.value} onClick={() => handleRangeChange(item.value)}>
                    {item.label}
                  </ToggleButton>
                ))}
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <ToggleButton active={showMA5} onClick={() => setShowMA5((value) => !value)}>MA5</ToggleButton>
                <ToggleButton active={showMA20} onClick={() => setShowMA20((value) => !value)}>MA20</ToggleButton>
                <ToggleButton active={showVolume} onClick={() => setShowVolume((value) => !value)}>VOL</ToggleButton>
              </div>
            </div>
          </div>

          {candleWarning && (
            <div style={{ color: '#fbbf24', background: 'rgba(251, 191, 36, 0.08)', padding: '9px 18px', fontSize: 12 }}>
              {candleWarning}
            </div>
          )}
          <div style={{ padding: isCompact ? '12px 10px 14px' : '14px 16px 18px', background: '#050a0f' }}>
            <KLineChart
              data={candleData}
              markers={chartMarkers}
              loading={candleLoading}
              showMA5={showMA5}
              showMA20={showMA20}
              showVolume={showVolume}
              compact={isCompact}
            />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: isCompact ? '1fr 1fr' : 'repeat(4, 1fr)', borderTop: '1px solid rgba(148, 163, 184, 0.13)' }}>
            {[
              ['周期', `${range.toUpperCase()} / 1D`],
              ['更新时间', formatShortDate(candleData?.fetched_at || selectedStock?.market_time)],
              ['买卖点', `${chartMarkers.length}`],
              ['数据源', candleData?.source || 'loading']
            ].map(([label, value]) => (
              <div key={label} style={{ padding: '11px 14px', borderRight: '1px solid rgba(148, 163, 184, 0.09)' }}>
                <div style={{ color: '#64748b', fontSize: 11, fontWeight: 800 }}>{label}</div>
                <div style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 800, marginTop: 4 }}>{value}</div>
              </div>
            ))}
          </div>
        </main>

        <aside style={{ display: 'grid', gap: 12 }}>
          <section style={{ ...panelStyle, padding: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 900 }}>纸上交易</div>
                <div style={{ color: '#64748b', fontSize: 12, marginTop: 4 }}>虚拟资金，不接真实券商</div>
              </div>
              <div style={{ color: '#94a3b8', fontSize: 12, fontWeight: 800 }}>{selectedSymbol}</div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
              <button
                type="button"
                onClick={() => setOrderSide('BUY')}
                style={{
                  border: '1px solid rgba(34, 197, 94, 0.45)',
                  background: orderSide === 'BUY' ? '#16a34a' : 'rgba(22, 163, 74, 0.12)',
                  color: '#f8fafc',
                  borderRadius: 6,
                  padding: '10px 0',
                  fontWeight: 900,
                  cursor: 'pointer'
                }}
              >
                买入
              </button>
              <button
                type="button"
                onClick={() => setOrderSide('SELL')}
                style={{
                  border: '1px solid rgba(239, 68, 68, 0.45)',
                  background: orderSide === 'SELL' ? '#dc2626' : 'rgba(220, 38, 38, 0.12)',
                  color: '#f8fafc',
                  borderRadius: 6,
                  padding: '10px 0',
                  fontWeight: 900,
                  cursor: 'pointer'
                }}
              >
                卖出
              </button>
            </div>
            <label className="form-group" style={{ marginBottom: 10 }}>
              <span className="form-label">股票代码</span>
              <input className="form-input" value={selectedSymbol} readOnly />
            </label>
            <label className="form-group" style={{ marginBottom: 12 }}>
              <span className="form-label">数量</span>
              <input className="form-input" value={orderQuantity} onChange={(event) => setOrderQuantity(event.target.value)} type="number" min={1} />
            </label>
            <div style={{ display: 'grid', gap: 8 }}>
              <button className="btn btn-primary" type="button" onClick={openTradePage}>
                去交易页下单
              </button>
              <button className="btn btn-secondary" type="button" onClick={handleAddManualMarker}>
                在 K 线上添加模拟标记
              </button>
            </div>
          </section>

          <section style={{ ...panelStyle, padding: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
              <div style={{ fontSize: 16, fontWeight: 900 }}>AI 观点</div>
              <div style={{ color: '#64748b', fontSize: 12 }}>{selectedDecisions.length} 条</div>
            </div>
            {selectedDecisions.length === 0 ? (
              <div style={{ color: '#94a3b8', lineHeight: 1.7, fontSize: 13 }}>
                运行 AI 模拟后，这里会显示智能体对 {selectedSymbol} 的买卖判断。
              </div>
            ) : (
              <div style={{ display: 'grid', gap: 10, maxHeight: 320, overflowY: 'auto' }}>
                {selectedDecisions.slice(0, 6).map((decision, index) => (
                  <div key={`${decision.agent}-${index}`} style={{ border: '1px solid rgba(148, 163, 184, 0.14)', borderRadius: 8, padding: 10, background: '#0a141d' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                      <strong>{decision.agent}</strong>
                      <span style={{ color: actionColor(decision.action), fontWeight: 900 }}>{actionLabel(decision.action)}</span>
                    </div>
                    <div style={{ color: '#64748b', fontSize: 12, marginTop: 4 }}>
                      信心 {Math.round(decision.confidence * 100)}% · 仓位 {Math.round(decision.target_fraction * 100)}%
                      {decision.llm_enhanced ? ' · LLM 已增强' : ''}
                    </div>
                    <div style={{ color: '#a7b4c5', fontSize: 13, lineHeight: 1.6, marginTop: 8 }}>
                      {decision.reason}
                    </div>
                    {decision.signals && (
                      <div style={{ color: '#64748b', fontSize: 12, lineHeight: 1.6, marginTop: 8 }}>
                        动量 {Number(decision.signals.momentum_percent || 0).toFixed(2)}% · 波动 {Number(decision.signals.volatility_percent || 0).toFixed(2)}% · 数据 {decision.signals.data_source || '-'}
                      </div>
                    )}
                    {decision.risk_note && (
                      <div style={{ color: '#fbbf24', fontSize: 12, lineHeight: 1.6, marginTop: 6 }}>
                        {decision.risk_note}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

          <section style={{ ...panelStyle, padding: 14 }}>
            <div style={{ fontSize: 16, fontWeight: 900, marginBottom: 12 }}>擂台状态</div>
            <div style={{ display: 'grid', gap: 10 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: '#94a3b8' }}>
                <span>领先智能体</span>
                <strong style={{ color: '#e2e8f0' }}>{bestAgent?.agent || '-'}</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: '#94a3b8' }}>
                <span>收益率</span>
                <strong style={{ color: (bestAgent?.return_percent || 0) >= 0 ? '#22c55e' : '#ef4444' }}>
                  {bestAgent ? formatSignedPercent(bestAgent.return_percent) : '-'}
                </strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: '#94a3b8' }}>
                <span>交易记录</span>
                <strong style={{ color: '#e2e8f0' }}>{trades.length}</strong>
              </div>
            </div>
          </section>
        </aside>
      </div>

      <section style={{ ...panelStyle, marginTop: 12, padding: 14 }}>
        <div style={{ display: 'grid', gridTemplateColumns: isCompact ? '1fr' : 'minmax(260px, 1fr) 170px 130px', gap: 12, alignItems: 'end' }}>
          <label className="form-group" style={{ marginBottom: 0 }}>
            <span className="form-label">参赛股票代码</span>
            <input className="form-input" value={symbols} onChange={(event) => setSymbols(event.target.value)} />
          </label>
          <label className="form-group" style={{ marginBottom: 0 }}>
            <span className="form-label">初始虚拟资金</span>
            <input className="form-input" type="number" min={1000} value={initialCash} onChange={(event) => setInitialCash(Number(event.target.value))} />
          </label>
          <button className="btn btn-secondary" type="button" onClick={runArena} disabled={loading}>
            刷新决策
          </button>
        </div>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 14 }}>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, color: '#94a3b8' }}>
            <input type="checkbox" checked={useApiAgent} onChange={(event) => setUseApiAgent(event.target.checked)} />
            启用 NewAPI 智能体参赛
          </label>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, color: '#94a3b8' }}>
            <input type="checkbox" checked={useLlm} onChange={(event) => setUseLlm(event.target.checked)} />
            使用大模型增强交易理由
          </label>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, color: '#94a3b8' }}>
            <input type="checkbox" checked={publishToPlatform} onChange={(event) => setPublishToPlatform(event.target.checked)} />
            同步到平台账户、持仓、策略和讨论
          </label>
        </div>
        <div style={{ marginTop: 12, color: '#94a3b8', fontSize: 12, lineHeight: 1.7 }}>
          {activeSystemStatus?.database?.persistence_note || '当前保留 SQLite 低成本部署方案。'}
          {' '}LLM 只增强中文解释，不改动作、仓位和风控；真实下单始终关闭。
        </div>
        {error && <div style={{ marginTop: 14, color: '#ef4444', fontWeight: 800 }}>{error}</div>}
      </section>

      {result && (
        <>
        <section style={{ display: 'grid', gridTemplateColumns: isCompact ? '1fr' : 'minmax(420px, 1fr) minmax(420px, 1fr)', gap: 12, marginTop: 12 }}>
          <div style={panelStyle}>
            <div style={{ padding: 14, borderBottom: '1px solid rgba(148, 163, 184, 0.13)', fontWeight: 900 }}>智能体排行榜</div>
            <div className="table-container">
              <table className="table">
                <thead>
                  <tr>
                    <th>排名</th>
                    <th>智能体</th>
                    <th>总资产</th>
                    <th>收益率</th>
                    <th>持仓</th>
                  </tr>
                </thead>
                <tbody>
                  {result.leaderboard.map((row, index) => (
                    <tr key={row.agent}>
                      <td>{index + 1}</td>
                      <td>{row.agent}</td>
                      <td>{formatMoney(row.total_value)}</td>
                      <td style={{ color: row.return_percent >= 0 ? '#22c55e' : '#ef4444', fontWeight: 800 }}>
                        {formatSignedPercent(row.return_percent)}
                      </td>
                      <td>{formatPositions(row.positions)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div style={panelStyle}>
            <div style={{ padding: 14, borderBottom: '1px solid rgba(148, 163, 184, 0.13)', fontWeight: 900 }}>当前股票交易记录</div>
            <div className="table-container">
              <table className="table">
                <thead>
                  <tr>
                    <th>智能体</th>
                    <th>操作</th>
                    <th>股票</th>
                    <th>股数</th>
                    <th>金额</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedTrades.map((trade, index) => (
                    <tr key={`${trade.agent}-${trade.symbol}-${index}`}>
                      <td>{trade.agent}</td>
                      <td style={{ color: actionColor(trade.action), fontWeight: 800 }}>{actionLabel(trade.action)}</td>
                      <td>{trade.symbol}</td>
                      <td>{trade.shares}</td>
                      <td>{formatMoney(trade.value)}</td>
                    </tr>
                  ))}
                  {selectedTrades.length === 0 && (
                    <tr>
                      <td colSpan={5}>当前还没有 {selectedSymbol} 的 AI 成交记录。</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section style={{ display: 'grid', gridTemplateColumns: isCompact ? '1fr' : 'minmax(420px, 1.2fr) minmax(320px, 0.8fr)', gap: 12, marginTop: 12 }}>
          <div style={panelStyle}>
            <div style={{ padding: 14, borderBottom: '1px solid rgba(148, 163, 184, 0.13)', fontWeight: 900 }}>智能体复盘</div>
            <div style={{ display: 'grid', gap: 10, padding: 14 }}>
              {(result.agent_reports || []).map((report) => (
                <div key={report.agent} style={{ border: '1px solid rgba(148, 163, 184, 0.14)', borderRadius: 8, padding: 12, background: '#0a141d' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
                    <div>
                      <strong style={{ color: '#f8fafc' }}>{report.agent}</strong>
                      <div style={{ color: '#94a3b8', fontSize: 12, marginTop: 4 }}>{report.profile.role} · {report.profile.style}</div>
                    </div>
                    <div style={{ color: report.return_percent >= 0 ? '#22c55e' : '#ef4444', fontWeight: 900 }}>
                      {formatSignedPercent(report.return_percent)}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 10, color: '#cbd5e1', fontSize: 12 }}>
                    <span>买 {report.decision_counts.BUY}</span>
                    <span>卖 {report.decision_counts.SELL}</span>
                    <span>持有 {report.decision_counts.HOLD}</span>
                    <span>成交 {report.trade_count}</span>
                  </div>
                  <div style={{ color: '#a7b4c5', fontSize: 13, lineHeight: 1.7, marginTop: 8 }}>{report.review}</div>
                  <div style={{ color: '#fbbf24', fontSize: 12, lineHeight: 1.6, marginTop: 8 }}>{report.profile.risk_rule}</div>
                </div>
              ))}
            </div>
          </div>

          <div style={{ display: 'grid', gap: 12 }}>
            <section style={{ ...panelStyle, padding: 14 }}>
              <div style={{ fontSize: 16, fontWeight: 900, marginBottom: 12 }}>风控与系统状态</div>
              <div style={{ display: 'grid', gap: 9 }}>
                {(result.risk_events || []).map((event, index) => (
                  <div key={`${event.code || event.message}-${index}`} style={{ display: 'grid', gridTemplateColumns: '10px minmax(0, 1fr)', gap: 9, alignItems: 'start' }}>
                    <span style={{ width: 9, height: 9, borderRadius: 99, background: severityColor(event.severity), marginTop: 5 }} />
                    <span style={{ color: '#a7b4c5', fontSize: 13, lineHeight: 1.6 }}>
                      {event.agent ? `${event.agent} · ` : ''}{event.symbol ? `${event.symbol} · ` : ''}{event.message}
                    </span>
                  </div>
                ))}
              </div>
              <div style={{ borderTop: '1px solid rgba(148, 163, 184, 0.13)', marginTop: 12, paddingTop: 12, color: '#94a3b8', fontSize: 12, lineHeight: 1.7 }}>
                {result.broker_status?.message || '模拟交易模式，真实下单关闭。'}<br />
                {result.llm?.message || llmStatusLabel(result.llm?.status)}
              </div>
            </section>

            <section style={{ ...panelStyle, padding: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', marginBottom: 12 }}>
                <div style={{ fontSize: 16, fontWeight: 900 }}>历史详情</div>
                <button className="btn btn-secondary" type="button" onClick={loadRunHistory}>刷新</button>
              </div>
              <div style={{ display: 'grid', gap: 8, maxHeight: 280, overflowY: 'auto' }}>
                {runHistory.length === 0 ? (
                  <div style={{ color: '#94a3b8', fontSize: 13 }}>暂无历史运行记录。</div>
                ) : (
                  runHistory.map((run) => (
                    <button
                      key={run.run_id}
                      type="button"
                      onClick={() => loadRunDetail(run.run_id)}
                      style={{
                        border: '1px solid rgba(148, 163, 184, 0.14)',
                        background: result.run_id === run.run_id ? 'rgba(217,169,79,0.16)' : '#0a141d',
                        color: '#e5edf6',
                        borderRadius: 8,
                        padding: 10,
                        textAlign: 'left',
                        cursor: 'pointer'
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                        <strong style={{ fontSize: 12 }}>{run.run_id}</strong>
                        <span style={{ color: '#94a3b8', fontSize: 12 }}>{historyLoadingId === run.run_id ? '加载中' : run.status}</span>
                      </div>
                      <div style={{ color: '#94a3b8', fontSize: 12, marginTop: 5 }}>
                        {formatShortDate(run.created_at)} · {run.summary?.trade_count || 0} 笔 · {llmStatusLabel(run.summary?.llm_status)}
                      </div>
                    </button>
                  ))
                )}
              </div>
            </section>
          </div>
        </section>
        </>
      )}
    </div>
  )
}
