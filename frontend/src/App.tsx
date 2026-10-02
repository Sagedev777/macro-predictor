/**
 * App.tsx — MacroPredictor v3 Dashboard
 * Dark trading-dashboard aesthetic, multi-currency architecture.
 *
 * Tabs:
 *   Signals   — per-event cards with currency strength + per-pair buy/sell + order levels
 *   Calendar  — upcoming events feed (red + orange), countdown badges
 *   Strength  — 8-currency strength meter panel + pair bias table
 *   Results   — historical accuracy ledger
 *   Telegram  — alert controls
 */

import './App.css'
import axios from 'axios'
import { useEffect, useState } from 'react'

// ── Types ─────────────────────────────────────────────────────────────────────

interface Indicator {
  fred_series: string
  description: string
  latest_value: number | null
  z_score: number | null
  signal: number
  weight: number
}

interface PairSignal {
  pair: string
  direction: 'BUY' | 'SELL' | 'NEUTRAL'
  bias: number
  confidence_pct: number
}

interface OrderSuggestion {
  pair: string
  bias: string
  current_price: number | null
  atr_14: number | null
  suggested_entry: number | null
  suggested_sl: number | null
  suggested_tp: number | null
  confidence_pct: number
  is_reference_only: boolean
}

interface Prediction {
  id: number
  event_code: string
  display_name: string
  currency: string
  lean_direction: string
  event_label: string
  explanation: string
  confidence_pct: number
  composite_score: number
  indicator_score?: number
  trade_signals: string[]
  pair_signals: PairSignal[]
  order_suggestions: OrderSuggestion[]
  indicators: Indicator[]
  created_at: string
  was_correct: boolean | null
  forecast: number | null
  actual: number | null
}

interface CalendarEvent {
  event_code: string | null
  event_name: string
  currency: string
  release_time_utc: string
  forecast: number | null
  previous: number | null
  actual: number | null
  impact: 'HIGH' | 'MEDIUM'
  display_name?: string
  is_simultaneous: boolean
  prediction?: Prediction | null
}

interface CurrencyStrength {
  currency: string
  strength_score: number
  confidence_pct: number
  n_trained: number
  indicator_score: number | null
  rate_diff_score: number | null
  cot_score: number | null
  sentiment_score: number | null
  recorded_at: string | null
}

interface PairBias {
  pair: string
  base: string
  quote: string
  base_strength: number
  quote_strength: number
  bias: number
  direction: 'BUY' | 'SELL' | 'NEUTRAL'
  confidence_pct: number
}

interface HistoryItem {
  id: number
  event_code: string
  display_name: string
  currency: string
  lean_direction: string
  confidence_pct: number
  forecast: number | null
  actual: number | null
  surprise: number | null
  was_correct: boolean
  date: string | null
}

interface AccuracyStats {
  total_predictions: number
  wins: number
  losses: number
  overall_hit_rate: number
  event_stats: { event_code: string; display_name: string; total: number; wins: number; hit_rate_pct: number }[]
  currency_stats: { currency: string; total: number; wins: number; hit_rate_pct: number }[]
  confidence_stats: { bucket: string; total: number; wins: number; hit_rate_pct: number }[]
}

interface FeatureDrift {
  currency: string
  feature_weights: { indicator_score: number; rate_diff_score: number; cot_score: number; sentiment_score: number }
}

type Tab = 'signals' | 'calendar' | 'strength' | 'results' | 'telegram'

// ── Constants ────────────────────────────────────────────────────────────────

