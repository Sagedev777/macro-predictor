# Implementation Plan — Simplified Prediction Output & Lifecycle Audit

---

## Findings from Code Audit

### End-to-End Lifecycle — Current Status

**(a) Data gathering before release** ✅ Already correct  
`scheduler.py → check_and_alert_upcoming()`: when `0 < hours_until <= hours_before+0.5`, it calls `build_composite_score(code)` (which pulls FRED/ECB/ONS indicators), fetches `get_latest_currency_strengths()` (rate diff + COT + sentiment from DB), and stores a `Prediction` row — all before release. No change needed.

**(b) Prediction generated and stored** ✅ Already correct  
The pre-release block in `check_and_alert_upcoming()` writes a `PredictionModel` row via `db.add()` + `db.commit()`. The `pair_signals` column stores the JSON pair bias list. No change needed.

**(c) `grade_prediction()` fires after release** ✅ Already correct  
The post-release block in `check_and_alert_upcoming()` calls `grade_prediction(code, lean, actual, forecast)` and writes `was_correct`, `actual`, `forecast`, `surprise` back to the prediction row. Same in `sync_actuals_from_feed()` in `api.py`. No change needed.

**(d) `learn_one()` fires regardless of outcome** ✅ Already correct  
Both call sites (`scheduler.py` post-release block and `api.py` `sync_actuals_from_feed`) call `learn_one()` unconditionally after `grade_prediction()`. The comment in `database.py` explicitly states `learn_one()` fires on ALL graded predictions. No change needed.

**(e) Simplified output format reaches Telegram and Signals tab** ❌ Needs fix  
- **Telegram (`alerts.py`):** Currently shows Macro Bias, Event Lean, Composite Score, Outlook paragraph, a "Pairs to be Affected" block, Trade Execution Signals block, then the full indicator breakdown as the main body. The clean `NFP → SELL USD` format is not implemented.
- **Signals tab (`SigCard` in `App.tsx`):** Currently shows pair signal chips (`chip-row`) directly in the card body, and the indicator list is behind a "Show indicators" toggle — but the pair chips are NOT behind that toggle (always visible). The pair chips come from the full `pair_biases` computation (all 13 canonical pairs filtered by currency), not from the event's `trade_signals` in `events.py`.

### config/events.py — trade_signals Audit

The trade_signals format is already `'BUY USDJPY'` / `'SELL EURUSD'` (no slash) — correct convention.

USD events: Most have only 3–4 pairs (e.g. NFP: BULLISH has `["BUY USDJPY", "SELL EURUSD", "SELL GBPUSD", "SELL XAUUSD"]` — 4 pairs). The spec requires 7 per USD event. Several events need their lists extended with the missing 3 USD majors: `USDCHF`, `AUDUSD`, `USDCAD`.

EUR events: Most have 2–3 pairs. Missing: EURCAD, EURAUD, EURNZD for most EUR events.

GBP events: Missing: GBPCHF, GBPAUD, GBPCAD, GBPNZD for most events.

JPY events: Most have 3–4 pairs. Missing: AUDJPY, CADJPY, NZDJPY for many.

AUD events: Missing: EURAUD, GBPAUD, AUDCHF, AUDNZD for most.

CAD events: Missing: EURCAD, GBPCAD, AUDCAD, CADCHF, NZDCAD for most.

CHF events: Missing: EURCHF, GBPCHF, AUDCHF, CADCHF, NZDCHF for most. **Note:** `CHF_CPI` has a bug: `"BUY USDCHF" if False else "SELL USDCHF"` — this evaluates to just `"SELL USDCHF"`, which is correct but written incorrectly.

NZD events: Only 2 pairs each. Missing 5 of 7.

### alerts.py — Trade Signals Source

`alerts.py` currently has a **hardcoded `default_pairs` dict** (e.g. `"NFP": ["EURUSD", "USDJPY", "GBPUSD", "XAUUSD"]`) used as a fallback, and separately extracts pairs from `trade_signals`. The affected-pairs list should come exclusively from `trade_signals` in `events.py` (no hardcoded fallback). This needs to change.

