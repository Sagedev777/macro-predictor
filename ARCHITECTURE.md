# MacroPredictor v4 — USD and XAU/USD Architecture

## Current implementation

The live product surface is limited to U.S. economic releases (USD) and a
separate XAU/USD release-reaction forecast. The USD model's BEAT/MISS/INLINE
output is an economic-number lean; it is not a gold-price forecast or a
probability. `gold_model.py` predicts the observed gold reaction independently,
with a five-minute primary horizon.

| Component | Current responsibility |
|---|---|
| `api.py` | FastAPI health, U.S. calendar, USD release forecasts/history, gold forecasts/model status, and data quality |
| `scheduler.py` | Release detection, pre/post-release alerts, price grading, grouped USD learning, and scheduled source refreshes |
| `gold_model.py` | Point-in-time XAU/USD features, release-moment forecasts, price outcomes, and gold-only evaluation |
| `learning.py` | Existing USD economic-release learner; release-moment grouping and stored feature snapshots |
| `price_data.py` | Gold price acquisition and release outcome grading |
| `calendar_feed.py` | U.S. economic release calendar and actual/consensus data |
| `indicators.py`, `data_sources.py`, `sentiment.py` | U.S. macro/yield, news-sentiment, and CFTC positioning inputs where available |
| `database.py` | SQLite persistence, safe schema upgrades, forecast/outcome records, and scheduler/training idempotency |
| `frontend/src/App.tsx` | USD economic-release and XAU/USD-focused dashboard |

Gold output records forecast cutoff, model version, probabilities when
supported, missing inputs, feature provenance, release identity, and market
outcomes. Missing or stale features remain explicitly missing. Expected gold
return is withheld until a magnitude model is validated. CME FedWatch futures
pricing and gold options-implied volatility are not currently available inputs;
the app does not synthesize them.

The dashboard presents USD BEAT/MISS forecasts separately from XAU/USD price
forecasts and outcomes. Gold reaction history is sourced from gold release-
moment records; unavailable or pending price data is not shown as a win or loss.
The model-status view reports gold training/data sufficiency separately from
the USD economic-release model.

Training consumes stored point-in-time feature snapshots and eligible,
chronologically prior gold outcomes. Simultaneous U.S. releases share one gold
forecast/outcome keyed by a stable release-moment ID. Historical consensus or
publication timestamps that cannot be recovered are disclosed as limitations.
Legacy currency-strength, rate-differential, and order-suggestion tables are
retained only for compatibility with existing SQLite databases; they are not
part of the active USD/XAU application flow and are not dropped by startup
migrations.

**End-to-End Learning Loop:** The scheduler executes an integrated grading and training pipeline. When price reactions are graded (or swept at >= 35 minutes post-release), `process_and_grade_gold_outcomes()` records 1-minute OHLC excursions and 1m/5m/15m/30m returns, persists outcomes into `gold_forecasts`, and triggers point-in-time River learning via `train_gold_outcome()`. Training deduplication and crash recovery are guaranteed across restarts via the `gold_model_training` table. On scheduler boot, `_rebuild_models_from_history()` replays chronological outcomes to rebuild both USD and gold River models.

Intentionally removed public routes: `/api/currency-strengths`,
`/api/currency-strengths/{ccy}`, `/api/pair-biases`, `/api/pair-bias/{pair}`,
`/api/order-suggestion/{event_code}`, `/api/feature-drift`, and
`/api/run-full-cycle`. The dashboard and Telegram alerts no longer expose
non-gold pair forecasts or order suggestions.

## Historical v3 design (superseded; not the live architecture)

## Overview

MacroPredictor retains its USD/economic-release learner and adds a separate XAU/USD news-reaction learner. The gold model forecasts the five-minute price reaction to a U.S. release and learns only from gold price outcomes; it does not use the correctness of the economic-number forecast as its label.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Data Sources (all free)                                                    │
│  FRED · ECB SDW · Eurostat · ONS · BoE · OECD · GDELT · RSS · CFTC COT    │
│  Twelve Data (free tier, key required for ATR)                              │
└──────────────────────────┬──────────────────────────────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │  Four feature signals    │
              │  per currency            │
              │                          │
              │  1. indicator_score      │  ← indicators.py   (FRED z-scores)
              │  2. rate_diff_score      │  ← data_sources.py (yield spreads)
              │  3. cot_score            │  ← sentiment.py    (CFTC COT)
              │  4. sentiment_score      │  ← sentiment.py    (local lexicon/GDELT)
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │  learning.py             │
              │  River ARFClassifier     │
              │  (one model per CCY)     │
              │  learn_one() after grade │
              │  ADWIN drift detection   │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │  Currency Strength Score │  [-1, +1] per currency
              │  Pair Bias              │  strength(base) - strength(quote)
              │  XAUUSD                 │  -USD_strength × 0.85
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │  price_data.py           │
              │  Twelve Data OHLC        │
              │  pandas Wilder ATR(14)   │
              │  Buy/Sell-stop levels    │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │  api.py (FastAPI)        │
              │  SQLite via SQLAlchemy   │
              └────────────┬────────────┘
                           │
              ┌────────────▼────────────┐
              │  React + Tailwind UI     │
              │  (Vite, TypeScript)      │
              └─────────────────────────┘
