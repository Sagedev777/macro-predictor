# USD-Only Simplification Audit

**Task:** Scope macro-predictor down to USD-only. Remove all multi-currency architecture.  
**Date:** 2025  
**Status:** Audit complete — Phase 2 implementation contract below.

---

## 1. Multi-Currency Code Inventory

### `config/events.py`

**What it is:** The single largest source of multi-currency code.

| Symbol / Block | Multi-currency? | Notes |
|---|---|---|
| `CURRENCIES = ["USD","EUR","GBP","JPY","AUD","CHF","CAD","NZD"]` | **YES — REMOVE** | Replace with `CURRENCIES = ["USD"]` |
| `CANONICAL_PAIRS` list (34 pairs) | **PARTIAL** | Keep only USD majors: `["EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","USDCAD","NZDUSD","XAUUSD"]`. Drop all EUR/GBP/JPY crosses. |
| `XAUUSD_USD_BETA = -0.85` | KEEP | Still relevant for the single USD model |
| `RATE_SERIES` dict (8 entries) | **REMOVE NON-USD** | Keep only `"USD": ("DGS10", "fred")`. Drop EUR/GBP/JPY/AUD/CHF/CAD/NZD entries. |
| `COT_CODES` dict (8 entries) | **REMOVE NON-USD** | Keep only `"USD": "US DOLLAR INDEX..."`. |
| `RSS_FEEDS` dict (8 entries) | **REMOVE NON-USD** | Keep only `"USD": [...]`. |
| `EVENTS` dict — USD entries (NFP, CPI, CORE_CPI, PPI, JOBLESS_CLAIMS, UNEMPLOYMENT_RATE, CONSUMER_CONFIDENCE, FOMC, RETAIL_SALES, ISM_MFG, GDP, CORE_PPI, CORE_RETAIL_SALES, ISM_SERVICES, AVG_HOURLY_EARNINGS, ADP_NFP, JOLTS, CORE_PCE, PCE, BUILDING_PERMITS, HOUSING_STARTS, DURABLE_GOODS, TRADE_BALANCE, INDUSTRIAL_PRODUCTION, EMPIRE_STATE, PHILLY_FED, GDP_DEFLATOR) | **KEEP ALL** | All USD events preserved verbatim |
| `EVENTS` dict — EUR entries (EUR_CPI, EUR_CORE_CPI, EUR_GDP, ECB_RATE, EUR_PMI_MFG, EUR_PMI_SERVICES, EUR_UNEMPLOYMENT, GERMAN_IFO, GERMAN_ZEW) | **REMOVE** | 9 EUR event definitions to delete |
| `EVENTS` dict — GBP entries (GBP_CPI, GBP_CORE_CPI, GBP_GDP, BOE_RATE, GBP_EMPLOYMENT, GBP_PMI_MFG, GBP_PMI_SERVICES, GBP_RETAIL_SALES) | **REMOVE** | 8 GBP event definitions to delete |
| `EVENTS` dict — JPY entries (JPY_CPI, BOJ_RATE, JAPAN_GDP, JAPAN_TANKAN) | **REMOVE** | 4 JPY event definitions to delete |
| `EVENTS` dict — AUD entries (AUD_CPI, RBA_RATE, AUD_EMPLOYMENT, AUD_RETAIL_SALES) | **REMOVE** | 4 AUD event definitions to delete |
| `EVENTS` dict — CAD entries (CAD_CPI, BOC_RATE, CAD_EMPLOYMENT, CAD_GDP) | **REMOVE** | 4 CAD event definitions to delete |
| `EVENTS` dict — NZD entries (NZD_CPI, RBNZ_RATE, NZD_EMPLOYMENT) | **REMOVE** | 3 NZD event definitions to delete |
| `EVENTS` dict — CHF entries (CHF_CPI, SNB_RATE, CHF_UNEMPLOYMENT) | **REMOVE** | 3 CHF event definitions to delete |
| Helper functions `get_event_config()`, `get_events_for_currency()` | **KEEP** | These are generic; just work with the reduced EVENTS dict |

**Summary for config/events.py:**
- Delete all `EUR_*`, `GBP_*`, `JPY_*`, `AUD_*`, `CAD_*`, `NZD_*`, `CHF_*` event entries (~31 event blocks)
- Reduce `CURRENCIES` to `["USD"]`
- Reduce `CANONICAL_PAIRS` to 8 USD majors only
- Reduce `RATE_SERIES`, `COT_CODES`, `RSS_FEEDS` to USD only