const API = '/api'
const CURRENCY_FLAGS: Record<string, string> = {
  USD: '🇺🇸', EUR: '🇪🇺', GBP: '🇬🇧', JPY: '🇯🇵',
  AUD: '🇦🇺', CHF: '🇨🇭', CAD: '🇨🇦', NZD: '🇳🇿',
}
const CURRENCY_NAMES: Record<string, string> = {
  USD: 'US Dollar', EUR: 'Euro', GBP: 'Sterling',
  JPY: 'Yen', AUD: 'Aussie', CHF: 'Franc',
  CAD: 'Loonie', NZD: 'Kiwi',
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function dirColor(dir: string): string {
  const d = dir?.toUpperCase()
  if (d === 'BUY' || d === 'BEAT' || d === 'BULLISH') return 'text-emerald-400'
  if (d === 'SELL' || d === 'MISS' || d === 'BEARISH') return 'text-rose-400'
  return 'text-slate-400'
}

function dirBg(dir: string): string {
  const d = dir?.toUpperCase()
  if (d === 'BUY' || d === 'BEAT' || d === 'BULLISH') return 'bg-emerald-500/15 border border-emerald-500/30 text-emerald-400'
  if (d === 'SELL' || d === 'MISS' || d === 'BEARISH') return 'bg-rose-500/15 border border-rose-500/30 text-rose-400'
  return 'bg-slate-700/40 border border-slate-600/30 text-slate-400'
}

function impactDot(impact: string) {
  return impact === 'HIGH'
    ? <span className="inline-block w-2 h-2 rounded-full bg-rose-500 mr-1.5" title="Red folder" />
    : <span className="inline-block w-2 h-2 rounded-full bg-amber-400 mr-1.5" title="Orange folder" />
}

function strengthColor(score: number): string {
  if (score > 0.2)  return 'text-emerald-400'
  if (score < -0.2) return 'text-rose-400'
  return 'text-slate-400'
}

function formatCountdown(releaseUtc: string, now: number): string {
  const ms = new Date(releaseUtc).getTime() - now
  if (ms <= 0) return 'Released'
  const h = Math.floor(ms / 3600000)
  const m = Math.floor((ms % 3600000) / 60000)
  if (h > 48) return `${Math.floor(h / 24)}d`
  if (h > 0)  return `${h}h ${m}m`
  return `${m}m`
}

function fmt(n: number | null, d = 4): string {
  if (n == null) return '—'
  return n.toFixed(d)
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ConfidenceBar({ pct, label }: { pct: number; label?: string }) {
  const color =
    pct >= 70 ? 'from-emerald-500 to-emerald-400' :
    pct >= 55 ? 'from-amber-500 to-amber-400' :
                'from-slate-500 to-slate-400'
  return (
    <div>
      <div className="flex justify-between items-center mb-1 text-xs text-slate-400">
        <span>{label ?? 'Confidence'}</span>
        <span className="font-mono font-semibold text-white">{pct.toFixed(1)}%</span>
      </div>
      <div className="confidence-bar-track">
        <div className={`confidence-bar-fill bg-gradient-to-r ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function StrengthBar({ score }: { score: number; currency?: string }) {
  const pct       = Math.abs(score) * 100
  const isPositive = score >= 0
  return (
    <div className="flex items-center gap-3 w-full">
      {/* Bear side */}
      <div className="flex-1 flex justify-end">
        <div
          className="h-2.5 rounded-full strength-fill-bear transition-all duration-700"
          style={{ width: isPositive ? '0%' : `${pct}%`, minWidth: isPositive ? 0 : 4 }}
        />
      </div>
      {/* Centre label */}
      <span className={`text-sm font-bold font-mono w-14 text-center ${strengthColor(score)}`}>
        {score > 0 ? '+' : ''}{(score * 100).toFixed(1)}
      </span>
      {/* Bull side */}
      <div className="flex-1">
        <div
          className="h-2.5 rounded-full strength-fill-bull transition-all duration-700"
          style={{ width: isPositive ? `${pct}%` : '0%', minWidth: isPositive ? 4 : 0 }}
        />
      </div>
    </div>
  )
}

function PairSignalBadge({ ps }: { ps: PairSignal }) {
  return (
    <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold ${dirBg(ps.direction)}`}>
      <span>{ps.pair}</span>
      <span className="opacity-70">|</span>
      <span>{ps.direction}</span>
      <span className="opacity-60 font-normal">{ps.confidence_pct.toFixed(0)}%</span>
    </div>
  )
}

function OrderLevelCard({ s }: { s: OrderSuggestion }) {
  if (!s.suggested_entry) return null
  return (
    <div className="glass-sm p-3 text-xs space-y-1">
      <div className="flex items-center justify-between mb-1">
        <span className="font-bold text-white">{s.pair}</span>
        <span className={`px-2 py-0.5 rounded-md font-semibold text-xs ${dirBg(s.bias)}`}>{s.bias}-STOP</span>
      </div>
      <div className="grid grid-cols-3 gap-1 text-center">
        <div>
          <div className="text-slate-500 mb-0.5">Entry</div>
          <div className="font-mono text-cyan-300">{fmt(s.suggested_entry, 5)}</div>
        </div>
        <div>
          <div className="text-slate-500 mb-0.5">SL</div>
          <div className="font-mono text-rose-400">{fmt(s.suggested_sl, 5)}</div>
        </div>
        <div>
          <div className="text-slate-500 mb-0.5">TP</div>
          <div className="font-mono text-emerald-400">{fmt(s.suggested_tp, 5)}</div>
        </div>
      </div>
      {s.atr_14 && (
        <div className="text-slate-600 text-[10px] pt-0.5">
          ATR(14): {fmt(s.atr_14, 5)} · Reference only — not a trade recommendation
        </div>
      )}
    </div>
  )
}

function IndicatorRow({ ind }: { ind: Indicator }) {
  const sig = ind.signal
  const icon = sig > 0 ? '▲' : sig < 0 ? '▼' : '●'
  const col  = sig > 0 ? 'text-emerald-400' : sig < 0 ? 'text-rose-400' : 'text-slate-500'
  return (
    <div className="flex items-center gap-2 py-1.5 border-b border-slate-800/60 last:border-0 text-xs">
      <span className={`w-4 text-center font-bold ${col}`}>{icon}</span>
      <span className="flex-1 text-slate-300">{ind.description}</span>
      <span className="font-mono text-slate-400 w-16 text-right">{fmt(ind.z_score, 2)}</span>
      <span className="text-slate-600 w-10 text-right">{(ind.weight * 100).toFixed(0)}%</span>
    </div>
  )
}

function SignalCard({ pred }: { pred: Prediction }) {
  const [expanded, setExpanded] = useState(false)
  const flag = CURRENCY_FLAGS[pred.currency] ?? '🌐'

  return (
    <div className={`glass p-5 space-y-4 ${
      pred.lean_direction === 'BEAT' || pred.lean_direction === 'BULLISH'
        ? 'border-glow-green'
        : pred.lean_direction === 'MISS' || pred.lean_direction === 'BEARISH'
        ? 'border-glow-red'
        : ''
    }`}>
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-lg">{flag}</span>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-widest">{pred.currency}</span>
          </div>
          <h3 className="text-base font-bold text-white leading-tight">{pred.display_name}</h3>
          <p className={`text-sm font-semibold mt-0.5 ${dirColor(pred.lean_direction)}`}>{pred.event_label}</p>
        </div>
        <div className={`shrink-0 px-3 py-1.5 rounded-xl text-xs font-bold uppercase tracking-wide ${dirBg(pred.lean_direction)}`}>
          {pred.lean_direction === 'BEAT' ? 'BULLISH' :
           pred.lean_direction === 'MISS' ? 'BEARISH' : pred.lean_direction}
        </div>
      </div>

      {/* Confidence */}
      <ConfidenceBar pct={pred.confidence_pct} />

      {/* Explanation */}
      <p className="text-xs text-slate-400 leading-relaxed">{pred.explanation}</p>

      {/* Pair signals */}
      {pred.pair_signals && pred.pair_signals.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">Affected Pairs</p>
          <div className="flex flex-wrap gap-1.5">
            {pred.pair_signals.slice(0, 8).map(ps => <PairSignalBadge key={ps.pair} ps={ps} />)}
          </div>
        </div>
      )}

      {/* Order levels */}
      {pred.order_suggestions && pred.order_suggestions.filter(s => s.suggested_entry).length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">Order Levels (Reference)</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {pred.order_suggestions
              .filter(s => s.suggested_entry && s.bias !== 'NEUTRAL')
              .slice(0, 4)
              .map(s => <OrderLevelCard key={s.pair} s={s} />)}
          </div>
        </div>
      )}

      {/* Expand indicator breakdown */}
      <button
        onClick={() => setExpanded(v => !v)}
        className="text-[10px] text-slate-500 hover:text-slate-300 transition-colors uppercase tracking-widest w-full text-left mt-1"
      >
        {expanded ? '▲ Hide' : '▼ Show'} indicators ({pred.indicators?.length ?? 0})
      </button>
      {expanded && (
        <div className="glass-sm p-3 mt-1">
          {(pred.indicators ?? []).map((ind, i) => <IndicatorRow key={i} ind={ind} />)}
        </div>
      )}
    </div>
  )
}