```

---

## File Map

| File | Role |
|---|---|
| `api.py` | FastAPI application — all REST endpoints |
| `scheduler.py` | APScheduler jobs — alerts, grading, River learn_one(), data refresh |
| `indicators.py` | FRED z-score computation; currency-level aggregation; DB persistence |
| `data_sources.py` | Unified fetch_series() router; rate-differential computation |
| `sentiment.py` | GDELT + RSS article fetching; local lexicon scoring; CFTC COT parsing |
| `learning.py` | River ARFClassifier registry; predict/learn/seed; pair bias computation |
| `gold_model.py` | Independent XAU/USD release-moment forecast, point-in-time features, 5-minute price labeling, and out-of-sample scores |
| `price_data.py` | Twelve Data OHLC; pandas Wilder ATR(14); order-level suggestion builder |
| `calendar_feed.py` | Forex Factory JSON feed; multi-currency; red+orange impact |
| `database.py` | SQLAlchemy models; init_db(); upsert/load helpers |
| `alerts.py` | Telegram message formatting and delivery |
| `config/events.py` | Event definitions for all 8 currencies; RATE_SERIES; COT_CODES; RSS_FEEDS |
| `frontend/src/App.tsx` | React dashboard — 5-tab trading UI |

---

## Database Tables

| Table | Contents |
|---|---|
| `indicator_snapshots` | Raw FRED/ECB/ONS z-score pulls per series |
| `predictions` | Historical prediction ledger (never wiped) |
| `releases` | Actual release prints from Forex Factory |
| `alert_logs` | Sent Telegram alerts (deduplication) |
| `currency_strengths` | Per-currency strength snapshot (timestamped) |
| `rate_differentials` | Daily benchmark yield spreads vs US 10Y |
| `cot_snapshots` | CFTC COT net-long positioning per currency |
| `sentiment_snapshots` | 48-hour lexicon-scored sentiment per currency |
| `river_model_state` | Serialised River ARFClassifier per currency (pickle) |
| `pair_suggestions` | ATR-based order-level suggestions per event/pair |
| `gold_forecasts` | One pre-release gold forecast and price outcome per release moment; stores point-in-time features and provenance |

---

## Scheduler Jobs

| Job | Trigger | Function |
|---|---|---|
| Release alerts, price grading + River learn_one() | Every minute | `check_and_alert_upcoming()` |
| Rate differential refresh | Daily 06:00 UTC | `refresh_rate_differentials()` |
| Currency strength cycle | Daily 07:00 UTC | `refresh_currency_strengths()` |
| Sentiment refresh | 00:30 and 12:30 UTC | `refresh_sentiment_cycle()` |
| CFTC USD and COMEX gold COT update | Friday 16:00 UTC | `refresh_cot_cycle()` |

`run_tick.py` uses the same cadence table and persists each job's `last_run_at`
in `periodic_job_runs`; `release_moment_training` is the cross-process
idempotency ledger for grouped River observations.

---

## Indicator z-Score Math (preserved from v1)

For each FRED/ECB/ONS series:
1. Pull 12 months of observations
2. Compute trailing 6-month mean and std (excluding latest)
3. z = (latest − mean) / std
4. Signal: +1 if z > 0.3 × sign, −1 if z < −0.3 × sign, 0 if |z| < 0.3
5. Weighted sum across indicators → `composite_score` ∈ [−1, +1]
6. Direction: BEAT if composite > 0.15, MISS if < −0.15, else INLINE
7. Confidence: 50% baseline, scaled by agreement ratio, capped at 85%

---

## River ARF Feature Vector

```python
{
    "indicator_score":  float,  # z-score aggregate     [-1, +1]
    "rate_diff_score":  float,  # yield spread vs US10Y  [-1, +1]
    "cot_score":        float,  # CFTC net-long %        [-1, +1]
    "sentiment_score":  float,  # local lexicon net score [-1, +1]
}
```

Output: `predict_proba_one()` → P(bullish) → `strength_score = 2 × P(bullish) − 1`

---

## XAU/USD Release-Reaction Model

- `gold_model.py` is independent of the existing USD learner. Simultaneous numeric USD events share one gold forecast and one training observation per `release_time_utc`.
- Primary horizon is five minutes. Labels are BULLISH, BEARISH, or NEUTRAL using `0.5 × median(|five-minute XAU/USD return|)` from earlier outcomes in the same event family. The current outcome is never used to set its own threshold.
- The stored inputs include Forex Factory consensus snapshots, point-in-time indicator/sentiment/positioning snapshots, recent XAU/USD returns and realized volatility, FRED two-year and real ten-year yields, and earlier same-family gold reactions. Each input stores its source, capture time, observation time when known, publication time when known, and an availability/staleness status.
- Missing values remain missing. CME FedWatch probabilities and gold-options implied volatility are currently marked unavailable; realized volatility is recorded separately and is not described as implied volatility. Weekly COMEX gold COT is captured through CFTC reports, but publication time remains unknown unless supplied by the source.
- Outcomes include gold returns at 1, 5, 15, and 30 minutes, five-minute maximum up/down movement, forecast-relative favorable/adverse movement, and first-seen actual release values.
- Probabilities are withheld until at least ten prior eligible release moments and at least two examples of each outcome class exist. Outputs remain provisional until sufficient out-of-sample evidence supports calibration. Stored pre-release probabilities are evaluated with direction accuracy, multiclass Brier score, confidence bands, and event-family breakdowns.
- Training rebuilds from stored feature snapshots and chronologically available gold outcomes. It never reads current feature values for a historical prediction.

---

## API Endpoints

### Existing (unchanged signatures)
- `GET  /api/health`
- `GET  /api/events`
- `POST /api/events/sync-actuals`
- `POST /api/events/record-actual`
- `GET  /api/prediction/{event_code}`
- `POST /api/run-all`
- `GET  /api/predictions`
- `GET  /api/history`
- `GET  /api/accuracy`
- `POST /api/scheduler/check-now`
- `POST /api/prediction/{event_code}/telegram`
- `POST /api/telegram/broadcast-all`
- `POST /api/telegram/test`

### New (v3)
- `GET  /api/currency-strengths`           — all 8 currency scores
- `GET  /api/currency-strengths/{ccy}`     — single currency detail
- `GET  /api/pair-biases`                  — all canonical pairs
- `GET  /api/pair-bias/{pair}`             — single pair
- `GET  /api/order-suggestion/{event_code}`— ATR-based order levels
- `GET  /api/feature-drift`               — River feature importance
- `POST /api/run-full-cycle`              — manual full pipeline trigger

---

## Data Source Reference

| Source | Endpoint | Key Required |
|---|---|---|
| FRED | `https://api.stlouisfed.org/fred/series/observations` | Yes — FRED_API_KEY |
| ECB SDW | `https://sdw-wsrest.ecb.europa.eu/service/` | No |
| Eurostat | `https://ec.europa.eu/eurostat/api/dissemination/` | No |
| ONS (UK) | `https://api.ons.gov.uk/` | No |
| Bank of England | `https://www.bankofengland.co.uk/boeapps/database/` | No |
| OECD | `https://stats.oecd.org/SDMX-JSON/` | No |
| GDELT 2.0 | `https://api.gdeltproject.org/api/v2/doc/doc` | No |
| ForexLive RSS | `https://www.forexlive.com/feed/news/` | No |
| FXStreet RSS | `https://www.fxstreet.com/rss/news` | No |
| CFTC COT | via `cot_reports` library | No |
| Twelve Data | `https://api.twelvedata.com` | Yes — TWELVE_DATA_API_KEY |
| Forex Factory | `https://nfs.faireconomy.media/ff_calendar_thisweek.json` | No |

---

## Pair Bias Formula

```
pair_bias(BASE/QUOTE) = strength(BASE) − strength(QUOTE)

XAUUSD: bias = −USD_strength × 0.85
```

Direction thresholds:
- `bias > +0.10` → BUY base
- `bias < −0.10` → SELL base
- else → NEUTRAL

---

## ATR Order-Level Formula

Given direction (BUY/SELL), current price P, and ATR(14):

| Level | BUY | SELL |
|---|---|---|
| Entry | P + 1.0 × ATR | P − 1.0 × ATR |
| Stop Loss | Entry − 1.5 × ATR | Entry + 1.5 × ATR |
| Take Profit | Entry + 2.0 × ATR | Entry − 2.0 × ATR |

XAUUSD uses 1.5 × ATR for entry distance. All levels are reference-only, not trade recommendations.