---

### `calendar_feed.py`

| Symbol / Block | Multi-currency? | Notes |
|---|---|---|
| `TRACKED_CURRENCIES = {"USD","EUR","GBP","JPY","AUD","CHF","CAD","NZD"}` | **REMOVE NON-USD** | Change to `TRACKED_CURRENCIES = {"USD"}` |
| `FF_EVENT_MAP` — USD section | **KEEP** | All USD title mappings preserved |
| `FF_EVENT_MAP` — EUR section (EUR_CPI, EUR_CORE_CPI, EUR_GDP, ECB_RATE, EUR_PMI_*, EUR_UNEMPLOYMENT, GERMAN_IFO, GERMAN_ZEW, etc.) | **REMOVE** | ~25 entries |
| `FF_EVENT_MAP` — GBP section (GBP_CPI, GBP_CORE_CPI, GBP_GDP, BOE_RATE, GBP_EMPLOYMENT, etc.) | **REMOVE** | ~12 entries |
| `FF_EVENT_MAP` — JPY section (JPY_CPI, BOJ_RATE, JAPAN_GDP, JAPAN_TANKAN) | **REMOVE** | ~8 entries |
| `FF_EVENT_MAP` — AUD section (AUD_CPI, RBA_RATE, AUD_EMPLOYMENT, AUD_RETAIL_SALES) | **REMOVE** | ~6 entries |
| `FF_EVENT_MAP` — CAD section (CAD_CPI, BOC_RATE, CAD_EMPLOYMENT, CAD_GDP) | **REMOVE** | ~6 entries |
| `FF_EVENT_MAP` — NZD section (NZD_CPI, RBNZ_RATE, NZD_EMPLOYMENT) | **REMOVE** | ~5 entries |
| `FF_EVENT_MAP` — CHF section (CHF_CPI, SNB_RATE, CHF_UNEMPLOYMENT) | **REMOVE** | ~4 entries |
| `_COUNTRY_DISAMBIG` dict (all non-USD rows) | **REMOVE** | Keep only `("USD", "unemployment rate"): "UNEMPLOYMENT_RATE"`. Remove ~30 non-USD disambig entries. |
| `_resolve_event_code()` — step 3 fallback prefix dict | **SIMPLIFY** | Remove all non-USD prefix keys; keep only `"USD": ""` |
| `fetch_calendar_events()` — diagnostic logging | **KEEP** | Works fine with single currency |
| `get_events_for_currency()` | **KEEP** | Generic helper, still useful |
| `get_red_events_only()` | **KEEP** | Generic filter, still useful |

**Summary for calendar_feed.py:**
- `TRACKED_CURRENCIES` → `{"USD"}`
- Gut `FF_EVENT_MAP` of all non-USD entries
- Gut `_COUNTRY_DISAMBIG` of all non-USD entries
- Simplify `_resolve_event_code()` step 3 fallback prefix dict to USD only

---

### `learning.py`

| Symbol / Block | Multi-currency? | Notes |
|---|---|---|
| `_ModelRegistry` class — holds one model per currency | **SIMPLIFY** | The class itself is fine; after CURRENCIES shrinks to `["USD"]`, all loops (`seed_models_with_priors`, `get_all_strengths`, `get_feature_importance_drift`) naturally iterate over only USD |
| `seed_models_with_priors()` — loops `for ccy in CURRENCIES` | **KEEP** | Will automatically only process USD once CURRENCIES is reduced |
| `get_all_strengths(feature_map)` — loops `for ccy in CURRENCIES` | **KEEP** | Same — USD only naturally |
| `compute_pair_bias()` — `XAUUSD` special case, multi-currency pair handling | **PARTIAL KEEP** | Keep the XAU/USD case; keep the generic `base/quote` mechanism (still needed for the 8 USD majors). The `compute_all_pair_biases()` function iterates `CANONICAL_PAIRS` which we shrink to 8 USD pairs. |
| `compute_all_pair_biases()` — iterates `CANONICAL_PAIRS` | **KEEP** | Shrinking CANONICAL_PAIRS handles this automatically |
| `get_feature_importance_drift()` — loops `for ccy in CURRENCIES` | **KEEP** | USD only once CURRENCIES reduced |
| `_XAUUSD_BETA` | **KEEP** | Still relevant |
| `PairBias` / `StrengthPrediction` dataclasses | **KEEP** | Still used for the single USD model |

