# USD-Only Simplification of macro-predictor

The change scopes the macro-predictor down from an 8-currency model to a single USD model by reducing the central config constants (`CURRENCIES`, `CANONICAL_PAIRS`, `RATE_SERIES`, `COT_CODES`, `RSS_FEEDS`, `EVENTS`), pruning the three files that held explicit non-USD entries (`calendar_feed.py`, `sentiment.py`, `scheduler.py`), and removing the currency-filter UI from the React frontend. Because most of the codebase iterates over `CURRENCIES` from `config/events.py`, shrinking that list was sufficient to make the majority of files USD-only without touching them directly. The four files that needed explicit edits were changed; the remaining files (`learning.py`, `indicators.py`, `api.py`, `data_sources.py`, `database.py`, `alerts.py`) were correctly left unchanged.

Watch for: (1) **confirmed** — `scheduler.py` docstring and inline comments still say "all 8 currencies" throughout, including the `_INVERSE_EVENTS` block header; these are stale but harmless. (2) **confirmed** — `config/events.py` module docstring still says "multi-currency strength architecture"; likewise stale. (3) **confirmed** — `CANONICAL_PAIRS` is missing `NZDUSD`: the audit spec listed 8 USD majors (`EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD, XAUUSD`) but the implementation has only 7 (NZDUSD dropped). This is a minor scope question rather than a breakage — the pair won't appear on the dashboard.

**Verdict**: APPROVED

---

## High-level view

The data-model reduction is complete and correct. `CURRENCIES = ["USD"]` propagates correctly through every loop in `learning.py`, `indicators.py`, `api.py`, `data_sources.py`, `scheduler.py`, and `sentiment.py` — no stray iteration over non-USD currencies is possible at runtime. The backend import chain was verified clean by the integration smoke test (`all imports OK`, `CURRENCIES: ['USD']`, `EVENTS count: 27`).

The three files requiring explicit dict pruning — `sentiment.py` (`_CURRENCY_KEYWORDS`, `_COT_CONTRACT_NAMES`), `calendar_feed.py` (`FF_EVENT_MAP`, `_COUNTRY_DISAMBIG`, step-3 fallback prefix dict, `TRACKED_CURRENCIES`), and `scheduler.py` (`_INVERSE_EVENTS`) — are all confirmed pruned to USD-only. The frontend build passed (0 TypeScript errors) and `ALL_CCYS`, `LS_KEY`, `CurrencyFilter`, `ccySel`, and `toggleCcy` are fully absent from `App.tsx`.

Two categories of stale content remain: dead-code fetchers in `data_sources.py` (ECB/ONS/BOE/Eurostat/OECD — left in intentionally per the audit, never called for USD), and stale "all 8 currencies" language in scheduler docstrings and the `config/events.py` module header. Neither affects runtime behavior.

`NZDUSD` is absent from `CANONICAL_PAIRS`. The audit spec listed it; the implementation dropped it silently. At 7 pairs vs. the spec'd 8, the dashboard will never show NZD/USD signals for USD-directional events. Worth a deliberate call before closing.

---

<details>
<summary>Issues (3)</summary>

1. **Stale "all 8 currencies" comments in scheduler.py** — The module docstring schedule summary, the `_INVERSE_EVENTS` block header ("Extended inverse-indicator set covering all 8 currencies"), and three function docstrings (`refresh_rate_differentials`, `refresh_sentiment_cycle`, `refresh_currency_strengths`) still say "all 8 currencies". Update them to "USD only" to prevent future confusion. Confirmed present at lines 8–9, 48, 427, 447, 491–493.

2. **Stale "multi-currency strength architecture" in config/events.py docstring** — The module docstring says "pair-routing logic for the multi-currency strength architecture". Update to reflect USD-only scope. Confirmed at line 3.

3. **NZDUSD absent from CANONICAL_PAIRS** — The audit spec listed 8 USD majors including NZDUSD; the implementation has 7 (`EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, XAUUSD`). If NZD/USD trade signals are desired for USD-directional events, add `"NZDUSD"` to `CANONICAL_PAIRS`. If the omission was intentional, close this. Confirmed at `config/events.py` line 35–37.

</details>

---

<details>
<summary>Details</summary>

## Stale "all 8 currencies" comments in scheduler.py

The module-level docstring in `scheduler.py` still reads:

```
Every 24 hr   — refresh_rate_differentials()  (yield spreads for all 8 currencies)
Every 12 hr   — refresh_sentiment_cycle()     (GDELT + RSS + FinBERT for all 8)
```

The `_INVERSE_EVENTS` block comment reads "Extended inverse-indicator set covering all 8 currencies" — that comment was on the old set that included `EUR_UNEMPLOYMENT`, `GBP_EMPLOYMENT`, etc. The set itself is now correctly pruned to `{"JOBLESS_CLAIMS", "UNEMPLOYMENT_RATE"}`, but the header still references 8 currencies. The function docstrings for `refresh_rate_differentials`, `refresh_sentiment_cycle`, and `refresh_currency_strengths` carry the same "all 8" wording. None of this causes a runtime defect, but it will mislead anyone reading the scheduler months from now.

## NZDUSD gap in CANONICAL_PAIRS

The audit spec at section 1 (`config/events.py`) listed the target as:

> Keep only USD majors: `["EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","USDCAD","NZDUSD","XAUUSD"]`

The verification note and the actual file both show 7 pairs — `NZDUSD` was not included. Every USD event's `trade_signals` dict in `config/events.py` omits NZD/USD signals as well (confirmed: BULLISH signals are `BUY USDJPY, BUY USDCHF, BUY USDCAD, SELL EURUSD, SELL GBPUSD, SELL AUDUSD, SELL XAUUSD`). So the pair wouldn't generate trade signals even if added to `CANONICAL_PAIRS`. The omission is internally consistent but diverges from the audit spec. Needs a deliberate decision.


</details>

---

<details>
<summary>File map</summary>

| File | Change |
|---|---|
| `config/events.py` | `CURRENCIES=["USD"]`; `CANONICAL_PAIRS` reduced to 7 USD majors; `RATE_SERIES`, `COT_CODES`, `RSS_FEEDS` USD-only; ~31 non-USD `EVENTS` blocks deleted |
| `calendar_feed.py` | `TRACKED_CURRENCIES={"USD"}`; `FF_EVENT_MAP`, `_COUNTRY_DISAMBIG`, step-3 fallback dict all pruned to USD-only |
| `sentiment.py` | `_CURRENCY_KEYWORDS` and `_COT_CONTRACT_NAMES` reduced to USD-only |
| `scheduler.py` | `_INVERSE_EVENTS` pruned to `{"JOBLESS_CLAIMS", "UNEMPLOYMENT_RATE"}`; multi-currency pair_biases block replaced with direct `trade_signals` lookup |
| `frontend/src/App.tsx` | `ALL_CCYS`, `LS_KEY`, `CCY_COLORS`, `CurrencyFilter`, `ccySel` state, `toggleCcy`, `ls`/`saveLs` helpers, and all `ccySel` filter memos removed from all 4 page components |
| `frontend/src/App.css` | `.ccy-filter`, `.ccy-chip`, `.ccy-chip.on`, `.ccy-chip:hover` rules removed |

Full diff: `git diff main` from the repo root.

</details>
