import './App.css'
import axios from 'axios'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import React from 'react'

const API = '/api'

// ── Types ─────────────────────────────────────────────────────────────────────

type Page = 'home' | 'calendar' | 'model' | 'track'

interface CalEvent {
  event_code: string | null
  event_name: string
  display_name?: string
  currency: string
  release_time_utc: string
  forecast: number | null
  previous: number | null
  actual: number | null
  impact: 'HIGH' | 'MEDIUM' | 'LOW'
  is_simultaneous: boolean
  prediction?: PredSummary | null
}

interface PredSummary {
  lean_direction: string
  event_label: string
  confidence_pct: number
  composite_score: number
  trade_signals: string[]
  pair_signals: PairSignal[]
  order_suggestions?: OrderSug[]
  indicators?: Indicator[]
}

interface PairSignal { pair: string; direction: string; bias: number; confidence_pct: number }

interface OrderSug {
  pair: string; bias: string; current_price: number | null
  suggested_entry: number | null; suggested_sl: number | null; suggested_tp: number | null
  confidence_pct: number
}

interface Indicator { description: string; z_score: number | null; signal: number; weight: number }

interface ModelStatus {
  currency: string; n_trained: number; n_real: number
  live_accuracy: number | null
  feature_weights: Record<string, number>
  last_updated: string | null
  status: 'learning' | 'seeded_only' | 'untrained'
}

interface AccTrendWindow {
  window_start: number; window_end: number; predictions: number
  wins: number; hit_rate_pct: number; date_from: string | null; date_to: string | null
}

interface AccTrendCcy {
  currency: string; total_graded: number; windows: AccTrendWindow[]; improving: boolean
}

interface HistItem {
  id: number; event_code: string; display_name: string; currency: string
  lean_direction: string; confidence_pct: number; forecast: number | null
  actual: number | null; surprise: number | null; was_correct: boolean; date: string | null
  is_late?: boolean; weight_shift?: string | null
}

interface AccStats {
  total_predictions: number; wins: number; losses: number; overall_hit_rate: number
  confidence_stats: { bucket: string; total: number; wins: number; hit_rate_pct: number }[]
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const FW_LABELS: Record<string, string> = {
  indicator_score: 'Indicator',
  rate_diff_score: 'Rate Diff',
  cot_score: 'COT',
  sentiment_score: 'Sentiment',
}
const FW_KEYS = ['indicator_score', 'rate_diff_score', 'cot_score', 'sentiment_score']
const FW_COLORS = ['#6366f1', '#06b6d4', '#f59e0b', '#10b981']

function formatCountdown(isoUtc: string, now: number): string {
  const ms = new Date(isoUtc).getTime() - now
  if (ms <= 0) return 'Released'
  const s = Math.floor(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sc = s % 60
  if (h > 48) return `${Math.floor(h / 24)}d ${h % 24}h`
  if (h > 0) return `${h}h ${m}m ${sc}s`
  if (m > 0) return `${m}m ${sc}s`
  return `${sc}s`
}

function formatTime(isoUtc: string): string {
  try {
    return new Date(isoUtc).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }) + ' UTC'
  } catch { return isoUtc }
}

