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
  NFP:                ['EUR/USD', 'USD/JPY', 'GBP/USD', 'XAU/USD', 'US500'],
  CPI:                ['EUR/USD', 'USD/JPY', 'XAU/USD', 'GBP/USD', 'US500'],
  CORE_CPI:           ['EUR/USD', 'USD/JPY', 'XAU/USD', 'GBP/USD'],
  PPI:                ['EUR/USD', 'USD/JPY', 'XAU/USD'],
  CORE_PPI:           ['EUR/USD', 'USD/JPY', 'XAU/USD'],
  JOBLESS_CLAIMS:     ['EUR/USD', 'USD/JPY', 'XAU/USD', 'GBP/USD'],
  UNEMPLOYMENT_RATE:  ['EUR/USD', 'USD/JPY', 'GBP/USD', 'XAU/USD'],
  GDP:                ['EUR/USD', 'USD/JPY', 'US500', 'XAU/USD'],
  FOMC:               ['EUR/USD', 'USD/JPY', 'XAU/USD', 'US500', 'US30'],
  RETAIL_SALES:       ['EUR/USD', 'USD/JPY', 'US30', 'XAU/USD'],
  CORE_RETAIL_SALES:  ['EUR/USD', 'USD/JPY', 'XAU/USD'],
  ISM_MFG:            ['USD/JPY', 'EUR/USD', 'US30'],
  ISM_SERVICES:       ['USD/JPY', 'EUR/USD', 'US30', 'XAU/USD'],
  CONSUMER_CONFIDENCE:['EUR/USD', 'USD/JPY', 'US500'],
  CORE_PCE:           ['EUR/USD', 'USD/JPY', 'XAU/USD', 'GBP/USD', 'US500'],
  PCE:                ['EUR/USD', 'USD/JPY', 'XAU/USD'],
  ADP_NFP:            ['EUR/USD', 'USD/JPY', 'GBP/USD', 'XAU/USD'],
  AVG_HOURLY_EARNINGS:['EUR/USD', 'USD/JPY', 'XAU/USD', 'US500'],
  JOLTS:              ['EUR/USD', 'USD/JPY', 'XAU/USD'],
  BUILDING_PERMITS:   ['USD/CAD', 'EUR/USD', 'US500'],
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

type DateScope = 'today' | 'week' | 'all'

function matchesDateScope(releaseTimeUtc: string | undefined, scope: DateScope, now: number): boolean {
  if (scope === 'all') return true
  if (!releaseTimeUtc) return false

  const releaseTime = new Date(releaseTimeUtc)
  if (Number.isNaN(releaseTime.getTime())) return false

  const start = new Date(now)
  start.setHours(0, 0, 0, 0)
  if (scope === 'week') {
    start.setDate(start.getDate() - ((start.getDay() + 6) % 7))
  }

  const end = new Date(start)
  end.setDate(end.getDate() + (scope === 'today' ? 1 : 7))
  return releaseTime >= start && releaseTime < end
}

function CountdownBadge({ releaseTimeUtc, now }: { releaseTimeUtc: string; now: number }) {
  const timing = getEventTiming(releaseTimeUtc, now)

  if (timing.urgency === 'imminent') {
    return (
      <span className="inline-flex max-w-full items-center gap-1.5 whitespace-normal px-3 py-1 rounded-full text-xs font-mono font-black bg-red-500/25 text-red-300 border border-red-500 animate-pulse shadow-lg shadow-red-500/30">
        <span className="w-2 h-2 rounded-full bg-red-400 animate-ping" />
        🚨 IMMINENT: {timing.countdownText}
      </span>
    )
  }

  if (timing.urgency === 'soon') {
    return (
      <span className="inline-flex max-w-full items-center gap-1.5 whitespace-normal px-3 py-1 rounded-full text-xs font-mono font-black bg-amber-500/20 text-amber-300 border border-amber-500/40 animate-pulse shadow-md shadow-amber-500/20">
        <Clock className="w-3.5 h-3.5 text-amber-400" />
        ⚠️ SOON: {timing.countdownText}
      </span>
    )
  }

  if (timing.urgency === 'today') {
    return (
      <span className="inline-flex max-w-full items-center gap-1.5 whitespace-normal px-2.5 py-1 rounded-full text-xs font-mono font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/40">
        <Clock className="w-3.5 h-3.5 text-indigo-400" />
        ⏳ TODAY: {timing.countdownText}
      </span>
    )
  }

  if (timing.urgency === 'passed') {
    return (
      <span className="inline-flex max-w-full items-center gap-1.5 whitespace-normal px-2.5 py-1 rounded-full text-xs font-mono font-medium bg-slate-800 text-slate-400 border border-white/10">
        <CheckCircle className="w-3.5 h-3.5 text-slate-500" />
        {timing.countdownText}
      </span>
    )
  }

  return (
    <span className="inline-flex max-w-full items-center gap-1.5 whitespace-normal px-2.5 py-1 rounded-full text-xs font-mono font-bold bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">
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

function getForecastDirectionLabel(eventCode: string, direction: string): string {
  if (direction === 'INLINE') return 'Near forecast'
  if (direction !== 'BEAT' && direction !== 'MISS' && direction !== 'BULLISH' && direction !== 'BEARISH') {
    return 'Not available'
  }

  const expectsHigher = INVERSE_EVENTS.has(eventCode)
    ? direction === 'MISS' || direction === 'BEARISH'
    : direction === 'BEAT' || direction === 'BULLISH'
  return expectsHigher ? 'Higher reading' : 'Lower reading'
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
  trade_signals?: Record<string, string[]> | string[]
  is_simultaneous?: boolean
  simultaneous_event_codes?: string[]
  simultaneous_event_names?: string[]
  prediction?: {
    lean_direction: string
    confidence_pct: number
    composite_score: number
    event_label: string
    explanation: string
    trade_signals: string[]
    indicators: Indicator[]
  } | null
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
    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between py-2.5 border-b border-white/5 last:border-0 gap-2 sm:gap-3">
      <div className="w-full min-w-0 sm:flex-1">
        <p className="text-xs text-slate-300 font-medium leading-snug break-words">{ind.description}</p>
        <p className="text-[10px] text-slate-500 font-mono">{ind.fred_series}</p>
      </div>
      <div className="flex w-full items-center justify-between gap-2 sm:w-auto sm:flex-shrink-0 sm:justify-start sm:gap-3">
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
      <div className="flex flex-col gap-2 mb-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <div className="min-w-0">
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

        <div className="flex flex-shrink-0 items-center gap-1.5 self-end sm:self-auto">
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
    NFP:                'Non-Farm Payrolls',
    CPI:                'Consumer Price Index',
    CORE_CPI:           'Core CPI (ex Food & Energy)',
    PPI:                'Producer Price Index',
    CORE_PPI:           'Core PPI (ex Food & Energy)',
    UNEMPLOYMENT_RATE:  'Unemployment Rate',
    JOBLESS_CLAIMS:     'Initial Jobless Claims',
    CONSUMER_CONFIDENCE:'Consumer Confidence',
    FOMC:               'FOMC Rate Decision',
    RETAIL_SALES:       'Retail Sales',
    CORE_RETAIL_SALES:  'Core Retail Sales',
    ISM_MFG:            'ISM Manufacturing PMI',
    ISM_SERVICES:       'ISM Services PMI',
    GDP:                'GDP Growth Rate',
    CORE_PCE:           'Core PCE Price Index',
    PCE:                'PCE Price Index',
    ADP_NFP:            'ADP Non-Farm Employment',
    AVG_HOURLY_EARNINGS:'Average Hourly Earnings',
    JOLTS:              'JOLTS Job Openings',
    BUILDING_PERMITS:   'Building Permits',
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
            <span
              role="button"
              tabIndex={0}
              onClick={(e) => { e.stopPropagation(); onSelect(null) }}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); onSelect(null) } }}
              className="text-[10px] text-slate-400 hover:text-red-400 px-2 py-0.5 rounded bg-white/5 hover:bg-red-500/10 border border-white/10 transition-all font-semibold cursor-pointer"
            >
              ✕ Clear
            </span>
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
            className="absolute z-50 w-full mt-2 bg-slate-950 border border-white/10 rounded-xl overflow-hidden shadow-2xl shadow-black/60"
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

