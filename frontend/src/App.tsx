import { useEffect, useState, useCallback, useRef } from 'react'
import axios from 'axios'
import { motion, AnimatePresence } from 'framer-motion'
import {
  RefreshCw, TrendingUp, TrendingDown, Minus, Zap,
  Bell, CheckCircle, AlertCircle, Calendar, Award,
  Clock, ArrowUpRight, Send, ChevronDown
} from 'lucide-react'

const API = (typeof window !== 'undefined' && (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') && window.location.port === '5173')
  ? 'http://localhost:8000'
  : ''

// Events where LOWER actual = positive surprise (fewer unemployed = stronger economy)
const INVERSE_EVENTS = new Set(['JOBLESS_CLAIMS', 'UNEMPLOYMENT_RATE'])

// Mapping of currency pairs and assets directly affected by each event
const EVENT_AFFECTED_PAIRS: Record<string, string[]> = {
  NFP: ['EUR/USD', 'USD/JPY', 'GBP/USD', 'XAU/USD', 'US500'],
  CPI: ['EUR/USD', 'USD/JPY', 'XAU/USD', 'GBP/USD', 'US500'],
  CORE_CPI: ['EUR/USD', 'USD/JPY', 'XAU/USD', 'GBP/USD'],
  PPI: ['EUR/USD', 'USD/JPY', 'XAU/USD'],
  JOBLESS_CLAIMS: ['EUR/USD', 'USD/JPY', 'XAU/USD', 'GBP/USD'],
  UNEMPLOYMENT_RATE: ['EUR/USD', 'USD/JPY', 'GBP/USD', 'XAU/USD'],
  GDP: ['EUR/USD', 'USD/JPY', 'US500', 'XAU/USD'],
  FOMC: ['EUR/USD', 'USD/JPY', 'XAU/USD', 'US500', 'US30'],
  RETAIL_SALES: ['EUR/USD', 'USD/JPY', 'US30', 'XAU/USD'],
  ISM_MFG: ['USD/JPY', 'EUR/USD', 'US30'],
  CONSUMER_CONFIDENCE: ['EUR/USD', 'USD/JPY', 'US500'],
}

interface EventTiming {
  dateFormatted: string
  timeNy: string
  timeLocal: string
  countdownText: string
  urgency: 'imminent' | 'soon' | 'today' | 'future' | 'passed'
  isPassed: boolean
  diffMs: number
}

function getEventTiming(releaseTimeUtc: string, now: number): EventTiming {
  if (!releaseTimeUtc) {
    return {
      dateFormatted: 'Date TBD',
      timeNy: 'TBD',
      timeLocal: 'TBD',
      countdownText: 'TBD',
      urgency: 'future',
      isPassed: false,
      diffMs: 0,
    }
  }

  const d = new Date(releaseTimeUtc)
  const targetMs = d.getTime()
  if (isNaN(targetMs)) {
    return {
      dateFormatted: 'Date TBD',
      timeNy: 'TBD',
      timeLocal: 'TBD',
      countdownText: 'TBD',
      urgency: 'future',
      isPassed: false,
      diffMs: 0,
    }
  }

  const dateFormatted = new Intl.DateTimeFormat('en-US', {
    weekday: 'long',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(d)

  let timeNy = ''
  try {
    timeNy = new Intl.DateTimeFormat('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'America/New_York',
      timeZoneName: 'short',
    }).format(d)
  } catch {
    timeNy = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }

  const timeLocal = new Intl.DateTimeFormat('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    timeZoneName: 'short',
  }).format(d)

  const diffMs = targetMs - now
  const isPassed = diffMs <= 0

  let countdownText = ''
  let urgency: 'imminent' | 'soon' | 'today' | 'future' | 'passed' = 'future'

  if (isPassed) {
    const passedMins = Math.floor(-diffMs / 60000)
    if (passedMins < 60) {
      countdownText = `Released ${passedMins}m ago`
    } else if (passedMins < 1440) {
      countdownText = `Released ${Math.floor(passedMins / 60)}h ${passedMins % 60}m ago`
    } else {
      countdownText = `Completed (${Math.floor(passedMins / 1440)}d ago)`
    }
    urgency = 'passed'
  } else {
    const totalSecs = Math.floor(diffMs / 1000)
    const days = Math.floor(totalSecs / 86400)
    const hours = Math.floor((totalSecs % 86400) / 3600)
    const mins = Math.floor((totalSecs % 3600) / 60)
    const secs = totalSecs % 60

    if (days > 0) {
      countdownText = `${days}d ${hours.toString().padStart(2, '0')}h ${mins.toString().padStart(2, '0')}m ${secs.toString().padStart(2, '0')}s`
    } else {
      countdownText = `${hours.toString().padStart(2, '0')}h ${mins.toString().padStart(2, '0')}m ${secs.toString().padStart(2, '0')}s`
    }

    if (diffMs <= 15 * 60 * 1000) {
      urgency = 'imminent'
    } else if (diffMs <= 2 * 3600 * 1000) {
      urgency = 'soon'
    } else if (diffMs <= 24 * 3600 * 1000) {
      urgency = 'today'
    } else {
      urgency = 'future'
    }
  }

  return {
    dateFormatted,
    timeNy,
    timeLocal,
    countdownText,
    urgency,
    isPassed,
    diffMs,
  }
}

function CountdownBadge({ releaseTimeUtc, now }: { releaseTimeUtc: string; now: number }) {
  const timing = getEventTiming(releaseTimeUtc, now)

  if (timing.urgency === 'imminent') {
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-mono font-black bg-red-500/25 text-red-300 border border-red-500 animate-pulse shadow-lg shadow-red-500/30">
        <span className="w-2 h-2 rounded-full bg-red-400 animate-ping" />
        🚨 IMMINENT: {timing.countdownText}
      </span>
    )
  }

  if (timing.urgency === 'soon') {
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-mono font-black bg-amber-500/20 text-amber-300 border border-amber-500/40 animate-pulse shadow-md shadow-amber-500/20">
        <Clock className="w-3.5 h-3.5 text-amber-400" />
        ⚠️ SOON: {timing.countdownText}
      </span>
    )
  }

  if (timing.urgency === 'today') {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/40">
        <Clock className="w-3.5 h-3.5 text-indigo-400" />
        ⏳ TODAY: {timing.countdownText}
      </span>
    )
  }

  if (timing.urgency === 'passed') {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono font-medium bg-slate-800 text-slate-400 border border-white/10">
        <CheckCircle className="w-3.5 h-3.5 text-slate-500" />
        {timing.countdownText}
      </span>
    )
  }

  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono font-bold bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">
      <Clock className="w-3.5 h-3.5 text-cyan-400" />
      ⏱️ {timing.countdownText}
    </span>
  )
}

function getSurpriseColor(eventCode: string, surprise: number | null): string {
  if (surprise == null) return '#94a3b8'
  const isInverse = INVERSE_EVENTS.has(eventCode)
  const isPositive = isInverse ? surprise < 0 : surprise > 0
  return isPositive ? '#34d399' : '#f87171'
}

function getSurpriseLabel(eventCode: string, surprise: number | null): string {
  if (surprise == null) return '—'
  const isInverse = INVERSE_EVENTS.has(eventCode)
  const sign = surprise > 0 ? '+' : ''
  const numStr = `${sign}${surprise}`
  if (Math.abs(surprise) < 0.001) return `${numStr} (In-Line)`
  const isPositive = isInverse ? surprise < 0 : surprise > 0
  return `${numStr} (${isPositive ? '✅ USD+' : '❌ USD−'})`
}

// ── Types ─────────────────────────────────────────────────────────────────────
interface Indicator {
  fred_series: string
  description: string
  latest_value: number | null
  prev_value: number | null
  z_score: number | null
  signal: number   // +1, 0, -1
  weight: number
}