### SigCard — pair_signals source

`pair_signals` stored in the DB comes from `compute_all_pair_biases(strengths)` filtered by currency — this gives ALL canonical pairs for that currency (up to 7 from the 13 CANONICAL_PAIRS list), not from `trade_signals`. After fixing `events.py` to have 7 pairs, the pre-release alert path in `scheduler.py` should be updated to read pair signals from `events.py trade_signals` instead of (or in addition to) the bias grid.

---

## Implementation Plan

- [ ] 1. **Extend `trade_signals` in `config/events.py` to 7 majors per currency event**

  Fill out every event's `BULLISH` and `BEARISH` `trade_signals` lists to the full 7 relevant majors. Direction rules: if currency is BASE in a pair, BULLISH = BUY; if QUOTE, BULLISH = SELL (the pair rises when base strengthens). INLINE stays `["WAIT / NO BIAS"]`.
  
  Use the instrument format already in use (no slash, e.g. `USDJPY`, `EURUSD`).

  **USD events** — standard 7 pairs: `EURUSD`, `GBPUSD`, `USDJPY`, `USDCHF`, `AUDUSD`, `USDCAD`, `XAUUSD`  
  BULLISH direction: `["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"]`  
  BEARISH direction: `["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"]`

  Apply this full 7-pair list to ALL USD events: `NFP`, `CPI`, `CORE_CPI`, `PPI`, `JOBLESS_CLAIMS`, `UNEMPLOYMENT_RATE`, `CONSUMER_CONFIDENCE`, `FOMC`, `RETAIL_SALES`, `ISM_MFG`, `GDP`, `CORE_PPI`, `CORE_RETAIL_SALES`, `ISM_SERVICES`, `AVG_HOURLY_EARNINGS`, `ADP_NFP`, `JOLTS`, `CORE_PCE`, `PCE`, `BUILDING_PERMITS`, `HOUSING_STARTS`, `DURABLE_GOODS`, `TRADE_BALANCE`, `INDUSTRIAL_PRODUCTION`, `EMPIRE_STATE`, `PHILLY_FED`, `GDP_DEFLATOR`.  
  _(Some events add equity indices like US500/US30 — keep those as extra entries beyond the 7 core forex pairs.)_

  **EUR events** — 7 pairs: `EURUSD`, `EURGBP`, `EURJPY`, `EURCHF`, `EURAUD`, `EURCAD`, `EURNZD`  
  BULLISH: `["BUY EURUSD", "BUY EURGBP", "BUY EURJPY", "BUY EURCHF", "BUY EURAUD", "BUY EURCAD", "BUY EURNZD"]`  
  BEARISH: `["SELL EURUSD", "SELL EURGBP", "SELL EURJPY", "SELL EURCHF", "SELL EURAUD", "SELL EURCAD", "SELL EURNZD"]`  
  Apply to: `EUR_CPI`, `EUR_CORE_CPI`, `EUR_GDP`, `ECB_RATE`, `EUR_PMI_MFG`, `EUR_PMI_SERVICES`, `EUR_UNEMPLOYMENT`, `GERMAN_IFO`, `GERMAN_ZEW`.

  **GBP events** — 7 pairs: `GBPUSD`, `GBPJPY`, `EURGBP`, `GBPCHF`, `GBPAUD`, `GBPCAD`, `GBPNZD`  
  BULLISH: `["BUY GBPUSD", "BUY GBPJPY", "BUY GBPCHF", "BUY GBPAUD", "BUY GBPCAD", "BUY GBPNZD", "SELL EURGBP"]`  
  BEARISH: `["SELL GBPUSD", "SELL GBPJPY", "SELL GBPCHF", "SELL GBPAUD", "SELL GBPCAD", "SELL GBPNZD", "BUY EURGBP"]`  
  Apply to: `GBP_CPI`, `GBP_CORE_CPI`, `GBP_GDP`, `BOE_RATE`, `GBP_EMPLOYMENT`, `GBP_PMI_MFG`, `GBP_RETAIL_SALES`.

  **JPY events** — 7 pairs: `USDJPY`, `EURJPY`, `GBPJPY`, `AUDJPY`, `CADJPY`, `CHFJPY`, `NZDJPY`  
  BULLISH (JPY strengthens = all JPY pairs fall): `["SELL USDJPY", "SELL EURJPY", "SELL GBPJPY", "SELL AUDJPY", "SELL CADJPY", "SELL CHFJPY", "SELL NZDJPY"]`  
  BEARISH (JPY weakens = all JPY pairs rise): `["BUY USDJPY", "BUY EURJPY", "BUY GBPJPY", "BUY AUDJPY", "BUY CADJPY", "BUY CHFJPY", "BUY NZDJPY"]`  
  Apply to: `JPY_CPI`, `BOJ_RATE`, `JAPAN_GDP`, `JAPAN_TANKAN`.

  **AUD events** — 7 pairs: `AUDUSD`, `AUDJPY`, `EURAUD`, `GBPAUD`, `AUDCAD`, `AUDCHF`, `AUDNZD`  
  BULLISH: `["BUY AUDUSD", "BUY AUDJPY", "BUY AUDCAD", "BUY AUDCHF", "BUY AUDNZD", "SELL EURAUD", "SELL GBPAUD"]`  
  BEARISH: `["SELL AUDUSD", "SELL AUDJPY", "SELL AUDCAD", "SELL AUDCHF", "SELL AUDNZD", "BUY EURAUD", "BUY GBPAUD"]`  
  Apply to: `AUD_CPI`, `RBA_RATE`, `AUD_EMPLOYMENT`, `AUD_RETAIL_SALES`.

  **CAD events** — 7 pairs: `USDCAD`, `EURCAD`, `GBPCAD`, `AUDCAD`, `CADJPY`, `CADCHF`, `NZDCAD`  
  BULLISH (CAD strengthens): `["SELL USDCAD", "SELL EURCAD", "SELL GBPCAD", "SELL AUDCAD", "SELL NZDCAD", "BUY CADJPY", "BUY CADCHF"]`  
  BEARISH (CAD weakens): `["BUY USDCAD", "BUY EURCAD", "BUY GBPCAD", "BUY AUDCAD", "BUY NZDCAD", "SELL CADJPY", "SELL CADCHF"]`  
  Apply to: `CAD_CPI`, `BOC_RATE`, `CAD_EMPLOYMENT`, `CAD_GDP`.

  **CHF events** — 7 pairs: `USDCHF`, `EURCHF`, `GBPCHF`, `AUDCHF`, `CHFJPY`, `CADCHF`, `NZDCHF`  
  BULLISH (CHF strengthens): `["SELL USDCHF", "SELL EURCHF", "SELL GBPCHF", "SELL AUDCHF", "SELL CADCHF", "SELL NZDCHF", "BUY CHFJPY"]`  
  BEARISH (CHF weakens): `["BUY USDCHF", "BUY EURCHF", "BUY GBPCHF", "BUY AUDCHF", "BUY CADCHF", "BUY NZDCHF", "SELL CHFJPY"]`  
  Apply to: `CHF_CPI` (also fix the `if False else` bug — replace the current malformed `trade_signals` dict), `SNB_RATE`, `CHF_UNEMPLOYMENT`.

  **NZD events** — 7 pairs: `NZDUSD`, `EURNZD`, `GBPNZD`, `AUDNZD`, `NZDJPY`, `NZDCAD`, `NZDCHF`  
  BULLISH: `["BUY NZDUSD", "BUY NZDJPY", "BUY NZDCAD", "BUY NZDCHF", "SELL EURNZD", "SELL GBPNZD", "SELL AUDNZD"]`  
  BEARISH: `["SELL NZDUSD", "SELL NZDJPY", "SELL NZDCAD", "SELL NZDCHF", "BUY EURNZD", "BUY GBPNZD", "BUY AUDNZD"]`  
  Apply to: `NZD_CPI`, `RBNZ_RATE`, `NZD_EMPLOYMENT`.

  Also update `CANONICAL_PAIRS` to include the new pairs needed for the 7-major logic. The current list is:
  ```python
  CANONICAL_PAIRS = [
      "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD",
      "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY",
      "AUDJPY", "CADJPY", "XAUUSD",
  ]
  ```
  Extend to include all pairs referenced in any `trade_signals` entry:
  ```python
  CANONICAL_PAIRS = [
      # USD majors
      "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "XAUUSD",
      # EUR crosses
      "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD",
      # GBP crosses
      "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD", "GBPNZD",
      # JPY crosses
      "AUDJPY", "CADJPY", "CHFJPY", "NZDJPY",
      # AUD crosses
      "AUDCAD", "AUDCHF", "AUDNZD",
      # CAD crosses
      "CADCHF", "NZDCAD",
      # CHF/NZD
      "NZDCHF",
  ]
  ```

  **Files:** `config/events.py`  
  **Verify:** `python -c "from config.events import EVENTS; errors = [(k,d,len(v)) for k,ev in EVENTS.items() for d,v in ev.get('trade_signals',{}).items() if d != 'INLINE' and v != ['WAIT / NO BIAS'] and len(v) < 7]; print('Short lists:', errors[:5] if errors else 'ALL OK')"` — should print `ALL OK`.

