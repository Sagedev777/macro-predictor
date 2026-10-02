# MacroPredictor v3 — Architecture

## Overview

MacroPredictor is a full-stack macro event prediction system that computes per-currency strength scores for 8 currencies (USD, EUR, GBP, JPY, AUD, CHF, CAD, NZD) using online machine learning, then derives directional bias and ATR-based order levels for every affected forex pair on each upcoming economic release.

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
              │  4. sentiment_score      │  ← sentiment.py    (FinBERT/GDELT)
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
              │  pandas-ta ATR(14)       │
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
| `sentiment.py` | GDELT + RSS article fetching; FinBERT scoring; CFTC COT parsing |
| `learning.py` | River ARFClassifier registry; predict/learn/seed; pair bias computation |
| `price_data.py` | Twelve Data OHLC; pandas-ta ATR(14); order-level suggestion builder |
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
| `sentiment_snapshots` | FinBERT 48h aggregated sentiment per currency |
| `river_model_state` | Serialised River ARFClassifier per currency (pickle) |
| `pair_suggestions` | ATR-based order-level suggestions per event/pair |

---

## Scheduler Jobs

| Job | Trigger | Function |
|---|---|---|
| Pre/post-release alerts + River learn_one() | Every 5 min | `check_and_alert_upcoming()` |
| Rate differential refresh | Daily 06:00 UTC | `refresh_rate_differentials()` |
| Currency strength cycle | Daily 07:00 UTC | `refresh_currency_strengths()` |
| Sentiment refresh (FinBERT) | 00:30 and 12:30 UTC | `refresh_sentiment_cycle()` |
| CFTC COT update | Friday 16:00 UTC | `refresh_cot_cycle()` |

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
    "sentiment_score":  float,  # FinBERT net score      [-1, +1]
}
```

Output: `predict_proba_one()` → P(bullish) → `strength_score = 2 × P(bullish) − 1`

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
| FinBERT | `ProsusAI/finbert` (HuggingFace) | No — ~440 MB download |
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