**Summary for learning.py:**
- No code changes required. All loops reference `CURRENCIES` from `config/events.py`. Shrinking that list makes learning.py USD-only automatically.
- The pair-bias logic in `compute_pair_bias()` is structurally sound — XAUUSD beta case is preserved and the other 7 USD majors still use the base/quote formula with USD as one constituent.

---

### `indicators.py`

| Symbol / Block | Multi-currency? | Notes |
|---|---|---|
| `get_indicator_score_for_currency(currency)` | **KEEP** | Generic; will only be called with "USD" |
| `get_indicator_scores_all_currencies()` — loops `for ccy in CURRENCIES` | **KEEP** | USD only once CURRENCIES reduced |
| `get_latest_currency_strengths()` — loops `for ccy in CURRENCIES` | **KEEP** | USD only once CURRENCIES reduced |
| `persist_currency_strength()` | **KEEP** | Generic DB write, no multi-currency logic |
| ECB/ONS/BOE routing in `_fetch_series_routed()` | **KEEP THE ROUTING** | The non-FRED fetchers are still invoked for USD indicator series that happen to use those prefixes. **However, no current USD events use ECB/ONS/BOE series** — all USD indicators use bare FRED IDs. These routing paths are dead code for USD-only but are harmless to keep. |
| `build_composite_score()` | **KEEP** | USD-only output unchanged |
| `pull_all_indicators_for_event()` | **KEEP** | Generic; no currency filtering |

**Summary for indicators.py:**
- No changes required. The multi-currency iteration in `get_indicator_scores_all_currencies()` and `get_latest_currency_strengths()` is loop-based over `CURRENCIES`; shrinking CURRENCIES handles it. 
- The non-FRED fetchers (`_fetch_ecb_sdw`, `_fetch_eurostat`, etc. via `data_sources.py`) remain in code but are never called for USD events — harmless dead code that requires no removal.

---

### `data_sources.py`