---

- [ ] 2. **Rewrite `alerts.py` — new Telegram format**

  Replace `_format_prediction_message()` with the new clean format. The `send_telegram_alert()` function signature stays unchanged.

  New message structure:
  ```
  📊 *PRE-RELEASE SIGNAL — NFP*

  NFP → 🔴 SELL USD
  Confidence: `67%` `██████░░░░`

  🎯 *Affected majors:*
  `SELL EURUSD` • `SELL GBPUSD` • `BUY USDJPY` • `BUY USDCHF` • `SELL AUDUSD` • `BUY USDCAD` • `SELL XAUUSD`

  🕐 Release: `13:30 UTC (in 94m)`
  ─────────────────────
  📋 *Indicator Details*
  • ❌ BEARISH  z=-1.42  _ADP Private Payrolls — direct private jobs proxy_
  • ❌ BEARISH  z=-0.87  _4-Week Avg Initial Jobless Claims — rising = soft labor_
  • ⚪ NEUTRAL  z=+0.12  _ISM Mfg Employment Sub-index — factory hiring_
  • ❌ BEARISH  z=-0.55  _Services Employment — services hiring proxy_
  • ❌ BEARISH  z=-0.33  _Layoffs & Discharges — corporate layoffs signal_
  ─────────────────────
  ⚠️ _Signal is probabilistic. Apply your own risk management._
  ```

  Key implementation rules:
  - The header line is: `{event_code} → {direction_emoji} {direction_label} {currency}`  
    where `direction_label` = `BUY` if BULLISH, `SELL` if BEARISH, `HOLD` if INLINE; `{currency}` from `event_cfg["currency"]`.
  - Direction emoji: `🟢` for BULLISH/BUY, `🔴` for BEARISH/SELL, `🟡` for INLINE.
  - **Affected majors line**: read directly from `event_cfg["trade_signals"][dir_key]` — format each entry as a backtick string (`` `BUY USDJPY` ``), joined by ` • `. Do NOT use the `default_pairs` fallback dict — delete it entirely.
  - **Remove:** Composite Score line, Outlook/explanation paragraph, separate "Pairs to be Affected" block, separate "Trade Execution Signals" block. These are all replaced by the single "Affected majors" line.
  - **Keep but move after a divider:** The indicator breakdown, now under `📋 *Indicator Details*`.
  - Remove the `release_time` from after the confidence bar; move it to before the divider.
  - The `send_telegram_alert()` function receives `pred_result` which has `event_code`, `lean_direction`, `confidence_pct`, `indicator_breakdown`, and `trade_signals` (already set by the caller). If `trade_signals` is missing from the dict, look it up from `EVENTS` using `dir_key`.

  **Files:** `alerts.py`  
  **Verify:** `python -c "from alerts import _format_prediction_message; p={'event_code':'NFP','lean_direction':'MISS','confidence_pct':67.0,'composite_score':-0.4,'indicator_breakdown':[{'description':'ADP','z_score':-1.42,'signal':-1,'weight':0.3}],'trade_signals':['SELL USDJPY','BUY EURUSD','BUY GBPUSD','SELL USDCHF','BUY AUDUSD','SELL USDCAD','BUY XAUUSD']}; msg=_format_prediction_message(p,'13:30'); print(msg)"` — output should start with `📊 *PRE-RELEASE SIGNAL — NFP*`, have an `NFP → 🔴 SELL USD` line, an `Affected majors:` line with 7 pairs, and a `📋 *Indicator Details*` section.

