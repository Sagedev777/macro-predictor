# USD-Only Simplification Verification

**Date:** 2025  
**Status:** COMPLETE — all 4 checks pass

---

## Check 1 — Backend import test

```
from learning import predict_strength, learn_one, seed_models_with_priors
from scheduler import check_and_alert_upcoming, grade_prediction
from api import app
```

**Result:** `all imports OK`

---

## Check 2 — USD-only calendar test

```
from calendar_feed import TRACKED_CURRENCIES
assert TRACKED_CURRENCIES == {'USD'}
```

**Result:** `TRACKED_CURRENCIES: {'USD'} — PASS: USD only`

---

## Check 3 — Full integration smoke test

```
CURRENCIES: ['USD']
EVENTS count: 27
CANONICAL_PAIRS: ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'AUDUSD', 'USDCAD', 'XAUUSD']
TRACKED_CURRENCIES: {'USD'}
_CURRENCY_KEYWORDS keys: ['USD']
_COT_CONTRACT_NAMES keys: ['USD']
_INVERSE_EVENTS: {'UNEMPLOYMENT_RATE', 'JOBLESS_CLAIMS'}
All good — USD only
```

---

## Check 4 — Frontend build

```
npm run build (frontend/)
```

**Result:** `✓ built in 1.53s — 0 TypeScript errors, 0 warnings`

---

## Changes Applied

| File | Change |
|---|---|
| `config/events.py` | `CURRENCIES=["USD"]`, `CANONICAL_PAIRS` (7 USD majors), `RATE_SERIES`/`COT_CODES`/`RSS_FEEDS` USD-only, removed 31 non-USD EVENTS blocks |
| `calendar_feed.py` | `TRACKED_CURRENCIES={"USD"}`, `FF_EVENT_MAP` USD-only, `_COUNTRY_DISAMBIG` USD-only, step-3 fallback dict USD-only |
| `sentiment.py` | `_CURRENCY_KEYWORDS` USD-only, `_COT_CONTRACT_NAMES` USD-only |
| `scheduler.py` | `_INVERSE_EVENTS` USD-only (JOBLESS_CLAIMS, UNEMPLOYMENT_RATE), replaced multi-currency pair_biases block with direct trade_signals lookup |
| `frontend/src/App.tsx` | Removed `LS_KEY`, `ALL_CCYS`, `CCY_COLORS`, `CurrencyFilter` component, `ls`/`saveLs` helpers, `ccySel` state, `toggleCcy`, all `ccySel` props and filter memos from all 4 page components |
| `frontend/src/App.css` | Removed `.ccy-filter`, `.ccy-chip`, `.ccy-chip.on`, `.ccy-chip:hover` rules |

## Telegram Alert Scope Confirmed

`alerts.py` has no hard-coded non-USD currency references. Alerts fire for whatever events `fetch_upcoming_red_folder_events()` returns, which is now USD-only. Confirmed USD-only scope.