interface Prediction {
  id: number
  event_code: string
  display_name: string
  lean_direction: 'BEAT' | 'MISS' | 'INLINE' | 'BULLISH' | 'BEARISH' | string
  event_label?: string
  explanation?: string
  confidence_pct: number
  composite_score: number
  created_at: string
  was_correct: boolean | null
  trade_signals?: string[]
  indicator_breakdown: Indicator[]
}

interface CalendarEvent {
  event_code: string
  event_name: string
  release_time_utc: string
  forecast: number | null
  previous: number | null
  actual: number | null
  impact: string
  currency?: string
  trade_signals?: Record<string, string[]>
}

interface HistoryItem {
  id: number
  event_code: string
  display_name: string
  lean_direction: string
  confidence_pct: number
  composite_score: number
  forecast: number | null
  actual: number | null
  surprise: number | null
  was_correct: boolean | null
  trade_signals: string[]
  date: string
}

interface AccuracyStats {
  total_predictions: number
  wins: number
  losses: number
  overall_hit_rate: number
  event_stats: {
    event_code: string
    display_name: string
    total: number
    wins: number
    hit_rate_pct: number
  }[]
}

interface HealthStatus {
  fred_configured: boolean
  telegram_configured: boolean
  alert_hours_before?: string
  supported_events: string[]
  scheduler_running?: boolean
}

const DIRECTION_CONFIG: Record<string, { label: string; color: string; bg: string; border: string; icon: any; glow: string }> = {
  BEAT:    { label: 'BULLISH USD', color: '#34d399', bg: 'rgba(52,211,153,0.12)', border: 'border-glow-green',  icon: TrendingUp,   glow: 'glow-green'  },
  BULLISH: { label: 'BULLISH USD', color: '#34d399', bg: 'rgba(52,211,153,0.12)', border: 'border-glow-green',  icon: TrendingUp,   glow: 'glow-green'  },
  MISS:    { label: 'BEARISH USD', color: '#f87171', bg: 'rgba(248,113,113,0.12)', border: 'border-glow-red',   icon: TrendingDown, glow: 'glow-red'    },
  BEARISH: { label: 'BEARISH USD', color: '#f87171', bg: 'rgba(248,113,113,0.12)', border: 'border-glow-red',   icon: TrendingDown, glow: 'glow-red'    },
  INLINE:  { label: 'INLINE',      color: '#fbbf24', bg: 'rgba(251,191,36,0.12)',  border: 'border-glow-yellow', icon: Minus,        glow: 'glow-yellow' },
}

const SIGNAL_LABELS: Record<number, { label: string; color: string }> = {
  1:    { label: 'BULLISH', color: '#34d399' },
  0:    { label: 'NEUTRAL', color: '#94a3b8' },
  '-1': { label: 'BEARISH', color: '#f87171' },
}

function ConfidenceBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="confidence-bar-track w-full">
      <motion.div
        className="confidence-bar-fill"
        style={{ background: color }}
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.8, ease: 'easeOut' }}
      />
    </div>
  )
}

function IndicatorRow({ ind }: { ind: Indicator }) {
  const sig = SIGNAL_LABELS[ind.signal] ?? SIGNAL_LABELS[0]
  const z = ind.z_score

  return (
    <div className="flex items-center justify-between py-2.5 border-b border-white/5 last:border-0 gap-3">
      <div className="flex-1 min-w-0">
        <p className="text-xs text-slate-300 font-medium truncate">{ind.description}</p>
        <p className="text-[10px] text-slate-500 font-mono">{ind.fred_series}</p>
      </div>
      <div className="flex items-center gap-3 flex-shrink-0">
        <span className="text-xs font-mono text-slate-400">
          {ind.latest_value != null ? ind.latest_value.toFixed(2) : '—'}
        </span>
        <span className="text-xs font-mono" style={{ color: z != null ? (z > 0 ? '#34d399' : z < 0 ? '#f87171' : '#94a3b8') : '#94a3b8' }}>
          {z != null ? `z${z >= 0 ? '+' : ''}${z.toFixed(2)}` : 'z=n/a'}
        </span>
        <span
          className="text-[11px] font-bold px-2 py-0.5 rounded-full"
          style={{ color: sig.color, background: sig.color + '18', minWidth: 62, textAlign: 'center' }}
        >
          {sig.label}
        </span>
        <span className="text-[11px] text-slate-500 w-8 text-right">{(ind.weight * 100).toFixed(0)}%</span>
      </div>
    </div>
  )
}