---

- [ ] 3. **Update `scheduler.py` — pass `trade_signals` from `events.py` to the Telegram alert**

  The pre-release alert path in `check_and_alert_upcoming()` calls `send_telegram_alert(pred_result, release_time=...)`. Currently `pred_result` comes from `build_composite_score(code)` which does NOT include `trade_signals`. The new format requires `trade_signals` to be in `pred_result`.

  After `pred_result = build_composite_score(code)` and `event_cfg = get_event_config(code)`, add:
  ```python
  dir_key = (
      "BULLISH" if pred_result["lean_direction"] in ("BEAT", "BULLISH") else
      "BEARISH" if pred_result["lean_direction"] in ("MISS", "BEARISH") else
      "INLINE"
  )
  pred_result["trade_signals"] = event_cfg.get("trade_signals", {}).get(dir_key, [])
  ```
  Place this before the `send_telegram_alert(pred_result, ...)` call.

  **Files:** `scheduler.py`  
  **Verify:** `python -c "from scheduler import grade_prediction; ok,msg = grade_prediction('NFP','BEARISH',180000,190000); print(ok, msg[:40])"` — should print `False Market surprised...` confirming the module imports without error.

---

- [ ] 4. **Update `SigCard` in `frontend/src/App.tsx` — new card layout**

  **Current layout (what to change):**
  - Main card body: flag + currency + time, display name, direction tag, confidence bar, pair chip row (always visible), order suggestions, "Show indicators" toggle
  - Behind toggle: indicator list

  **New layout:**
  - Main card body: flag + currency + time, display name, direction tag, confidence bar, then a single "Affected majors" text line derived from `pred.trade_signals` (from the API response, which already carries `trade_signals` from `events.py`)
  - Behind "Show details" toggle (rename from "Show indicators"): pair chip row AND indicator list

  **Step-by-step changes to `SigCard`:**

  a) Read `trade_signals` from `pred`. The API response already includes `trade_signals` (a string array like `["BUY USDJPY", "SELL EURUSD", ...]`). Add it to the `StoredPred` interface:
  ```typescript
  interface StoredPred {
    // ... existing fields ...
    trade_signals: string[]
    order_suggestions: OrderSug[]
    indicators: Indicator[]
  }
  ```

  b) Build the "Affected majors" display string inside `SigCard`:
  ```typescript
  const affectedMajors = (pred.trade_signals ?? [])
    .filter(s => s !== 'WAIT / NO BIAS' && !s.startsWith('WAIT'))
    .map(s => {
      // Format: "BUY USDJPY" → "BUY USD/JPY" for display
      const parts = s.split(' ')
      const dir = parts[0]
      const sym = parts[1] ?? ''
      // Insert slash for 6-char forex pairs; leave XAUUSD, US500 etc as-is
      const fmtSym = sym.length === 6 && !sym.startsWith('XAU') && !sym.startsWith('US')
        ? `${sym.slice(0,3)}/${sym.slice(3)}`
        : sym
      return `${dir} ${fmtSym}`
    })
    .join(', ')
  ```

  c) Remove the `hasPairs` chip row block from the default card body. Replace with:
  ```tsx
  {affectedMajors && (
    <div className="sc-majors">
      <span className="sc-majors-lbl">Affected majors:</span>
      <span className="sc-majors-val">{affectedMajors}</span>
    </div>
  )}
  ```

  d) Move the pair chips inside the toggle section. The toggle button text changes from "Show indicators" → "Show details". The expanded section shows:
  - Pair chip row (if `hasPairs`)
  - Indicator list (if `pred.indicators?.length > 0`)

  e) Remove the order suggestions block from the default card body (move inside the toggle or remove entirely — the original brief says drop it from primary view; keep it in the collapsible if desired, or remove since it was already secondary).

  **After these changes the `SigCard` renders as:**
  ```
  ┌─────────────────────────────────┐
  │ 🇺🇸 USD  13:31  [BEARISH]       │
  │ Non-Farm Payrolls               │
  │ 67%  ██████░░░░                 │
  │ Affected majors: SELL EUR/USD,  │
  │ SELL GBP/USD, BUY USD/JPY, ...  │
  │ [Show details ▼]    [Refresh]   │
  └─────────────────────────────────┘
  ```
  Expanded "Show details":
  ```
  ┌─────────────────────────────────┐
  │ [pair chips: EURUSD SELL 67%…]  │
  │ ▼ ADP Private Payrolls  z=-1.42 │
  │ ▼ 4-Wk Jobless Claims   z=-0.87 │
  │ …                               │
  └─────────────────────────────────┘
  ```

  **Also update `ALL_PAIRS` constant and `PairFilter`** to reflect the extended `CANONICAL_PAIRS` (add the new cross pairs from step 1 so the Strength tab pair filter includes them). The new `ALL_PAIRS` should mirror the updated `CANONICAL_PAIRS` list from step 1.

  **Files:** `frontend/src/App.tsx`  
  **Verify:** `cd c:\Users\TITANFXSAGE\Desktop\macro-predictor\frontend && npm run build` — build completes with 0 errors (TypeScript type-checks pass).