| Symbol / Block | Multi-currency? | Notes |
|---|---|---|
| `RATE_SERIES` import from `config/events.py` | **AUTO-FIXED** | Once RATE_SERIES is reduced to USD only in events.py, compute_rate_differentials() will only fetch the US 10Y (and USD's self-differential = 0). |
| `_fetch_ecb_sdw()` | **KEEP AS DEAD CODE** | Harmless; never called once non-EUR/CHF/JPY rate series are gone |
| `_fetch_eurostat()` | **KEEP AS DEAD CODE** | Same — never invoked for USD |
| `_fetch_ons()` | **KEEP AS DEAD CODE** | Same |
| `_fetch_boe()` | **KEEP AS DEAD CODE** | Same |
| `_fetch_oecd()` | **KEEP AS DEAD CODE** | Same |
| `compute_rate_differentials()` — loops `for currency, (series_id, source) in RATE_SERIES.items()` | **AUTO-FIXED** | Shrinking RATE_SERIES to USD only means only the USD row (spread=0, trend=FLAT) is computed. No code change needed. |
| `get_all_rate_differentials()` — loops `for ccy in CURRENCIES` | **AUTO-FIXED** | CURRENCIES will only contain USD |
| `rate_diff_to_score()` — returns 0.0 for USD | **KEEP** | Always returns 0.0 for USD anyway; function signature unchanged |

**Summary for data_sources.py:**
- No code changes required. Reducing `RATE_SERIES` and `CURRENCIES` in `config/events.py` automatically limits all data_sources.py activity to USD. The ECB/ONS/BOE/Eurostat/OECD fetchers become dead code — they can optionally be removed for cleanliness but are not harmful.

---

### `sentiment.py`

| Symbol / Block | Multi-currency? | Notes |
|---|---|---|
| `_CURRENCY_KEYWORDS` dict (8 currencies) | **REMOVE NON-USD** | Keep only `"USD": [...]`. Remove EUR/GBP/JPY/AUD/CHF/CAD/NZD keyword arrays. |
| `_fetch_gdelt_articles(currency)` | **KEEP** | Generic; called with "USD" only |
| `_fetch_rss_articles(currency)` — imports `RSS_FEEDS` from events.py | **AUTO-FIXED** | Once RSS_FEEDS in events.py is USD-only, rss_articles only processes USD feeds |
| `refresh_all_sentiment()` — loops `for ccy in CURRENCIES` | **AUTO-FIXED** | USD only once CURRENCIES reduced |
| `_COT_CONTRACT_NAMES` dict (8 currencies) | **REMOVE NON-USD** | Keep only `"USD": "US DOLLAR INDEX - ICE FUTURES U.S."`. Remove 7 other entries. |
| `refresh_all_cot()` — loops `for ccy in CURRENCIES` | **AUTO-FIXED** | USD only once CURRENCIES reduced |
| `get_cot_positioning(currency)` | **KEEP** | Generic; will only be called with "USD" |

**Summary for sentiment.py:**
- **Two explicit changes needed:** Reduce `_CURRENCY_KEYWORDS` to USD-only. Reduce `_COT_CONTRACT_NAMES` to USD-only.
- All `refresh_all_*` loops auto-fix via CURRENCIES.
- RSS_FEEDS auto-fixes via events.py change.

---

### `scheduler.py`

| Symbol / Block | Multi-currency? | Notes |
|---|---|---|
| `_INVERSE_EVENTS` set — contains USD + non-USD entries | **REMOVE NON-USD** | Keep: `"JOBLESS_CLAIMS"`, `"UNEMPLOYMENT_RATE"`. Remove: `"EUR_UNEMPLOYMENT"`, `"GBP_EMPLOYMENT"`, `"AUD_EMPLOYMENT"`, `"CAD_EMPLOYMENT"`, `"NZD_EMPLOYMENT"`, `"CHF_UNEMPLOYMENT"` |
| `from config.events import CURRENCIES` | **AUTO-FIXED** | Now only `["USD"]` |
| `check_and_alert_upcoming()` — inner block builds fmap for all CURRENCIES | **AUTO-FIXED** | Loop iterates CURRENCIES = ["USD"] only |
| `refresh_rate_differentials()` | **AUTO-FIXED** | compute_rate_differentials now USD-only |
| `refresh_sentiment_cycle()` — calls `refresh_all_sentiment` | **AUTO-FIXED** | refresh_all_sentiment loops CURRENCIES = ["USD"] |
| `refresh_cot_cycle()` — calls `refresh_all_cot` | **AUTO-FIXED** | refresh_all_cot loops CURRENCIES = ["USD"] |
| `refresh_currency_strengths()` — loops `for ccy in CURRENCIES` | **AUTO-FIXED** | CURRENCIES = ["USD"] |
| `_maybe_seed_models()` — calls `seed_models_with_priors` | **AUTO-FIXED** | seed loops CURRENCIES = ["USD"] |

**Summary for scheduler.py:**
- **One explicit change:** Remove non-USD entries from `_INVERSE_EVENTS`.
- Everything else auto-fixes via the CURRENCIES reduction.

---

### `api.py`

| Symbol / Block | Multi-currency? | Notes |
|---|---|---|
| `from config.events import CANONICAL_PAIRS, CURRENCIES, EVENTS` | **AUTO-FIXED** | Will import the reduced USD-only versions |
| `/api/health` — `"tracked_currencies": CURRENCIES` | **AUTO-FIXED** | Returns `["USD"]` |
| `_get_cached_strengths()` — loops `for ccy in CURRENCIES` | **AUTO-FIXED** | USD only |
| `/api/currency-strengths` — loops `for ccy in CURRENCIES` | **AUTO-FIXED** | USD only |
| `/api/currency-strengths/{currency}` — validates against `CURRENCIES` | **AUTO-FIXED** | Only "USD" valid |
| `/api/pair-biases` — builds StrengthPrediction for all CURRENCIES | **AUTO-FIXED** | USD only once CURRENCIES reduced |
| `/api/model-status` — loops `for ccy in CURRENCIES` | **AUTO-FIXED** | USD only |
| `/api/accuracy-trend` — groups by currency, includes per-ccy trend | **KEEP** | Will show only USD trend naturally |
| `/api/calibration?currency=` param | **KEEP** | Optional filter, still valid for USD |
| `/api/run-full-cycle` — loops `for ccy in CURRENCIES` | **AUTO-FIXED** | USD only |
| `/api/feature-drift` — calls `get_feature_importance_drift()` | **AUTO-FIXED** | Returns USD only |
| `get_accuracy()` — `currency_breakdown` dict | **KEEP** | Will only accumulate USD entries |

**Summary for api.py:**
- No explicit code changes required. Every multi-currency loop references `CURRENCIES` from config. The API naturally becomes USD-only once that constant is reduced.

---

### `database.py`

| Symbol / Block | Multi-currency? | Notes |
|---|---|---|
| `CurrencyStrength` table | **KEEP** | Used for USD strength snapshots; no structural change |
| `RateDifferential` table | **KEEP** | Will contain only USD rows going forward |
| `CotSnapshot` table | **KEEP** | Will contain only USD rows |
| `SentimentSnapshot` table | **KEEP** | Will contain only USD rows |
| `RiverModelState` table | **KEEP** | Will contain only one row (USD) |
| `Prediction.currency` column | **KEEP** | Will always be "USD" going forward |
| No iteration over currencies — pure ORM | **NO CHANGE** | All queries are parameterized by currency string |

**Summary for database.py:**
- No changes required. Tables are schema-generic and will naturally only accumulate USD rows going forward. Old non-USD rows in existing DB (if any) are harmless — they'll never be queried once CURRENCIES = ["USD"].

---

### `frontend/src/App.tsx`

| Symbol / Block | Multi-currency? | Notes |
|---|---|---|
| `const ALL_CCYS = ['USD','EUR','GBP','JPY','AUD','CHF','CAD','NZD']` | **REMOVE** | Entire constant removed |
| `const LS_KEY = 'macro_currency_filter'` | **REMOVE** | localStorage filter state no longer needed |
| `CurrencyFilter` component | **REMOVE ENTIRELY** | The chip-filter UI component is removed |
| `ccySel` state in `App()` | **REMOVE** | Replace with hardcoded `["USD"]` or eliminate the prop pattern entirely |
| `toggle` callback in `App()` | **REMOVE** | No longer needed |
| `HomePage({ ccySel, now })` — filters events by `ccySel` | **SIMPLIFY** | Remove `ccySel` prop; always show USD events. Keep the rest of the component unchanged. |
| `CalendarPage({ ccySel })` — filters events by `ccySel` | **SIMPLIFY** | Remove `ccySel` prop; always filter for `currency === 'USD'` or show all (since all events will be USD). |
| `ModelPage({ ccySel })` — `filtModels`, `filtTrend`, `filtMistakes` filters | **SIMPLIFY** | With USD-only backend these filter expressions always return the full set. Can simplify to `models` / `trend` / `mistakes` directly (no filter needed). Remove `ccySel` prop. |
| `TrackPage({ ccySel })` — `filtered` memo filters by ccySel | **SIMPLIFY** | Remove filter; show all history (which will all be USD). Remove `ccySel` prop. |
| `CCY_COLORS` array (8 colors) | **SIMPLIFY** | Can reduce to single color for USD, or keep as-is (harmless) |
| `<CurrencyFilter sel={ccySel} toggle={toggleCcy} />` render in `App()` | **REMOVE** | Don't render the filter chip row |
| localStorage read/write for filter | **REMOVE** | `ls(LS_KEY, ALL_CCYS)` and `saveLs` calls removed |
| `TrendChart` — still useful for USD | **KEEP** | Shows single USD trend chart |
| All page components otherwise | **KEEP** | The 5 Model Progress sections, Calendar layout, Track Record table — all unchanged |

**Summary for App.tsx:**
- Remove `ALL_CCYS`, `LS_KEY`, `CurrencyFilter` component, and the `ccySel`/`toggleCcy` state from `App()`.
- Remove `ccySel` props from all four page components.
- Remove the `<CurrencyFilter>` render from the `App()` layout.
- Simplify filter expressions in page components (they either become no-ops or trivially filter for USD).
- The rest of the UI — calendar layout, home card, model sections, track record table — stays exactly as-is.

---

## 2. Shared Functions That Serve Both USD and Non-USD Paths

These functions are shared but USD-safe — they take a `currency` string parameter and are called correctly. After the reduction:

| Function | Shared path? | Safe after change? |
|---|---|---|
| `indicators.build_composite_score(event_code)` | No — always USD events | ✅ Unchanged |
| `data_sources.fetch_series(series_id)` | Routes by prefix — FRED for USD | ✅ ECB/ONS/BOE paths become dead code, not harmful |
| `learning.predict_strength(currency, features)` | Takes currency string | ✅ Will only receive "USD" |
| `learning.compute_pair_bias(base, quote, strengths)` | Generic; base/quote params | ✅ Will only receive USD majors |
| `sentiment.get_cot_positioning(currency)` | Takes currency string | ✅ Only USD called |
| `sentinel.get_currency_sentiment(currency)` | Takes currency string | ✅ Only USD called |
| `calendar_feed._resolve_event_code(country, title, impact)` | All 8 currencies currently | ⚠️ Needs `_COUNTRY_DISAMBIG` and step-3 fallback dict pruned |

**No circular dependency issues identified.** The import chain is: `api.py` → `scheduler.py` → `learning.py` / `indicators.py` / `data_sources.py` / `sentiment.py` / `calendar_feed.py` → `config/events.py` → (no further imports). `database.py` is imported at the bottom of the chain by most modules. All imports are one-directional.

---

## 3. Files Requiring NO Changes

These files work correctly after CURRENCIES is reduced to ["USD"] and need no direct edits:

- `database.py` — Schema-generic, no currency logic
- `learning.py` — All loops reference CURRENCIES from config; pair bias logic is structurally correct for USD majors
- `indicators.py` — All loops reference CURRENCIES; no hard-coded non-USD logic
- `api.py` — All loops reference CURRENCIES or EVENTS; no hard-coded non-USD logic
- `data_sources.py` — RATE_SERIES drives the loop; reducing it in events.py is sufficient
- `alerts.py` — USD-only already (sends alerts for events from calendar feed; once calendar feed is USD-only, alerts are USD-only)
- `price_data.py` — Referenced by api.py for ATR order suggestions; builds suggestions for pairs in pair_biases_dict which comes from CANONICAL_PAIRS (auto-fixed)
- `scheduler.py` — Only `_INVERSE_EVENTS` needs pruning (see above)

---

## 4. Ordered Implementation Plan for Phase 2

Changes are ordered by dependency — each step must be complete before the next to keep the codebase in a runnable state.

---

- [ ] **Step 1 — Reduce `config/events.py`** *(everything else depends on this)*

  **What:** This is the single source of truth for all multi-currency data. Making it USD-only propagates through the entire codebase automatically.

  **Changes:**
  1. `CURRENCIES = ["USD"]` — remove EUR, GBP, JPY, AUD, CHF, CAD, NZD
  2. `CANONICAL_PAIRS` — reduce to `["EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","USDCAD","NZDUSD","XAUUSD"]`
  3. `RATE_SERIES` — keep only `"USD": ("DGS10", "fred")`
  4. `COT_CODES` — keep only `"USD": "US DOLLAR INDEX - ICE FUTURES U.S."`
  5. `RSS_FEEDS` — keep only `"USD": [...]`
  6. `EVENTS` — delete all 31 non-USD event blocks (EUR_CPI, EUR_CORE_CPI, EUR_GDP, ECB_RATE, EUR_PMI_MFG, EUR_PMI_SERVICES, EUR_UNEMPLOYMENT, GERMAN_IFO, GERMAN_ZEW, GBP_CPI, GBP_CORE_CPI, GBP_GDP, BOE_RATE, GBP_EMPLOYMENT, GBP_PMI_MFG, GBP_PMI_SERVICES, GBP_RETAIL_SALES, JPY_CPI, BOJ_RATE, JAPAN_GDP, JAPAN_TANKAN, AUD_CPI, RBA_RATE, AUD_EMPLOYMENT, AUD_RETAIL_SALES, CAD_CPI, BOC_RATE, CAD_EMPLOYMENT, CAD_GDP, NZD_CPI, RBNZ_RATE, NZD_EMPLOYMENT, CHF_CPI, SNB_RATE, CHF_UNEMPLOYMENT)
  7. Keep `XAUUSD_USD_BETA`, all USD event blocks, and both helper functions (`get_event_config`, `get_events_for_currency`) unchanged.

  **Files:** `config/events.py`

  **Verify:** `python -c "from config.events import CURRENCIES, EVENTS; assert CURRENCIES == ['USD']; assert all(e.get('currency') == 'USD' for e in EVENTS.values()); print('PASS', len(EVENTS), 'USD events')"` — should print PASS with ~27 events.

---

- [ ] **Step 2 — Prune `calendar_feed.py`**

  **What:** Reduce FF parsing to USD-only by shrinking the two maps that drive currency resolution.

  **Changes:**
  1. `TRACKED_CURRENCIES = {"USD"}` — replace the 8-currency set
  2. `FF_EVENT_MAP` — delete the EUR, GBP, JPY, AUD, CAD, NZD, CHF sections (all entries with non-USD event codes). Keep the entire USD section unchanged.
  3. `_COUNTRY_DISAMBIG` — delete all non-USD rows. Keep only `("USD", "unemployment rate"): "UNEMPLOYMENT_RATE"`.
  4. In `_resolve_event_code()` step 3 fallback, the prefix dict — change to `{"USD": ""}` only (remove EUR/GBP/JPY/AUD/CHF/CAD/NZD prefix entries).

  **Files:** `calendar_feed.py`

  **Verify:** `python -c "from calendar_feed import TRACKED_CURRENCIES, FF_EVENT_MAP; assert TRACKED_CURRENCIES == {'USD'}; assert all(not k.startswith('EUR_') for k in FF_EVENT_MAP.values()); print('PASS')"` — should print PASS.

---

- [ ] **Step 3 — Prune `sentiment.py`**

  **What:** Two explicit dict reductions; everything else auto-fixes via CURRENCIES.

  **Changes:**
  1. `_CURRENCY_KEYWORDS` — keep only `"USD": [...]`. Remove EUR, GBP, JPY, AUD, CHF, CAD, NZD keyword arrays.
  2. `_COT_CONTRACT_NAMES` — keep only `"USD": "US DOLLAR INDEX - ICE FUTURES U.S."`. Remove the other 7 entries.

  **Files:** `sentiment.py`

  **Verify:** `python -c "from sentiment import _CURRENCY_KEYWORDS, _COT_CONTRACT_NAMES; assert list(_CURRENCY_KEYWORDS.keys()) == ['USD']; assert list(_COT_CONTRACT_NAMES.keys()) == ['USD']; print('PASS')"` — should print PASS.

---

- [ ] **Step 4 — Prune `scheduler.py`**

  **What:** One explicit dict reduction; everything else auto-fixes.

  **Changes:**
  1. `_INVERSE_EVENTS` — keep only `{"JOBLESS_CLAIMS", "UNEMPLOYMENT_RATE"}`. Remove `EUR_UNEMPLOYMENT`, `GBP_EMPLOYMENT`, `AUD_EMPLOYMENT`, `CAD_EMPLOYMENT`, `NZD_EMPLOYMENT`, `CHF_UNEMPLOYMENT`.

  **Files:** `scheduler.py`

  **Verify:** `python -c "from scheduler import _INVERSE_EVENTS; assert _INVERSE_EVENTS == {'JOBLESS_CLAIMS', 'UNEMPLOYMENT_RATE'}; print('PASS')"` — should print PASS.

---

- [ ] **Step 5 — Integration smoke test (backend)**

  **What:** After Steps 1-4, verify the full backend import chain and scheduler bootstrap are clean.

  **Verify:**
  ```
  cd c:\Users\TITANFXSAGE\Desktop\macro-predictor
  python -c "
  from config.events import CURRENCIES, EVENTS, CANONICAL_PAIRS
  from calendar_feed import TRACKED_CURRENCIES
  from sentiment import _CURRENCY_KEYWORDS, _COT_CONTRACT_NAMES
  from scheduler import _INVERSE_EVENTS
  from learning import build_features, predict_strength
  from indicators import build_composite_score
  from api import app
  print('CURRENCIES:', CURRENCIES)
  print('EVENTS count:', len(EVENTS))
  print('CANONICAL_PAIRS count:', len(CANONICAL_PAIRS))
  print('TRACKED_CURRENCIES:', TRACKED_CURRENCIES)
  print('All good — USD only')
  "
  ```
  Expected: No import errors. CURRENCIES=['USD'], EVENTS count ~27, CANONICAL_PAIRS count=8.

---

- [ ] **Step 6 — Remove multi-currency UI from `frontend/src/App.tsx`**

  **What:** Drop the currency filter chips and their state. Simplify page components. This is a pure UI change with no backend coupling.

  **Changes:**
  1. Delete `const ALL_CCYS = [...]` and `const LS_KEY = 'macro_currency_filter'`
  2. Delete `CurrencyFilter` component entirely
  3. In `App()` root component:
     - Remove `ccySel` state and `toggleCcy` callback
     - Remove `ls()` / `saveLs()` calls for the filter
     - Remove `<CurrencyFilter .../>` from the JSX render
     - Pass no `ccySel` prop to page components (remove the prop)
  4. In `HomePage`: remove `ccySel` prop; the `nextEvent` memo currently filters `events.filter(e => ccySel.includes(e.currency))` — change to `events` directly (all events will be USD anyway)
  5. In `CalendarPage`: remove `ccySel` prop; the `filtered` memo currently filters by `ccySel.includes(e.currency)` — change to `events` directly
  6. In `ModelPage`: remove `ccySel` prop; remove `filtModels`/`filtTrend`/`filtMistakes` filter memos — use `models`/`trend`/`mistakes` directly
  7. In `TrackPage`: remove `ccySel` prop; remove `filtered` currency filter memo — use `history` directly

  **Files:** `frontend/src/App.tsx`

  **Verify:** 
  ```
  cd c:\Users\TITANFXSAGE\Desktop\macro-predictor\frontend
  npm run build
  ```
  Build should complete with zero TypeScript errors and no warnings about undefined `ccySel`.

---

- [ ] **Step 7 — Confirm Telegram alerts scope (read-only verification)**

  **What:** The user asked to confirm alerts already only cover USD events. No code change needed — this is a verification step only.

  **Evidence already found in audit:**
  - `alerts.py` sends alerts for whatever `pred_result` it receives from `scheduler.py`
  - `scheduler.py:check_and_alert_upcoming()` iterates events from `fetch_upcoming_red_folder_events()`
  - After Step 2, `fetch_upcoming_red_folder_events()` returns only USD (HIGH/MEDIUM) events
  - Therefore alerts are automatically USD-only after Step 2. No change needed in `alerts.py`.

  **Verify:** `python -c "from alerts import send_telegram_alert; print('alerts.py imports clean')"` — should print clean. Review `alerts.py` manually to confirm no hard-coded non-USD currency references.

---

## 5. Files to Change — Summary

| File | Changes needed | Complexity |
|---|---|---|
| `config/events.py` | CURRENCIES, CANONICAL_PAIRS, RATE_SERIES, COT_CODES, RSS_FEEDS, delete ~31 EVENTS blocks | Medium |
| `calendar_feed.py` | TRACKED_CURRENCIES, FF_EVENT_MAP, _COUNTRY_DISAMBIG, _resolve fallback dict | Medium |
| `sentiment.py` | _CURRENCY_KEYWORDS, _COT_CONTRACT_NAMES | Trivial |
| `scheduler.py` | _INVERSE_EVENTS | Trivial |
| `frontend/src/App.tsx` | Remove CurrencyFilter component, ccySel state, filter memos | Small |

## 6. Files That Need NO Changes

`database.py`, `learning.py`, `indicators.py`, `api.py`, `data_sources.py`, `alerts.py`, `price_data.py`

---

## 7. Risk Notes

1. **Existing DB rows for non-USD currencies** — `currency_strengths`, `rate_differentials`, `cot_snapshots`, `sentiment_snapshots`, `river_model_state` tables may have EUR/GBP/etc. rows from the multi-currency build. These are harmless (never queried) but can be cleaned with `DELETE FROM <table> WHERE currency != 'USD'` if desired. Not required for correctness.

2. **`calendar_cache.json`** — The disk cache file may contain non-USD events from prior fetches. It will be overwritten on the next successful FF fetch. If the app starts before a successful fetch, the old cache events will be served but filtered by `TRACKED_CURRENCIES = {"USD"}` in-memory — so non-USD events will be silently dropped. **No action needed**, but noting it.

3. **No config/events.py `get_event_config()` call will break** — The function raises a `KeyError` for unknown event codes. After removing non-USD events, any non-USD event code passed to it (from old DB rows or stale cache) will raise. The existing `try/except` wrappers in `scheduler.py` and `api.py` catch these gracefully. **No code change needed**, but the audit confirms the safety net exists.
