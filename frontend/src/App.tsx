import { useEffect, useState, useCallback } from 'react'
import axios from 'axios'
import { motion, AnimatePresence } from 'framer-motion'
import {
  RefreshCw, TrendingUp, TrendingDown, Minus, Zap,
  Bell, CheckCircle, AlertCircle, Calendar, Award,
  Clock, ArrowUpRight, Send
} from 'lucide-react'

const API = 'http://localhost:8000'

// Events where LOWER actual = positive surprise (fewer unemployed = stronger economy)
const INVERSE_EVENTS = new Set(['JOBLESS_CLAIMS', 'UNEMPLOYMENT_RATE'])

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
  onRefresh,
  onSendTelegram
}: {
  pred: Prediction
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
      <div className="flex items-start justify-between gap-4 mb-4">
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
      <div className="max-w-4xl mx-auto px-4 py-8">

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

        {/* ── Navigation Tabs ── */}
        <div className="flex items-center gap-2 mb-6 border-b border-white/10 pb-2 overflow-x-auto">
          <button
            onClick={() => setActiveTab('predictions')}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all ${
              activeTab === 'predictions'
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
                : 'text-slate-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <Zap className="w-4 h-4" />
            Live Predictions ({predictions.length})
          </button>

          <button
            onClick={() => { setActiveTab('calendar'); fetchCalendar() }}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all ${
              activeTab === 'calendar'
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
                : 'text-slate-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <Calendar className="w-4 h-4" />
            Red-Folder Calendar ({calendarEvents.length})
          </button>

          <button
            onClick={() => { setActiveTab('accuracy'); fetchHistory() }}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all ${
              activeTab === 'accuracy'
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
                : 'text-slate-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <Award className="w-4 h-4" />
            Accuracy & History ({accuracy?.overall_hit_rate ?? 0}% Win Rate)
          </button>

          <button
            onClick={() => setActiveTab('telegram')}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all ${
              activeTab === 'telegram'
                ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30'
                : 'text-slate-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <Bell className="w-4 h-4" />
            Telegram & Scheduler
          </button>
        </div>

        {/* ── TAB 1: PREDICTIONS ── */}
        {activeTab === 'predictions' && (
          <div>
            <div className="flex flex-wrap gap-3 mb-6">
              <button
                onClick={runAll}
                disabled={runningAll}
                className="flex-1 min-w-[200px] flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-bold py-3 px-4 rounded-xl transition-all active:scale-95 shadow-lg shadow-indigo-600/20"
              >
                <Zap className={`w-4 h-4 ${runningAll ? 'animate-pulse' : ''}`} />
                {runningAll ? 'Recalculating all macro indicators…' : 'Run All Predictions'}
              </button>

              <button
                onClick={broadcastAllTelegram}
                disabled={broadcastingTg}
                className="flex items-center justify-center gap-2 bg-cyan-600/20 hover:bg-cyan-600/30 border border-cyan-500/40 text-cyan-300 font-bold py-3 px-5 rounded-xl transition-all active:scale-95 shadow-lg shadow-cyan-600/10"
              >
                {broadcastingTg ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : broadcastSent ? (
                  <CheckCircle className="w-4 h-4 text-emerald-400" />
                ) : (
                  <Bell className="w-4 h-4" />
                )}
                {broadcastSent ? 'Signals Sent!' : 'Send to Telegram'}
              </button>

              <button
                onClick={fetchPredictions}
                title="Refresh predictions"
                className="p-3 glass-sm hover:bg-white/10 rounded-xl transition-all active:scale-95 border border-white/10"
              >
                <RefreshCw className="w-4 h-4 text-slate-400" />
              </button>
            </div>

            {/* ── Event Filter Pills ── */}
            <div className="flex items-center gap-1.5 mb-5 overflow-x-auto pb-1.5 no-scrollbar">
              <button
                onClick={() => setSelectedEventCode(null)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold font-mono transition-all whitespace-nowrap ${
                  selectedEventCode === null
                    ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/30'
                    : 'glass-sm text-slate-400 hover:text-white'
                }`}
              >
                All Events ({predictions.length})
              </button>
              {health?.supported_events.map(code => (
                <button
                  key={code}
                  onClick={() => setSelectedEventCode(code)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold font-mono transition-all whitespace-nowrap ${
                    selectedEventCode === code
                      ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/30 border border-indigo-400/40'
                      : 'glass-sm text-slate-400 hover:text-white'
                  }`}
                >
                  {code}
                </button>
              ))}
            </div>

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

            <div className={`grid gap-4 ${selectedEventCode ? 'grid-cols-1 max-w-2xl mx-auto' : 'grid-cols-1 md:grid-cols-2'}`}>
              <AnimatePresence>
                {(selectedEventCode
                  ? predictions.filter(p => p.event_code === selectedEventCode)
                  : predictions
                ).map(pred => (
                  <PredictionCard
                    key={pred.id}
                    pred={pred}
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
                <h3 className="text-base font-bold text-white">This Week's High-Impact Releases</h3>
                <p className="text-xs text-slate-400">Forex Factory Live Feed with automated 2-hour pre-release alerting</p>
              </div>
              <button
                onClick={fetchCalendar}
                className="p-2 rounded-xl glass-sm hover:bg-white/10 text-slate-400 hover:text-white transition-all"
              >
                <RefreshCw className="w-4 h-4" />
              </button>
            </div>

            {calendarEvents.length === 0 ? (
              <div className="glass p-8 text-center text-slate-400">
                No high-impact USD events found for this week in the feed.
              </div>
            ) : (
              calendarEvents.map((ev, idx) => (
                <div key={idx} className="glass p-5 border border-white/5 hover:border-white/15 transition-all">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-[10px] font-black uppercase px-2 py-0.5 rounded bg-red-500/20 text-red-400 border border-red-500/30">
                          {ev.impact} IMPACT
                        </span>
                        <span className="text-xs font-mono text-slate-400">
                          {ev.release_time_utc ? new Date(ev.release_time_utc).toLocaleString() : 'TBD'}
                        </span>
                      </div>
                      <h4 className="text-base font-bold text-white">{ev.event_name}</h4>
                    </div>

                    <div className="flex items-center gap-6">
                      <div className="text-right">
                        <p className="text-[10px] text-slate-500 uppercase">Forecast</p>
                        <p className="text-sm font-mono font-bold text-slate-200">{ev.forecast ?? '—'}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-[10px] text-slate-500 uppercase">Previous</p>
                        <p className="text-sm font-mono font-bold text-slate-400">{ev.previous ?? '—'}</p>
                      </div>
                      {ev.actual != null && (
                        <div className="text-right">
                          <p className="text-[10px] text-emerald-500 uppercase font-bold">Actual</p>
                          <p className="text-sm font-mono font-bold text-emerald-400">{ev.actual}</p>
                        </div>
                      )}
                      <button
                        onClick={() => handleAnalyzeEvent(ev.event_code)}
                        className="bg-indigo-600 hover:bg-indigo-500 text-white px-3.5 py-2 rounded-xl text-xs font-bold transition-all shadow-md shadow-indigo-600/20 flex items-center gap-1.5 active:scale-95"
                      >
                        <Zap className="w-3.5 h-3.5 text-amber-300" />
                        Analyze {ev.event_code}
                      </button>
                    </div>
                  </div>
                </div>
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