function CalendarCard({ ev, now }: { ev: CalendarEvent; now: number }) {
  const released = ev.actual != null
  const countdown = formatCountdown(ev.release_time_utc, now)

  return (
    <div className="glass-sm p-4 space-y-3">
      {/* Row 1: impact + currency + title */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5">
            {impactDot(ev.impact)}
            <span className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold">
              {CURRENCY_FLAGS[ev.currency] ?? ''} {ev.currency}
            </span>
          </div>
          <p className="text-sm font-semibold text-white leading-tight truncate">{ev.display_name ?? ev.event_name}</p>
        </div>
        <div className={`shrink-0 px-2.5 py-1 rounded-lg text-xs font-mono font-semibold ${
          released ? 'bg-slate-700/60 text-slate-400' : 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/30'
        }`}>
          {released ? 'Released' : countdown}
        </div>
      </div>

      {/* Row 2: data grid */}
      <div className="grid grid-cols-3 gap-2 text-xs text-center">
        {[
          ['Forecast', ev.forecast],
          ['Previous', ev.previous],
          ['Actual',   ev.actual],
        ].map(([label, val]) => (
          <div key={label as string} className="glass-sm py-1.5">
            <div className="text-slate-600 text-[10px] mb-0.5">{label}</div>
            <div className={`font-mono font-semibold ${
              label === 'Actual' && val != null ? 'text-cyan-300' : 'text-slate-300'
            }`}>
              {val != null ? String(val) : '—'}
            </div>
          </div>
        ))}
      </div>

      {/* Row 3: pre-release prediction pill */}
      {ev.prediction && (
        <div className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs ${dirBg(ev.prediction.lean_direction)}`}>
          <span className="font-semibold">Model lean:</span>
          <span>{ev.prediction.event_label}</span>
          <span className="ml-auto font-mono">{ev.prediction.confidence_pct?.toFixed(1)}%</span>
        </div>
      )}
    </div>
  )
}

function CurrencyMeter({ cs }: { cs: CurrencyStrength }) {
  const score = cs.strength_score ?? 0
  return (
    <div className="glass-sm p-3.5">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xl">{CURRENCY_FLAGS[cs.currency]}</span>
        <div>
          <div className="text-xs font-bold text-white">{cs.currency}</div>
          <div className="text-[10px] text-slate-500">{CURRENCY_NAMES[cs.currency]}</div>
        </div>
        <div className={`ml-auto text-sm font-mono font-bold ${strengthColor(score)}`}>
          {score > 0 ? '+' : ''}{(score * 100).toFixed(1)}
        </div>
      </div>
      <StrengthBar score={score} currency={cs.currency} />
      <div className="flex items-center gap-3 mt-2 text-[10px] text-slate-600">
        <span>n={cs.n_trained}</span>
        <span>conf={cs.confidence_pct?.toFixed(0)}%</span>
        {cs.recorded_at && <span className="ml-auto">{new Date(cs.recorded_at).toLocaleDateString()}</span>}
      </div>
    </div>
  )
}

function FeatureDriftPanel({ drifts }: { drifts: FeatureDrift[] }) {
  const keys = ['indicator_score', 'rate_diff_score', 'cot_score', 'sentiment_score']
  const labels: Record<string, string> = {
    indicator_score:  'Indicator Z',
    rate_diff_score:  'Rate Diff',
    cot_score:        'COT',
    sentiment_score:  'Sentiment',
  }
  const colors = ['bg-indigo-500', 'bg-cyan-500', 'bg-amber-500', 'bg-emerald-500']

  return (
    <div className="glass p-5 space-y-4">
      <h3 className="text-sm font-bold text-white">Feature Importance Drift</h3>
      <p className="text-xs text-slate-500">Which signal type is currently most predictive per currency model</p>
      <div className="space-y-3">
        {drifts.map(({ currency, feature_weights: fw }) => (
          <div key={currency}>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-sm">{CURRENCY_FLAGS[currency]}</span>
              <span className="text-xs font-bold text-slate-300">{currency}</span>
            </div>
            <div className="flex h-2.5 w-full rounded-full overflow-hidden gap-px">
              {keys.map((k, i) => (
                <div
                  key={k}
                  className={`${colors[i]} transition-all duration-700`}
                  style={{ width: `${((fw as any)[k] ?? 0.25) * 100}%` }}
                  title={`${labels[k]}: ${(((fw as any)[k] ?? 0) * 100).toFixed(1)}%`}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-3 mt-1">
        {keys.map((k, i) => (
          <div key={k} className="flex items-center gap-1.5 text-[10px] text-slate-500">
            <span className={`inline-block w-2.5 h-2.5 rounded-sm ${colors[i]}`} />
            {labels[k]}
          </div>
        ))}
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// MAIN APP
// ══════════════════════════════════════════════════════════════════════════════

export default function App() {
  const [tab, setTab]                   = useState<Tab>('signals')
  const [now, setNow]                   = useState(Date.now())
  const [loading, setLoading]           = useState(false)
  const [toast, setToast]               = useState<string | null>(null)

  // Data state
  const [predictions, setPredictions]   = useState<Prediction[]>([])
  const [calendarEvs, setCalendarEvs]   = useState<CalendarEvent[]>([])
  const [strengths, setStrengths]       = useState<CurrencyStrength[]>([])
  const [pairBiases, setPairBiases]     = useState<PairBias[]>([])
  const [drifts, setDrifts]             = useState<FeatureDrift[]>([])
  const [history, setHistory]           = useState<HistoryItem[]>([])
  const [accuracy, setAccuracy]         = useState<AccuracyStats | null>(null)

  // Telegram form
  const [tgEventCode, setTgEventCode]   = useState('')
  const [tgStatus, setTgStatus]         = useState<string | null>(null)

  // Ticker clock
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(id)
  }, [])

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3000)
  }

  // ── Data fetchers ───────────────────────────────────────────────────────────
  const fetchPredictions = async () => {
    const r = await axios.get(`${API}/predictions?limit=50`)
    setPredictions(r.data.predictions ?? [])
  }

  const fetchCalendar = async (force = false) => {
    const r = await axios.get(`${API}/events${force ? '?force_refresh=true' : ''}`)
    setCalendarEvs(r.data.events ?? [])
  }

  const fetchStrengths = async () => {
    const [sRes, pbRes, dRes] = await Promise.all([
      axios.get(`${API}/currency-strengths`),
      axios.get(`${API}/pair-biases`),
      axios.get(`${API}/feature-drift`),
    ])
    setStrengths(sRes.data.currency_strengths ?? [])
    setPairBiases(pbRes.data.pair_biases ?? [])
    setDrifts(dRes.data.currencies ?? [])
  }

  const fetchResults = async () => {
    const [hRes, aRes] = await Promise.all([
      axios.get(`${API}/history?limit=50`),
      axios.get(`${API}/accuracy`),
    ])
    setHistory(hRes.data.history ?? [])
    setAccuracy(aRes.data)
  }

  // ── Load on tab switch ──────────────────────────────────────────────────────
  useEffect(() => {
    setLoading(true)
    const p =
      tab === 'signals'   ? fetchPredictions() :
      tab === 'calendar'  ? fetchCalendar()     :
      tab === 'strength'  ? fetchStrengths()    :
      tab === 'results'   ? fetchResults()      :
      Promise.resolve()
    p.catch(e => showToast(`Load failed: ${e.message}`))
      .finally(() => setLoading(false))
  }, [tab]) // eslint-disable-line

  // ── Actions ─────────────────────────────────────────────────────────────────
  const syncActuals = async () => {
    setLoading(true)
    try {
      const r = await axios.post(`${API}/events/sync-actuals`)
      showToast(`Synced ${r.data.synced_events} events, graded ${r.data.newly_graded}`)
      fetchCalendar(true)
    } catch (e: any) {
      showToast(`Sync failed: ${e.message}`)
    } finally { setLoading(false) }
  }

  const runFullCycle = async () => {
    setLoading(true)
    try {
      await axios.post(`${API}/run-full-cycle`)
      showToast('Full prediction cycle complete')
      fetchStrengths()
    } catch (e: any) {
      showToast(`Cycle failed: ${e.message}`)
    } finally { setLoading(false) }
  }

  const sendTelegram = async () => {
    if (!tgEventCode) return
    try {
      const r = await axios.post(`${API}/prediction/${tgEventCode}/telegram`)
      setTgStatus(r.data.success ? '✅ Sent!' : '❌ Failed')
    } catch { setTgStatus('❌ Error') }
  }

  const sendTestTelegram = async () => {
    try {
      await axios.post(`${API}/telegram/test`)
      setTgStatus('✅ Test message sent')
    } catch { setTgStatus('❌ Error') }
  }

  const broadcastAll = async () => {
    setLoading(true)
    try {
      await axios.post(`${API}/telegram/broadcast-all`)
      showToast('Broadcast complete')
    } catch (e: any) {
      showToast(`Broadcast failed: ${e.message}`)
    } finally { setLoading(false) }
  }

  // ── Tab definitions ─────────────────────────────────────────────────────────
  const TABS: { id: Tab; label: string; icon: string }[] = [
    { id: 'signals',  label: 'Signals',   icon: '⚡' },
    { id: 'calendar', label: 'Calendar',  icon: '📅' },
    { id: 'strength', label: 'Strength',  icon: '📊' },
    { id: 'results',  label: 'Results',   icon: '🎯' },
    { id: 'telegram', label: 'Telegram',  icon: '📲' },
  ]

  // ══════════════════════════════════════════════════════════════════════════
  // RENDER
  // ══════════════════════════════════════════════════════════════════════════
  return (
    <div className="bg-ambient min-h-screen text-slate-200 font-sans">

      {/* ── Toast ──────────────────────────────────────────────────────────── */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 glass px-4 py-3 text-sm font-medium text-white shadow-2xl">
          {toast}
        </div>
      )}

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-40 border-b border-white/5 backdrop-blur-xl bg-[#060610]/80">
        <div className="max-w-6xl mx-auto px-4 flex items-center justify-between h-14">
          <div className="flex items-center gap-3">
            <div className="live-dot" />
            <span className="font-bold text-white tracking-tight text-sm">
              MacroPredictor <span className="text-indigo-400 font-normal">v3</span>
            </span>
          </div>
          <div className="flex items-center gap-2">
            {loading && (
              <span className="text-xs text-slate-500 animate-pulse">loading…</span>
            )}
            <button
              onClick={() => { tab === 'calendar' ? fetchCalendar(true) : tab === 'strength' ? fetchStrengths() : fetchPredictions() }}
              className="text-xs px-3 py-1.5 rounded-lg glass-sm hover:bg-white/5 transition-colors text-slate-400"
            >
              ↻ Refresh
            </button>
          </div>
        </div>

        {/* Tab bar */}
        <div className="max-w-6xl mx-auto px-4 flex gap-1 pb-0">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`relative px-4 py-2.5 text-xs font-semibold transition-colors rounded-t-lg ${
                tab === t.id
                  ? 'text-white tab-active'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              <span className="mr-1.5">{t.icon}</span>{t.label}
            </button>
          ))}
        </div>
      </header>

      {/* ── Main content ───────────────────────────────────────────────────── */}
      <main className="max-w-6xl mx-auto px-4 py-6">

        {/* ══ SIGNALS TAB ══════════════════════════════════════════════════ */}
        {tab === 'signals' && (
          <div>
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-lg font-bold text-white">Live Signals</h2>
                <p className="text-xs text-slate-500 mt-0.5">
                  Per-currency strength model · {predictions.length} events tracked
                </p>
              </div>
              <div className="flex gap-2">
                <button onClick={syncActuals}
                  className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600/30 border border-indigo-500/30 text-indigo-300 hover:bg-indigo-600/50 transition-colors">
                  Sync Actuals
                </button>
              </div>
            </div>
            {predictions.length === 0 ? (
              <div className="glass p-12 text-center text-slate-500">
                No predictions yet. <button className="text-indigo-400 underline" onClick={fetchPredictions}>Reload</button>
              </div>
            ) : (
              <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
                {predictions.map(p => <SignalCard key={p.id} pred={p} />)}
              </div>
            )}
          </div>
        )}

        {/* ══ CALENDAR TAB ═════════════════════════════════════════════════ */}
        {tab === 'calendar' && (
          <div>
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-lg font-bold text-white">Economic Calendar</h2>
                <p className="text-xs text-slate-500 mt-0.5">Red + orange folder · all 8 currencies</p>
              </div>
              <div className="flex gap-2">
                <button onClick={() => fetchCalendar(true)}
                  className="text-xs px-3 py-1.5 rounded-lg bg-slate-700/60 border border-slate-600/30 text-slate-300 hover:bg-slate-700 transition-colors">
                  Force Refresh
                </button>
                <button onClick={syncActuals}
                  className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600/30 border border-indigo-500/30 text-indigo-300 hover:bg-indigo-600/50 transition-colors">
                  Sync Actuals
                </button>
              </div>
            </div>

            {/* Impact filter pills */}
            <div className="flex items-center gap-3 mb-4 text-xs text-slate-500">
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-2 h-2 rounded-full bg-rose-500" />High impact
              </span>
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-2 h-2 rounded-full bg-amber-400" />Medium impact
              </span>
              <span className="ml-auto font-mono">{calendarEvs.length} events this week</span>
            </div>

            {calendarEvs.length === 0 ? (
              <div className="glass p-12 text-center text-slate-500">No events loaded.</div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {calendarEvs.map((ev, i) => <CalendarCard key={i} ev={ev} now={now} />)}
              </div>
            )}
          </div>
        )}

        {/* ══ STRENGTH TAB ═════════════════════════════════════════════════ */}
        {tab === 'strength' && (
          <div className="space-y-8">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-bold text-white">Currency Strength</h2>
                <p className="text-xs text-slate-500 mt-0.5">River ARF model · 4 features · live scores</p>
              </div>
              <button onClick={runFullCycle}
                className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600/30 border border-indigo-500/30 text-indigo-300 hover:bg-indigo-600/50 transition-colors">
                Run Full Cycle
              </button>
            </div>

            {/* 8-currency meters */}
            <div className="grid gap-3 grid-cols-2 sm:grid-cols-4">
              {strengths.length === 0
                ? Array.from({ length: 8 }).map((_, i) => (
                    <div key={i} className="glass-sm p-4 animate-pulse h-24" />
                  ))
                : strengths
                    .slice()
                    .sort((a, b) => b.strength_score - a.strength_score)
                    .map(cs => <CurrencyMeter key={cs.currency} cs={cs} />)
              }
            </div>

            {/* Pair bias table */}
            {pairBiases.length > 0 && (
              <div className="glass p-5">
                <h3 className="text-sm font-bold text-white mb-4">Pair Bias Matrix</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-left">
                    <thead>
                      <tr className="text-slate-500 border-b border-slate-800">
                        <th className="py-2 pr-4 font-semibold">Pair</th>
                        <th className="py-2 pr-4 font-semibold">Direction</th>
                        <th className="py-2 pr-4 font-semibold">Bias</th>
                        <th className="py-2 pr-4 font-semibold">Base</th>
                        <th className="py-2 pr-4 font-semibold">Quote</th>
                        <th className="py-2 font-semibold">Confidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pairBiases.slice(0, 20).map(pb => (
                        <tr key={pb.pair} className="border-b border-slate-800/50 hover:bg-white/2">
                          <td className="py-2 pr-4 font-bold text-white">{pb.pair}</td>
                          <td className={`py-2 pr-4 font-semibold ${dirColor(pb.direction)}`}>{pb.direction}</td>
                          <td className={`py-2 pr-4 font-mono ${pb.bias > 0 ? 'text-emerald-400' : pb.bias < 0 ? 'text-rose-400' : 'text-slate-500'}`}>
                            {pb.bias > 0 ? '+' : ''}{(pb.bias * 100).toFixed(1)}
                          </td>
                          <td className="py-2 pr-4 font-mono text-slate-400">{(pb.base_strength * 100).toFixed(1)}</td>
                          <td className="py-2 pr-4 font-mono text-slate-400">{(pb.quote_strength * 100).toFixed(1)}</td>
                          <td className="py-2">
                            <div className="w-24">
                              <ConfidenceBar pct={pb.confidence_pct} />
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Feature drift */}
            {drifts.length > 0 && <FeatureDriftPanel drifts={drifts} />}
          </div>
        )}

        {/* ══ RESULTS TAB ══════════════════════════════════════════════════ */}
        {tab === 'results' && (
          <div className="space-y-6">
            <h2 className="text-lg font-bold text-white">Historical Accuracy</h2>

            {/* KPI bar */}
            {accuracy && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {[
                  { label: 'Total Predictions', val: accuracy.total_predictions },
                  { label: 'Wins',              val: accuracy.wins,              col: 'text-emerald-400' },
                  { label: 'Losses',            val: accuracy.losses,            col: 'text-rose-400' },
                  { label: 'Hit Rate',          val: `${accuracy.overall_hit_rate}%`,
                    col: accuracy.overall_hit_rate >= 60 ? 'text-emerald-400' : 'text-amber-400' },
                ].map(({ label, val, col }) => (
                  <div key={label} className="glass-sm p-4 text-center">
                    <div className={`text-2xl font-bold font-mono mb-0.5 ${col ?? 'text-white'}`}>{val}</div>
                    <div className="text-[10px] text-slate-500 uppercase tracking-widest">{label}</div>
                  </div>
                ))}
              </div>
            )}

            {/* Confidence buckets */}
            {accuracy?.confidence_stats && accuracy.confidence_stats.length > 0 && (
              <div className="glass p-5">
                <h3 className="text-sm font-bold text-white mb-4">Accuracy by Confidence Bucket</h3>
                <div className="space-y-3">
                  {accuracy.confidence_stats.map(b => (
                    <div key={b.bucket} className="flex items-center gap-4">
                      <span className="text-xs text-slate-400 w-16 shrink-0">{b.bucket}</span>
                      <div className="flex-1">
                        <ConfidenceBar pct={b.hit_rate_pct} label={`${b.wins}/${b.total}`} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Currency stats */}
            {accuracy?.currency_stats && accuracy.currency_stats.length > 0 && (
              <div className="glass p-5">
                <h3 className="text-sm font-bold text-white mb-4">Accuracy by Currency</h3>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                  {accuracy.currency_stats.map(c => (
                    <div key={c.currency} className="glass-sm p-3">
                      <div className="flex items-center gap-2 mb-2">
                        <span>{CURRENCY_FLAGS[c.currency]}</span>
                        <span className="text-xs font-bold text-white">{c.currency}</span>
                        <span className={`ml-auto text-xs font-mono font-bold ${c.hit_rate_pct >= 60 ? 'text-emerald-400' : 'text-amber-400'}`}>
                          {c.hit_rate_pct}%
                        </span>
                      </div>
                      <ConfidenceBar pct={c.hit_rate_pct} label={`${c.wins}/${c.total}`} />
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* History table */}
            <div className="glass p-5">
              <h3 className="text-sm font-bold text-white mb-4">Prediction Ledger</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-slate-500 border-b border-slate-800">
                      {['Event', 'CCY', 'Lean', 'Forecast', 'Actual', 'Surprise', 'Conf', 'Result', 'Date'].map(h => (
                        <th key={h} className="py-2 pr-3 text-left font-semibold">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {history.map(h => (
                      <tr key={h.id} className="border-b border-slate-800/50 hover:bg-white/2">
                        <td className="py-2 pr-3 text-slate-300 max-w-28 truncate">{h.display_name}</td>
                        <td className="py-2 pr-3 text-slate-400">{CURRENCY_FLAGS[h.currency ?? 'USD']}{h.currency}</td>
                        <td className={`py-2 pr-3 font-semibold ${dirColor(h.lean_direction)}`}>
                          {h.lean_direction === 'BEAT' ? 'BULL' : h.lean_direction === 'MISS' ? 'BEAR' : 'FLAT'}
                        </td>
                        <td className="py-2 pr-3 font-mono text-slate-400">{fmt(h.forecast, 3)}</td>
                        <td className="py-2 pr-3 font-mono text-cyan-300">{fmt(h.actual, 3)}</td>
                        <td className={`py-2 pr-3 font-mono ${(h.surprise ?? 0) > 0 ? 'text-emerald-400' : (h.surprise ?? 0) < 0 ? 'text-rose-400' : 'text-slate-500'}`}>
                          {h.surprise != null ? `${h.surprise > 0 ? '+' : ''}${h.surprise.toFixed(3)}` : '—'}
                        </td>
                        <td className="py-2 pr-3 font-mono text-slate-400">{h.confidence_pct?.toFixed(0)}%</td>
                        <td className="py-2 pr-3">
                          {h.was_correct
                            ? <span className="text-emerald-400 font-bold">✓</span>
                            : <span className="text-rose-400 font-bold">✗</span>}
                        </td>
                        <td className="py-2 text-slate-600">{h.date ? new Date(h.date).toLocaleDateString() : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {history.length === 0 && (
                  <div className="text-center text-slate-500 py-8">No graded predictions yet.</div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ══ TELEGRAM TAB ═════════════════════════════════════════════════ */}
        {tab === 'telegram' && (
          <div className="space-y-6 max-w-lg">
            <h2 className="text-lg font-bold text-white">Telegram Alerts</h2>

            <div className="glass p-5 space-y-4">
              <h3 className="text-sm font-semibold text-slate-300">Send Single Event Alert</h3>
              <input
                value={tgEventCode}
                onChange={e => setTgEventCode(e.target.value.toUpperCase())}
                placeholder="Event code e.g. NFP, EUR_CPI"
                className="w-full bg-slate-800/60 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500"
              />
              <button onClick={sendTelegram} disabled={!tgEventCode}
                className="w-full py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-sm font-semibold transition-colors">
                Send Alert
              </button>
              {tgStatus && <p className="text-sm text-slate-400">{tgStatus}</p>}
            </div>

            <div className="glass p-5 space-y-3">
              <h3 className="text-sm font-semibold text-slate-300">Bulk Actions</h3>
              <button onClick={broadcastAll}
                className="w-full py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-sm font-semibold transition-colors">
                📢 Broadcast All Predictions
              </button>
              <button onClick={sendTestTelegram}
                className="w-full py-2 rounded-lg glass-sm hover:bg-white/5 text-sm transition-colors text-slate-300">
                🧪 Send Test Message
              </button>
              <button onClick={() => axios.post(`${API}/scheduler/check-now`).then(() => showToast('Scheduler check triggered'))}
                className="w-full py-2 rounded-lg glass-sm hover:bg-white/5 text-sm transition-colors text-slate-300">
                ⚡ Force Scheduler Check
              </button>
            </div>

            <div className="glass p-5">
              <h3 className="text-sm font-semibold text-slate-300 mb-3">Alert Schedule</h3>
              <ul className="space-y-2 text-xs text-slate-400">
                {[
                  ['Every 5 min',  'Pre-release + post-release grading + River learn_one()'],
                  ['06:00 UTC',    'Rate differential refresh (all 8 currencies)'],
                  ['07:00 UTC',    'Full currency strength cycle'],
                  ['00:30/12:30',  'FinBERT sentiment refresh'],
                  ['Friday 16:00', 'CFTC COT positioning update'],
                ].map(([when, what]) => (
                  <li key={when} className="flex gap-3">
                    <span className="text-indigo-400 font-mono w-28 shrink-0">{when}</span>
                    <span>{what}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}

      </main>
    </div>
  )
}