---

- [ ] 5. **Add `sc-majors` CSS to the frontend stylesheet**

  The new `sc-majors` and `sc-majors-lbl` / `sc-majors-val` classes need styling. Find the existing stylesheet (likely `frontend/src/App.css` or similar) and add:
  ```css
  .sc-majors {
    padding: 4px 0 6px;
    font-size: 0.78rem;
    line-height: 1.5;
    color: var(--text-muted, #9ca3af);
  }
  .sc-majors-lbl {
    font-weight: 600;
    color: var(--text-secondary, #d1d5db);
    margin-right: 4px;
  }
  .sc-majors-val {
    color: var(--text-primary, #f3f4f6);
  }
  ```

  **Files:** `frontend/src/App.css` (verify path first — if `App.tsx` imports a different CSS file, use that one)  
  **Verify:** Included in the `npm run build` from step 4.

---

- [ ] 6. **Update `api.py` — include `trade_signals` in the `/api/predictions` list response**

  The `list_predictions()` endpoint already includes `trade_signals` (line ~774 in the file), but let me confirm the field is correctly populated in the stored prediction response used by `SigCard`. Looking at the code: yes, `trade_signals` is already in the response dict for both `/api/prediction/{code}` (GET) and `/api/predictions` (list). The field comes from `cfg.get("trade_signals", {}).get(p.lean_direction) or cfg.get("trade_signals", {}).get(dir_key, [])`.

  **Verify the normalization is correct:** The lean stored in the DB can be `"BEAT"` or `"BULLISH"` or `"MISS"` — the existing `dir_key` lookup normalizes this. No code change needed if the lookup is working. However, the `order_suggestions` field in the response is currently always populated (from `get_latest_suggestions(code)` in the single-prediction endpoint but NOT in the list endpoint). Since `SigCard` currently uses `order_suggestions`, and we're moving it behind the toggle, no API change is needed.

  **One real change needed:** The `pair_signals` stored in the DB (from the pre-release path in `scheduler.py`) comes from `compute_all_pair_biases` filtered by currency — this is the live pair bias grid, NOT the `trade_signals` from events.py. The `SigCard` should use `trade_signals` (from events.py config) for the "Affected majors" line and keep `pair_signals` only for the expanded chip row. This is already handled in step 4 (the `SigCard` reads `pred.trade_signals` for the majors line and `pred.pair_signals` for the chips). No API change needed — just confirm both fields exist in the response, which they do.

  **Files:** `api.py` — no changes needed  
  **Verify:** `python -c "import api; print('api imports OK')"` — should print `api imports OK` (imports cleanly after other changes are applied).

