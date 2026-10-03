import './App.css'
import axios from 'axios'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

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
  impact: 'HIGH' | 'MEDIUM'
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

const FLAG: Record<string, string> = {
  USD: '🇺🇸', EUR: '🇪🇺', GBP: '🇬🇧', JPY: '🇯🇵',
  AUD: '🇦🇺', CHF: '🇨🇭', CAD: '🇨🇦', NZD: '🇳🇿',
}

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

function groupDateLabel(isoUtc: string): string {
  const d = new Date(isoUtc)
  const today = new Date()
  const todayUTC = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate())
  const eventUTC = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate())
  const diff = (eventUTC - todayUTC) / 86400000
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Tomorrow'
  return formatDate(isoUtc)
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

function directionEmoji(d: string, ccy: string): string {
  const u = d?.toUpperCase()
  if (u === 'BEAT' || u === 'BULLISH') return `🟢 BUY ${ccy}`
  if (u === 'MISS' || u === 'BEARISH') return `🔴 SELL ${ccy}`
  return `🟡 HOLD ${ccy}`
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
  // Fallback: top pair_signals
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
          {FLAG[c]} {c}
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

const NAV_ITEMS: { page: Page; icon: string; label: string }[] = [
  { page: 'home', icon: '🏠', label: 'Home' },
  { page: 'calendar', icon: '📅', label: 'Calendar' },
  { page: 'model', icon: '📈', label: 'Model' },
  { page: 'track', icon: '📋', label: 'Records' },
]

function SideNav({ page, setPage }: { page: Page; setPage: (p: Page) => void }) {
  return (
    <nav className="side-rail" aria-label="Main navigation">
      <div className="rail-logo">
        <span className="rail-dot" />
        MacroPredictor
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
      // Re-fetch events after warmup delay to pick up predictions
      const timer = setTimeout(() => {
        axios.get(`${API}/events`)
          .then(r => setEvents(r.data.events ?? []))
          .catch(() => { /* noop */ })
      }, 15000)
      return () => clearTimeout(timer)
    }
  }, [events.length])

  // Find next upcoming event matching selected currencies
  const nextEvent = useMemo(() => {
    if (events.length === 0) return null
    const nowMs = now
    const upcoming = events
      .filter(e => e.release_time_utc && e.actual === null)
      .filter(e => ccySel.includes(e.currency))
      .sort((a, b) => new Date(a.release_time_utc).getTime() - new Date(b.release_time_utc).getTime())

    if (upcoming.length > 0) return upcoming[0]

    // Fallback: nearest past within 1h
    const recent = events
      .filter(e => ccySel.includes(e.currency))
      .filter(e => {
        const ms = new Date(e.release_time_utc).getTime()
        return nowMs - ms < 3600000 && nowMs - ms >= 0
      })
      .sort((a, b) => new Date(b.release_time_utc).getTime() - new Date(a.release_time_utc).getTime())

    return recent[0] ?? null
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
          <span style={{ fontSize: 32 }}>📭</span>
          <span>No events in the next 24h</span>
          <span style={{ fontSize: 13, color: 'var(--text-dim)' }}>Check back later or broaden your currency filter</span>
        </div>
      </div>
    )
  }

  const pred = nextEvent.prediction
  const released = nextEvent.actual !== null || new Date(nextEvent.release_time_utc).getTime() <= now
  const countdown = formatCountdown(nextEvent.release_time_utc, now)
  const eventName = nextEvent.display_name ?? nextEvent.event_name
  const pairs = pred ? buildPairsFromPred(pred) : []

  // Top suggested entry
  const topEntry = pred?.order_suggestions?.find(s => s.suggested_entry != null)

  return (
    <div className="page">
      <div className="home-card">
        {/* Header */}
        <div className="home-header">
          <div className="home-event-name">{eventName}</div>
          <div className="home-ccy-chip">
            <span>{FLAG[nextEvent.currency] ?? ''}</span>
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

        {/* Countdown row */}
        <div className="home-countdown-row">
          <span className="home-countdown-label">Release</span>
          <span className="home-countdown-time">{formatTime(nextEvent.release_time_utc)}</span>
          <span className={`home-countdown-value${released ? ' released' : ''}`}>{countdown}</span>
        </div>

        {/* Direction + Confidence */}
        {pred ? (
          <div className="home-direction">
            <div className={`home-dir-label ${directionClass(pred.lean_direction)}`}>
              {directionEmoji(pred.lean_direction, nextEvent.currency)}
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
// CALENDAR PAGE
// ══════════════════════════════════════════════════════════════════════════════

function CalendarEventRow({ ev, now }: { ev: CalEvent; now: number }) {
  const [open, setOpen] = useState(false)
  const [showIndicators, setShowIndicators] = useState(false)
  const pred = ev.prediction
  const released = ev.actual !== null

  const pairs = pred ? buildPairsFromPred(pred) : []
  const indicators = pred?.indicators ?? []

  return (
    <div className="cal-row" onClick={() => setOpen(v => !v)} role="button" aria-expanded={open}>
      <div className="cal-row-top">
        <span className={`cal-impact-dot ${ev.impact === 'HIGH' ? 'high' : 'med'}`} aria-hidden="true" />
        <span style={{ fontSize: 16 }}>{FLAG[ev.currency] ?? ''}</span>
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', flexShrink: 0 }}>{ev.currency}</span>
        <span className="cal-row-name">{ev.display_name ?? ev.event_name}</span>
        <span className="cal-row-time">{formatTime(ev.release_time_utc)}</span>
        {released
          ? <span className="cal-row-released">Released</span>
          : <span className="cal-row-cd">{formatCountdown(ev.release_time_utc, now)}</span>
        }
      </div>

      <div className="cal-row-data" onClick={e => e.stopPropagation()}>
        {ev.forecast != null && (
          <div className="cal-data-item">
            <span className="cal-data-label">Forecast</span>
            <span className="cal-data-value">{ev.forecast}</span>
          </div>
        )}
        {ev.previous != null && (
          <div className="cal-data-item">
            <span className="cal-data-label">Previous</span>
            <span className="cal-data-value">{ev.previous}</span>
          </div>
        )}
        {ev.actual != null && (
          <div className="cal-data-item">
            <span className="cal-data-label">Actual</span>
            <span className="cal-data-value actual-val">{ev.actual}</span>
          </div>
        )}
      </div>

      {open && pred && (
        <div className="cal-detail" onClick={e => e.stopPropagation()}>
          <div className="cal-pred-label">Prediction</div>
          <div className={`cal-dir ${directionClass(pred.lean_direction)}`}>
            {directionEmoji(pred.lean_direction, ev.currency)}
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
                onClick={() => setShowIndicators(v => !v)}
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

      {open && !pred && (
        <div className="cal-detail" onClick={e => e.stopPropagation()}>
          <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>No prediction available</div>
        </div>
      )}
    </div>
  )
}

function CalendarPage({ ccySel, now }: { ccySel: string[]; now: number }) {
  const [events, setEvents] = useState<CalEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  const flash = (msg: string) => { setToast(msg); setTimeout(() => setToast(null), 3000) }

  const load = useCallback(async () => {
    setLoading(true)
    try { const r = await axios.get(`${API}/events`); setEvents(r.data.events ?? []) }
    catch { setEvents([]) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const syncActuals = async () => {
    setSyncing(true)
    try {
      const r = await axios.post(`${API}/events/sync-actuals`)
      flash(`${r.data.newly_graded ?? 0} event(s) graded`)
      load()
    } catch { flash('Sync failed') }
    finally { setSyncing(false) }
  }

  const filtered = useMemo(
    () => events.filter(e => ccySel.includes(e.currency)),
    [events, ccySel]
  )

  // Group by date label, preserving chronological order of groups
  const groups = useMemo(() => {
    const map = new Map<string, { label: string; ts: number; events: CalEvent[] }>()
    for (const ev of filtered) {
      const label = groupDateLabel(ev.release_time_utc)
      const ts = new Date(ev.release_time_utc).getTime()
      if (!map.has(label)) map.set(label, { label, ts, events: [] })
      map.get(label)!.events.push(ev)
    }
    return [...map.values()].sort((a, b) => a.ts - b.ts)
  }, [filtered])

  return (
    <div className="page">
      {toast && <div className="toast">{toast}</div>}

      <div className="cal-toolbar">
        <button className="cal-sync-btn" onClick={syncActuals} disabled={syncing}>
          {syncing ? <Spinner /> : '🔄'} Sync Actuals
        </button>
        <button className="cal-sync-btn" onClick={load} disabled={loading}>
          {loading ? <Spinner /> : '↻'} Refresh
        </button>
      </div>

      {loading && (
        <div className="loading-center"><Spinner /><span>Loading calendar…</span></div>
      )}

      {!loading && filtered.length === 0 && (
        <div className="empty-state">
          <p>No events match selected currencies.</p>
          <p className="sub">Toggle currencies in the filter bar above.</p>
        </div>
      )}

      {!loading && groups.map(g => (
        <div key={g.label} className="cal-group">
          <div className="cal-group-header">{g.label}</div>
          {g.events.map((ev, i) => (
            <CalendarEventRow key={ev.event_code ?? `${ev.currency}-${i}`} ev={ev} now={now} />
          ))}
        </div>
      ))}
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
          <span>{FLAG[ccy] ?? ''}</span>
          <span>{ccy}</span>
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
        <span>{FLAG[ccy] ?? ''}</span>
        <span>{ccy}</span>
        {improving && <span className="trend-improving">↑ improving</span>}
      </div>
      <div className="trend-svg-wrap">
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} aria-label={`${ccy} accuracy trend`}>
          {/* Grid lines */}
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
          {/* 50% reference */}
          {minVal < 50 && maxVal > 50 && (
            <line x1={PAD.left} y1={yScale(50)} x2={W - PAD.right} y2={yScale(50)}
              stroke="rgba(99,102,241,0.3)" strokeWidth={1} strokeDasharray="4 4" />
          )}
          {/* Line */}
          <polyline
            points={points}
            fill="none"
            stroke="#6366f1"
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
              fill="#6366f1"
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

  // Calibration: compute from accStats
  const calibRows = (accStats?.confidence_stats ?? []).filter(c => c.total > 0)
  const bucketMidpoints: Record<string, number> = {
    '<60%': 55, '60-70%': 65, '70-80%': 75, '>80%': 85,
  }

  return (
    <div className="page">

      {/* Section 1: Learning Status */}
      <div className="section-title">Learning Status</div>
      {filtModels.length === 0 ? (
        <div className="empty-state"><p>No data for selected currencies.</p></div>
      ) : (
        <div className="model-grid">
          {filtModels.map(m => (
            <div key={m.currency} className="model-card">
              <div className="model-card-head">
                <span className="model-flag">{FLAG[m.currency] ?? ''}</span>
                <span className="model-ccy">{m.currency}</span>
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

      {/* Section 2: Feature Importance */}
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
                  <span>{FLAG[m.currency] ?? ''}</span>
                  <span>{m.currency}</span>
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

      {/* Section 3: Accuracy Trend */}
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

      {/* Section 4: Calibration Check */}
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
                {diverges && <span className="calib-flag-icon" title="Diverges from expected">⚠️</span>}
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

      {/* KPI row */}
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

      {/* Confidence bucket accuracy */}
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

      {/* Result filter */}
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

      {/* Ledger */}
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
                  <td style={{ whiteSpace: 'nowrap' }}>{FLAG[item.currency] ?? ''} {item.currency}</td>
                  <td className={`ledger-dir ${directionClass(item.lean_direction)}`}>
                    {directionLabel(item.lean_direction)}
                  </td>
                  <td className="ledger-conf">{item.confidence_pct.toFixed(0)}%</td>
                  <td className="ledger-result">{item.was_correct ? '✅' : '❌'}</td>
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

  // Persisted currency filter — default USD on first load
  const [ccySel, setCcySel] = useState<string[]>(() => ls(LS_KEY, ['USD']))

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const toggleCcy = useCallback((c: string) => {
    setCcySel(prev => {
      // Must keep at least one selected
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
            {page === 'calendar' && <CalendarPage ccySel={ccySel} now={now} />}
            {page === 'model' && <ModelPage ccySel={ccySel} />}
            {page === 'track' && <TrackPage ccySel={ccySel} />}
          </main>
        </div>
      </div>

      <BottomNav page={page} setPage={setPage} />
    </div>
  )
}