function PredictionCard({
  pred,
  calendarEvent,
  now = Date.now(),
  onRefresh,
  onSendTelegram
}: {
  pred: Prediction
  calendarEvent?: CalendarEvent
  now?: number
  onRefresh: (code: string) => void
  onSendTelegram: (code: string) => Promise<boolean>
}) {
  const [expanded, setExpanded] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [sendingTg, setSendingTg] = useState(false)
  const [sentTg, setSentTg] = useState(false)

  const cfg = DIRECTION_CONFIG[pred.lean_direction] ?? DIRECTION_CONFIG.INLINE
  const Icon = cfg.icon

  const indicators: Indicator[] = (pred.indicator_breakdown && pred.indicator_breakdown.length > 0)
    ? pred.indicator_breakdown
    : ((pred as any).indicators || [])

  const handleRefresh = async () => {
    setRefreshing(true)
    await onRefresh(pred.event_code)
    setRefreshing(false)
  }

  const handleSendTelegram = async () => {
    setSendingTg(true)
    const ok = await onSendTelegram(pred.event_code)
    setSendingTg(false)
    if (ok) {
      setSentTg(true)
      setTimeout(() => setSentTg(false), 3000)
    }
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      className={`glass p-5 ${cfg.border} transition-all hover:bg-slate-900/60`}
      style={{ borderColor: cfg.color + '35' }}
    >
      {/* ── Header row ── */}
      <div className="flex items-start justify-between gap-4 mb-3">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-black tracking-widest text-indigo-400 uppercase bg-indigo-500/10 px-2 py-0.5 rounded">
              {pred.event_code}
            </span>
            <span className="live-dot" />
            <span className="text-[11px] text-slate-500 font-mono">
              {new Date(pred.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
            {/* ── Honest Outcome Badge (only shown after grading) ── */}
            {pred.was_correct === true && (
              <span className="ml-1 flex items-center gap-1 text-[10px] font-black px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 uppercase tracking-wide">
                <CheckCircle className="w-3 h-3" /> PREDICTION WON
              </span>
            )}
            {pred.was_correct === false && (
              <span className="ml-1 flex items-center gap-1 text-[10px] font-black px-2 py-0.5 rounded-full bg-red-500/20 text-red-400 border border-red-500/30 uppercase tracking-wide">
                <AlertCircle className="w-3 h-3" /> PREDICTION MISSED
              </span>
            )}
          </div>
          <h2 className="text-lg font-bold text-white tracking-tight">{pred.display_name}</h2>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={handleSendTelegram}
            title="Send this signal to Telegram"
            className={`p-2 rounded-xl glass-sm transition-all active:scale-95 ${
              sentTg
                ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                : 'hover:bg-cyan-500/10 text-cyan-400 hover:text-cyan-300 border border-cyan-500/20'
            }`}
          >
            {sendingTg ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : sentTg ? (
              <CheckCircle className="w-4 h-4 text-emerald-400" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </button>

          <button
            onClick={handleRefresh}
            title="Recalculate leading indicators"
            className="p-2 rounded-xl glass-sm hover:bg-white/10 transition-all active:scale-95 text-slate-400 hover:text-white border border-white/5"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin text-indigo-400' : ''}`} />
          </button>
        </div>
      </div>

      {/* ── Scheduled Release Time & Live Countdown Bar ── */}
      {calendarEvent?.release_time_utc && (
        <div className="mb-4 px-3 py-2 rounded-xl bg-slate-800/80 border border-indigo-500/20 flex flex-wrap items-center justify-between gap-2 text-xs">
          <div className="flex items-center gap-2 text-slate-300">
            <Clock className="w-3.5 h-3.5 text-indigo-400 flex-shrink-0" />
            <span className="font-semibold text-slate-200">
              {getEventTiming(calendarEvent.release_time_utc, now).dateFormatted}
            </span>
            <span className="text-cyan-300 font-mono text-[11px]">
              • {getEventTiming(calendarEvent.release_time_utc, now).timeNy} (NY)
            </span>
          </div>
          <CountdownBadge releaseTimeUtc={calendarEvent.release_time_utc} now={now} />
        </div>
      )}

      {/* ── Direction + Score Banner ── */}
      <div className="flex items-center justify-between gap-4 mb-4 bg-white/[0.02] p-3 rounded-xl border border-white/5">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-lg" style={{ background: cfg.bg }}>
            <Icon className="w-5 h-5" style={{ color: cfg.color }} />
          </div>
          <div>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">
              {pred.lean_direction === 'BEAT' || pred.lean_direction === 'BULLISH'
                ? '🟢 USD BULLISH BIAS'
                : pred.lean_direction === 'MISS' || pred.lean_direction === 'BEARISH'
                ? '🔴 USD BEARISH BIAS'
                : '🟡 NEUTRAL / INLINE'}
            </p>
            <span className={`text-base font-black tracking-wide ${cfg.glow}`} style={{ color: cfg.color }}>
              {pred.event_label || cfg.label}
            </span>
          </div>
        </div>

        <div className="text-right">
          <p className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Composite</p>
          <p className="text-lg font-mono font-bold" style={{ color: cfg.color }}>
            {pred.composite_score >= 0 ? '+' : ''}{pred.composite_score.toFixed(3)}
          </p>
        </div>
      </div>

      {/* ── Confidence bar ── */}
      <div className="mb-4">
        <div className="flex justify-between items-center mb-1.5">
          <span className="text-[11px] text-slate-400 uppercase tracking-wider font-medium">Model Confidence</span>
          <span className="text-sm font-black font-mono" style={{ color: cfg.color }}>
            {pred.confidence_pct.toFixed(0)}%
          </span>
        </div>
        <ConfidenceBar pct={pred.confidence_pct} color={cfg.color} />
      </div>

      {/* ── Affected Pairs ── */}
      <div className="mb-3">
        <p className="text-[10px] text-slate-400 uppercase font-bold tracking-wider mb-1.5">
          🎯 Pairs to be Affected
        </p>
        <div className="flex flex-wrap gap-1.5">
          {(EVENT_AFFECTED_PAIRS[pred.event_code] || ['EUR/USD', 'USD/JPY', 'GBP/USD', 'XAU/USD', 'US500']).map((pair, idx) => (
            <span
              key={idx}
              className="text-xs font-mono font-bold px-2.5 py-0.5 rounded-md bg-indigo-950/40 text-indigo-300 border border-indigo-500/20"
            >
              {pair}
            </span>
          ))}
        </div>
      </div>

      {/* ── Trade Signals ── */}
      {pred.trade_signals && pred.trade_signals.length > 0 && (
        <div className="mb-3">
          <p className="text-[10px] text-slate-500 uppercase font-semibold mb-1.5 tracking-wider">Trading Recommendations</p>
          <div className="flex flex-wrap gap-1.5">
            {pred.trade_signals.map((sig, idx) => {
              const isBuy = sig.startsWith('BUY')
              const isWait = sig.startsWith('WAIT')
              return (
                <span
                  key={idx}
                  className={`text-xs font-mono font-bold px-2.5 py-1 rounded-md border flex items-center gap-1.5 ${
                    isBuy
                      ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
                      : isWait
                      ? 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                      : 'bg-red-500/10 text-red-300 border-red-500/30'
                  }`}
                >
                  <ArrowUpRight className={`w-3.5 h-3.5 ${isBuy ? 'text-emerald-400' : isWait ? 'text-amber-400' : 'text-red-400 rotate-90'}`} />
                  {sig}
                </span>
              )
            })}
          </div>
        </div>
      )}

      {/* ── Market Outlook / Explanation ── */}
      <div className="glass-sm p-3 mb-3 border-l-2" style={{ borderLeftColor: cfg.color }}>
        <p className="text-xs text-slate-300 leading-relaxed">
          {pred.explanation || (
            pred.lean_direction === 'BEAT' || pred.lean_direction === 'BULLISH'
              ? `Leading indicators point to economic strength. Look for USD upside (Buy USDJPY, Sell EURUSD & Gold).`
              : `Leading indicators point to economic softening. Look for USD downside (Sell USDJPY, Buy EURUSD & Gold).`
          )}
        </p>
      </div>

      {/* ── Leading Indicator Breakdown (Visible by Default) ── */}
      <div className="mt-3">
        <div
          onClick={() => setExpanded(e => !e)}
          className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-white/5 cursor-pointer text-slate-400 transition-colors"
        >
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-300">Leading Indicators</span>
            <span className="text-[11px] px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 font-mono">
              {indicators.length} signals
            </span>
          </div>
          <span className="text-[11px] text-slate-500">
            {expanded ? '▲ Collapse' : '▼ Expand'}
          </span>
        </div>

        <AnimatePresence>
          {expanded && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-2 overflow-hidden"
            >
              <div className="glass-sm p-3.5 border border-white/10 space-y-1">
                {indicators.length === 0 ? (
                  <p className="text-xs text-slate-500 text-center py-2">
                    No indicator snapshot recorded yet. Tap refresh ↺ to query FRED.
                  </p>
                ) : (
                  indicators.map((ind, i) => (
                    <IndicatorRow key={i} ind={ind} />
                  ))
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  )
}

// ── Event Filter Dropdown ────────────────────────────────────────────────────
function EventFilterDropdown({
  events, selected, onSelect, totalCount
}: {
  events: string[]
  selected: string | null
  onSelect: (code: string | null) => void
  totalCount: number
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const EVENT_LABELS: Record<string, string> = {
    NFP: 'Non-Farm Payrolls',
    CPI: 'Consumer Price Index',
    CORE_CPI: 'Core CPI (ex Food & Energy)',
    PPI: 'Producer Price Index',
    UNEMPLOYMENT_RATE: 'Unemployment Rate',
    JOBLESS_CLAIMS: 'Initial Jobless Claims',
    CONSUMER_CONFIDENCE: 'Consumer Confidence',
    FOMC: 'FOMC Rate Decision',
    RETAIL_SALES: 'Retail Sales',
    ISM_MFG: 'ISM Manufacturing PMI',
    GDP: 'GDP Growth Rate',
  }

  const selectedLabel = selected ? (EVENT_LABELS[selected] || selected) : `All Events (${totalCount})`

  return (
    <div ref={ref} className="relative mb-5">
      {/* Trigger button */}
      <button
        onClick={() => setOpen(o => !o)}
        className={`w-full flex items-center justify-between gap-3 px-4 py-3 rounded-xl border transition-all ${
          open || selected
            ? 'bg-indigo-600/20 border-indigo-500/50 text-white'
            : 'glass border-white/10 text-slate-300 hover:border-white/20 hover:text-white'
        }`}
        style={open ? { boxShadow: '0 0 0 2px rgba(99,102,241,0.35)' } : {}}
      >
        <div className="flex items-center gap-2.5">
          <div className={`w-2 h-2 rounded-full flex-shrink-0 ${
            selected ? 'bg-green-400 shadow-sm shadow-green-400' : 'bg-slate-500'
          }`} />
          <span className="text-sm font-bold font-mono">{selectedLabel}</span>
          {selected && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 font-semibold">
              FOCUSED
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {selected && (
            <button
              onClick={(e) => { e.stopPropagation(); onSelect(null) }}
              className="text-[10px] text-slate-400 hover:text-red-400 px-2 py-0.5 rounded bg-white/5 hover:bg-red-500/10 border border-white/10 transition-all font-semibold"
            >
              ✕ Clear
            </button>
          )}
          <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform duration-200 ${open ? 'rotate-180' : ''}`} />
        </div>
      </button>

      {/* Dropdown panel */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -8, scaleY: 0.92 }}
            animate={{ opacity: 1, y: 0, scaleY: 1 }}
            exit={{ opacity: 0, y: -8, scaleY: 0.92 }}
            transition={{ duration: 0.15, ease: 'easeOut' }}
            style={{ transformOrigin: 'top' }}
            className="absolute z-50 w-full mt-2 glass border border-white/10 rounded-xl overflow-hidden shadow-2xl shadow-black/60"
          >
            {/* All Events option */}
            <button
              onClick={() => { onSelect(null); setOpen(false) }}
              className={`w-full flex items-center justify-between px-4 py-3 text-sm font-semibold transition-all border-b border-white/5 ${
                selected === null
                  ? 'bg-indigo-600/25 text-white'
                  : 'text-slate-400 hover:bg-white/5 hover:text-white'
              }`}
            >
              <div className="flex items-center gap-2.5">
                <span className="text-base">📊</span>
                <span>All Events</span>
              </div>
              <span className="text-xs font-mono text-slate-500">{totalCount} loaded</span>
            </button>

            {/* Individual events */}
            <div className="grid grid-cols-1 sm:grid-cols-2">
              {events.map((code) => {
                const isSelected = selected === code
                const icons: Record<string, string> = {
                  NFP: '💼', CPI: '🏷️', CORE_CPI: '🔥', PPI: '🏭',
                  UNEMPLOYMENT_RATE: '📉', JOBLESS_CLAIMS: '📋',
                  CONSUMER_CONFIDENCE: '😊', FOMC: '🏛️',
                  RETAIL_SALES: '🛒', ISM_MFG: '⚙️', GDP: '📈'
                }
                return (
                  <button
                    key={code}
                    onClick={() => { onSelect(code); setOpen(false) }}
                    className={`flex items-center gap-3 px-4 py-3 text-left transition-all border-b border-white/[0.04] last:border-0 ${
                      isSelected
                        ? 'bg-indigo-600/20 text-white'
                        : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'
                    }`}
                  >
                    <span className="text-base flex-shrink-0">{icons[code] || '📌'}</span>
                    <div className="min-w-0">
                      <p className="text-xs font-black font-mono" style={{ color: isSelected ? '#818cf8' : '' }}>{code}</p>
                      <p className="text-[10px] text-slate-500 truncate">{EVENT_LABELS[code] || code}</p>
                    </div>
                    {isSelected && <CheckCircle className="w-3.5 h-3.5 text-indigo-400 ml-auto flex-shrink-0" />}
                  </button>
                )
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ── Next Major Red-Folder News Radar Banner ──────────────────────────────────
function NextEventRadar({
  events,
  onAnalyze,
  now
}: {
  events: CalendarEvent[]
  onAnalyze: (code: string) => void
  now: number
}) {
  if (!events || events.length === 0) return null

  // Sort chronologically
  const sorted = [...events].sort((a, b) => {
    const tA = new Date(a.release_time_utc).getTime() || 0
    const tB = new Date(b.release_time_utc).getTime() || 0
    return tA - tB
  })

  // Find nearest upcoming event that hasn't passed, or fall back to the first
  const upcoming = sorted.find(e => {
    const t = new Date(e.release_time_utc).getTime()
    return t && t > now
  }) || sorted[0]

  if (!upcoming) return null

  const timing = getEventTiming(upcoming.release_time_utc, now)
  const pairs = EVENT_AFFECTED_PAIRS[upcoming.event_code] || ['EUR/USD', 'USD/JPY', 'XAU/USD', 'US500']

  return (
    <div className="mb-6 relative overflow-hidden rounded-2xl border border-indigo-500/30 bg-gradient-to-r from-slate-900/90 via-indigo-950/40 to-slate-900/90 p-4 sm:p-5 shadow-xl shadow-indigo-950/50 backdrop-blur-md">
      {/* Decorative ambient glow */}
      <div className="absolute -top-12 -right-12 w-48 h-48 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute -bottom-12 -left-12 w-48 h-48 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />

      <div className="relative flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        {/* Left: Indicator Info */}
        <div className="space-y-1.5 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-black uppercase tracking-wider bg-red-500/20 text-red-400 border border-red-500/30">
              <span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-ping" />
              {upcoming.impact} IMPACT
            </span>
            <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
              {upcoming.event_code}
            </span>
            <span className="text-[11px] text-slate-400 font-mono">
              NEXT HIGH-IMPACT RELEASE
            </span>
          </div>

          <h3 className="text-lg sm:text-xl font-black text-white tracking-tight truncate">
            {upcoming.event_name}
          </h3>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-300">
            <span className="flex items-center gap-1.5 font-medium text-slate-200">
              <Calendar className="w-3.5 h-3.5 text-indigo-400" />
              {timing.dateFormatted}
            </span>
            <span className="flex items-center gap-1.5 font-mono text-cyan-300">
              <Clock className="w-3.5 h-3.5 text-cyan-400" />
              {timing.timeNy} (NY) • {timing.timeLocal} (Local)
            </span>
          </div>

          {/* Affected pairs */}
          <div className="flex items-center gap-1.5 pt-1 flex-wrap">
            <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Affected Pairs:</span>
            {pairs.map((p, idx) => (
              <span key={idx} className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-white/5 text-slate-200 border border-white/10">
                {p}
              </span>
            ))}
          </div>
        </div>

        {/* Right: Big Countdown Clock & Direct Analyze Action */}
        <div className="flex flex-row sm:flex-col lg:flex-row items-center gap-3 sm:gap-4 flex-shrink-0 pt-2 lg:pt-0 border-t lg:border-t-0 border-white/10">
          <div className="text-left sm:text-right">
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Live Release Countdown</p>
            <p className="text-xl sm:text-2xl font-black font-mono tracking-tight text-white flex items-center gap-2">
              <span className={timing.isPassed ? 'text-slate-400' : timing.urgency === 'imminent' ? 'text-red-400 animate-pulse' : timing.urgency === 'soon' ? 'text-amber-400' : 'text-emerald-400'}>
                {timing.countdownText}
              </span>
            </p>
          </div>

          <button
            onClick={() => onAnalyze(upcoming.event_code)}
            className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white font-bold px-4 py-2.5 rounded-xl text-xs transition-all shadow-lg shadow-indigo-600/30 active:scale-95 whitespace-nowrap ml-auto sm:ml-0"
          >
            <Zap className="w-3.5 h-3.5 text-amber-300" />
            Analyze News
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Red-Folder Calendar Event Card ────────────────────────────────────────────
function CalendarEventCard({
  ev,
  onAnalyze,
  now
}: {
  ev: CalendarEvent
  onAnalyze: (code: string) => void
  now: number
}) {
  const timing = getEventTiming(ev.release_time_utc, now)
  const pairs = EVENT_AFFECTED_PAIRS[ev.event_code] || ['EUR/USD', 'USD/JPY', 'XAU/USD', 'US500']

  return (
    <div className="glass p-5 border border-white/10 hover:border-indigo-500/30 transition-all rounded-2xl relative overflow-hidden bg-slate-900/60">
      {/* Top row: Badges & Live Countdown */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-black uppercase px-2.5 py-0.5 rounded-full border ${
            ev.impact.toUpperCase() === 'HIGH'
              ? 'bg-red-500/20 text-red-400 border-red-500/30'
              : 'bg-amber-500/20 text-amber-400 border-amber-500/30'
          }`}>
            {ev.impact} IMPACT
          </span>
          <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            {ev.currency || 'USD'}
          </span>
          <span className="text-[11px] font-mono font-bold text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/20">
            {ev.event_code}
          </span>
        </div>

        {/* Live Countdown Badge */}
        <CountdownBadge releaseTimeUtc={ev.release_time_utc} now={now} />
      </div>

      {/* Event Title */}
      <h4 className="text-lg font-bold text-white mb-2 tracking-tight">
        {ev.event_name}
      </h4>

      {/* Date & Exact Time Display */}
      <div className="glass-sm p-3 rounded-xl border border-white/5 mb-3 grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
        <div className="flex items-center gap-2 text-slate-300">
          <Calendar className="w-4 h-4 text-indigo-400 flex-shrink-0" />
          <div>
            <p className="text-[10px] text-slate-500 uppercase font-semibold">Exact Date</p>
            <p className="font-semibold text-slate-200">{timing.dateFormatted}</p>
          </div>
        </div>

        <div className="flex items-center gap-2 text-slate-300">
          <Clock className="w-4 h-4 text-cyan-400 flex-shrink-0" />
          <div>
            <p className="text-[10px] text-slate-500 uppercase font-semibold">Exact Release Time</p>
            <p className="font-mono font-bold text-cyan-300">
              {timing.timeNy} <span className="text-slate-400 font-normal">NY</span> • {timing.timeLocal} <span className="text-slate-400 font-normal">Local</span>
            </p>
          </div>
        </div>
      </div>

      {/* Pairs to be Affected */}
      <div className="mb-4">
        <p className="text-[10px] uppercase font-bold text-slate-400 tracking-wider mb-1.5">
          Pairs to be Affected:
        </p>
        <div className="flex flex-wrap gap-1.5">
          {pairs.map((pair, idx) => (
            <span
              key={idx}
              className="text-xs font-mono font-bold px-2.5 py-1 rounded-lg bg-indigo-950/50 text-indigo-300 border border-indigo-500/25"
            >
              {pair}
            </span>
          ))}
        </div>
      </div>

      {/* Forecast & Previous Metrics + Action button */}
      <div className="flex flex-wrap items-center justify-between gap-4 pt-3 border-t border-white/5">
        <div className="flex items-center gap-5">
          <div>
            <p className="text-[10px] text-slate-500 uppercase font-semibold">Forecast</p>
            <p className="text-sm font-mono font-bold text-slate-200">{ev.forecast ?? '—'}</p>
          </div>
          <div>
            <p className="text-[10px] text-slate-500 uppercase font-semibold">Previous</p>
            <p className="text-sm font-mono font-bold text-slate-400">{ev.previous ?? '—'}</p>
          </div>
          {ev.actual != null && (
            <div>
              <p className="text-[10px] text-emerald-400 uppercase font-bold">Actual</p>
              <p className="text-sm font-mono font-bold text-emerald-300">{ev.actual}</p>
            </div>
          )}
        </div>

        <button
          onClick={() => onAnalyze(ev.event_code)}
          className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-xl text-xs font-bold transition-all shadow-md shadow-indigo-600/20 flex items-center gap-2 active:scale-95"
        >
          <Zap className="w-3.5 h-3.5 text-amber-300" />
          Analyze {ev.event_code} News & Signals
        </button>
      </div>
    </div>
  )
}

// ── Main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [activeTab, setActiveTab] = useState<'predictions' | 'calendar' | 'accuracy' | 'telegram'>('predictions')
  const [predictions, setPredictions] = useState<Prediction[]>([])
  const [calendarEvents, setCalendarEvents] = useState<CalendarEvent[]>([])
  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([])
  const [accuracy, setAccuracy] = useState<AccuracyStats | null>(null)
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [runningAll, setRunningAll] = useState(false)
  const [broadcastingTg, setBroadcastingTg] = useState(false)
  const [broadcastSent, setBroadcastSent] = useState(false)
  const [selectedEventCode, setSelectedEventCode] = useState<string | null>(null)
  const [analyzingCode, setAnalyzingCode] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [now, setNow] = useState<number>(Date.now())

  // Dynamic 1-second clock ticker for real-time live countdowns
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])

  const handleAnalyzeEvent = async (eventCode: string) => {
    setSelectedEventCode(eventCode)
    setActiveTab('predictions')
    setAnalyzingCode(eventCode)
    await runPrediction(eventCode)
    setAnalyzingCode(null)
  }

  const fetchHealth = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/health`)
      setHealth(r.data)
    } catch {}
  }, [])

  const fetchPredictions = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/predictions?limit=15`)
      setPredictions(r.data.predictions)
      setError(null)
    } catch {
      setError('Cannot reach backend on port 8000. Is the API server running?')
    }
  }, [])

  const fetchCalendar = useCallback(async () => {
    try {
      const r = await axios.get(`${API}/api/events`)
      setCalendarEvents(r.data.events)
    } catch {}
  }, [])

  const fetchHistory = useCallback(async () => {
    try {
      const [histRes, accRes] = await Promise.all([
        axios.get(`${API}/api/history?limit=30`),
        axios.get(`${API}/api/accuracy`),
      ])
      setHistoryItems(histRes.data.history)
      setAccuracy(accRes.data)
    } catch {}
  }, [])

  const runPrediction = async (eventCode: string) => {
    try {
      const r = await axios.get(`${API}/api/prediction/${eventCode}?send_alert=false`)
      setPredictions(prev => {
        const updated = prev.filter(p => p.event_code !== eventCode)
        return [r.data, ...updated]
      })
      await fetchHistory()
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? `Failed to run ${eventCode}`)
    }
  }

  const runAll = async () => {
    setRunningAll(true)
    try {
      await axios.post(`${API}/api/run-all?send_alerts=false`)
      await fetchPredictions()
      await fetchHistory()
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Failed to run all predictions')
    } finally {
      setRunningAll(false)
    }
  }

  const sendSingleToTelegram = async (eventCode: string): Promise<boolean> => {
    try {
      const r = await axios.post(`${API}/api/prediction/${eventCode}/telegram`)
      return r.data.success
    } catch (err: any) {
      alert(`Telegram send error for ${eventCode}: ${err?.response?.data?.detail || err.message}`)
      return false
    }
  }

  const broadcastAllTelegram = async () => {
    setBroadcastingTg(true)
    try {
      const r = await axios.post(`${API}/api/telegram/broadcast-all`)
      const successCount = r.data.broadcast.filter((b: any) => b.success).length
      setBroadcastSent(true)
      setTimeout(() => setBroadcastSent(false), 4000)
      alert(`Dispatched ${successCount} signals directly to your Telegram chat!`)
    } catch (err: any) {
      alert(`Failed to broadcast: ${err?.response?.data?.detail || err.message}`)
    } finally {
      setBroadcastingTg(false)
    }
  }

  const sendTestTelegram = async () => {
    try {
      const r = await axios.post(`${API}/api/telegram/test`)
      if (r.data.success) {
        alert('Telegram connection verified! Check your Telegram chat.')
      } else {
        alert('Telegram test failed. Please check your BOT_TOKEN and CHAT_ID.')
      }
    } catch {
      alert('Error triggering Telegram test.')
    }
  }

  const triggerSchedulerCheck = async () => {
    try {
      await axios.post(`${API}/api/scheduler/check-now`)
      alert('Scheduler alert check executed! Check your Telegram.')
    } catch {
      alert('Failed to trigger scheduler check.')
    }
  }

  useEffect(() => {
    fetchHealth()
    fetchPredictions()
    fetchCalendar()
    fetchHistory()
    const interval = setInterval(() => {
      fetchPredictions()
    }, 60000)
    return () => clearInterval(interval)
  }, [fetchHealth, fetchPredictions, fetchCalendar, fetchHistory])

  return (
    <div className="bg-ambient min-h-screen text-slate-100">
      <div className="max-w-5xl mx-auto px-3 sm:px-6 py-6 sm:py-8">

        {/* ── Top Header ── */}
        <header className="mb-6 flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-white/5 pb-6">
          <div className="flex items-center gap-4">
            {/* TitanFX Sage Logo */}
            <div className="relative flex-shrink-0">
              <img
                src="/logo.png"
                alt="TitanFX Sage Logo"
                className="w-14 h-14 rounded-2xl object-contain"
                style={{ filter: 'drop-shadow(0 0 12px rgba(74,222,128,0.4))' }}
              />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-black tracking-tight text-white">
                  TITAN<span style={{ color: '#4ade80' }}>FX</span>
                  <span className="text-slate-300 ml-1">SAGE</span>
                </h1>
                <span className="text-[10px] font-bold tracking-wider px-2 py-0.5 rounded border" style={{ background: 'rgba(74,222,128,0.1)', color: '#4ade80', borderColor: 'rgba(74,222,128,0.3)' }}>
                  v3.0
                </span>
              </div>
              <p className="text-xs text-slate-400 font-mono mt-0.5">Trade With Logic. Code Your Edge. Master The Market.</p>
            </div>
          </div>

          {/* Status Badges */}
          <div className="flex items-center gap-2 flex-wrap">
            {health && (
              <>
                <span className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border ${health.fred_configured ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-red-500/10 text-red-400 border-red-500/20'}`}>
                  {health.fred_configured ? <CheckCircle className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
                  FRED API
                </span>
                <span className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border ${health.telegram_configured ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-amber-500/10 text-amber-400 border-amber-500/20'}`}>
                  {health.telegram_configured ? <CheckCircle className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
                  Telegram Bot
                </span>
                <span className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-cyan-500/10 text-cyan-300 border border-cyan-500/20">
                  <Clock className="w-3 h-3" />
                  Auto-Alert (2h prior)
                </span>
              </>
            )}
          </div>
        </header>

        {/* ── Error Banner ── */}
        {error && (
          <div className="glass border border-red-500/30 p-4 mb-6 text-sm text-red-400 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}

        {/* ── Next Major Red-Folder News Radar Banner ── */}
        <NextEventRadar
          events={calendarEvents}
          onAnalyze={handleAnalyzeEvent}
          now={now}
        />

        {/* ── Navigation Tabs ── */}
        <div className="flex items-center gap-1 mb-6 border-b border-white/10 pb-2 overflow-x-auto no-scrollbar">
          <button
            onClick={() => setActiveTab('predictions')}
            className={`flex items-center gap-1.5 px-3 sm:px-4 py-2.5 rounded-xl text-xs sm:text-sm font-semibold transition-all whitespace-nowrap flex-shrink-0 ${
              activeTab === 'predictions'
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
                : 'text-slate-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <Zap className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
            <span>Signals</span>
            <span className="hidden sm:inline">({predictions.length})</span>
          </button>

          <button
            onClick={() => { setActiveTab('calendar'); fetchCalendar() }}
            className={`flex items-center gap-1.5 px-3 sm:px-4 py-2.5 rounded-xl text-xs sm:text-sm font-semibold transition-all whitespace-nowrap flex-shrink-0 ${
              activeTab === 'calendar'
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
                : 'text-slate-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <Calendar className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
            <span className="hidden xs:inline">Calendar</span>
            <span className="hidden sm:inline">({calendarEvents.length})</span>
          </button>

          <button
            onClick={() => { setActiveTab('accuracy'); fetchHistory() }}
            className={`flex items-center gap-1.5 px-3 sm:px-4 py-2.5 rounded-xl text-xs sm:text-sm font-semibold transition-all whitespace-nowrap flex-shrink-0 ${
              activeTab === 'accuracy'
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
                : 'text-slate-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <Award className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
            <span>Accuracy</span>
            <span className="hidden sm:inline"> ({accuracy?.overall_hit_rate ?? 0}%)</span>
          </button>

          <button
            onClick={() => setActiveTab('telegram')}
            className={`flex items-center gap-1.5 px-3 sm:px-4 py-2.5 rounded-xl text-xs sm:text-sm font-semibold transition-all whitespace-nowrap flex-shrink-0 ${
              activeTab === 'telegram'
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
                : 'text-slate-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <Bell className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
            <span className="hidden xs:inline">Telegram</span>
          </button>
        </div>

        {/* ── TAB 1: PREDICTIONS ── */}
        {activeTab === 'predictions' && (
          <div>
            {/* Action Buttons - fully responsive */}
            <div className="flex flex-col sm:flex-row gap-3 mb-6">
              <button
                onClick={runAll}
                disabled={runningAll}
                className="flex-1 flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-bold py-3 px-4 rounded-xl transition-all active:scale-95 shadow-lg shadow-indigo-600/20"
              >
                <Zap className={`w-4 h-4 ${runningAll ? 'animate-pulse' : ''}`} />
                {runningAll ? 'Recalculating…' : 'Run All Predictions'}
              </button>

              <div className="flex gap-2">
                <button
                  onClick={broadcastAllTelegram}
                  disabled={broadcastingTg}
                  className="flex-1 sm:flex-none flex items-center justify-center gap-2 bg-cyan-600/20 hover:bg-cyan-600/30 border border-cyan-500/40 text-cyan-300 font-bold py-3 px-4 rounded-xl transition-all active:scale-95"
                >
                  {broadcastingTg ? (
                    <RefreshCw className="w-4 h-4 animate-spin" />
                  ) : broadcastSent ? (
                    <CheckCircle className="w-4 h-4 text-emerald-400" />
                  ) : (
                    <Bell className="w-4 h-4" />
                  )}
                  <span className="hidden sm:inline">{broadcastSent ? 'Sent!' : 'Send All to Telegram'}</span>
                  <span className="sm:hidden">{broadcastSent ? 'Sent!' : 'Telegram'}</span>
                </button>

                <button
                  onClick={fetchPredictions}
                  title="Refresh predictions"
                  className="p-3 glass-sm hover:bg-white/10 rounded-xl transition-all active:scale-95 border border-white/10 flex-shrink-0"
                >
                  <RefreshCw className="w-4 h-4 text-slate-400" />
                </button>
              </div>
            </div>

            {/* ── Event Filter Dropdown ── */}
            <EventFilterDropdown
              events={health?.supported_events ?? []}
              selected={selectedEventCode}
              onSelect={setSelectedEventCode}
              totalCount={predictions.length}
            />

            {/* ── Focused Single-Event Banner ── */}
            {selectedEventCode && (
              <div className="mb-5 flex flex-wrap items-center justify-between gap-3 glass p-4 border border-indigo-500/30 bg-indigo-950/20">
                <div className="flex items-center gap-2.5">
                  <span className="text-xs text-indigo-400 font-bold uppercase tracking-wider">
                    Focused News Analysis:
                  </span>
                  <span className="text-sm font-black text-white font-mono bg-indigo-500/20 px-2.5 py-1 rounded border border-indigo-500/30">
                    {selectedEventCode}
                  </span>
                  {analyzingCode === selectedEventCode && (
                    <span className="text-xs text-indigo-300 flex items-center gap-1.5 animate-pulse ml-2 font-medium">
                      <RefreshCw className="w-3.5 h-3.5 animate-spin text-indigo-400" />
                      Analyzing leading indicators for {selectedEventCode}...
                    </span>
                  )}
                </div>
                <button
                  onClick={() => setSelectedEventCode(null)}
                  className="text-xs font-semibold text-slate-300 hover:text-white flex items-center gap-1.5 glass-sm px-3 py-1.5 rounded-lg border border-white/10 hover:bg-white/10 transition-all active:scale-95"
                >
                  ← Show All Events
                </button>
              </div>
            )}

            {predictions.length === 0 && !runningAll && (
              <div className="glass p-12 text-center">
                <Zap className="w-12 h-12 text-indigo-400 mx-auto mb-4 opacity-50" />
                <p className="text-slate-300 font-bold mb-1 text-lg">No predictions calculated yet</p>
                <p className="text-slate-500 text-sm max-w-md mx-auto mb-6">
                  Click below to pull leading indicators from FRED for NFP, CPI, PPI, Jobless Claims, and Unemployment Rate.
                </p>
                <button
                  onClick={runAll}
                  className="bg-indigo-600 hover:bg-indigo-500 text-white px-6 py-2.5 rounded-xl font-bold transition-all text-sm"
                >
                  Run Predictions Now
                </button>
              </div>
            )}

            {/* If a single event is selected but hasn't finished loading yet */}
            {selectedEventCode && predictions.filter(p => p.event_code === selectedEventCode).length === 0 && analyzingCode === selectedEventCode && (
              <div className="glass p-10 text-center border border-indigo-500/30">
                <RefreshCw className="w-8 h-8 text-indigo-400 animate-spin mx-auto mb-3" />
                <p className="text-white font-bold text-base mb-1">
                  Analyzing {selectedEventCode} Leading Indicators...
                </p>
                <p className="text-slate-400 text-xs">
                  Querying FRED series and computing composite z-score model...
                </p>
              </div>
            )}

            <div className={`grid gap-4 ${selectedEventCode ? 'grid-cols-1 max-w-2xl mx-auto' : 'grid-cols-1 lg:grid-cols-2'}`}>
              <AnimatePresence>
                {(selectedEventCode
                  ? predictions.filter(p => p.event_code === selectedEventCode)
                  : predictions
                ).map(pred => (
                  <PredictionCard
                    key={pred.id}
                    pred={pred}
                    calendarEvent={calendarEvents.find(c => c.event_code === pred.event_code)}
                    now={now}
                    onRefresh={runPrediction}
                    onSendTelegram={sendSingleToTelegram}
                  />
                ))}
              </AnimatePresence>
            </div>
          </div>
        )}

        {/* ── TAB 2: RED-FOLDER CALENDAR ── */}
        {activeTab === 'calendar' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between mb-2">
              <div>
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" />
                  This Week's High-Impact Releases
                </h3>
                <p className="text-xs text-slate-400">Forex Factory Live Feed with exact release times, live countdowns, and affected asset pairs</p>
              </div>
              <button
                onClick={fetchCalendar}
                className="p-2 rounded-xl glass-sm hover:bg-white/10 text-slate-400 hover:text-white transition-all flex items-center gap-1.5 text-xs font-semibold"
                title="Refresh calendar"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Refresh</span>
              </button>
            </div>

            {calendarEvents.length === 0 ? (
              <div className="glass p-8 text-center text-slate-400">
                No high-impact USD events found for this week in the feed.
              </div>
            ) : (
              calendarEvents.map((ev, idx) => (
                <CalendarEventCard
                  key={idx}
                  ev={ev}
                  onAnalyze={handleAnalyzeEvent}
                  now={now}
                />
              ))
            )}
          </div>
        )}

        {/* ── TAB 3: ACCURACY & HISTORY ── */}
        {activeTab === 'accuracy' && (
          <div className="space-y-6">
            {/* Top Stat Summary Cards */}
            {accuracy && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="glass p-4 border border-indigo-500/20">
                  <p className="text-xs text-slate-400 uppercase font-semibold">Overall Hit Rate</p>
                  <p className="text-2xl font-black text-indigo-400 font-mono mt-1">{accuracy.overall_hit_rate}%</p>
                  <p className="text-[10px] text-slate-500 mt-1">Across all graded releases</p>
                </div>
                <div className="glass p-4 border border-emerald-500/20">
                  <p className="text-xs text-slate-400 uppercase font-semibold">Correct Predictions</p>
                  <p className="text-2xl font-black text-emerald-400 font-mono mt-1">{accuracy.wins}</p>
                  <p className="text-[10px] text-slate-500 mt-1">Confirmed by actual prints</p>
                </div>
                <div className="glass p-4 border border-red-500/20">
                  <p className="text-xs text-slate-400 uppercase font-semibold">Missed Predictions</p>
                  <p className="text-2xl font-black text-red-400 font-mono mt-1">{accuracy.losses}</p>
                  <p className="text-[10px] text-slate-500 mt-1">Market surprised model</p>
                </div>
                <div className="glass p-4 border border-cyan-500/20">
                  <p className="text-xs text-slate-400 uppercase font-semibold">Total Sample</p>
                  <p className="text-2xl font-black text-cyan-400 font-mono mt-1">{accuracy.total_predictions}</p>
                  <p className="text-[10px] text-slate-500 mt-1">Tracked releases</p>
                </div>
              </div>
            )}

            {/* Per-event breakdown table */}
            {accuracy && accuracy.event_stats.length > 0 && (
              <div className="glass p-5 border border-white/5">
                <h4 className="text-sm font-bold text-white uppercase tracking-wider mb-3">Accuracy by News Event</h4>
                <div className="space-y-2">
                  {accuracy.event_stats.map((st, i) => (
                    <div key={i} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
                      <div>
                        <p className="text-sm font-bold text-slate-200">{st.display_name}</p>
                        <p className="text-[10px] text-slate-500 font-mono">{st.event_code}</p>
                      </div>
                      <div className="flex items-center gap-4">
                        <span className="text-xs text-slate-400 font-mono">
                          {st.wins} / {st.total} correct
                        </span>
                        <span className="text-sm font-black font-mono px-2.5 py-0.5 rounded bg-white/5 text-emerald-400">
                          {st.hit_rate_pct}%
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Side-by-side past outcomes list */}
            <div className="glass p-5 border border-white/5">
              <h4 className="text-sm font-bold text-white uppercase tracking-wider mb-1">Past Predictions vs Actuals — Honest Ledger</h4>
              <p className="text-[11px] text-slate-500 mb-4">Zero falsification. Every incorrect prediction is recorded as a loss. No missed call is labelled correct.</p>
              <div className="space-y-3">
                {historyItems.map((item) => {
                  const surpriseColor = getSurpriseColor(item.event_code, item.surprise)
                  const surpriseLabel = getSurpriseLabel(item.event_code, item.surprise)
                  const isInverse = INVERSE_EVENTS.has(item.event_code)

                  // Build the human-readable honest verdict
                  let verdictText = ''
                  if (item.was_correct === true) {
                    verdictText = `Model predicted ${item.lean_direction} and the actual print (${item.actual}) ${isInverse ? 'was lower than' : 'exceeded'} forecast (${item.forecast}). Correct call.`
                  } else if (item.was_correct === false) {
                    const direction = item.surprise != null
                      ? (isInverse
                          ? (item.surprise < 0 ? 'LOWER (USD bullish surprise)' : 'HIGHER (USD bearish surprise)')
                          : (item.surprise > 0 ? 'HIGHER (USD bullish surprise)' : 'LOWER (USD bearish surprise)'))
                      : 'different from forecast'
                    verdictText = `Model predicted ${item.lean_direction} but actual (${item.actual}) came in ${direction} than forecast (${item.forecast}). Prediction was WRONG — recorded as a loss.`
                  } else {
                    verdictText = 'Awaiting actual release data to grade this prediction.'
                  }

                  return (
                    <div key={item.id} className={`glass-sm p-4 border flex flex-col gap-3 ${
                      item.was_correct === true ? 'border-emerald-500/20 bg-emerald-950/10' :
                      item.was_correct === false ? 'border-red-500/20 bg-red-950/10' :
                      'border-white/5'
                    }`}>
                      {/* Row 1: info + numbers + verdict badge */}
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                        <div>
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 font-mono">
                              {item.event_code}
                            </span>
                            {isInverse && (
                              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 uppercase">
                                ⚠ Inverse Event
                              </span>
                            )}
                            <span className="text-xs text-slate-500">
                              {new Date(item.date).toLocaleDateString()}
                            </span>
                          </div>
                          <h5 className="text-sm font-bold text-white">{item.display_name}</h5>
                          <div className="flex items-center gap-2 mt-1">
                            <span className="text-xs text-slate-400">Pre-Release Lean:</span>
                            <span className={`text-xs font-bold ${
                              item.lean_direction === 'BEAT' || item.lean_direction === 'BULLISH' ? 'text-emerald-400' :
                              item.lean_direction === 'MISS' || item.lean_direction === 'BEARISH' ? 'text-red-400' : 'text-amber-400'
                            }`}>
                              {item.lean_direction} ({item.confidence_pct.toFixed(0)}% confidence)
                            </span>
                          </div>
                        </div>

                        <div className="flex items-center gap-4 flex-wrap">
                          <div className="text-right">
                            <p className="text-[10px] text-slate-500 uppercase">Forecast</p>
                            <p className="text-xs font-mono font-bold text-slate-300">{item.forecast ?? '—'}</p>
                          </div>
                          <div className="text-right">
                            <p className="text-[10px] text-slate-500 uppercase">Actual</p>
                            <p className="text-xs font-mono font-bold text-white">{item.actual ?? '—'}</p>
                          </div>
                          <div className="text-right">
                            <p className="text-[10px] text-slate-500 uppercase">Surprise</p>
                            <p className="text-xs font-mono font-bold" style={{ color: surpriseColor }}>
                              {surpriseLabel}
                            </p>
                          </div>
                          <div>
                            {item.was_correct === true && (
                              <span className="flex items-center gap-1 text-xs font-black px-3 py-1.5 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                                <CheckCircle className="w-3.5 h-3.5" /> CORRECT
                              </span>
                            )}
                            {item.was_correct === false && (
                              <span className="flex items-center gap-1 text-xs font-black px-3 py-1.5 rounded-lg bg-red-500/20 text-red-400 border border-red-500/30">
                                <AlertCircle className="w-3.5 h-3.5" /> WRONG
                              </span>
                            )}
                            {item.was_correct === null && (
                              <span className="flex items-center gap-1 text-xs font-semibold px-3 py-1.5 rounded-lg bg-slate-500/10 text-slate-400 border border-slate-500/20">
                                <Clock className="w-3.5 h-3.5" /> PENDING
                              </span>
                            )}
                          </div>
                        </div>
                      </div>

                      {/* Row 2: Honest verdict explanation */}
                      <div className={`text-[11px] leading-relaxed px-3 py-2 rounded-lg border-l-2 ${
                        item.was_correct === true
                          ? 'border-emerald-500 bg-emerald-950/20 text-emerald-300'
                          : item.was_correct === false
                          ? 'border-red-500 bg-red-950/20 text-red-300'
                          : 'border-slate-600 bg-slate-900/30 text-slate-400'
                      }`}>
                        {verdictText}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )}

        {/* ── TAB 4: TELEGRAM & SCHEDULER ── */}
        {activeTab === 'telegram' && (
          <div className="space-y-6">
            <div className="glass p-6 border border-white/5">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-xl bg-cyan-500/20 border border-cyan-500/40 flex items-center justify-center">
                  <Bell className="w-5 h-5 text-cyan-400" />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-white">Telegram Autonomous Alert Bot</h3>
                  <p className="text-xs text-slate-400">Automated pre-release signals & post-release grading directly to your chat</p>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
                <div className="glass-sm p-4 border border-white/5">
                  <p className="text-xs text-slate-400 font-semibold mb-1">Bot Status</p>
                  <p className="text-sm font-bold text-emerald-400 flex items-center gap-1.5">
                    <CheckCircle className="w-4 h-4" /> Active & Connected
                  </p>
                  <p className="text-[11px] text-slate-500 mt-2">Configured in `.env` with token and chat ID.</p>
                </div>
                <div className="glass-sm p-4 border border-white/5">
                  <p className="text-xs text-slate-400 font-semibold mb-1">Scheduler Frequency</p>
                  <p className="text-sm font-bold text-indigo-400 flex items-center gap-1.5">
                    <Clock className="w-4 h-4" /> Every 5 Minutes
                  </p>
                  <p className="text-[11px] text-slate-500 mt-2">Checks Forex Factory calendar and triggers 2 hours prior to release.</p>
                </div>
              </div>

              <div className="space-y-4">
                <div className="flex flex-wrap gap-3">
                  <button
                    onClick={broadcastAllTelegram}
                    disabled={broadcastingTg}
                    className="flex items-center gap-2 bg-cyan-600 hover:bg-cyan-500 text-white font-bold py-2.5 px-4 rounded-xl text-sm transition-all shadow-lg shadow-cyan-600/20 active:scale-95"
                  >
                    <Bell className="w-4 h-4" />
                    {broadcastingTg ? 'Broadcasting...' : 'Broadcast All Signals to Telegram'}
                  </button>

                  <button
                    onClick={sendTestTelegram}
                    className="flex items-center gap-2 bg-white/10 hover:bg-white/20 text-white font-bold py-2.5 px-4 rounded-xl text-sm transition-all border border-white/10 active:scale-95"
                  >
                    <CheckCircle className="w-4 h-4 text-emerald-400" />
                    Send Test Ping
                  </button>

                  <button
                    onClick={triggerSchedulerCheck}
                    className="flex items-center gap-2 bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-300 font-bold py-2.5 px-4 rounded-xl text-sm transition-all border border-indigo-500/30 active:scale-95"
                  >
                    <Zap className="w-4 h-4 text-amber-400" />
                    Trigger Auto-Scheduler Check
                  </button>
                </div>

                {/* Instant single-event trigger buttons */}
                <div className="pt-4 border-t border-white/5">
                  <p className="text-xs font-semibold text-slate-400 mb-2 uppercase tracking-wider">
                    Quick-Dispatch Single Signal to Telegram:
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {health?.supported_events.map((code) => (
                      <button
                        key={code}
                        onClick={() => sendSingleToTelegram(code)}
                        className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-cyan-500/20 text-xs font-mono font-semibold text-slate-300 hover:text-cyan-300 border border-white/10 hover:border-cyan-500/40 transition-all flex items-center gap-1.5 active:scale-95"
                      >
                        <Send className="w-3 h-3 text-cyan-400" />
                        {code}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            <div className="glass p-6 border border-white/5">
              <h4 className="text-sm font-bold text-white uppercase tracking-wider mb-2">How the Alert Cycle Works</h4>
              <ul className="space-y-2 text-xs text-slate-400 leading-relaxed list-disc list-inside">
                <li><strong className="text-slate-200">2 Hours Before Release:</strong> The background scheduler detects an upcoming red folder event on Forex Factory, queries FRED for all leading indicators, computes the z-score composite, and sends the pre-release signal (BEAT / MISS / INLINE with confidence % and indicator breakdown) to your Telegram.</li>
                <li><strong className="text-slate-200">After Release Drops:</strong> Once actual numbers are published, the engine computes the surprise, grades the prediction, records the outcome in your history, and sends a Telegram update confirming if the call was a WIN or MISS.</li>
              </ul>
            </div>
          </div>
        )}

        <footer className="text-center text-xs text-slate-600 mt-12 border-t border-white/5 pt-6 space-y-1">
          <div className="flex items-center justify-center gap-2">
            <img src="/logo.png" alt="TitanFX Sage" className="w-5 h-5 rounded object-contain opacity-60" />
            <span className="font-bold text-slate-500">TitanFX Sage — Macro Predictor</span>
          </div>
          <p>Real-time Leading Indicators via FRED & Forex Factory · Built for serious traders</p>
          <p style={{ color: '#4ade8040' }}>Trade With Logic. Code Your Edge. Master The Market.</p>
        </footer>
      </div>
    </div>
  )
}