---

## NFP Example Output

### Telegram Alert (new format)

```
📊 *PRE-RELEASE SIGNAL — NFP*

NFP → 🔴 SELL USD
Confidence: `67%` `██████░░░░`

🎯 *Affected majors:*
`SELL EURUSD` • `SELL GBPUSD` • `BUY USDJPY` • `BUY USDCHF` • `SELL AUDUSD` • `BUY USDCAD` • `SELL XAUUSD`

🕐 Release: `13:30 UTC (in 94m)`
─────────────────────
📋 *Indicator Details*
• ❌ BEARISH  `z=-1.42`  _ADP Private Payrolls — direct private jobs proxy_
• ❌ BEARISH  `z=-0.87`  _4-Week Avg Initial Jobless Claims — rising = soft labor_
• ⚪ NEUTRAL  `z=+0.12`  _ISM Mfg Employment Sub-index — factory hiring_
• ❌ BEARISH  `z=-0.55`  _Services Employment — services hiring proxy_
• ❌ BEARISH  `z=-0.33`  _Layoffs & Discharges — corporate layoffs signal_
─────────────────────
⚠️ _Signal is probabilistic. Apply your own risk management._
```

### Signals Tab — SigCard (new layout)

**Default view (what's visible without tapping anything):**
```
┌──────────────────────────────────────────┐
│ 🇺🇸 USD  08:31              [BEARISH]   │
│ Non-Farm Payrolls                        │
│ 67%  ██████░░░░                          │
│ Affected majors: SELL EUR/USD,           │
│ SELL GBP/USD, BUY USD/JPY, BUY USD/CHF, │
│ SELL AUD/USD, BUY USD/CAD, SELL XAU/USD │
│                                          │
│ [Show details ▼]           [Refresh]    │
└──────────────────────────────────────────┘
```

**After tapping "Show details":**
```
┌──────────────────────────────────────────┐
│ … (same header as above) …               │
│ [Hide details ▲]                         │
│                                          │
│ Pair chips:                              │
│ [EURUSD SELL 67%] [GBPUSD SELL 65%]     │
│ [USDJPY BUY 62%]  [USDCHF BUY 58%]     │
│ [AUDUSD SELL 71%] [USDCAD BUY 60%]     │
│ [XAUUSD SELL 69%]                        │
│                                          │
│ ▼ ADP Private Payrolls          z=-1.42  │
│ ▼ 4-Wk Avg Initial Jobless Claims z=-0.87│
│ ● ISM Mfg Employment Sub-index  z=+0.12  │
│ ▼ Services Employment           z=-0.55  │
│ ▼ Layoffs & Discharges          z=-0.33  │
└──────────────────────────────────────────┘
```

*Values are illustrative. BEARISH lean means NFP is expected to miss consensus — ADP and claims data are showing labor softness. The 7 affected USD pairs all reflect the USD weakness theme.*

---

## Dependency Order

1 → 2 (alerts.py needs the full trade_signals lists from events.py)  
1 → 3 (scheduler needs the correct trade_signals to exist)  
1 → 4 (frontend uses trade_signals from the API which reads from events.py)  
4 → 5 (CSS is a dependency of the component change)  
6 is independent (confirmation only, no code change required)

Items 2, 3, 4, 5, 6 are independent of each other once item 1 is done.