function formatDate(isoUtc: string): string {
  try {
    return new Date(isoUtc).toLocaleDateString('en-GB', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' })
  } catch { return '' }
}

function directionClass(d: string): 'bull' | 'bear' | 'flat' {
  const u = d?.toUpperCase()
  if (u === 'BEAT' || u === 'BULLISH' || u === 'BUY') return 'bull'
  if (u === 'MISS' || u === 'BEARISH' || u === 'SELL') return 'bear'
  return 'flat'
}

function directionLabel(d: string): string {
  const u = d?.toUpperCase()
  if (u === 'BEAT' || u === 'BULLISH') return 'BULLISH'
  if (u === 'MISS' || u === 'BEARISH') return 'BEARISH'
  return 'INLINE'
}

function confBarClass(pct: number): string {
  if (pct >= 70) return 'hi'
  if (pct >= 50) return 'mid'
  return 'lo'
}

function formatPairSignal(raw: string): { dir: string; pair: string } {
  const parts = raw.trim().split(' ')
  const dir = parts[0] ?? ''
  const sym = (parts[1] ?? '').toUpperCase()
  const fmtSym = sym.includes('/')
    ? sym
    : sym.length === 6
      ? `${sym.slice(0, 3)}/${sym.slice(3)}`
      : sym
  return { dir, pair: fmtSym }
}

const USD_MAJORS = ['EUR/USD','GBP/USD','USD/JPY','USD/CHF','AUD/USD','USD/CAD','XAU/USD']

function buildPairsFromPred(pred: PredSummary): { dir: string; pair: string }[] {
  const signals = pred.trade_signals ?? []
  if (signals.length > 0) {
    return signals
      .filter(s => s && !s.toUpperCase().startsWith('WAIT') && !s.toUpperCase().startsWith('HOLD'))
      .map(formatPairSignal)
      .filter(p => p.dir && p.pair && USD_MAJORS.includes(p.pair))
  }
  // Fallback: use pair_signals but only for the 7 USD majors
  return (pred.pair_signals ?? [])
    .filter(ps => USD_MAJORS.includes(ps.pair?.replace('/', '') === ps.pair
      ? `${ps.pair.slice(0,3)}/${ps.pair.slice(3)}` : ps.pair))
    .slice(0, 7)
    .map(ps => ({
      dir: (ps.direction ?? '').toUpperCase().includes('BUY') || (ps.direction ?? '').toUpperCase() === 'BULLISH' ? 'BUY' : 'SELL',
      pair: ps.pair?.length === 6 ? `${ps.pair.slice(0,3)}/${ps.pair.slice(3)}` : ps.pair
    }))
}

function fmtNum(n: number | null, dp = 3): string {
  return n == null ? '—' : n.toFixed(dp)
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Spinner() {
  return <div className="spinner" role="status" aria-label="Loading" />
}

function ConfBar({ pct, cls }: { pct: number; cls?: string }) {
  const barClass = cls ?? confBarClass(pct)
  return (
    <div className="home-conf-bar-outer" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <div
        className={`home-conf-bar-inner ${barClass}`}
        style={{ width: `${Math.min(pct, 100)}%` }}
      />
    </div>
  )
}

function CalConfBar({ pct, cls }: { pct: number; cls?: string }) {
  const barClass = cls ?? confBarClass(pct)
  return (
    <div className="cal-conf-bar-outer" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <div
        className={`cal-conf-bar-inner ${barClass}`}
        style={{ width: `${Math.min(pct, 100)}%` }}
      />
    </div>
  )
}

// ── Navigation components ─────────────────────────────────────────────────────

const NAV_ITEMS: { page: Page; icon: React.ReactNode; label: string }[] = [
  {
    page: 'home',
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>
        <polyline points="9 22 9 12 15 12 15 22"/>
      </svg>
    ),
    label: 'Home',
  },
  {
    page: 'calendar',
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
        <line x1="16" y1="2" x2="16" y2="6"/>
        <line x1="8" y1="2" x2="8" y2="6"/>
        <line x1="3" y1="10" x2="21" y2="10"/>
      </svg>
    ),
    label: 'Calendar',
  },
  {
    page: 'model',
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <line x1="18" y1="20" x2="18" y2="10"/>
        <line x1="12" y1="20" x2="12" y2="4"/>
        <line x1="6" y1="20" x2="6" y2="14"/>
      </svg>
    ),
    label: 'Model',
  },
  {
    page: 'track',
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
        <polyline points="10 9 9 9 8 9"/>
      </svg>
    ),
    label: 'Records',
  },
]

function SideNav({ page, setPage }: { page: Page; setPage: (p: Page) => void }) {
  return (
    <nav className="side-rail" aria-label="Main navigation">
      <div className="rail-logo">
        <img src="/logo.png" alt="Titanfxsage" style={{ width: 28, height: 28, objectFit: 'contain' }} />
        Titanfxsage
      </div>
      <div className="rail-nav">
        {NAV_ITEMS.map(item => (
          <button
            key={item.page}
            className={`rail-item${page === item.page ? ' active' : ''}`}
            onClick={() => setPage(item.page)}
            aria-current={page === item.page ? 'page' : undefined}
          >
            <span className="rail-icon">{item.icon}</span>
            {item.label}
          </button>
        ))}
      </div>
    </nav>
  )
}

function BottomNav({ page, setPage }: { page: Page; setPage: (p: Page) => void }) {
  return (
    <nav className="bottom-nav" aria-label="Main navigation">
      {NAV_ITEMS.map(item => (
        <button
          key={item.page}
          className={`bn-item${page === item.page ? ' active' : ''}`}
          onClick={() => setPage(item.page)}
          aria-current={page === item.page ? 'page' : undefined}
        >
          <span className="bn-icon">{item.icon}</span>
          {item.label}
        </button>
      ))}
    </nav>
  )
}

// ── ImpactDot ─────────────────────────────────────────────────────────────────

function ImpactDot({ impact }: { impact: string }) {
  const cls = impact === 'HIGH' ? 'high' : impact === 'MEDIUM' ? 'medium' : 'low'
  return <span className={`impact-dot impact-dot-${cls}`} aria-label={impact} />
}

// ══════════════════════════════════════════════════════════════════════════════
// HOME PAGE
// ══════════════════════════════════════════════════════════════════════════════

