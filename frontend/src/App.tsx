import './App.css'
import axios from 'axios'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import React from 'react'

const API = '/api'
const LS_KEY = 'macro_currency_filter'
const ALL_CCYS = ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CHF', 'CAD', 'NZD']

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

function buildPairsFromPred(pred: PredSummary): { dir: string; pair: string }[] {
  const signals = pred.trade_signals ?? []
  if (signals.length > 0) {
    return signals
      .filter(s => s && !s.toUpperCase().startsWith('WAIT') && !s.toUpperCase().startsWith('HOLD'))
      .map(formatPairSignal)
      .filter(p => p.dir && p.pair)
  }
  return (pred.pair_signals ?? [])
    .slice(0, 7)
    .map(ps => ({ dir: ps.direction.toUpperCase().includes('BUY') || ps.direction.toUpperCase() === 'BULLISH' ? 'BUY' : 'SELL', pair: ps.pair }))
}

function ls<T>(key: string, fallback: T): T {
  try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback } catch { return fallback }
}
function saveLs(key: string, val: unknown) {
  try { localStorage.setItem(key, JSON.stringify(val)) } catch { /* noop */ }
}

function fmtNum(n: number | null, dp = 3): string {
  return n == null ? '—' : n.toFixed(dp)
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Spinner() {
  return <div className="spinner" role="status" aria-label="Loading" />
}

function CurrencyFilter({ sel, toggle }: { sel: string[]; toggle: (c: string) => void }) {
  return (
    <div className="ccy-filter" role="list" aria-label="Currency filter">
      {ALL_CCYS.map(c => (
        <button
          key={c}
          role="listitem"
          className={`ccy-chip${sel.includes(c) ? ' on' : ''}`}
          onClick={() => toggle(c)}
          aria-pressed={sel.includes(c)}
        >
          {c}
        </button>
      ))}
    </div>
  )
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

function HomePage({ ccySel, now }: { ccySel: string[]; now: number }) {
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

  // Find next upcoming event matching selected currencies
  const nextEvent = useMemo(() => {
    if (events.length === 0) return null
    const nowMs = now

    const filtered = events
      .filter(e => e.release_time_utc && ccySel.includes(e.currency))

    if (filtered.length === 0) return null

    const upcoming = filtered
      .filter(e => new Date(e.release_time_utc).getTime() > nowMs && e.actual === null)
      .sort((a, b) => new Date(a.release_time_utc).getTime() - new Date(b.release_time_utc).getTime())
    if (upcoming.length > 0) return upcoming[0]

    const anyFuture = filtered
      .filter(e => new Date(e.release_time_utc).getTime() > nowMs)
      .sort((a, b) => new Date(a.release_time_utc).getTime() - new Date(b.release_time_utc).getTime())
    if (anyFuture.length > 0) return anyFuture[0]

    const past = filtered
      .sort((a, b) => new Date(b.release_time_utc).getTime() - new Date(a.release_time_utc).getTime())
    return past[0] ?? null
  }, [events, ccySel, now])

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
              <Spinner />
              <span>Prediction loading…</span>
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

function CalendarPage({ ccySel }: { ccySel: string[] }) {
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

  const filtered = useMemo(
    () => events.filter(e => ccySel.includes(e.currency)),
    [events, ccySel]
  )

  // Group into past days, today, and future days
  const { pastGroups, todayGroup, futureGroups } = useMemo(() => {
    const today = new Date()
    const todayUTC = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate())

    const byDate = new Map<number, CalEvent[]>()
    for (const ev of filtered) {
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

    return { pastGroups: past, todayGroup: todayGrp, futureGroups: future }
  }, [filtered])

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

      {!loading && filtered.length === 0 && (
        <div className="empty-state">
          <p>No events match selected currencies.</p>
          <p className="sub">Toggle currencies in the filter bar above.</p>
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

function TrendChart({ ccy, windows, improving }: { ccy: string; windows: AccTrendWindow[]; improving: boolean }) {
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
  const H = 100
  const PAD = { top: 10, right: 10, bottom: 20, left: 30 }
  const chartW = W - PAD.left - PAD.right
  const chartH = H - PAD.top - PAD.bottom

  const vals = windows.map(w => w.hit_rate_pct)
  const minVal = Math.max(0, Math.min(...vals) - 5)
  const maxVal = Math.min(100, Math.max(...vals) + 5)

  const xScale = (i: number) => PAD.left + (i / (windows.length - 1)) * chartW
  const yScale = (v: number) => PAD.top + chartH - ((v - minVal) / (maxVal - minVal)) * chartH

  const points = windows.map((w, i) => `${xScale(i)},${yScale(w.hit_rate_pct)}`).join(' ')

  return (
    <div className="trend-card">
      <div className="trend-card-head">
        <span className="ccy-badge">{ccy}</span>
        {improving && <span className="trend-improving">improving</span>}
      </div>
      <div className="trend-svg-wrap">
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} aria-label={`${ccy} accuracy trend`}>
          {[0, 50, 100].map(v => {
            if (v < minVal || v > maxVal) return null
            const y = yScale(v)
            return (
              <g key={v}>
                <line x1={PAD.left} y1={y} x2={W - PAD.right} y2={y}
                  stroke="rgba(255,255,255,0.05)" strokeWidth={1} />
                <text x={PAD.left - 4} y={y + 4} fontSize={8} fill="rgba(255,255,255,0.3)" textAnchor="end">{v}</text>
              </g>
            )
          })}
          {minVal < 50 && maxVal > 50 && (
            <line x1={PAD.left} y1={yScale(50)} x2={W - PAD.right} y2={yScale(50)}
              stroke="rgba(59,130,246,0.3)" strokeWidth={1} strokeDasharray="4 4" />
          )}
          <polyline
            points={points}
            fill="none"
            stroke="#3b82f6"
            strokeWidth={2}
            strokeLinejoin="round"
          />
          {windows.map((w, i) => (
            <circle
              key={i}
              cx={xScale(i)}
              cy={yScale(w.hit_rate_pct)}
              r={3}
              fill="#3b82f6"
            />
          ))}
        </svg>
      </div>
    </div>
  )
}

function ModelPage({ ccySel }: { ccySel: string[] }) {
  const [models, setModels] = useState<ModelStatus[]>([])
  const [trend, setTrend] = useState<AccTrendCcy[]>([])
  const [accStats, setAccStats] = useState<AccStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      axios.get(`${API}/model-status`),
      axios.get(`${API}/accuracy-trend`),
      axios.get(`${API}/accuracy`),
    ])
      .then(([ms, at, ac]) => {
        setModels(ms.data.currencies ?? [])
        setTrend(at.data.trend ?? [])
        setAccStats(ac.data)
      })
      .catch(() => { /* show empty state */ })
      .finally(() => setLoading(false))
  }, [])

  const filtModels = useMemo(() => models.filter(m => ccySel.includes(m.currency)), [models, ccySel])
  const filtTrend = useMemo(() => trend.filter(t => ccySel.includes(t.currency)), [trend, ccySel])

  if (loading) {
    return (
      <div className="page">
        <div className="loading-center"><Spinner /><span>Loading model data…</span></div>
      </div>
    )
  }

  const calibRows = (accStats?.confidence_stats ?? []).filter(c => c.total > 0)
  const bucketMidpoints: Record<string, number> = {
    '<60%': 55, '60-70%': 65, '70-80%': 75, '>80%': 85,
  }

  return (
    <div className="page">

      <div className="section-title">Learning Status</div>
      {filtModels.length === 0 ? (
        <div className="empty-state"><p>No data for selected currencies.</p></div>
      ) : (
        <div className="model-grid">
          {filtModels.map(m => (
            <div key={m.currency} className="model-card">
              <div className="model-card-head">
                <span className="ccy-badge model-ccy">{m.currency}</span>
                <span className={`status-badge ${m.status}`}>
                  {m.status === 'learning' ? 'Learning' : m.status === 'seeded_only' ? 'Seeded' : 'Untrained'}
                </span>
              </div>
              <div className="model-n">n = {m.n_trained}</div>
              <div className="model-n-sub">
                {m.n_real > 0 ? `${m.n_real} real learn_one() calls` : 'Seed data only (first 10 are seeds)'}
              </div>
              {m.live_accuracy != null && (
                <div className="model-acc">{(m.live_accuracy * 100).toFixed(1)}% accuracy</div>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="section-title">Feature Importance</div>
      {filtModels.length === 0 ? (
        <div className="empty-state"><p>No data.</p></div>
      ) : (
        <div className="features-grid">
          {filtModels.map(m => {
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

      <div className="section-title">Accuracy Trend</div>
      {filtTrend.length === 0 ? (
        <div className="empty-state"><p>No trend data yet.</p></div>
      ) : (
        <div className="trend-charts-grid">
          {filtTrend.map(t => (
            <TrendChart key={t.currency} ccy={t.currency} windows={t.windows} improving={t.improving} />
          ))}
        </div>
      )}

      <div className="section-title">Calibration Check</div>
      {calibRows.length === 0 ? (
        <div className="empty-state"><p>No graded predictions yet.</p></div>
      ) : (
        <div className="calib-card">
          {calibRows.map(row => {
            const expected = bucketMidpoints[row.bucket] ?? 70
            const diverges = Math.abs(row.hit_rate_pct - expected) > 10
            return (
              <div key={row.bucket} className="calib-row">
                <span className="calib-bucket">{row.bucket}</span>
                <div className="calib-bar-outer">
                  <div
                    className={`calib-bar-inner${diverges ? ' flag' : ''}`}
                    style={{ width: `${row.hit_rate_pct}%` }}
                  />
                </div>
                <span className={`calib-pct${diverges ? ' text-bear' : ''}`}>
                  {row.hit_rate_pct.toFixed(0)}%
                </span>
                <span className="calib-expected">exp. ~{expected}%</span>
                {diverges && (
                  <span className="calib-flag-icon" title="Diverges from expected" style={{ color: 'var(--sell)', fontSize: 12 }}>!</span>
                )}
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

function TrackPage({ ccySel }: { ccySel: string[] }) {
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

  const filtered = useMemo(
    () => history.filter(h => ccySel.includes(h.currency)),
    [history, ccySel]
  )

  const ledger = useMemo(() => {
    if (resultFilter === 'wins') return filtered.filter(h => h.was_correct)
    if (resultFilter === 'losses') return filtered.filter(h => !h.was_correct)
    return filtered
  }, [filtered, resultFilter])

  const wins = useMemo(() => filtered.filter(h => h.was_correct).length, [filtered])
  const winRate = filtered.length > 0 ? (wins / filtered.length) * 100 : 0
  const avgConf = filtered.length > 0
    ? filtered.reduce((s, h) => s + h.confidence_pct, 0) / filtered.length
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
          <div className="kpi-value">{filtered.length}</div>
          <div className="kpi-label">Predictions</div>
        </div>
        <div className="kpi-card">
          <div className={`kpi-value ${winRate >= 60 ? 'green' : winRate >= 50 ? 'yellow' : ''}`}>
            {filtered.length > 0 ? `${winRate.toFixed(0)}%` : '—'}
          </div>
          <div className="kpi-label">Win Rate</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-value yellow">
            {filtered.length > 0 ? `${avgConf.toFixed(0)}%` : '—'}
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
          <p>{filtered.length === 0 ? 'No history for selected currencies.' : 'No results match this filter.'}</p>
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

  const [ccySel, setCcySel] = useState<string[]>(() => ls(LS_KEY, ['USD']))

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const toggleCcy = useCallback((c: string) => {
    setCcySel(prev => {
      if (prev.includes(c) && prev.length === 1) return prev
      const next = prev.includes(c) ? prev.filter(x => x !== c) : [...prev, c]
      saveLs(LS_KEY, next)
      return next
    })
  }, [])

  return (
    <div className="app">
      <div className="layout">
        <SideNav page={page} setPage={setPage} />

        <div className="content">
          <CurrencyFilter sel={ccySel} toggle={toggleCcy} />

          <main>
            {page === 'home' && <HomePage ccySel={ccySel} now={now} />}
            {page === 'calendar' && <CalendarPage ccySel={ccySel} />}
            {page === 'model' && <ModelPage ccySel={ccySel} />}
            {page === 'track' && <TrackPage ccySel={ccySel} />}
          </main>
        </div>
      </div>

      <BottomNav page={page} setPage={setPage} />
    </div>
  )
}