// ── Next Major Red-Folder News Radar Banner (Supports Simultaneous Releases) ──
function NextEventRadar({
  events,
  onAnalyze,
  now
}: {
  events: CalendarEvent[]
  onAnalyze: (code: string) => void
  now: number
}) {
  // Only work with events that have a known event_code (mapped events)
  const mapped = (events || []).filter(e => e.event_code)
  if (mapped.length === 0) return null

  // Sort chronologically
  const sorted = [...mapped].sort((a, b) => {
    const tA = new Date(a.release_time_utc).getTime() || 0
    const tB = new Date(b.release_time_utc).getTime() || 0
    return tA - tB
  })

  // Find the nearest truly-upcoming release group (time > now)
  const nextUpcoming = sorted.find(e => {
    const t = new Date(e.release_time_utc).getTime()
    return t && t > now
  })

  // If nothing upcoming, check if something released very recently (within last 2h) to show as 'just released'
  const twoHoursAgo = now - 2 * 3600 * 1000
  const recentlyReleased = !nextUpcoming
    ? sorted.filter(e => {
        const t = new Date(e.release_time_utc).getTime()
        return t && t >= twoHoursAgo && t <= now
      })
    : []

  // Target time: use next upcoming cluster, or most recent released cluster
  let targetTimeStr: string
  let showAsReleased = false

  if (nextUpcoming) {
    targetTimeStr = nextUpcoming.release_time_utc
  } else if (recentlyReleased.length > 0) {
    targetTimeStr = recentlyReleased[recentlyReleased.length - 1].release_time_utc
    showAsReleased = true
  } else {
    // Nothing upcoming and nothing recent — just show the last event
    targetTimeStr = sorted[sorted.length - 1]?.release_time_utc
    if (!targetTimeStr) return null
    showAsReleased = true
  }

  const targetTimeMs = new Date(targetTimeStr).getTime()

  // Find ALL events releasing at the exact same time (or within 5 min window)
  const simultaneousEvents = sorted.filter(e => {
    if (!e.release_time_utc) return false
    const tMs = new Date(e.release_time_utc).getTime()
    return Math.abs(tMs - targetTimeMs) < 300000
  })

  const timing = getEventTiming(targetTimeStr, now)
  const isMulti = simultaneousEvents.length > 1

  // Compute combined market bias across all simultaneous events
  const leans = simultaneousEvents.map(e => e.prediction?.lean_direction || 'INLINE')
  const bullishCount = leans.filter(l => l === 'BULLISH' || l === 'BEAT').length
  const bearishCount = leans.filter(l => l === 'BEARISH' || l === 'MISS').length

  let combinedVerdict = ''
  let combinedColor = '#818cf8'
  if (isMulti) {
    if (bullishCount > 0 && bearishCount === 0) {
      combinedVerdict = `🟢 HIGH CONVICTION DUAL USD BULLISH: All ${simultaneousEvents.length} co-releasing events lean positive for USD. Expect strong upside momentum on USD/JPY & pressure on Gold.`
      combinedColor = '#34d399'
    } else if (bearishCount > 0 && bullishCount === 0) {
      combinedVerdict = `🔴 HIGH CONVICTION DUAL USD BEARISH: All ${simultaneousEvents.length} co-releasing events lean negative for USD. Downside pressure on USD/JPY & upside for EUR/USD & Gold.`
      combinedColor = '#f87171'
    } else if (bullishCount > 0 && bearishCount > 0) {
      combinedVerdict = `⚠️ DIVERGENT SIMULTANEOUS SIGNALS: One event leans Bullish USD while another leans Bearish USD. High two-way whipsaw volatility expected at release!`
      combinedColor = '#fbbf24'
    } else {
      combinedVerdict = `⚡ SIMULTANEOUS MULTI-RELEASE: ${simultaneousEvents.length} high-impact red folder events releasing simultaneously at ${timing.timeNy} NY.`
      combinedColor = '#818cf8'
    }
  }

  return (
    <div className="mb-6 relative overflow-hidden rounded-2xl border border-indigo-500/35 bg-gradient-to-r from-slate-900/95 via-indigo-950/50 to-slate-900/95 p-4 sm:p-6 shadow-2xl shadow-indigo-950/70 backdrop-blur-md">
      {/* Ambient glows */}
      <div className="absolute -top-12 -right-12 w-56 h-56 bg-indigo-500/15 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute -bottom-12 -left-12 w-56 h-56 bg-cyan-500/15 rounded-full blur-3xl pointer-events-none" />

      {/* Top Banner Tag */}
      <div className="flex flex-col items-start gap-2 mb-4 pb-3 border-b border-white/10 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {showAsReleased ? (
            <span className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-black uppercase tracking-wider bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
              <CheckCircle className="w-3.5 h-3.5" />
              {isMulti ? `⚡ ${simultaneousEvents.length}-EVENT SIMULTANEOUS RELEASE` : '📌 RECENTLY RELEASED'}
            </span>
          ) : isMulti ? (
            <span className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-black uppercase tracking-wider bg-red-500/25 text-red-300 border border-red-500/50 animate-pulse shadow-lg shadow-red-500/20">
              <span className="w-2 h-2 rounded-full bg-red-400 animate-ping" />
              ⚡ SIMULTANEOUS {simultaneousEvents.length}-EVENT RED FOLDER DROP
            </span>
          ) : (
            <span className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-black uppercase tracking-wider bg-red-500/20 text-red-400 border border-red-500/30">
              <span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-ping" />
              {simultaneousEvents[0]?.impact ?? 'HIGH'} IMPACT RED FOLDER
            </span>
          )}
          <span className="max-w-full whitespace-normal text-xs font-mono font-bold text-cyan-300 bg-cyan-500/10 px-2.5 py-0.5 rounded border border-cyan-500/20">
            {timing.dateFormatted} • {timing.timeNy} (NY)
          </span>
        </div>

        <CountdownBadge releaseTimeUtc={targetTimeStr} now={now} />
      </div>

      {/* Multi-event Cards Layout */}
      <div className={`grid gap-4 mb-4 ${isMulti ? 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3' : 'grid-cols-1'}`}>
        {simultaneousEvents.map((ev, idx) => {
          const pred = ev.prediction
          const lean = pred?.lean_direction || 'INLINE'
          const cfg = DIRECTION_CONFIG[lean] || DIRECTION_CONFIG.INLINE
          const pairs = EVENT_AFFECTED_PAIRS[ev.event_code] || ['EUR/USD', 'USD/JPY', 'XAU/USD', 'US500']

          return (
            <div
              key={idx}
              className="glass p-4 rounded-xl border border-white/10 hover:border-indigo-500/40 transition-all bg-slate-900/80 flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between gap-2 mb-1.5">
                  <span className="text-[10px] font-black font-mono text-indigo-300 bg-indigo-500/20 px-2 py-0.5 rounded border border-indigo-500/30">
                    {ev.event_code}
                  </span>
                  {pred && (
                    <span
                      className="text-[10px] font-black px-2 py-0.5 rounded-full border uppercase font-mono flex items-center gap-1"
                      style={{ color: cfg.color, background: cfg.bg, borderColor: cfg.color + '40' }}
                    >
                      {pred.event_label || cfg.label} ({pred.confidence_pct.toFixed(0)}%)
                    </span>
                  )}
                </div>

                <h4 className="text-base font-bold text-white mb-2 tracking-tight">
                  {ev.event_name}
                </h4>

                <div className="flex items-center gap-3 text-xs font-mono text-slate-300 mb-2 flex-wrap">
                  <span>Fcst: <strong className="text-slate-100">{ev.forecast ?? '—'}</strong></span>
                  <span>Prev: <strong className="text-slate-400">{ev.previous ?? '—'}</strong></span>
                  {ev.actual != null && (
                    <span>Actual: <strong className="text-emerald-300">{ev.actual}</strong></span>
                  )}
                </div>

                {/* Affected pairs */}
                <div className="flex flex-wrap gap-1 mb-3">
                  {pairs.slice(0, 4).map((p, pIdx) => (
                    <span key={pIdx} className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-white/5 text-slate-300 border border-white/10">
                      {p}
                    </span>
                  ))}
                </div>
              </div>

              {/* Action Button */}
              {ev.event_code && (
                <button
                  onClick={() => onAnalyze(ev.event_code)}
                  className="w-full mt-2 flex items-center justify-center gap-1.5 bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-2 rounded-lg text-xs transition-all active:scale-95 shadow-md shadow-indigo-600/20"
                >
                  <Zap className="w-3.5 h-3.5 text-amber-300" />
                  Analyze {ev.event_code}
                </button>
              )}
            </div>
          )
        })}
      </div>

      {/* Combined Multi-Release Verdict Banner (when > 1 event releasing together) */}
      {isMulti && combinedVerdict && (
        <div className="p-3.5 rounded-xl bg-slate-900/90 border border-indigo-500/30 flex items-start gap-2.5 text-xs text-slate-200">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: combinedColor }} />
          <p className="leading-relaxed font-semibold">{combinedVerdict}</p>
        </div>
      )}
    </div>
  )
}

