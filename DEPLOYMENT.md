# MacroPredictor v3 — Deployment Guide

## Prerequisites

- Python 3.9
- Node.js 20+ / npm
- cPanel hosting with Passenger WSGI support (current setup: titanfxsage.omubedhe.com)
- Enough disk/RAM for the application and its data

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

Sentiment retains GDELT/RSS article collection and uses a deterministic local
positive/negative word-list scorer. It does not download or load a model.
RSS and Atom feeds are parsed with the Python standard library.

`requirements.txt` pins the Python 3.9 dependency closure. The pinned
`cot_reports==0.1.3` release is the one exception to wheel-backed artifacts:
PyPI declares no `Requires-Python` and publishes only a source distribution.
Its source parses with Python 3.9 grammar, but a live install/run on Python 3.9
could not be verified on this machine because that interpreter is unavailable.

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

To create a separate empty schema database, run
`python fresh_db.py --output /path/to/new.db`. Use `python preview_alerts.py`
to print sample Telegram text without sending; `python send_test_telegram.py`
sends one explicit connectivity test message.

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

#### Cron-driven scheduler

Set `ENABLE_BACKGROUND_SCHEDULER=false` in the web application's environment so
Passenger does not also start an in-process scheduler. Add this cPanel cron job
to run one cycle every minute (replace `CPANEL_USERNAME` with the cPanel
account name):

```cron
* * * * * /home/CPANEL_USERNAME/virtualenv/macro-predictor/3.9/bin/python /home/CPANEL_USERNAME/macro-predictor/run_tick.py >> /home/CPANEL_USERNAME/macro-predictor/run_tick.log 2>&1
```

`run_tick.py` resolves project paths from its own location, takes a non-blocking
lock to skip overlapping runs, executes the one-minute event cycle and every
periodic job due according to its UTC schedule, records each job's last run in
the database, and exits.

---

## First-Run Sequence

On the very first startup after deployment:

1. `init_db()` creates all new tables and migrates existing columns.
2. `_maybe_seed_models()` seeds the 8 River ARF models with COT + rate-differential priors (10 synthetic samples each). This requires the DB to have at least one rate-differential and COT snapshot. If those haven't run yet, the models start from equal-weight priors and the first real `learn_one()` calls begin building genuine signal.
3. The configured scheduler runs `check_and_alert_upcoming()` every minute.
4. Rate differentials and currency strengths are computed on the first 06:00/07:00 UTC cron fire (or manually via `POST /api/run-full-cycle`).
5. Sentiment refresh collects GDELT/RSS articles and applies the local lexicon scorer.

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
| COT data empty | `cot_reports` couldn't download CFTC file | Check server has outbound HTTPS; CFTC publishes Fridays |
| `No module named 'river'` | venv not activated or pip install failed | Re-run `pip install -r requirements.txt` in venv |
| Sentiment all neutral | No lexicon terms in recent articles | Check feed collection and article text |
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