function HomePage({ now }: { now: number }) {
  const [events, setEvents] = useState<CalEvent[]>([])
  const [loading, setLoading] = useState(true)
  const warmupFired = useRef(false)

  useEffect(() => {
    setLoading(true)
    axios.get(`${API}/events`)
      .then(r => setEvents(r.data.events ?? []))
      .catch(() => setEvents([]))
      .finally(() => setLoading(false))
  }, [])

  // Fire warmup + full cycle once after events load
  useEffect(() => {
    if (events.length > 0 && !warmupFired.current) {
      warmupFired.current = true
      axios.post(`${API}/predictions/warmup`).catch(() => { /* fire and forget */ })
      axios.post(`${API}/run-full-cycle`).catch(() => { /* fire and forget */ })
      const timer = setTimeout(() => {
        axios.get(`${API}/events`)
          .then(r => setEvents(r.data.events ?? []))
          .catch(() => { /* noop */ })
      }, 15000)
      return () => clearTimeout(timer)
    }
  }, [events.length])

  // Auto-refresh events every 60 seconds
  useEffect(() => {
    const id = setInterval(() => {
      axios.get(`${API}/events`)
        .then(r => setEvents(r.data.events ?? []))
        .catch(() => {})
    }, 60000)
    return () => clearInterval(id)
  }, [])

  // Find next upcoming event (all events are USD)
  const nextEvent = useMemo(() => {
    if (events.length === 0) return null
    const nowMs = now

    const upcoming = events
      .filter(e => e.release_time_utc && new Date(e.release_time_utc).getTime() > nowMs && e.actual === null)
      .sort((a, b) => new Date(a.release_time_utc).getTime() - new Date(b.release_time_utc).getTime())
    if (upcoming.length > 0) return upcoming[0]

    const anyFuture = events
      .filter(e => e.release_time_utc && new Date(e.release_time_utc).getTime() > nowMs)
      .sort((a, b) => new Date(a.release_time_utc).getTime() - new Date(b.release_time_utc).getTime())
    if (anyFuture.length > 0) return anyFuture[0]

    const past = events
      .filter(e => e.release_time_utc)
      .sort((a, b) => new Date(b.release_time_utc).getTime() - new Date(a.release_time_utc).getTime())
    return past[0] ?? null
  }, [events, now])

  if (loading) {
    return (
      <div className="page">
        <div className="loading-center"><Spinner /><span>Loading events…</span></div>
      </div>
    )
  }

  if (!nextEvent) {
    return (
      <div className="page">
        <div className="home-no-event">
          <span style={{ fontSize: 32, color: 'var(--text-dim)' }}>—</span>
          <span>No events found</span>
          <span style={{ fontSize: 13, color: 'var(--text-dim)' }}>Try selecting a different currency or wait for the calendar to refresh</span>
        </div>
      </div>
    )
  }

  const pred = nextEvent.prediction
  const released = nextEvent.actual !== null || new Date(nextEvent.release_time_utc).getTime() <= now
  const countdown = formatCountdown(nextEvent.release_time_utc, now)
  const eventName = nextEvent.display_name ?? nextEvent.event_name
  const pairs = pred ? buildPairsFromPred(pred) : []

  const topEntry = pred?.order_suggestions?.find(s => s.suggested_entry != null)

  return (
    <div className="page">
      <div className="home-card">
        {/* Header — FIX 7: impact badge added, FIX 2: no FLAG emoji */}
        <div className="home-header">
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="home-event-name">{eventName}</div>
            <div style={{ marginTop: 4 }}>
              <span className={`impact-badge impact-${(nextEvent.impact ?? 'medium').toLowerCase()}`}>
                {nextEvent.impact ?? 'MEDIUM'}
              </span>
            </div>
          </div>
          <div className="home-ccy-chip">
            <span>{nextEvent.currency}</span>
          </div>
        </div>

        {/* Forecast / Previous */}
        <div className="home-meta">
          {nextEvent.forecast != null && (
            <div className="home-meta-item">
              <span className="home-meta-label">Forecast</span>
              <span className="home-meta-value">{nextEvent.forecast}</span>
            </div>
          )}
          {nextEvent.previous != null && (
            <div className="home-meta-item">
              <span className="home-meta-label">Previous</span>
              <span className="home-meta-value">{nextEvent.previous}</span>
            </div>
          )}
          {nextEvent.actual != null && (
            <div className="home-meta-item">
              <span className="home-meta-label">Actual</span>
              <span className="home-meta-value text-bull">{nextEvent.actual}</span>
            </div>
          )}
        </div>

        {/* Countdown row — FIX 1: unchanged, already working */}
        <div className="home-countdown-row">
          <span className="home-countdown-label">Release</span>
          <span className="home-countdown-time">{formatTime(nextEvent.release_time_utc)}</span>
          <span className={`home-countdown-value${released ? ' released' : ''}`}>{countdown}</span>
        </div>

        {/* Direction + Confidence — FIX 2: no directionEmoji */}
        {pred ? (
          <div className="home-direction">
            <div className={`home-dir-label ${directionClass(pred.lean_direction)}`}>
              <span className={`badge badge-${directionClass(pred.lean_direction) === 'bull' ? 'buy' : directionClass(pred.lean_direction) === 'bear' ? 'sell' : 'hold'}`}>
                {directionLabel(pred.lean_direction)}
              </span>
              <span style={{ marginLeft: 8, fontSize: 16, color: 'var(--text)' }}>{nextEvent.currency}</span>
            </div>
            {pred.event_label && pred.event_label !== pred.lean_direction && (
              <div className="home-dir-sub">{pred.event_label}</div>
            )}
            <div className="home-conf-wrap">
              <ConfBar pct={pred.confidence_pct} />
              <div className="home-conf-label">{pred.confidence_pct.toFixed(0)}% confidence</div>
            </div>
          </div>
        ) : (
          <div className="home-direction">
            <div className="home-no-pred">
              <span style={{ color: 'var(--text-dim)', fontSize: 13 }}>Pre-release signal not yet generated</span>
              <span style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 4 }}>Will appear when indicators are fetched before release</span>
            </div>
          </div>
        )}

        {/* Affected pairs */}
        {pairs.length > 0 && (
          <div className="home-pairs">
            <div className="home-pairs-title">Affected majors</div>
            <div className="home-pairs-list">
              {pairs.map((p, i) => (
                <div key={i} className={`home-pair-row ${p.dir.toUpperCase() === 'BUY' ? 'bull' : 'bear'}`}>
                  <span className="home-pair-dir">{p.dir}</span>
                  <span className="home-pair-name">{p.pair}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Suggested entry */}
        <div className="home-entry">
          <div className="home-entry-label">Suggested entry</div>
          <div className="home-entry-value">
            {topEntry?.suggested_entry != null
              ? fmtNum(topEntry.suggested_entry, 5)
              : '— await release'}
          </div>
        </div>
        <div className="home-disclaimer">Reference only — not financial advice</div>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// CALENDAR PAGE — FIX 5 (Forex Factory layout) + FIX 6 (auto-refresh)
// ══════════════════════════════════════════════════════════════════════════════

function CalendarEventRow({ ev, isExpanded, onToggle }: {
  ev: CalEvent; isExpanded: boolean; onToggle: () => void
}) {
  const pred = ev.prediction
  const released = ev.actual !== null
  const [showIndicators, setShowIndicators] = useState(false)

  const pairs = pred ? buildPairsFromPred(pred) : []
  const indicators = pred?.indicators ?? []

  const timeStr = (() => {
    try {
      return new Date(ev.release_time_utc).toLocaleTimeString('en-GB', {
        hour: '2-digit', minute: '2-digit', timeZone: 'UTC'
      })
    } catch { return '' }
  })()

  const actualColor = (() => {
    if (ev.actual == null || ev.forecast == null) return 'var(--text)'
    if (ev.actual > ev.forecast) return 'var(--buy)'
    if (ev.actual < ev.forecast) return 'var(--sell)'
    return 'var(--text-dim)'
  })()

  return (
    <div
      className="cal2-row"
      onClick={onToggle}
      role="button"
      aria-expanded={isExpanded}
      tabIndex={0}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') onToggle() }}
    >
      <div className="cal2-row-main">
        <span className="cal2-time" style={{ opacity: released ? 0.45 : 1 }}>{timeStr}</span>
        <span className="ccy-badge" style={{ opacity: released ? 0.45 : 1 }}>{ev.currency}</span>
        <span className="cal2-name" style={{ opacity: released ? 0.45 : 1 }}>{ev.display_name ?? ev.event_name}</span>
        <span style={{ opacity: released ? 0.45 : 1 }}><ImpactDot impact={ev.impact} /></span>
        <span className="cal2-num" style={{ opacity: released ? 0.45 : 1 }}>{ev.forecast != null ? ev.forecast : '—'}</span>
        <span className="cal2-num" style={{ opacity: released ? 0.45 : 1 }}>{ev.previous != null ? ev.previous : '—'}</span>
        <span className="cal2-actual" style={{ color: ev.actual != null ? actualColor : 'var(--text-dim)' }}>
          {ev.actual != null ? ev.actual : '—'}
        </span>
      </div>

      {isExpanded && pred && (
        <div className="cal-detail" onClick={e => e.stopPropagation()}>
          <div className="cal-pred-label">Prediction</div>
          <div className={`cal-dir ${directionClass(pred.lean_direction)}`}>
            <span className={`badge badge-${directionClass(pred.lean_direction) === 'bull' ? 'buy' : directionClass(pred.lean_direction) === 'bear' ? 'sell' : 'hold'}`}>
              {directionLabel(pred.lean_direction)}
            </span>
            <span style={{ marginLeft: 8, fontSize: 14, color: 'var(--text)' }}>{ev.currency}</span>
          </div>
          <CalConfBar pct={pred.confidence_pct} />
          <div className="cal-conf-label">{pred.confidence_pct.toFixed(0)}% confidence</div>

          {pairs.length > 0 && (
            <div className="cal-pairs-list">
              {pairs.map((p, i) => (
                <div key={i} className={`cal-pair-row ${p.dir.toUpperCase() === 'BUY' ? 'bull' : 'bear'}`}>
                  <span style={{ fontSize: 11, opacity: 0.8, minWidth: 32 }}>{p.dir}</span>
                  <span style={{ fontWeight: 700, fontSize: 14 }}>{p.pair}</span>
                </div>
              ))}
            </div>
          )}

          {indicators.length > 0 && (
            <>
              <button
                className="cal-indicators-toggle"
                onClick={e => { e.stopPropagation(); setShowIndicators(v => !v) }}
                aria-expanded={showIndicators}
              >
                {showIndicators ? 'Hide indicators ▲' : 'Show indicators ▼'}
              </button>
              {showIndicators && (
                <div className="cal-indicators-list">
                  {indicators.map((ind, i) => (
                    <div key={i} className="cal-ind-row">
                      <span className={`cal-ind-dot ${ind.signal > 0 ? 'bull' : ind.signal < 0 ? 'bear' : 'flat'}`}>
                        {ind.signal > 0 ? '▲' : ind.signal < 0 ? '▼' : '●'}
                      </span>
                      <span className="cal-ind-desc">{ind.description}</span>
                      <span className="cal-ind-z">{ind.z_score != null ? ind.z_score.toFixed(2) : '—'}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {isExpanded && !pred && (
        <div className="cal-detail" onClick={e => e.stopPropagation()}>
          <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>No prediction available</div>
        </div>
      )}
    </div>
  )
}

function CalendarPage() {
  const [events, setEvents] = useState<CalEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [pastExpanded, setPastExpanded] = useState(false)

  const load = useCallback(async () => {
    try { const r = await axios.get(`${API}/events`); setEvents(r.data.events ?? []) }
    catch { setEvents([]) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  // Auto-refresh every 60 seconds
  useEffect(() => {
    const id = setInterval(() => { load() }, 60000)
    return () => clearInterval(id)
  }, [load])

  // Group into past days, today, and future days (all events are USD)
  const { pastGroups, todayGroup, futureGroups } = useMemo(() => {
    const today = new Date()
    const todayUTC = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate())

    const byDate = new Map<number, CalEvent[]>()
    for (const ev of events) {
      const d = new Date(ev.release_time_utc)
      const dUTC = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate())
      if (!byDate.has(dUTC)) byDate.set(dUTC, [])
      byDate.get(dUTC)!.push(ev)
    }

    const dateLabel = (dUTC: number): string => {
      const diff = (dUTC - todayUTC) / 86400000
      if (diff === 0) return 'Today'
      if (diff === 1) return 'Tomorrow'
      const d = new Date(dUTC)
      return d.toLocaleDateString('en-GB', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' })
    }

    const past: { label: string; dUTC: number; events: CalEvent[] }[] = []
    let todayGrp: { label: string; dUTC: number; events: CalEvent[] } | null = null
    const future: { label: string; dUTC: number; events: CalEvent[] }[] = []

    const sortedDates = [...byDate.keys()].sort((a, b) => a - b)
    for (const dUTC of sortedDates) {
      const evs = (byDate.get(dUTC) ?? []).sort(
        (a, b) => new Date(a.release_time_utc).getTime() - new Date(b.release_time_utc).getTime()
      )
      const grp = { label: dateLabel(dUTC), dUTC, events: evs }
      if (dUTC < todayUTC) past.push(grp)
      else if (dUTC === todayUTC) todayGrp = grp
      else future.push(grp)
    }

    // If calendar is stale (no today/future events), promote the most recent
    // past day into "todayGroup" and the rest into future so they show by default
    if (!todayGrp && future.length === 0 && past.length > 0) {
      const mostRecent = past[past.length - 1]
      todayGrp = { ...mostRecent, label: mostRecent.label + ' · most recent' }
      const remaining = past.slice(0, -1)
      // Show all days from stale cache — promote them all to future so they're visible
      return { pastGroups: [], todayGroup: todayGrp, futureGroups: remaining.reverse() }
    }

    return { pastGroups: past, todayGroup: todayGrp, futureGroups: future }
  }, [events])

  const toggleRow = useCallback((id: string) => {
    setExpandedId(prev => prev === id ? null : id)
  }, [])

  const renderGroup = (grp: { label: string; dUTC: number; events: CalEvent[] }, isPast: boolean) => (
    <div key={grp.dUTC} className="cal2-group">
      <div className="cal2-group-header">
        <span>{grp.label}</span>
        {isPast && <span className="cal2-group-meta">{grp.events.length} events</span>}
      </div>
      <div className="cal2-table">
        <div className="cal2-table-head">
          <span className="cal2-time" style={{ color: 'var(--text-dim)', fontSize: 11 }}>Time</span>
          <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>CCY</span>
          <span className="cal2-name" style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Event</span>
          <span />
          <span className="cal2-num" style={{ color: 'var(--text-dim)', fontSize: 11 }}>Fcst</span>
          <span className="cal2-num" style={{ color: 'var(--text-dim)', fontSize: 11 }}>Prev</span>
          <span className="cal2-actual" style={{ color: 'var(--text-dim)', fontSize: 11 }}>Actual</span>
        </div>
        {grp.events.map((ev, i) => {
          const rowId = ev.event_code ?? `${ev.currency}-${grp.dUTC}-${i}`
          return (
            <CalendarEventRow
              key={rowId}
              ev={ev}
              isExpanded={expandedId === rowId}
              onToggle={() => toggleRow(rowId)}
            />
          )
        })}
      </div>
    </div>
  )

  const totalPast = pastGroups.reduce((s, g) => s + g.events.length, 0)

  return (
    <div className="page">
      {loading && (
        <div className="loading-center"><Spinner /><span>Loading calendar…</span></div>
      )}

      {!loading && events.length === 0 && (
        <div className="empty-state">
          <p>No events found.</p>
          <p className="sub">Calendar will refresh automatically.</p>
        </div>
      )}

      {!loading && totalPast > 0 && (
        <div className="cal2-past-toggle">
          <button className="cal-sync-btn" onClick={() => setPastExpanded(v => !v)}>
            {pastExpanded ? `▲ Hide ${totalPast} past event${totalPast !== 1 ? 's' : ''}` : `▼ Show ${totalPast} past event${totalPast !== 1 ? 's' : ''}`}
          </button>
        </div>
      )}

      {!loading && pastExpanded && pastGroups.map(g => renderGroup(g, true))}

      {!loading && todayGroup && renderGroup(todayGroup, false)}

      {!loading && futureGroups.map(g => renderGroup(g, false))}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// MODEL PROGRESS PAGE
// ══════════════════════════════════════════════════════════════════════════════

// Calibration row type (matches /api/calibration array response)
interface CalibRow {
  bucket: string
  stated_midpoint: number
  actual_win_rate: number
  count: number
  flagged: boolean
}

function TrendChart({ ccy, windows, improving }: { ccy: string; windows: AccTrendWindow[]; improving: boolean }) {
  const ccyColor = '#3b82f6'  // USD blue

  if (windows.length < 2) {
    return (
      <div className="trend-card">
        <div className="trend-card-head">
          <span className="ccy-badge">{ccy}</span>
        </div>
        <div className="trend-no-data">Not enough data yet</div>
      </div>
    )
  }

  const W = 300
  const H = 120
  const PAD = { top: 14, right: 14, bottom: 24, left: 34 }
  const chartW = W - PAD.left - PAD.right
  const chartH = H - PAD.top - PAD.bottom

  const xScale = (i: number) => PAD.left + (i / Math.max(windows.length - 1, 1)) * chartW
  const yScale = (v: number) => PAD.top + chartH - (v / 100) * chartH

  const points = windows.map((w, i) => `${xScale(i)},${yScale(w.hit_rate_pct)}`).join(' ')

  const firstDate = windows[0]?.date_from ? new Date(windows[0].date_from).toLocaleDateString('en-GB', { month: 'short', day: 'numeric', timeZone: 'UTC' }) : ''
  const lastDate = windows[windows.length - 1]?.date_to ? new Date(windows[windows.length - 1].date_to!).toLocaleDateString('en-GB', { month: 'short', day: 'numeric', timeZone: 'UTC' }) : ''

  return (
    <div className="trend-card">
      <div className="trend-card-head">
        <span className="ccy-badge">{ccy}</span>
        {improving && <span className="trend-improving">improving</span>}
      </div>
      <div className="trend-svg-wrap">
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={120} aria-label={`${ccy} accuracy trend`}>
          {/* Y-axis grid lines at 0 and 100 */}
          {([0, 100] as number[]).map(v => (
            <g key={v}>
              <line x1={PAD.left} y1={yScale(v)} x2={W - PAD.right} y2={yScale(v)}
                stroke="rgba(255,255,255,0.06)" strokeWidth={1} />
              <text x={PAD.left - 4} y={yScale(v) + 4} fontSize={8} fill="rgba(255,255,255,0.3)" textAnchor="end">{v}</text>
            </g>
          ))}
          {/* Baseline at 50% (dashed accent) */}
          <line x1={PAD.left} y1={yScale(50)} x2={W - PAD.right} y2={yScale(50)}
            stroke="rgba(59,130,246,0.35)" strokeWidth={1} strokeDasharray="4 3" />
          <text x={PAD.left - 4} y={yScale(50) + 4} fontSize={8} fill="rgba(59,130,246,0.5)" textAnchor="end">50</text>
          {/* X tick labels */}
          {firstDate && (
            <text x={PAD.left} y={H - 4} fontSize={8} fill="rgba(255,255,255,0.3)" textAnchor="start">{firstDate}</text>
          )}
          {lastDate && windows.length > 1 && (
            <text x={W - PAD.right} y={H - 4} fontSize={8} fill="rgba(255,255,255,0.3)" textAnchor="end">{lastDate}</text>
          )}
          {/* Polyline */}
          <polyline
            points={points}
            fill="none"
            stroke={ccyColor}
            strokeWidth={2}
            strokeLinejoin="round"
          />
          {/* Dots */}
          {windows.map((w, i) => (
            <circle
              key={i}
              cx={xScale(i)}
              cy={yScale(w.hit_rate_pct)}
              r={3}
              fill={ccyColor}
            />
          ))}
        </svg>
      </div>
    </div>
  )
}

function ModelPage() {
  const [models,   setModels]   = useState<ModelStatus[]>([])
  const [trend,    setTrend]    = useState<AccTrendCcy[]>([])
  const [mistakes, setMistakes] = useState<HistItem[]>([])
  const [calibration, setCalib] = useState<CalibRow[]>([])
  const [loading,  setLoading]  = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      axios.get(`${API}/model-status`),
      axios.get(`${API}/accuracy-trend`),
      axios.get(`${API}/history?limit=60`),
      axios.get(`${API}/calibration`),
    ])
      .then(([ms, at, hist, calib]) => {
        setModels(ms.data.currencies ?? [])
        setTrend(at.data.trend ?? [])
        // filter wrong predictions only
        const allHist: HistItem[] = hist.data.history ?? []
        setMistakes(allHist.filter(h => h.was_correct === false))
        setCalib(Array.isArray(calib.data) ? calib.data : [])
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="page">
        <div className="loading-center"><Spinner /><span>Loading model data…</span></div>
      </div>
    )
  }

  return (
    <div className="page">

      {/* ── SECTION 1: Accuracy Trend ──────────────────────────────────── */}
      <div className="section-title">1 · Accuracy Trend</div>
      {trend.filter(t => t.currency !== 'ALL').length === 0 ? (
        <div className="empty-state"><p>No trend data available yet.</p></div>
      ) : (
        <div className="trend-charts-grid">
          {trend.filter(t => t.currency !== 'ALL').map(t => (
            <TrendChart key={t.currency} ccy={t.currency} windows={t.windows} improving={t.improving} />
          ))}
        </div>
      )}

      {/* ── SECTION 2: n_trained per currency ─────────────────────────── */}
      <div className="section-title">2 · Training Progress</div>
      {models.length === 0 ? (
        <div className="empty-state"><p>No model data available.</p></div>
      ) : (
        <div className="model-grid">
          {models.map(m => (
            <div key={m.currency} className="model-card">
              <div className="model-card-head">
                <span className="ccy-badge model-ccy">{m.currency}</span>
                <span className={`status-badge ${m.status}`}>
                  {m.status === 'learning' ? 'Learning' : m.status === 'seeded_only' ? 'Seeded' : 'Untrained'}
                </span>
              </div>
              <div className="model-n">n = {m.n_trained}</div>
              <div className="model-n-sub">
                {m.n_real > 0 ? `${m.n_real} real outcomes` : 'Seed data only'}
              </div>
              {m.live_accuracy != null && (
                <div className="model-acc">{(m.live_accuracy * 100).toFixed(1)}% accuracy</div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── SECTION 3: Mistake Log ────────────────────────────────────── */}
      <div className="section-title">3 · Mistake Log</div>
      {mistakes.length === 0 ? (
        <div className="empty-state"><p>No wrong predictions recorded yet.</p></div>
      ) : (
        <div className="mistake-list">
          {mistakes.map(h => {
            const date = h.date ? new Date(h.date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'
            const surprise = h.surprise != null
              ? (h.surprise > 0 ? `+${h.surprise}` : `${h.surprise}`)
              : '—'
            const outcome = h.actual != null && h.forecast != null
              ? (h.actual > h.forecast ? 'BEAT' : h.actual < h.forecast ? 'MISS' : 'INLINE')
              : '—'
            return (
              <div key={h.id} className="mistake-row">
                <div className="mistake-header">
                  <span className="mistake-name">{h.display_name}</span>
                  <span className="mistake-date">{date}</span>
                </div>
                <div className="mistake-body">
                  <div className="mistake-field">
                    <span className="mistake-label">Predicted</span>
                    <span className="badge badge-sell">{h.lean_direction}</span>
                    <span className="mistake-conf">{h.confidence_pct.toFixed(0)}% conf</span>
                  </div>
                  <div className="mistake-field">
                    <span className="mistake-label">Actual outcome</span>
                    <span className={outcome === 'BEAT' ? 'text-bull' : 'text-bear'}>{outcome}</span>
                    <span className="mistake-nums">fcst {h.forecast ?? '—'} / actual {h.actual ?? '—'} (surprise {surprise})</span>
                  </div>
                  <div className="mistake-field">
                    <span className="mistake-label">Weight shift</span>
                    <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
                      {h.weight_shift ?? 'Equal priors retained (n<5) · Dynamic drift active at n=5'}
                    </span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* ── SECTION 4: Feature Importance ────────────────────────────── */}
      <div className="section-title">4 · Feature Importance</div>
      {models.length === 0 ? (
        <div className="empty-state"><p>No data.</p></div>
      ) : (
        <div className="features-grid">
          {models.map(m => {
            const weights = m.feature_weights ?? {}
            return (
              <div key={m.currency} className="fw-card">
                <div className="fw-card-head">
                  <span className="ccy-badge">{m.currency}</span>
                </div>
                {FW_KEYS.map((k, i) => {
                  const w = weights[k] ?? 0
                  return (
                    <div key={k} className="fw-row">
                      <span className="fw-label">{FW_LABELS[k]}</span>
                      <div className="fw-bar-outer">
                        <div
                          className="fw-bar-inner"
                          style={{ width: `${Math.min(w * 100, 100)}%`, background: FW_COLORS[i] }}
                        />
                      </div>
                      <span className="fw-pct">{(w * 100).toFixed(0)}%</span>
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>
      )}

      {/* ── SECTION 5: Calibration Check ─────────────────────────────── */}
      <div className="section-title">5 · Calibration Check</div>
      {calibration.length === 0 ? (
        <div className="empty-state"><p>No graded predictions yet.</p></div>
      ) : (
        <div className="calib-card">
          <div className="calib-table-head">
            <span>Bucket</span>
            <span>Stated</span>
            <span>Actual win rate</span>
            <span>Count</span>
            <span>Flag</span>
          </div>
          {calibration.map(row => {
            const winPct = (row.actual_win_rate * 100).toFixed(1)
            const diverge = row.flagged
            return (
              <div key={row.bucket} className={`calib-row${diverge ? ' calib-flagged' : ''}`}>
                <span className="calib-bucket">{row.bucket}</span>
                <span className="calib-expected">~{row.stated_midpoint}%</span>
                <span className={`calib-pct ${row.actual_win_rate * 100 >= row.stated_midpoint ? 'text-bull' : 'text-bear'}`}>
                  {winPct}%
                </span>
                <span style={{ color: 'var(--text-dim)', fontSize: 13 }}>{row.count}</span>
                <span className="calib-flag">
                  {diverge
                    ? <span className="flag-warn">!</span>
                    : row.count < 10
                      ? <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>min 10</span>
                      : <span style={{ color: 'var(--text-dim)' }}>—</span>
                  }
                </span>
              </div>
            )
          })}
        </div>
      )}

    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TRACK RECORD PAGE
// ══════════════════════════════════════════════════════════════════════════════

type ResultFilter = 'all' | 'wins' | 'losses'

function TrackPage() {
  const [history, setHistory] = useState<HistItem[]>([])
  const [accStats, setAccStats] = useState<AccStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [resultFilter, setResultFilter] = useState<ResultFilter>('all')

  useEffect(() => {
    setLoading(true)
    Promise.all([
      axios.get(`${API}/history?limit=60`),
      axios.get(`${API}/accuracy`),
    ])
      .then(([h, a]) => {
        setHistory(h.data.history ?? [])
        setAccStats(a.data)
      })
      .catch(() => { /* show empty state */ })
      .finally(() => setLoading(false))
  }, [])

  const ledger = useMemo(() => {
    if (resultFilter === 'wins') return history.filter(h => h.was_correct)
    if (resultFilter === 'losses') return history.filter(h => !h.was_correct)
    return history
  }, [history, resultFilter])

  const wins = useMemo(() => history.filter(h => h.was_correct).length, [history])
  const winRate = history.length > 0 ? (wins / history.length) * 100 : 0
  const avgConf = history.length > 0
    ? history.reduce((s, h) => s + h.confidence_pct, 0) / history.length
    : 0

  if (loading) {
    return (
      <div className="page">
        <div className="loading-center"><Spinner /><span>Loading track record…</span></div>
      </div>
    )
  }

  return (
    <div className="page">

      <div className="kpi-row">
        <div className="kpi-card">
          <div className="kpi-value">{history.length}</div>
          <div className="kpi-label">Predictions</div>
        </div>
        <div className="kpi-card">
          <div className={`kpi-value ${winRate >= 60 ? 'green' : winRate >= 50 ? 'yellow' : ''}`}>
            {history.length > 0 ? `${winRate.toFixed(0)}%` : '—'}
          </div>
          <div className="kpi-label">Win Rate</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-value yellow">
            {history.length > 0 ? `${avgConf.toFixed(0)}%` : '—'}
          </div>
          <div className="kpi-label">Avg Confidence</div>
        </div>
      </div>

      {accStats && accStats.confidence_stats.filter(c => c.total > 0).length > 0 && (
        <>
          <div className="section-title">Accuracy by Confidence</div>
          <div className="bucket-list">
            {accStats.confidence_stats.filter(c => c.total > 0).map(c => (
              <div key={c.bucket} className="bucket-row">
                <span className="bucket-label">{c.bucket}</span>
                <span className="bucket-count">{c.total} calls</span>
                <div className="bucket-bar-outer">
                  <div className="bucket-bar-inner" style={{ width: `${c.hit_rate_pct}%` }} />
                </div>
                <span className="bucket-pct">{c.hit_rate_pct.toFixed(0)}%</span>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="result-filter" role="group" aria-label="Filter results">
        {(['all', 'wins', 'losses'] as ResultFilter[]).map(f => (
          <button
            key={f}
            className={`result-filter-btn${resultFilter === f ? ' active' : ''}`}
            onClick={() => setResultFilter(f)}
            aria-pressed={resultFilter === f}
          >
            {f === 'all' ? 'All' : f === 'wins' ? 'Wins' : 'Losses'}
          </button>
        ))}
      </div>

      {ledger.length === 0 ? (
        <div className="empty-state">
          <p>{history.length === 0 ? 'No history recorded yet.' : 'No results match this filter.'}</p>
        </div>
      ) : (
        <div className="ledger-wrap">
          <table className="ledger-table">
            <thead>
              <tr>
                <th>Event</th>
                <th>CCY</th>
                <th>Direction</th>
                <th>Conf</th>
                <th>Result</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {ledger.map(item => (
                <tr key={item.id}>
                  <td className="ledger-event" title={item.display_name}>{item.display_name}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>{item.currency}</td>
                  <td className={`ledger-dir ${directionClass(item.lean_direction)}`}>
                    {directionLabel(item.lean_direction)}
                  </td>
                  <td className="ledger-conf">{item.confidence_pct.toFixed(0)}%</td>
                  <td className="ledger-result">
                    {item.was_correct
                      ? <span className="badge badge-buy">W</span>
                      : <span className="badge badge-sell">L</span>
                    }
                  </td>
                  <td className="ledger-date">{item.date ? formatDate(item.date) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// APP ROOT
// ══════════════════════════════════════════════════════════════════════════════

export default function App() {
  const [page, setPage] = useState<Page>('home')
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="app">
      <div className="layout">
        <SideNav page={page} setPage={setPage} />

        <div className="content">
          <main>
            {page === 'home' && <HomePage now={now} />}
            {page === 'calendar' && <CalendarPage />}
            {page === 'model' && <ModelPage />}
            {page === 'track' && <TrackPage />}
          </main>
        </div>
      </div>

      <BottomNav page={page} setPage={setPage} />
    </div>
  )
}