// ── Red-Folder Calendar Event Card ────────────────────────────────────────────
function CalendarEventCard({
  ev,
  onAnalyze,
  now,
  compact = false,
  onSyncActuals
}: {
  ev: CalendarEvent
  onAnalyze: (code: string) => void
  now: number
  compact?: boolean
  onSyncActuals?: () => void
}) {
  const timing = getEventTiming(ev.release_time_utc, now)
  const pairs = ev.event_code ? (EVENT_AFFECTED_PAIRS[ev.event_code] || ['EUR/USD', 'USD/JPY', 'XAU/USD', 'US500']) : []
  const pred = ev.prediction
  const cfg = pred ? (DIRECTION_CONFIG[pred.lean_direction] || DIRECTION_CONFIG.INLINE) : null
  const isReleased = timing.isPassed
  const isSpeech = !ev.event_code || ev.forecast == null

  // ── COMPACT mode: used inside simultaneous group containers ──────────────────
  if (compact) {
    return (
      <div className={`p-4 ${isReleased ? 'opacity-85' : ''}`}>
        <div className="flex items-center gap-1.5 flex-wrap mb-2">
          <span className={`text-[10px] font-black uppercase px-2 py-0.5 rounded-full border ${
            (ev.impact || '').toUpperCase() === 'HIGH'
              ? 'bg-red-500/20 text-red-400 border-red-500/30'
              : (ev.impact || '').toUpperCase() === 'MEDIUM'
              ? 'bg-amber-500/20 text-amber-400 border-amber-500/30'
              : 'bg-slate-500/20 text-slate-400 border-slate-500/30'
          }`}>
            {ev.impact || 'MED'}
          </span>
          {ev.event_code && (
            <span className="text-[10px] font-mono font-bold text-indigo-300 bg-indigo-500/15 px-2 py-0.5 rounded border border-indigo-500/20">
              {ev.event_code}
            </span>
          )}
          {pred && cfg && (
            <span className="text-[10px] font-black px-2 py-0.5 rounded-full border uppercase font-mono"
              style={{ color: cfg.color, background: cfg.bg, borderColor: cfg.color + '40' }}>
              {pred.lean_direction} {pred.confidence_pct.toFixed(0)}%
            </span>
          )}
        </div>
        <h4 className="text-sm font-bold text-white mb-2">{ev.event_name}</h4>
        <div className="flex items-center gap-3 text-xs font-mono text-slate-300 mb-2 flex-wrap">
          {ev.forecast != null && <span>Fcst: <strong className="text-slate-100">{ev.forecast}</strong></span>}
          {ev.previous != null && <span>Prev: <strong className="text-slate-400">{ev.previous}</strong></span>}
          {ev.actual != null && (
            <span>Actual: <strong className="text-emerald-300 text-sm font-black">{ev.actual}</strong></span>
          )}
        </div>
        {ev.event_code && !isReleased && (
          <button
            onClick={() => onAnalyze(ev.event_code!)}
            className="w-full mt-1 flex items-center justify-center gap-1 bg-indigo-600/80 hover:bg-indigo-500 text-white font-bold py-1.5 rounded-lg text-[11px] transition-all active:scale-95"
          >
            <Zap className="w-3 h-3 text-amber-300" />
            Analyze {ev.event_code}
          </button>
        )}
        {isReleased && onSyncActuals && ev.actual == null && (
          <button
            onClick={onSyncActuals}
            className="w-full mt-1 flex items-center justify-center gap-1 bg-emerald-600/20 hover:bg-emerald-600/40 text-emerald-300 border border-emerald-500/30 font-bold py-1 rounded-lg text-[10px] transition-all active:scale-95"
          >
            {ev.actual != null ? '✏️ Edit Actual' : '🔄 Sync Actuals from Feed'}
          </button>
        )}
      </div>
    )
  }

  // ── FULL card mode ─────────────────────────────────────────────────────────
  return (
    <div className={`glass p-5 border transition-all rounded-2xl relative overflow-hidden ${
      isReleased
        ? 'border-slate-500/20 bg-slate-900/40 hover:border-slate-500/30'
        : 'border-white/10 bg-slate-900/60 hover:border-indigo-500/30'
    }`}>
      {/* Top row: Badges & Live Countdown */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-[10px] font-black uppercase px-2.5 py-0.5 rounded-full border ${
            (ev.impact || '').toUpperCase() === 'HIGH'
              ? 'bg-red-500/20 text-red-400 border-red-500/30'
              : (ev.impact || '').toUpperCase() === 'MEDIUM'
              ? 'bg-amber-500/20 text-amber-400 border-amber-500/30'
              : 'bg-slate-500/20 text-slate-400 border-slate-500/30'
          }`}>
            {ev.impact || 'LOW'} IMPACT
          </span>
          <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            {ev.currency || 'USD'}
          </span>
          {ev.event_code && (
            <span className="text-[11px] font-mono font-bold text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/20">
              {ev.event_code}
            </span>
          )}
          {isSpeech && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-slate-700/50 text-slate-400 border border-slate-600/30">
              📣 SPEECH
            </span>
          )}
          {isReleased && (
            <span className="text-[10px] font-black px-2 py-0.5 rounded-full bg-slate-500/20 text-slate-400 border border-slate-500/30 flex items-center gap-1">
              <CheckCircle className="w-3 h-3" /> RELEASED
            </span>
          )}
        </div>
        <CountdownBadge releaseTimeUtc={ev.release_time_utc} now={now} />
      </div>

      {/* Event Title */}
      <h4 className="text-lg font-bold text-white mb-2 tracking-tight">
        {ev.event_name}
      </h4>

      {/* Date & Time */}
      <div className="glass-sm p-3 rounded-xl border border-white/5 mb-3 grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
        <div className="flex items-center gap-2 text-slate-300">
          <Calendar className="w-4 h-4 text-indigo-400 flex-shrink-0" />
          <div>
            <p className="text-[10px] text-slate-500 uppercase font-semibold">Date</p>
            <p className="font-semibold text-slate-200">{timing.dateFormatted}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-slate-300">
          <Clock className="w-4 h-4 text-cyan-400 flex-shrink-0" />
          <div>
            <p className="text-[10px] text-slate-500 uppercase font-semibold">Release Time</p>
            <p className="font-mono font-bold text-cyan-300">
              {timing.timeNy} <span className="text-slate-400 font-normal">NY</span> • {timing.timeLocal} <span className="text-slate-400 font-normal">Local</span>
            </p>
          </div>
        </div>
      </div>

      {/* Actual released value: prominent green banner or record actual prompt */}
      {ev.actual != null ? (
        <div className="mb-3 p-3 rounded-xl bg-emerald-950/30 border border-emerald-500/30 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3 flex-wrap">
            <div>
              <p className="text-[10px] uppercase font-bold text-emerald-400 tracking-wider">✅ Actual Released</p>
              <p className="text-xl font-black font-mono text-emerald-300">{ev.actual}</p>
            </div>
            {ev.forecast != null && (
              <div className="text-xs font-mono text-slate-400">
                <span>vs Forecast: <span className="text-slate-200 font-bold">{ev.forecast}</span></span>
                {ev.actual !== ev.forecast && (
                  <span className={`ml-2 font-black ${(ev.actual - ev.forecast) > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    ({(ev.actual - ev.forecast) > 0 ? '+' : ''}{(ev.actual - ev.forecast).toFixed(2)} surprise)
                  </span>
                )}
              </div>
            )}
          </div>
          {false && (
            <button
              onClick={onSyncActuals}
              className="text-[10px] font-bold px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white border border-white/10 transition-all active:scale-95"
            >
              🔄 Sync Actuals
            </button>
          )}
        </div>
      ) : isReleased ? (
        <div className="mb-3 p-3 rounded-xl bg-slate-800/40 border border-slate-700/50 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-amber-400" />
            <span className="text-xs text-slate-300 font-medium">Actuals auto-synced every 5 min from live feed</span>
          </div>
          {false && (
            <button
              onClick={onSyncActuals}
              className="text-xs font-bold px-3 py-1.5 rounded-lg bg-emerald-600/30 hover:bg-emerald-600/50 text-emerald-300 border border-emerald-500/30 transition-all flex items-center gap-1 active:scale-95"
            >
              🔄 Sync Actuals from Feed
            </button>
          )}
        </div>
      ) : null}

      {/* Model Prediction Outcome Banner */}
      {pred && cfg && (
        <div
          className="mb-3.5 p-3 rounded-xl border flex flex-col sm:flex-row sm:items-center justify-between gap-2.5"
          style={{ background: cfg.bg, borderColor: cfg.color + '40' }}
        >
          <div>
            <p className="text-[10px] uppercase tracking-wider font-bold text-slate-400 mb-0.5">🤖 Model Predicted Outcome</p>
            <p className="text-sm font-black font-mono tracking-wide" style={{ color: cfg.color }}>
              {pred.event_label || cfg.label} ({pred.confidence_pct.toFixed(0)}% Confidence)
            </p>
          </div>
          {pred.trade_signals && pred.trade_signals.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {pred.trade_signals.slice(0, 3).map((sig: string, sIdx: number) => (
                <span key={sIdx} className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-black/40 text-slate-200 border border-white/10">
                  {sig}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Affected Pairs */}
      {pairs.length > 0 && (
        <div className="mb-4">
          <p className="text-[10px] uppercase font-bold text-slate-400 tracking-wider mb-1.5">Pairs to be Affected:</p>
          <div className="flex flex-wrap gap-1.5">
            {pairs.map((pair, idx) => (
              <span key={idx} className="text-xs font-mono font-bold px-2.5 py-1 rounded-lg bg-indigo-950/50 text-indigo-300 border border-indigo-500/25">
                {pair}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Forecast / Previous / Action */}
      <div className="flex flex-wrap items-center justify-between gap-4 pt-3 border-t border-white/5">
        <div className="flex items-center gap-5">
          {ev.forecast != null && (
            <div>
              <p className="text-[10px] text-slate-500 uppercase font-semibold">Forecast</p>
              <p className="text-sm font-mono font-bold text-slate-200">{ev.forecast}</p>
            </div>
          )}
          {ev.previous != null && (
            <div>
              <p className="text-[10px] text-slate-500 uppercase font-semibold">Previous</p>
              <p className="text-sm font-mono font-bold text-slate-400">{ev.previous}</p>
            </div>
          )}
        </div>

        {ev.event_code && !isSpeech && (
          <button
            onClick={() => onAnalyze(ev.event_code!)}
            className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-xl text-xs font-bold transition-all shadow-md shadow-indigo-600/20 flex items-center gap-2 active:scale-95"
          >
            <Zap className="w-3.5 h-3.5 text-amber-300" />
            {ev.event_code} Breakdown
          </button>
        )}
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
  const [signalDateScope, setSignalDateScope] = useState<DateScope>('today')
  const [signalsHighImpactOnly, setSignalsHighImpactOnly] = useState(true)
  const [calendarDateScope, setCalendarDateScope] = useState<DateScope>('today')
  const [calendarHighImpactOnly, setCalendarHighImpactOnly] = useState(true)

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

  // Fully automatic: polls live FF feed, detects actuals, grades predictions. No user input.
  const [syncingActuals, setSyncingActuals] = useState(false)
  const [lastSyncResult, setLastSyncResult] = useState<{ graded: number; names: string[] } | null>(null)

  const handleSyncActuals = async () => {
    setSyncingActuals(true)
    setLastSyncResult(null)
    try {
      const res = await axios.post(`${API}/api/events/sync-actuals`)
      const graded = res.data.graded ?? []
      setLastSyncResult({ graded: graded.length, names: graded.map((g: any) => g.display_name) })
      await fetchCalendar()
      await fetchHistory()
      await fetchPredictions()
    } catch (err: any) {
      console.error('Sync actuals failed:', err?.response?.data?.detail || err.message)
    } finally {
      setSyncingActuals(false)
    }
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
    // Refresh predictions every 60s, calendar every 5min (live countdown data)
    const predInterval = setInterval(() => {
      fetchPredictions()
    }, 60000)
    const calInterval = setInterval(() => {
      fetchCalendar()
    }, 300000) // 5 minutes
    return () => {
      clearInterval(predInterval)
      clearInterval(calInterval)
    }
  }, [fetchHealth, fetchPredictions, fetchCalendar, fetchHistory])

  const visiblePredictions = predictions
    .filter(prediction => {
      const event = calendarEvents.find(item => item.event_code === prediction.event_code)
      if (selectedEventCode && prediction.event_code !== selectedEventCode) return false
      if (signalsHighImpactOnly && event?.impact.toUpperCase() !== 'HIGH') return false
      return matchesDateScope(event?.release_time_utc, signalDateScope, now)
    })
    .sort((left, right) => {
      const leftEvent = calendarEvents.find(item => item.event_code === left.event_code)
      const rightEvent = calendarEvents.find(item => item.event_code === right.event_code)
      const leftTime = leftEvent?.release_time_utc ? new Date(leftEvent.release_time_utc).getTime() : Number.NaN
      const rightTime = rightEvent?.release_time_utc ? new Date(rightEvent.release_time_utc).getTime() : Number.NaN
      const leftHasTime = Number.isFinite(leftTime)
      const rightHasTime = Number.isFinite(rightTime)
      const leftUpcoming = leftHasTime && leftTime >= now
      const rightUpcoming = rightHasTime && rightTime >= now

      if (leftUpcoming !== rightUpcoming) return leftUpcoming ? -1 : 1
      if (leftHasTime !== rightHasTime) return leftHasTime ? -1 : 1
      if (leftHasTime && rightHasTime) return leftUpcoming ? leftTime - rightTime : rightTime - leftTime
      return new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
    })

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
              <p className="text-xs text-slate-400 mt-0.5">Economic calendar and pre-release forecasts</p>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <span className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border border-emerald-500/20 bg-emerald-500/10 text-emerald-300">
              <TrendingUp className="w-3 h-3" />
              Economic calendar
            </span>
            <span className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border border-cyan-500/20 bg-cyan-500/10 text-cyan-300">
              <Calendar className="w-3 h-3" />
              Pre-release forecasts
            </span>
            <span className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border border-amber-500/20 bg-amber-500/10 text-amber-300">
              <Award className="w-3 h-3" />
              Release history
            </span>
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
        <div className="grid grid-cols-2 gap-2 mb-6 border-b border-white/10 pb-2 sm:flex sm:flex-wrap sm:items-center sm:gap-1">
          <button
            onClick={() => setActiveTab('predictions')}
            className={`flex w-full items-center justify-center gap-1.5 px-2 py-2.5 rounded-xl text-xs sm:w-auto sm:px-4 sm:text-sm font-semibold transition-all whitespace-nowrap ${
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
            className={`flex w-full items-center justify-center gap-1.5 px-2 py-2.5 rounded-xl text-xs sm:w-auto sm:px-4 sm:text-sm font-semibold transition-all whitespace-nowrap ${
              activeTab === 'calendar'
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
                : 'text-slate-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <Calendar className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
            <span>Calendar</span>
            <span className="hidden sm:inline">({calendarEvents.length})</span>
          </button>

          <button
            onClick={() => { setActiveTab('accuracy'); fetchHistory(); fetchPredictions() }}
            className={`flex w-full items-center justify-center gap-1.5 px-2 py-2.5 rounded-xl text-xs sm:w-auto sm:px-4 sm:text-sm font-semibold transition-all whitespace-nowrap ${
              activeTab === 'accuracy'
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
                : 'text-slate-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <Award className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
            <span>Results</span>
          </button>

          <button
            onClick={() => setActiveTab('telegram')}
            className={`flex w-full items-center justify-center gap-1.5 px-2 py-2.5 rounded-xl text-xs sm:w-auto sm:px-4 sm:text-sm font-semibold transition-all whitespace-nowrap ${
              activeTab === 'telegram'
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
                : 'text-slate-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <Bell className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
            <span>Telegram</span>
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

            <div className="glass-sm mb-4 flex flex-col gap-3 p-3 sm:flex-row sm:items-end">
              <label className="flex flex-col gap-1.5 text-xs font-semibold text-slate-400">
                Release window
                <select
                  value={signalDateScope}
                  onChange={event => setSignalDateScope(event.target.value as DateScope)}
                  className="min-h-10 rounded-lg border border-white/10 bg-slate-900 px-3 text-sm text-slate-100"
                >
                  <option value="all">All dates</option>
                  <option value="today">Today</option>
                  <option value="week">This week</option>
                </select>
              </label>
              <label className="flex min-h-10 cursor-pointer items-center gap-2 text-sm font-semibold text-slate-200">
                <input
                  type="checkbox"
                  checked={signalsHighImpactOnly}
                  onChange={event => setSignalsHighImpactOnly(event.target.checked)}
                  className="h-4 w-4 accent-red-500"
                />
                Red-folder only
              </label>
              <p className="text-xs text-slate-500 sm:ml-auto">
                {visiblePredictions.length} of {predictions.length} signals · nearest release first
              </p>
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

            {predictions.length > 0 && visiblePredictions.length === 0 && analyzingCode !== selectedEventCode && (
              <div className="glass mb-4 p-6 text-center">
                <p className="font-semibold text-slate-200">No signals match these filters.</p>
                <button
                  onClick={() => {
                    setSignalDateScope('all')
                    setSignalsHighImpactOnly(false)
                    setSelectedEventCode(null)
                  }}
                  className="mt-3 rounded-lg border border-white/10 px-3 py-2 text-sm text-slate-300 hover:bg-white/5"
                >
                  Clear filters
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
                {visiblePredictions.map(pred => (
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
        {activeTab === 'calendar' && (() => {
          const scopedEvents = calendarEvents.filter(event => {
            const isHighImpact = (event.impact || '').toUpperCase() === 'HIGH'
            return (!calendarHighImpactOnly || isHighImpact) &&
              matchesDateScope(event.release_time_utc, calendarDateScope, now)
          })

          // Split into upcoming vs released
          const upcoming = scopedEvents.filter(e => {
            const t = e.release_time_utc ? new Date(e.release_time_utc).getTime() : 0
            return t > now
          }).sort((a, b) => new Date(a.release_time_utc).getTime() - new Date(b.release_time_utc).getTime())
          const released = scopedEvents.filter(e => {
            const t = e.release_time_utc ? new Date(e.release_time_utc).getTime() : 0
            return t && t <= now
          }).sort((a, b) => new Date(b.release_time_utc).getTime() - new Date(a.release_time_utc).getTime())

          // Group upcoming events by release time (within 5 min = simultaneous)
          const groupByTime = (evs: CalendarEvent[]) => {
            const groups: CalendarEvent[][] = []
            const used = new Set<number>()
            evs.forEach((ev, i) => {
              if (used.has(i)) return
              const tA = new Date(ev.release_time_utc).getTime()
              const group = [ev]
              evs.forEach((ev2, j) => {
                if (j === i || used.has(j)) return
                const tB = new Date(ev2.release_time_utc).getTime()
                if (Math.abs(tA - tB) < 300000) { group.push(ev2); used.add(j) }
              })
              used.add(i)
              groups.push(group)
            })
            return groups
          }

          const upcomingGroups = groupByTime(upcoming)
          const releasedGroups = groupByTime(released)

          return (
            <div className="space-y-5">
              {/* Header */}
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-base font-bold text-white flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" />
                    {calendarDateScope === 'today' ? "Today's USD agenda" : calendarDateScope === 'week' ? "This week's USD agenda" : 'All scheduled USD events'}
                  </h3>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {scopedEvents.length} events · {upcoming.length} upcoming · {released.length} released
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleSyncActuals}
                    disabled={syncingActuals}
                    className={`p-2 rounded-xl glass-sm text-xs font-bold flex items-center gap-1.5 transition-all ${
                      syncingActuals
                        ? 'opacity-60 cursor-not-allowed text-sky-400'
                        : 'hover:bg-sky-500/20 text-sky-400 hover:text-sky-300'
                    }`}
                    title="Sync actual prints from live Forex Factory feed — no manual input needed"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${syncingActuals ? 'animate-spin' : ''}`} />
                    <span className="hidden sm:inline">{syncingActuals ? 'Syncing…' : 'Sync Actuals'}</span>
                  </button>
                  <button
                    onClick={fetchCalendar}
                    className="p-2 rounded-xl glass-sm hover:bg-white/10 text-slate-400 hover:text-white transition-all flex items-center gap-1.5 text-xs font-semibold"
                    title="Refresh calendar"
                  >
                    <RefreshCw className="w-3.5 h-3.5" />
                    <span className="hidden sm:inline">Refresh</span>
                  </button>
                </div>
              </div>

              <div className="glass-sm flex flex-col gap-3 p-3 sm:flex-row sm:items-end">
                <label className="flex flex-col gap-1.5 text-xs font-semibold text-slate-400">
                  Show dates
                  <select
                    value={calendarDateScope}
                    onChange={event => setCalendarDateScope(event.target.value as DateScope)}
                    className="min-h-10 rounded-lg border border-white/10 bg-slate-900 px-3 text-sm text-slate-100"
                  >
                    <option value="today">Today</option>
                    <option value="week">This week</option>
                    <option value="all">All dates</option>
                  </select>
                </label>
                <label className="flex min-h-10 cursor-pointer items-center gap-2 text-sm font-semibold text-slate-200">
                  <input
                    type="checkbox"
                    checked={calendarHighImpactOnly}
                    onChange={event => setCalendarHighImpactOnly(event.target.checked)}
                    className="h-4 w-4 accent-red-500"
                  />
                  Red-folder only
                </label>
                <p className="text-xs text-slate-500 sm:ml-auto">
                  {calendarHighImpactOnly ? 'High-impact events' : 'All impact levels'}
                </p>
              </div>
              {lastSyncResult && (
                <div className={`mt-2 px-3 py-2 rounded-xl text-xs font-semibold flex items-center gap-2 ${
                  lastSyncResult.graded > 0
                    ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                    : 'bg-slate-700/40 text-slate-400 border border-slate-600/30'
                }`}>
                  {lastSyncResult.graded > 0 ? '✅' : 'ℹ️'}
                  {lastSyncResult.graded > 0
                    ? `Auto-graded ${lastSyncResult.graded} event${lastSyncResult.graded > 1 ? 's' : ''}: ${lastSyncResult.names.join(', ')}`
                    : 'No new actuals detected yet — Forex Factory may not have published them yet.'}
                </div>
              )}

              {calendarEvents.length === 0 && (
                <div className="glass p-8 text-center text-slate-400">
                  No USD events found for this week. Check connection.
                </div>
              )}

              {calendarEvents.length > 0 && scopedEvents.length === 0 && (
                <div className="glass p-6 text-center">
                  <p className="font-semibold text-slate-200">No events match this view.</p>
                  <button
                    onClick={() => {
                      setCalendarDateScope('week')
                      setCalendarHighImpactOnly(false)
                    }}
                    className="mt-3 rounded-lg border border-white/10 px-3 py-2 text-sm text-slate-300 hover:bg-white/5"
                  >
                    Show all this week
                  </button>
                </div>
              )}

              {/* ── UPCOMING SECTION ── */}
              {upcoming.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <span className="text-xs font-black uppercase tracking-widest text-cyan-400 bg-cyan-500/10 px-2.5 py-1 rounded-lg border border-cyan-500/20">
                      ⏳ UPCOMING ({upcoming.length})
                    </span>
                    <div className="h-px flex-1 bg-white/10" />
                  </div>
                  <div className="space-y-3">
                    {upcomingGroups.map((group, gIdx) => (
                      group.length > 1 ? (
                        // Simultaneous group
                        <div key={gIdx} className="glass border border-red-500/30 rounded-2xl overflow-hidden bg-slate-900/60">
                          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-red-500/20 bg-red-500/5">
                            <span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-ping" />
                            <span className="text-[10px] font-black uppercase tracking-wider text-red-300">
                              ⚡ {group.length} Events Releasing Simultaneously
                            </span>
                            <span className="ml-auto text-[10px] font-mono text-cyan-300">
                              {getEventTiming(group[0].release_time_utc, now).timeNy} NY
                            </span>
                            <CountdownBadge releaseTimeUtc={group[0].release_time_utc} now={now} />
                          </div>
                          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-0 divide-y md:divide-y-0 md:divide-x divide-white/5">
                            {group.map((ev, eIdx) => (
                              <CalendarEventCard key={eIdx} ev={ev} onAnalyze={handleAnalyzeEvent} now={now} compact onSyncActuals={handleSyncActuals} />
                            ))}
                          </div>
                        </div>
                      ) : (
                        <CalendarEventCard key={gIdx} ev={group[0]} onAnalyze={handleAnalyzeEvent} now={now} onSyncActuals={handleSyncActuals} />
                      )
                    ))}
                  </div>
                </div>
              )}

              {/* ── RELEASED SECTION ── */}
              {released.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-3 mt-2">
                    <span className="text-xs font-black uppercase tracking-widest text-slate-400 bg-slate-500/10 px-2.5 py-1 rounded-lg border border-slate-500/20">
                      ✅ RELEASED ({released.length})
                    </span>
                    <div className="h-px flex-1 bg-white/5" />
                  </div>
                  <div className="space-y-3 opacity-90">
                    {releasedGroups.map((group, gIdx) => (
                      group.length > 1 ? (
                        <div key={gIdx} className="glass border border-slate-500/20 rounded-2xl overflow-hidden bg-slate-900/40">
                          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-white/5 bg-slate-800/30">
                            <CheckCircle className="w-3 h-3 text-slate-400" />
                            <span className="text-[10px] font-black uppercase tracking-wider text-slate-400">
                              ⚡ {group.length} Simultaneous Releases
                            </span>
                            <span className="ml-auto text-[10px] font-mono text-slate-500">
                              {getEventTiming(group[0].release_time_utc, now).timeNy} NY
                            </span>
                            <CountdownBadge releaseTimeUtc={group[0].release_time_utc} now={now} />
                          </div>
                          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-0 divide-y md:divide-y-0 md:divide-x divide-white/5">
                            {group.map((ev, eIdx) => (
                              <CalendarEventCard key={eIdx} ev={ev} onAnalyze={handleAnalyzeEvent} now={now} compact onSyncActuals={handleSyncActuals} />
                            ))}
                          </div>
                        </div>
                      ) : (
                        <CalendarEventCard key={gIdx} ev={group[0]} onAnalyze={handleAnalyzeEvent} now={now} onSyncActuals={handleSyncActuals} />
                      )
                    ))}
                  </div>
                </div>
              )}
            </div>
          )
        })()}

        {/* ── TAB 3: ACCURACY & HISTORY ── */}
        {activeTab === 'accuracy' && (
          <div className="space-y-6">
            {/* Top Stat Summary Cards */}
            {accuracy && accuracy.total_predictions > 0 && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="glass p-4 border border-indigo-500/20">
                  <p className="text-xs text-slate-400 uppercase font-semibold">Recorded accuracy</p>
                  <p className="text-2xl font-black text-indigo-400 font-mono mt-1">{accuracy.overall_hit_rate}%</p>
                  <p className="text-[10px] text-slate-500 mt-1">Of {accuracy.total_predictions} tracked releases</p>
                </div>
                <div className="glass p-4 border border-emerald-500/20">
                  <p className="text-xs text-slate-400 uppercase font-semibold">Correct</p>
                  <p className="text-2xl font-black text-emerald-400 font-mono mt-1">{accuracy.wins}</p>
                  <p className="text-[10px] text-slate-500 mt-1">Matched the release outcome</p>
                </div>
                <div className="glass p-4 border border-red-500/20">
                  <p className="text-xs text-slate-400 uppercase font-semibold">Incorrect</p>
                  <p className="text-2xl font-black text-red-400 font-mono mt-1">{accuracy.losses}</p>
                  <p className="text-[10px] text-slate-500 mt-1">Did not match the release outcome</p>
                </div>
                <div className="glass p-4 border border-cyan-500/20">
                  <p className="text-xs text-slate-400 uppercase font-semibold">Releases counted</p>
                  <p className="text-2xl font-black text-cyan-400 font-mono mt-1">{accuracy.total_predictions}</p>
                  <p className="text-[10px] text-slate-500 mt-1">With a saved pre-release forecast</p>
                </div>
              </div>
            )}
            {accuracy && accuracy.total_predictions === 0 && (
              <div className="glass p-4 border border-white/10 text-sm text-slate-300">
                No verified release results yet. A forecast is counted only when it was saved before its scheduled release.
              </div>
            )}

            {/* Per-event breakdown table */}
            {accuracy && accuracy.event_stats.length > 0 && (
              <div className="glass p-5 border border-white/5">
                <h4 className="text-sm font-bold text-white uppercase tracking-wider mb-3">Results by release</h4>
                <div className="space-y-2">
                  {accuracy.event_stats.map((st, i) => (
                    <div key={i} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
                      <div>
                        <p className="text-sm font-bold text-slate-200">{st.display_name}</p>
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
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4">
                <div>
                  <h4 className="text-sm font-bold text-white uppercase tracking-wider mb-0.5">Tracked forecasts and actual releases</h4>
                  <p className="text-[11px] text-slate-500">
                    Only forecasts saved before a scheduled release are counted. This list covers releases recorded by this app; it is not a complete news archive.
                  </p>
                </div>
                <button
                  onClick={() => { fetchHistory(); fetchPredictions() }}
                  className="px-3 py-1.5 rounded-xl glass-sm hover:bg-white/10 text-slate-400 hover:text-white transition-all flex items-center gap-1.5 text-xs font-semibold self-start sm:self-auto flex-shrink-0"
                  title="Reload release results"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>Refresh results</span>
                </button>
              </div>
              {historyItems.length === 0 ? (
                <p className="text-sm text-slate-400">
                  No tracked releases to show yet. Releases missed while the app was offline will not appear here.
                </p>
              ) : (
                <div className="space-y-3">
                  {historyItems.map((item) => {
                    const surpriseColor = getSurpriseColor(item.event_code, item.surprise)
                    const surpriseLabel = getSurpriseLabel(item.event_code, item.surprise)

                    let verdictText = ''
                    const actualVsForecast = item.surprise == null || item.surprise === 0
                      ? 'matched the forecast'
                      : item.surprise > 0 ? 'was above the forecast' : 'was below the forecast'
                    if (item.was_correct === true) {
                      verdictText = `Actual ${item.actual} ${actualVsForecast} of ${item.forecast}. This forecast was graded correct.`
                    } else if (item.was_correct === false) {
                      verdictText = `Actual ${item.actual} ${actualVsForecast} of ${item.forecast}. This forecast was graded incorrect.`
                    }

                    return (
                      <div key={item.id} className={`glass-sm p-4 border flex flex-col gap-3 ${
                        item.was_correct === true ? 'border-emerald-500/20 bg-emerald-950/10' :
                        item.was_correct === false ? 'border-red-500/20 bg-red-950/10' :
                        'border-white/5'
                      }`}>
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                          <div>
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-xs text-slate-500">
                                {new Date(item.date).toLocaleDateString()}
                              </span>
                            </div>
                            <h5 className="text-sm font-bold text-white">{item.display_name}</h5>
                            <div className="flex items-center gap-2 mt-1">
                              <span className="text-xs text-slate-400">Before release:</span>
                              <span className="text-xs font-bold text-slate-200">
                                {getForecastDirectionLabel(item.event_code, item.lean_direction)}
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
                              <p className="text-[10px] text-slate-500 uppercase">Difference</p>
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
              )}
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
            <span className="font-bold text-slate-400">TitanFX Sage — Macro Predictor</span>
          </div>
          <p className="pt-1 text-sm font-semibold text-emerald-300">See beyond the price. Trade the bigger picture.</p>
        </footer>
      </div>
    </div>
  )
}
