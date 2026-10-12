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
  gold_forecast?: GoldForecast | null
}

interface PredSummary {
  lean_direction: string
  event_label: string
  explanation?: string
  confidence_pct: number
  composite_score: number
  indicators?: Indicator[]
  gold_forecast?: GoldForecast | null
}

interface GoldFeatureInput {
  value: number | null
  source: string
  observed_at: string | null
  published_at: string | null
  captured_at: string
  available_at?: string | null
  staleness_status?: string
  revision_status?: string
  status: string
}

interface GoldForecast {
  release_moment_id?: string
  release_time_utc?: string
  forecast_cutoff_utc?: string | null
  status: string
  confidence_status?: string
  direction: 'BULLISH' | 'BEARISH' | 'NEUTRAL' | null
  predicted_direction?: 'BULLISH' | 'BEARISH' | 'NEUTRAL' | null
  probabilities: { bullish: number; bearish: number; neutral: number } | null
  p_bullish?: number | null
  p_bearish?: number | null
  p_neutral?: number | null
  expected_return_5m?: number | null
  expected_move_pct: number | null
  horizon_minutes: number
  n_trained: number
  threshold_pct: number | null
  event_family: string
  missing_features?: string[]
  feature_provenance?: Record<string, GoldFeatureInput>
  feature_coverage?: { available: number; total: number; inputs: Record<string, GoldFeatureInput> }
  validation_note: string
  out_of_sample_performance?: {
    overall: { n: number; accuracy_pct: number | null; brier_score: number | null }
    by_event_family: Record<string, { n: number; accuracy_pct: number | null; brier_score: number | null }>
  }
  outcome?: {
    label: string | null
    gold_price_at_release: number | null
    change_1m_pct: number | null
    change_5m_pct: number | null
    change_15m_pct: number | null
    change_30m_pct: number | null
    max_up_5m_pct: number | null
    max_down_5m_pct: number | null
    max_favorable_5m_pct: number | null
    max_adverse_5m_pct: number | null
    threshold_pct: number | null
    data_quality?: {
      source?: string
      price_type?: string
      status?: string
      missing_targets?: string[]
    }
    actual_releases: { event_code: string; forecast: number | null; previous: number | null; previous_revised: number | null; actual: number | null }[]
  } | null
}

interface Indicator {
  description: string
  latest_value?: number | null
  prev_value?: number | null
  z_score: number | null
  signal: number
  weight: number
}

interface ModelStatus {
  currency: string; n_trained: number; n_real: number
  live_accuracy: number | null
  feature_weights: Record<string, number>
  last_updated: string | null
  status: 'learning' | 'seeded_only' | 'untrained'
}

interface GoldModelStatus {
  model: string
  model_version: string
  horizon_minutes: number
  status: string
  n_forecasts: number
  n_trained: number
  n_outcomes: number
  training_class_counts: Record<string, number>
  probabilities_available: boolean
  expected_return_5m_status: string
}

