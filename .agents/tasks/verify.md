# Verification Note — Simplified Prediction Output

## What Passed

1. **`config/events.py`** — All trade_signals extended to 7 majors per currency:
   - Verified with: `python -c "from config.events import EVENTS, CANONICAL_PAIRS; errors = [(k,d,len(v)) for k,ev in EVENTS.items() for d,v in ev.get('trade_signals',{}).items() if d != 'INLINE' and v != ['WAIT / NO BIAS'] and len(v) < 7]; print('Short lists:', errors[:5] if errors else 'ALL OK')"`
   - Result: `Short lists: ALL OK`
   - `CANONICAL_PAIRS` extended from 13 to 29 pairs.
   - `CHF_CPI` `if False else` bug fixed.
   - US500/US30 equity index signals removed from all trade_signals.

2. **`alerts.py`** — Verified new format output:
   ```
   📊 *PRE-RELEASE SIGNAL — NFP*
   NFP → 🔴 SELL USD
   Confidence: `67%` `██████░░░░`
   🎯 *Affected majors:*
   `SELL USD/JPY` • `SELL USD/CHF` • `SELL USD/CAD` • `BUY EUR/USD` • `BUY GBP/USD` • `BUY AUD/USD` • `BUY XAU/USD`
   🕐 Release: `13:30 UTC (in 94m)`
   ─────────────────────
   📋 *Indicator Details*
   • ❌ BEARISH  `z=-1.42`  _ADP Private Payrolls — direct private jobs proxy_
   • ❌ BEARISH  `z=-0.87`  _4-Week Avg Initial Jobless Claims — rising = soft …_
   • ⚪ NEUTRAL  `z=+0.12`  _ISM Mfg Employment Sub-index — factory hiring_
   • ❌ BEARISH  `z=-0.55`  _Services Employment — services hiring proxy_
   • ❌ BEARISH  `z=-0.33`  _Layoffs and Discharges — corporate layoffs signal_
   ─────────────────────
   ⚠️ _Signal is probabilistic. Apply your own risk management._
   ```
   - Removed: Composite Score, Outlook paragraph, "Pairs to be Affected" block, "Trade Execution Signals" block, `default_pairs` fallback dict, `extracted_pairs` regex.
   - Trade signals sourced exclusively from `config/events.py`.

3. **`scheduler.py`** — `pred_result["trade_signals"]` injected from events.py before `send_telegram_alert()`. Syntax verified clean.

4. **`frontend/src/App.tsx`** — TypeScript build passes 0 errors:
   - `StoredPred` interface extended with `trade_signals: string[]`
   - `ALL_PAIRS` extended from 13 to 29 pairs
   - `SigCard` redesigned:
     - Default view: header, confidence bar, "Affected majors" line, outcome badge, Details toggle + Refresh
     - "Details ▼" reveals: pair chips, order suggestions, indicator list
     - Pair chips and order suggestions removed from default view
     - `was_correct` outcome badge: ✓ Correct (green) / ✗ Incorrect (red) / nothing
   - Build: `npm run build` → `✓ built in 9.22s`, 0 TypeScript errors

5. **`frontend/src/App.css`** — New CSS classes added:
   - `.sc-majors`, `.sc-majors-lbl`, `.sc-majors-val`
   - `.sc-outcome`, `.sc-outcome-ok`, `.sc-outcome-err`
   - `.sc-actions`, `.sc-detail`

## NFP Example Output

### Telegram Alert (new format)
```
📊 *PRE-RELEASE SIGNAL — NFP*

NFP → 🔴 SELL USD
Confidence: `67%` `██████░░░░`

🎯 *Affected majors:*
`SELL USD/JPY` • `SELL USD/CHF` • `SELL USD/CAD` • `BUY EUR/USD` • `BUY GBP/USD` • `BUY AUD/USD` • `BUY XAU/USD`

🕐 Release: `13:30 UTC (in 94m)`
─────────────────────
📋 *Indicator Details*
• ❌ BEARISH  `z=-1.42`  _ADP Private Payrolls — direct private jobs proxy_
• ❌ BEARISH  `z=-0.87`  _4-Week Avg Initial Jobless Claims — rising = soft labor_
• ⚪ NEUTRAL  `z=+0.12`  _ISM Mfg Employment Sub-index — factory hiring_
• ❌ BEARISH  `z=-0.55`  _Services Employment — services hiring proxy_
• ❌ BEARISH  `z=-0.33`  _Layoffs and Discharges — corporate layoffs signal_
─────────────────────
⚠️ _Signal is probabilistic. Apply your own risk management._
```

### Signals Tab — SigCard (new layout)

**Default view:**
```
┌──────────────────────────────────────────┐
│ 🇺🇸 USD  08:31              [BEARISH]   │
│ Non-Farm Payrolls                        │
│ 67.0%  ██████░░░░                        │
│ Affected majors: SELL USD/JPY • SELL     │
│ USD/CHF • SELL USD/CAD • BUY EUR/USD •  │
│ BUY GBP/USD • BUY AUD/USD • BUY XAU/USD │
│                                          │
│ [Details ▼]               [Refresh]     │
└──────────────────────────────────────────┘
```

**After tapping "Details ▼":**
```
┌──────────────────────────────────────────┐
│ … (same header as above) …               │
│ [Details ▲]                              │
│ ─────────────────────────                │
│ [EURUSD BUY 62%] [GBPUSD BUY 65%]       │
│ [USDJPY SELL 67%] ...                    │
│ ▼ ADP Private Payrolls          z=-1.42  │
│ ▼ 4-Wk Avg Initial Claims       z=-0.87  │
│ ● ISM Mfg Employment            z=+0.12  │
│ ▼ Services Employment           z=-0.55  │
│ ▼ Layoffs & Discharges          z=-0.33  │
└──────────────────────────────────────────┘
```

## learn_one() Fires on Both Outcomes — Code Reference

**`scheduler.py` (post-release grading block, line ~297):**
```python
was_correct, verdict_msg = grade_prediction(code, lean, actual, forecast)
# ... update DB ...
# ── River learn_one() — fires on ALL graded predictions ────
# is_pre_release_prediction only gates accuracy DISPLAY,
# not training — every real outcome is valid training data.
try:
    ...
    outcome = lean_to_outcome(lean, was_correct)
    stats   = learn_one(currency, features, outcome)
```

`learn_one()` is called unconditionally after `grade_prediction()` — NOT gated behind `if was_correct:`. The comment in the code explicitly states "fires on ALL graded predictions".

The same unconditional pattern exists in `api.py`'s `sync_actuals_from_feed` endpoint.

## Files Changed

| File | Changes |
|------|---------|
| `config/events.py` | Extended `CANONICAL_PAIRS` (13→29 pairs); all `trade_signals` extended to 7 majors; `CHF_CPI` if-False bug fixed; US500/US30 removed |
| `alerts.py` | Complete rewrite of `_format_prediction_message()`; removed default_pairs/regex; new clean format |
| `scheduler.py` | Added `pred_result["trade_signals"]` injection before `send_telegram_alert()` |
| `frontend/src/App.tsx` | Extended `ALL_PAIRS`; `StoredPred` interface + `trade_signals`; `SigCard` redesigned |
| `frontend/src/App.css` | Added `.sc-majors`, `.sc-outcome`, `.sc-actions`, `.sc-detail` classes |
