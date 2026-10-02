# MacroPredictor v3 — Deployment Guide

## Prerequisites

- Python 3.11+
- Node.js 20+ / npm
- cPanel hosting with Passenger WSGI support (current setup: titanfxsage.omubedhe.com)
- ~2 GB free disk space (FinBERT model weights: ~440 MB)
- ~1.5 GB free RAM (FinBERT CPU inference)

---

## Environment Setup

### 1. Copy and fill in environment variables

```bash
cp .env.example .env
```

Edit `.env` and set:
- `FRED_API_KEY` — get free at https://fred.stlouisfed.org/docs/api/api_key.html
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — from @BotFather
- `TWELVE_DATA_API_KEY` — **new for v3**, register free at https://twelvedata.com/register

---

### 2. Install Python dependencies

```bash
cd /path/to/macro-predictor
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**First-run note on torch:** `torch` is a large package (~800 MB wheel). If disk space is tight, install the CPU-only wheel explicitly:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

**First-run note on FinBERT:** The `ProsusAI/finbert` model weights (~440 MB) download automatically from HuggingFace on the first call to `sentiment.py`. This happens once and is cached in `~/.cache/huggingface/`. Subsequent starts use the local cache.

---

### 3. Build the React frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

The built assets land in `frontend/dist/`. The FastAPI app serves them from `dist/` at the root path (configured in `api.py`).

---

### 4. Initialise the database

The database auto-migrates on startup. No manual migration step is needed. The existing `macro_predictor.db` historical ledger is preserved — new tables and columns are added non-destructively via `init_db()`.

---

### 5. Start the server

#### Development

```bash
# Backend (in one terminal)
uvicorn api:app --reload --port 8000

# Frontend dev server (optional, in another terminal)
cd frontend && npm run dev
```

The Vite dev server proxies `/api` to `localhost:8000` automatically.

#### Production (cPanel / Passenger)

The existing `passenger_wsgi.py` works unchanged — Passenger imports `api:app` and serves it. Ensure your cPanel Python app is pointing at the venv.

```python
# passenger_wsgi.py (existing — no changes needed)
from api import app as application
```

Restart the app from cPanel after deploying to pick up the new code.

---

## First-Run Sequence

On the very first startup after deployment:

1. `init_db()` creates all new tables and migrates existing columns.
2. `_maybe_seed_models()` seeds the 8 River ARF models with COT + rate-differential priors (10 synthetic samples each). This requires the DB to have at least one rate-differential and COT snapshot. If those haven't run yet, the models start from equal-weight priors and the first real `learn_one()` calls begin building genuine signal.
3. The scheduler fires its first `check_and_alert_upcoming()` within 5 minutes.
4. Rate differentials and currency strengths are computed on the first 06:00/07:00 UTC cron fire (or manually via `POST /api/run-full-cycle`).
5. FinBERT downloads weights on the first 00:30 UTC sentiment cron (or manually via `POST /api/run-full-cycle`). Expect ~5–10 minutes for the download on a typical VPS.

To bootstrap everything immediately without waiting for cron:

```bash
curl -X POST https://titanfxsage.omubedhe.com/api/run-full-cycle
```

---

## Twelve Data Rate Limit Management

Free tier: 800 calls/day, 8 calls/min.

`price_data.py` enforces a 7.5-second delay between Twelve Data calls. With 13 canonical pairs × 1 OHLC fetch each = 13 calls per order-suggestion cycle. Budget:
- 13 pairs × 2 calls (OHLC + ATR) = 26 calls per full event cycle
- Running order suggestions for 5 events per day ≈ 130 calls
- Well within the 800/day free limit

Order suggestions are cached in the `pair_suggestions` DB table and served from cache on repeat `/api/order-suggestion/{event}` requests.

---

## Monitoring

### Health check

```
GET /api/health
```

Returns `fred_configured`, `telegram_configured`, `twelve_data_configured` booleans.

### Manual scheduler trigger

```
POST /api/scheduler/check-now
```

### Force full cycle

```
POST /api/run-full-cycle
```

Runs: rate differentials → currency strengths (all 8) → persists to DB. Takes ~30–60 seconds depending on external API latency.

---

## Upgrading from v2

1. Deploy new code.
2. `init_db()` handles the migration automatically on startup — the existing `predictions` table keeps all historical rows. Three new nullable columns (`currency`, `pair_signals`, `model_version`) are added to existing rows as NULL.
3. Old predictions in the ledger continue to count in accuracy stats; they just won't have `currency`/`pair_signals` populated.
4. No manual SQL required.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `FRED_API_KEY not set` in logs | `.env` not loaded | Check `.env` exists in project root, not in `frontend/` |
| Order levels all null | `TWELVE_DATA_API_KEY` missing or invalid | Set key in `.env`, restart |
| FinBERT never loads | Disk full or no internet on first run | Free disk space; ensure outbound HTTPS on server |
| COT data empty | `cot_reports` couldn't download CFTC file | Check server has outbound HTTPS; CFTC publishes Fridays |
| `No module named 'river'` | venv not activated or pip install failed | Re-run `pip install -r requirements.txt` in venv |
| Sentiment all neutral | FinBERT not loaded (check logs for load error) | See FinBERT note above; check disk/RAM |
| Calendar shows only USD | Old `calendar_cache.json` from v2 still cached | Delete `calendar_cache.json`, force refresh via `/api/events?force_refresh=true` |

---

## Production Checklist

- [ ] `.env` populated with all 3 keys (FRED, Telegram, Twelve Data)
- [ ] `pip install -r requirements.txt` completed in venv
- [ ] `cd frontend && npm run build` completed
- [ ] `passenger_wsgi.py` points to venv Python
- [ ] cPanel app restarted after deploy
- [ ] `GET /api/health` returns all three `_configured: true`
- [ ] `POST /api/run-full-cycle` returns `status: ok`
- [ ] Calendar tab shows events for multiple currencies
- [ ] Strength tab shows 8 currency gauges (may be all 0 until first cycle)
- [ ] Telegram test message received via `POST /api/telegram/test`