interface DataQualityStatus {
  gold: {
    forecast_count: number
    outcome_count: number
    forecasts_without_outcomes: number
    unavailable_outcomes: number
    limitations: string[]
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const FW_LABELS: Record<string, string> = {
  indicator_score: 'Economic indicators',
  rate_diff_score: 'Interest-rate gap',
  cot_score: 'Market positioning',
  sentiment_score: 'Market sentiment',
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

function confBarClass(pct: number): string {
  if (pct >= 70) return 'hi'
  if (pct >= 50) return 'mid'
  return 'lo'
}

function indicatorAlignment(pred: PredSummary) {
  const active = (pred.indicators ?? []).filter(ind => ind.signal !== 0)
  const aligned = active.filter(ind =>
    (pred.lean_direction === 'BEAT' && ind.signal > 0) ||
    (pred.lean_direction === 'MISS' && ind.signal < 0)
  )
  const activeWeight = active.reduce((sum, ind) => sum + ind.weight, 0)
  const alignedWeight = aligned.reduce((sum, ind) => sum + ind.weight, 0)
  return {
    active: active.length,
    aligned: aligned.length,
    weightedPercent: activeWeight > 0 ? Math.round((alignedWeight / activeWeight) * 100) : null,
  }
}

function IndicatorEvidence({ prediction }: { prediction: PredSummary }) {
  const [expanded, setExpanded] = useState(false)
  const indicators = prediction.indicators ?? []
  const alignment = indicatorAlignment(prediction)
  const leanText = prediction.lean_direction === 'BEAT'
    ? 'above consensus'
    : prediction.lean_direction === 'MISS'
      ? 'below consensus'
      : 'inline with consensus'

  if (indicators.length === 0) return null

  return (
    <section className="evidence-card">
      <div className="insight-section-heading">Why this release lean?</div>
      <p className="evidence-summary">
        {alignment.aligned} of {alignment.active} active leading-indicator signals support a result {leanText}
        {alignment.weightedPercent != null ? ` (${alignment.weightedPercent}% of active weight)` : ''}.
      </p>
      {prediction.explanation && <p className="evidence-interpretation">{prediction.explanation}</p>}
      <button
        className="evidence-toggle"
        onClick={() => setExpanded(value => !value)}
        aria-expanded={expanded}
      >
        {expanded ? 'Hide indicator evidence' : `View ${indicators.length} indicator inputs`}
      </button>
      {expanded && (
        <div className="evidence-list">
          {indicators.map((indicator, index) => (
            <div className="evidence-row" key={`${indicator.description}-${index}`}>
              <span className={`evidence-signal ${indicator.signal > 0 ? 'bull' : indicator.signal < 0 ? 'bear' : 'flat'}`}>
                {indicator.signal > 0 ? 'Supports beat' : indicator.signal < 0 ? 'Supports miss' : 'Neutral'}
              </span>
              <div className="evidence-main">
                <strong>{indicator.description}</strong>
                <span>
                  Latest {indicator.latest_value ?? '—'}
                  {indicator.prev_value != null ? ` · previous ${indicator.prev_value}` : ''}
                  {indicator.z_score != null ? ` · 6-month z-score ${indicator.z_score.toFixed(2)}` : ''}
                </span>
              </div>
              <span className="evidence-weight">{(indicator.weight * 100).toFixed(0)}% weight</span>
            </div>
          ))}
        </div>
      )}
      <p className="evidence-disclaimer">
        These are economic indicator inputs, not a live-news research summary. A positive lean is not a guarantee of the release or market reaction.
      </p>
    </section>
  )
}

function GoldOutlook({ forecast }: { forecast?: GoldForecast | null }) {
  const [showEvidence, setShowEvidence] = useState(false)
  if (!forecast) return null
  const inputs = Object.entries(forecast.feature_coverage?.inputs ?? {})
  const familyPerformance = forecast.out_of_sample_performance?.by_event_family[forecast.event_family]
  const label = (key: string) => key
    .replace(/^consensus_/, 'Consensus · ')
    .replace(/^gold_/, 'Gold · ')
    .replace(/^stored_/, '')
    .replaceAll('_', ' ')

  return (
    <section className="gold-outlook">
      <div className="insight-section-heading">Gold reaction forecast · XAU/USD</div>
      <p className="insight-section-copy">
        Separate from the USD economic-number lean. {forecast.event_family.toUpperCase()} ·
        {' '}primary horizon: {forecast.horizon_minutes} minutes after release.
      </p>
      <p className="gold-feature-count">
        Forecast cutoff: {forecast.forecast_cutoff_utc ?? 'not recorded'}
        {' · '}status: {(forecast.confidence_status ?? forecast.status).replaceAll('_', ' ')}
      </p>
      {forecast.probabilities ? (
        <>
          <div className={`gold-direction ${forecast.direction?.toLowerCase() ?? 'neutral'}`}>
            {forecast.direction ?? 'NO DIRECTION'}
          </div>
          <div className="gold-probabilities">
            {(['bullish', 'bearish', 'neutral'] as const).map(outcome => (
              <div key={outcome}>
                <span>{outcome}</span>
                <strong>{(forecast.probabilities![outcome] * 100).toFixed(1)}%</strong>
              </div>
            ))}
          </div>
          <div className="gold-outcome-meta">
            <span>Expected return: {forecast.expected_return_5m == null ? 'not validated' : `${forecast.expected_return_5m.toFixed(3)}%`}</span>
            <span>Training moments: {forecast.n_trained}</span>
          </div>
        </>
      ) : (
        <div className="gold-warmup">
          <strong>Learning from gold reactions</strong>
          <span>{forecast.n_trained} eligible historical release moments; probabilities are withheld until the training minimum is met.</span>
        </div>
      )}
      {forecast.outcome && (
        <div className="gold-realized">
          <strong>Observed gold reaction</strong>
          {forecast.outcome.label ? (
            <span>Outcome: {forecast.outcome.label.toLowerCase()} · threshold {forecast.outcome.threshold_pct?.toFixed(3)}%</span>
          ) : (
            <span>
              {forecast.outcome.data_quality?.status === 'unavailable'
                ? 'Outcome unavailable: required gold candles were not available.'
                : 'Price recorded; a valid prior-move threshold is not available yet.'}
            </span>
          )}
          <div className="gold-realized-horizons">
            {[
              ['1m', forecast.outcome.change_1m_pct],
              ['5m', forecast.outcome.change_5m_pct],
              ['15m', forecast.outcome.change_15m_pct],
              ['30m', forecast.outcome.change_30m_pct],
            ].map(([horizon, value]) => (
              <div key={horizon}>
                <span>{horizon}</span>
                <b>{typeof value === 'number' ? `${value.toFixed(3)}%` : '—'}</b>
              </div>
            ))}
          </div>
          <small>
            Five-minute range: up {forecast.outcome.max_up_5m_pct?.toFixed(3) ?? '—'}% · down {forecast.outcome.max_down_5m_pct?.toFixed(3) ?? '—'}%
            {forecast.outcome.max_favorable_5m_pct != null && forecast.outcome.max_adverse_5m_pct != null
              ? ` · favorable ${forecast.outcome.max_favorable_5m_pct.toFixed(3)}% · adverse ${forecast.outcome.max_adverse_5m_pct.toFixed(3)}%`
              : ''}
          </small>
          {forecast.outcome.data_quality?.source && (
            <small>
              Price source: {forecast.outcome.data_quality.source}
              {forecast.outcome.data_quality.price_type ? ` · ${forecast.outcome.data_quality.price_type}` : ''}
              {forecast.outcome.data_quality.status ? ` · ${forecast.outcome.data_quality.status.replaceAll('_', ' ')}` : ''}
            </small>
          )}
          {forecast.outcome.actual_releases.length > 0 && (
            <small>
              First-seen release values: {forecast.outcome.actual_releases
                .map(release => `${release.event_code} ${release.actual ?? '—'} (forecast ${release.forecast ?? '—'})`)
                .join(' · ')}
            </small>
          )}
        </div>
      )}
      <p className="gold-validation-note">{forecast.validation_note}</p>
      {familyPerformance && familyPerformance.n > 0 ? (
        <p className="gold-validation-note">
          {forecast.event_family.toUpperCase()} out-of-sample: {familyPerformance.n} releases
          {' · '}{familyPerformance.accuracy_pct?.toFixed(1)}% direction accuracy
          {' · Brier '}{familyPerformance.brier_score?.toFixed(3)}
        </p>
      ) : (
        <p className="gold-validation-note">
          No completed out-of-sample evaluation is available for this event type yet.
        </p>
      )}
      {forecast.feature_coverage && (
        <>
          <p className="gold-feature-count">
            {forecast.feature_coverage.available} of {forecast.feature_coverage.total} captured inputs available
            {forecast.missing_features && forecast.missing_features.length > 0
              ? ` · ${forecast.missing_features.length} missing or stale`
              : ''}
          </p>
          <button
            className="evidence-toggle"
            onClick={() => setShowEvidence(value => !value)}
            aria-expanded={showEvidence}
          >
            {showEvidence ? 'Hide gold evidence and data status' : 'View gold evidence and data status'}
          </button>
          {showEvidence && (
            <div className="gold-input-list">
              {inputs.map(([key, item]) => (
                <div className="gold-input-row" key={key}>
                  <strong>{label(key)}</strong>
                  <span>{item.value == null ? 'Unavailable' : item.value.toFixed(4)}</span>
                  <small>{item.source} · {item.status.replaceAll('_', ' ')}</small>
                  <small>
                    Observed: {item.observed_at ?? 'not supplied'}
                    {' · Published: '}{item.published_at ?? 'not supplied'}
                  </small>
                  <small>
                    Available: {item.available_at ?? item.captured_at}
                    {' · Revision: '}{(item.revision_status ?? 'unknown').replaceAll('_', ' ')}
                    {' · Freshness: '}{(item.staleness_status ?? 'unknown').replaceAll('_', ' ')}
                  </small>
                </div>
              ))}
            </div>
          )}
        </>
      )}
      <p className="evidence-disclaimer">
        Stored values are never replaced with current values during training. Missing or stale inputs remain explicitly unavailable.
      </p>
    </section>
  )
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
    label: 'Insights',
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
    label: 'History',
  },
]

function SideNav({ page, setPage }: { page: Page; setPage: (p: Page) => void }) {
  return (
    <nav className="side-rail" aria-label="Main navigation">
      <div className="rail-logo">
        <img src="/logo.png" alt="" style={{ width: 34, height: 34, objectFit: 'contain' }} />
        <span className="rail-brand-copy">
          <strong>TitanFX Sage</strong>
          <small>MACRO INSIGHTS</small>
        </span>
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

function HomePage({ now, onOpenCalendar }: { now: number; onOpenCalendar: () => void }) {
  const [events, setEvents] = useState<CalEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const warmupFired = useRef(false)

  const loadEvents = useCallback(async (showLoading = false) => {
    if (showLoading) setLoading(true)
    try {
      const response = await axios.get(`${API}/events`)
      setEvents(response.data.events ?? [])
      setLoadError(false)
    } catch {
      setLoadError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadEvents(true)
  }, [loadEvents])

  // Start cached predictions once after the event calendar loads
  useEffect(() => {
    if (events.length > 0 && !warmupFired.current) {
      warmupFired.current = true
      axios.post(`${API}/predictions/warmup`).catch(() => { /* fire and forget */ })
      const timer = setTimeout(() => { void loadEvents() }, 15000)
      return () => clearTimeout(timer)
    }
  }, [events.length, loadEvents])

  // Auto-refresh events every 60 seconds
  useEffect(() => {
    const id = setInterval(() => { void loadEvents() }, 60000)
    return () => clearInterval(id)
  }, [loadEvents])

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
          <span className="empty-state-icon" aria-hidden="true">◷</span>
          <h2>{loadError ? 'Calendar unavailable right now' : 'No upcoming releases'}</h2>
          <p>
            {loadError
              ? 'We couldn’t reach the calendar. Please try again in a moment.'
              : 'The economic calendar refreshes automatically. Check the full calendar for recent updates.'}
          </p>
          {loadError
            ? <button className="primary-action" onClick={() => void loadEvents(true)}>Try again</button>
            : <button className="primary-action" onClick={onOpenCalendar}>View calendar</button>}
        </div>
      </div>
    )
  }

  const pred = nextEvent.prediction
  const released = nextEvent.actual !== null || new Date(nextEvent.release_time_utc).getTime() <= now
  const countdown = formatCountdown(nextEvent.release_time_utc, now)
  const eventName = nextEvent.display_name ?? nextEvent.event_name

  return (
    <div className="page">
      <div className="home-card">
        <div className="home-card-kicker">NEXT U.S. RELEASE</div>
        <div className="home-header">
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="home-event-name">{eventName}</div>
            <div style={{ marginTop: 4 }}>
              <span className={`impact-badge impact-${(nextEvent.impact ?? 'medium').toLowerCase()}`}>
                {nextEvent.impact ?? 'MEDIUM'}
              </span>
            </div>
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
              <span className="home-meta-value">{nextEvent.actual}</span>
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
                {pred.lean_direction}
              </span>
              <span style={{ marginLeft: 8, fontSize: 16, color: 'var(--text)' }}>release lean</span>
            </div>
            {pred.event_label && pred.event_label !== pred.lean_direction && (
              <div className="home-dir-sub">{pred.event_label}</div>
            )}
            <div className="home-conf-wrap">
              <ConfBar pct={pred.confidence_pct} />
              <div className="home-conf-label">{pred.confidence_pct.toFixed(0)}% heuristic score · not a probability</div>
            </div>
            <p className="confidence-explainer">
              This rule-based score is capped at 85%. A score of 85 does not mean an 85% chance of being right.
            </p>
          </div>
        ) : (
          <div className="home-direction">
            <div className="home-no-pred">
              <span style={{ color: 'var(--text-dim)', fontSize: 13 }}>Pre-release signal not yet generated</span>
              <span style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 4 }}>Will appear when indicators are fetched before release</span>
            </div>
          </div>
        )}

        {pred && <IndicatorEvidence prediction={pred} />}
        <GoldOutlook forecast={pred?.gold_forecast ?? nextEvent.gold_forecast} />
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

  const timeStr = (() => {
    try {
      return new Date(ev.release_time_utc).toLocaleTimeString('en-GB', {
        hour: '2-digit', minute: '2-digit', timeZone: 'UTC'
      })
    } catch { return '' }
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
        <span className="cal2-name" style={{ opacity: released ? 0.45 : 1 }}>{ev.display_name ?? ev.event_name}</span>
        <span style={{ opacity: released ? 0.45 : 1 }}><ImpactDot impact={ev.impact} /></span>
        <span className="cal2-num" style={{ opacity: released ? 0.45 : 1 }}>{ev.forecast != null ? ev.forecast : '—'}</span>
        <span className="cal2-num" style={{ opacity: released ? 0.45 : 1 }}>{ev.previous != null ? ev.previous : '—'}</span>
        <span className="cal2-actual" style={{ color: ev.actual != null ? 'var(--text)' : 'var(--text-dim)' }}>
          {ev.actual != null ? ev.actual : '—'}
        </span>
      </div>

      {isExpanded && pred && (
        <div className="cal-detail" onClick={e => e.stopPropagation()}>
          <div className="cal-pred-label">Prediction</div>
          <div className={`cal-dir ${directionClass(pred.lean_direction)}`}>
            <span className={`badge badge-${directionClass(pred.lean_direction) === 'bull' ? 'buy' : directionClass(pred.lean_direction) === 'bear' ? 'sell' : 'hold'}`}>
            {pred.lean_direction}
            </span>
            <span style={{ marginLeft: 8, fontSize: 14, color: 'var(--text)' }}>release lean</span>
          </div>
          <CalConfBar pct={pred.confidence_pct} />
          <div className="cal-conf-label">{pred.confidence_pct.toFixed(0)}% heuristic score · not a probability</div>
          <p className="confidence-explainer">
            The rule-based indicator-alignment score is capped at 85%; this is not an 85% chance of being correct.
          </p>
          <IndicatorEvidence prediction={pred} />
          <GoldOutlook forecast={ev.gold_forecast ?? pred.gold_forecast} />
        </div>
      )}

      {isExpanded && !pred && (
        <div className="cal-detail" onClick={e => e.stopPropagation()}>
          <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>No prediction available</div>
          <GoldOutlook forecast={ev.gold_forecast} />
        </div>
      )}
    </div>
  )
}

function CalendarPage() {
  const [events, setEvents] = useState<CalEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [pastExpanded, setPastExpanded] = useState(false)

  const load = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/events`)
      setEvents(response.data.events ?? [])
      setLoadError(false)
    } catch {
      setLoadError(true)
    }
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
          <span className="cal2-time" style={{ color: 'var(--text-dim)', fontSize: 11 }}>UTC</span>
          <span className="cal2-name" style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Event</span>
          <span />
          <span className="cal2-num" style={{ color: 'var(--text-dim)', fontSize: 11 }}>Forecast</span>
          <span className="cal2-num" style={{ color: 'var(--text-dim)', fontSize: 11 }}>Previous</span>
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
          <h2>{loadError ? 'Calendar unavailable right now' : 'No upcoming releases'}</h2>
          <p>{loadError
            ? 'We couldn’t load the calendar. Please try again in a moment.'
            : 'New releases will appear here as soon as they are available.'}</p>
          {loadError && <button className="primary-action" onClick={() => { setLoading(true); void load() }}>Try again</button>}
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

function ModelPage() {
  const [models,   setModels]   = useState<ModelStatus[]>([])
  const [goldStatus, setGoldStatus] = useState<GoldModelStatus | null>(null)
  const [dataQuality, setDataQuality] = useState<DataQualityStatus | null>(null)
  const [loading,  setLoading]  = useState(true)
  const [loadError, setLoadError] = useState(false)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      axios.get(`${API}/model-status`),
      axios.get(`${API}/gold/model-status`),
      axios.get(`${API}/data-quality`),
    ])
      .then(([ms, gold, quality]) => {
        setModels((ms.data.currencies ?? []).filter((model: ModelStatus) => model.currency === 'USD'))
        setGoldStatus(gold.data)
        setDataQuality(quality.data)
        setLoadError(false)
      })
      .catch(() => setLoadError(true))
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

      <div className="section-title">XAU/USD reaction model</div>
      {loadError && <div className="empty-state"><p>Some model details could not be loaded. Please refresh to try again.</p></div>}
      {goldStatus && (
        <div className="model-card gold-model-status">
          <div className="model-card-head">
            <strong>{goldStatus.model}</strong>
            <span className={`status-badge ${goldStatus.status}`}>
              {goldStatus.status === 'provisional' ? 'Provisional' : 'Warming up'}
            </span>
          </div>
          <div className="model-n">{goldStatus.n_trained} eligible training moments</div>
          <div className="model-n-sub">
            {goldStatus.n_outcomes} recorded outcomes · {goldStatus.horizon_minutes}-minute primary horizon · {goldStatus.model_version}
          </div>
          <div className="gold-outcome-meta">
            {Object.entries(goldStatus.training_class_counts).map(([label, count]) => (
              <span key={label}>{label.toLowerCase()}: {count}</span>
            ))}
          </div>
          <p className="gold-validation-note">
            {goldStatus.probabilities_available
              ? 'Probabilities are available but remain provisional until validated out of sample.'
              : 'Probabilities are withheld until the training sample contains enough release moments from each class.'}
            {' '}Expected return: {goldStatus.expected_return_5m_status.replaceAll('_', ' ')}.
          </p>
        </div>
      )}
      {dataQuality && (
        <div className="model-card">
          <div className="model-card-head"><strong>Gold price data quality</strong></div>
          <div className="model-n-sub">
            {dataQuality.gold.outcome_count}/{dataQuality.gold.forecast_count} forecasts have recorded outcomes;
          {' '}{dataQuality.gold.unavailable_outcomes} outcome fetches are marked unavailable.
          </div>
          {dataQuality.gold.limitations.map(item => <p key={item}>{item}</p>)}
        </div>
      )}

      <div className="section-title">USD economic release model</div>
      <p className="gold-validation-note">
        This model estimates whether a U.S. release will beat or miss consensus. It does not forecast gold direction.
      </p>
      {models.length === 0 ? (
        <div className="empty-state"><p>USD release-model status is not available yet.</p></div>
      ) : (
        <div className="model-grid">
          {models.map(m => (
            <div key={m.currency} className="model-card">
              <div className="model-card-head">
                <strong>USD · consensus surprise</strong>
                <span className={`status-badge ${m.status}`}>
                  {m.status === 'learning' ? 'Learning' : m.status === 'seeded_only' ? 'Getting started' : 'Not started'}
                </span>
              </div>
              <div className="model-n">{m.n_trained} training observations</div>
              <div className="model-n-sub">
                {m.n_real > 0 ? `${m.n_real} recorded release outcomes` : 'No recorded release outcomes yet'}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="section-title">Inputs used by the USD release model</div>
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

    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// TRACK RECORD PAGE
// ══════════════════════════════════════════════════════════════════════════════

type GoldResultFilter = 'all' | 'evaluated' | 'unavailable' | 'pending'

function TrackPage() {
  const [forecasts, setForecasts] = useState<GoldForecast[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [resultFilter, setResultFilter] = useState<GoldResultFilter>('all')

  const loadForecasts = useCallback(async () => {
    setLoading(true)
    try {
      const response = await axios.get(`${API}/gold/forecasts?limit=100`)
      setForecasts(response.data.forecasts ?? [])
      setLoadError(false)
    } catch {
      setLoadError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void loadForecasts() }, [loadForecasts])

  const outcomeState = (forecast: GoldForecast) => {
    if (!forecast.outcome) return 'pending'
    if (forecast.outcome.data_quality?.status === 'unavailable') return 'unavailable'
    return forecast.outcome.change_5m_pct == null ? 'unavailable' : 'evaluated'
  }
  const evaluatedCount = forecasts.filter(forecast => outcomeState(forecast) === 'evaluated').length
  const unavailableCount = forecasts.filter(forecast => outcomeState(forecast) === 'unavailable').length
  const pendingCount = forecasts.filter(forecast => outcomeState(forecast) === 'pending').length
  const ledger = forecasts.filter(forecast => resultFilter === 'all' || outcomeState(forecast) === resultFilter)
  const filters: { value: GoldResultFilter; label: string; count: number }[] = [
    { value: 'all', label: 'All', count: forecasts.length },
    { value: 'evaluated', label: 'Evaluated', count: evaluatedCount },
    { value: 'unavailable', label: 'Unavailable', count: unavailableCount },
    { value: 'pending', label: 'Awaiting outcome', count: pendingCount },
  ]

  if (loading) {
    return (
      <div className="page">
        <div className="loading-center"><Spinner /><span>Loading gold reaction history…</span></div>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="kpi-row">
        <div className="kpi-card">
          <div className="kpi-value">{forecasts.length}</div>
          <div className="kpi-label">Gold release moments</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-value green">{evaluatedCount}</div>
          <div className="kpi-label">Price outcomes evaluated</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-value yellow">{unavailableCount + pendingCount}</div>
          <div className="kpi-label">Unavailable or awaiting data</div>
        </div>
      </div>
      <p className="gold-validation-note">
        This history scores XAU/USD price movement after each release moment. USD BEAT/MISS results are a separate task and are not counted here.
      </p>

      <div className="result-filter" role="group" aria-label="Filter results">
        {filters.map(filter => (
          <button
            key={filter.value}
            className={`result-filter-btn${resultFilter === filter.value ? ' active' : ''}`}
            onClick={() => setResultFilter(filter.value)}
            aria-pressed={resultFilter === filter.value}
          >
            {filter.label} <span>{filter.count}</span>
          </button>
        ))}
      </div>

      {ledger.length === 0 ? (
        <div className="empty-state">
          <p>{loadError ? 'Gold reaction history is unavailable right now.' : forecasts.length === 0 ? 'No gold release moments have been recorded yet.' : 'No release moments match this filter.'}</p>
          {loadError && <button className="primary-action" onClick={() => void loadForecasts()}>Try again</button>}
        </div>
      ) : (
        <div className="ledger-wrap gold-history-wrap">
          <table className="ledger-table gold-history-table">
            <thead>
              <tr>
                <th>Release · UTC</th>
                <th>Event group</th>
                <th>Gold forecast · 5m</th>
                <th>Observed outcome</th>
                <th>Gold return · 5m</th>
                <th>Other horizons</th>
              </tr>
            </thead>
            <tbody>
              {ledger.map((forecast, index) => {
                const outcome = forecast.outcome
                const state = outcomeState(forecast)
                const probs = forecast.probabilities
                const momentId = forecast.release_moment_id ?? `${forecast.release_time_utc}-${forecast.event_family}-${index}`
                return (
                  <tr key={momentId}>
                    <td className="ledger-date">{forecast.release_time_utc ? `${formatDate(forecast.release_time_utc)} · ${formatTime(forecast.release_time_utc)}` : '—'}</td>
                    <td>{forecast.event_family.toUpperCase()}</td>
                    <td>
                      <span className={`ledger-dir ${directionClass(forecast.direction ?? '')}`}>
                        {probs ? `${forecast.direction ?? 'No direction'} · Bull ${(probs.bullish * 100).toFixed(0)}% / Bear ${(probs.bearish * 100).toFixed(0)}% / Neutral ${(probs.neutral * 100).toFixed(0)}%` : 'Not issued'}
                      </span>
                    </td>
                    <td>
                      {state === 'evaluated'
                        ? outcome?.label ?? 'No label · threshold unavailable'
                        : state === 'unavailable'
                          ? 'Price data unavailable'
                          : 'Awaiting price data'}
                    </td>
                    <td className={outcome?.change_5m_pct != null ? directionClass(outcome.change_5m_pct >= 0 ? 'BULLISH' : 'BEARISH') : ''}>
                      {outcome?.change_5m_pct == null ? '—' : `${outcome.change_5m_pct.toFixed(3)}%`}
                    </td>
                    <td className="gold-history-horizons">
                      1m {outcome?.change_1m_pct == null ? '—' : `${outcome.change_1m_pct.toFixed(3)}%`}
                      {' · '}15m {outcome?.change_15m_pct == null ? '—' : `${outcome.change_15m_pct.toFixed(3)}%`}
                      {' · '}30m {outcome?.change_30m_pct == null ? '—' : `${outcome.change_30m_pct.toFixed(3)}%`}
                    </td>
                  </tr>
                )
              })}
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

  const pageCopy: Record<Page, { title: string; description: string }> = {
    home: {
      title: 'Market overview',
      description: 'A clear look at the next major economic release.',
    },
    calendar: {
      title: 'Economic calendar',
      description: 'Upcoming U.S. releases, expectations, and results.',
    },
    model: {
      title: 'Forecast insights',
      description: 'See how the USD and gold forecast systems differ.',
    },
    track: {
      title: 'Gold reaction history',
      description: 'Review XAU/USD outcomes after each U.S. release moment.',
    },
  }
  const localDateTime = new Intl.DateTimeFormat(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(now))

  return (
    <div className="app">
      <div className="layout">
        <SideNav page={page} setPage={setPage} />

        <div className="content">
          <header className="workspace-header">
            <div className="workspace-heading">
              <div className="mobile-brand">
                <img src="/logo.png" alt="" />
                <span>TitanFX Sage</span>
              </div>
              <h1>{pageCopy[page].title}</h1>
              <p>{pageCopy[page].description}</p>
            </div>
            <div className="local-clock">
              <span className="local-clock-icon" aria-hidden="true">◷</span>
              <span>
                <small>YOUR LOCAL TIME</small>
                <strong>{localDateTime}</strong>
              </span>
            </div>
          </header>
          <main>
            {page === 'home' && <HomePage now={now} onOpenCalendar={() => setPage('calendar')} />}
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
