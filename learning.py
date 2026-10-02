"""
learning.py — Online/continuous learning engine using River's Adaptive Random Forest.

Architecture:
  - One ARFClassifier per currency (8 models total: USD, EUR, GBP, JPY, AUD, CHF, CAD, NZD)
  - Each model takes 4 feature signals as input:
        indicator_score   float [-1, +1]  — z-score aggregate from indicators.py
        rate_diff_score   float [-1, +1]  — yield spread from data_sources.py
        cot_score         float [-1, +1]  — COT net-long from sentiment.py
        sentiment_score   float [-1, +1]  — FinBERT net from sentiment.py
  - Output: predicted class (1=bullish, 0=bearish) + probability → strength score
  - ARF has native concept-drift detection (ADWIN per tree) — no manual decay needed

Seeding strategy (day-one, before any real learn_one() calls):
  - Feed synthetic "warm-up" observations built from current COT + rate differential
    so the model starts with "what the market already believes" as its prior
  - 10 synthetic samples per currency — low weight but enough to give ARF a
    directional starting point rather than a coin-flip

Persistence:
  - Model state serialised via pickle and stored in river_model_state table
  - database.upsert_river_model() / load_river_model() handle the DB I/O

Feature importance drift:
  - ARF does not expose built-in feature importances the way sklearn does
  - We track drift by logging the rolling correlation of each feature with
    correct predictions over the last N outcomes (sliding window)
  - Stored as JSON in river_model_state.feature_weights for dashboard display

Public interface:
  get_model(currency)                         → ARFClassifier (loads from DB or creates fresh)
  predict_strength(currency, features)        → StrengthPrediction
  learn_one(currency, features, outcome)      → updated model stats
  seed_models_with_priors()                   → seed all 8 models on first run
  get_all_strengths(feature_dict)             → dict[currency, StrengthPrediction]
  compute_pair_bias(base, quote, features)    → PairBias
  get_feature_importance_drift()              → dict[currency, dict]
"""

import json
import logging
import pickle
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

log = logging.getLogger("learning")

# ── Feature names (order matters — must match feature dicts throughout) ───────
FEATURE_NAMES = ["indicator_score", "rate_diff_score", "cot_score", "sentiment_score"]

# ── ARF hyperparameters ───────────────────────────────────────────────────────
# n_models=10 balances accuracy vs speed on a CPU-only server.
# drift_detector=ADWIN (default in River ARF) detects concept drift per tree.
# warning_detector=ADWIN triggers retraining before full drift confirmation.
ARF_N_MODELS       = 10
ARF_LAMBDA         = 6      # Poisson λ for online bagging weight
ARF_GRACE_PERIOD   = 50     # minimum samples before a split is considered
ARF_DELTA          = 1e-5   # ADWIN confidence — lower = more sensitive to drift

# ── Sliding window for feature correlation tracking ───────────────────────────
_DRIFT_WINDOW = 50   # last N learn_one() calls used for importance correlation

# ── Seeding parameters ────────────────────────────────────────────────────────
_SEED_SAMPLES = 10   # synthetic warm-up observations per currency


# ══════════════════════════════════════════════════════════════════════════════
# RESULT TYPES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class StrengthPrediction:
    currency:         str
    strength_score:   float          # [-1, +1] — positive = bullish
    confidence_pct:   float          # 0–100
    predicted_class:  int            # 1 = bullish, 0 = bearish
    feature_inputs:   dict           = field(default_factory=dict)
    n_trained:        int            = 0
    model_version:    str            = "river_arf_v1"


@dataclass
class PairBias:
    pair:           str
    base:           str
    quote:          str
    base_strength:  float
    quote_strength: float
    bias:           float            # base_strength - quote_strength
    direction:      str              # "BUY" | "SELL" | "NEUTRAL"
    confidence_pct: float


# ══════════════════════════════════════════════════════════════════════════════
# MODEL REGISTRY — in-process cache so we only load from DB once per session
# ══════════════════════════════════════════════════════════════════════════════

class _ModelRegistry:
    """
    Per-process singleton holding one River ARFClassifier per currency.
    Thread-safe for single-threaded async FastAPI (GIL-protected).
    """

    def __init__(self):
        self._models:    dict[str, object]            = {}  # currency → ARFClassifier
        self._n_trained: dict[str, int]               = {}  # currency → count
        self._accuracy:  dict[str, object]            = {}  # currency → river.metrics.Accuracy
        self._history:   dict[str, deque]             = {}  # currency → deque of (features, outcome)
        self._loaded:    set[str]                     = set()

    def _make_fresh_model(self):
        """Create a new ARFClassifier with project-standard hyperparameters."""
        from river.forest import ARFClassifier
        from river.drift import ADWIN

        return ARFClassifier(
            n_models=ARF_N_MODELS,
            lambda_value=ARF_LAMBDA,
            grace_period=ARF_GRACE_PERIOD,
            drift_detector=ADWIN(delta=ARF_DELTA),
            warning_detector=ADWIN(delta=ARF_DELTA * 10),
            seed=42,
        )

    def _make_fresh_accuracy(self):
        from river import metrics
        return metrics.Accuracy()

    def get(self, currency: str):
        """Return the live ARFClassifier for a currency, loading from DB if needed."""
        ccy = currency.upper()
        if ccy in self._loaded:
            return self._models[ccy]

        # Try loading from DB
        from database import load_river_model
        model, n_trained, live_accuracy, feature_weights = load_river_model(ccy)

        if model is None:
            log.info("No saved model for %s — creating fresh ARFClassifier.", ccy)
            model    = self._make_fresh_model()
            n_trained = 0

        self._models[ccy]    = model
        self._n_trained[ccy] = n_trained or 0
        self._accuracy[ccy]  = self._make_fresh_accuracy()
        self._history[ccy]   = deque(maxlen=_DRIFT_WINDOW)
        self._loaded.add(ccy)
        return model

    def update(self, currency: str, model, n_trained: int,
               live_accuracy: float, feature_weights: str):
        """Persist updated model state to DB."""
        from database import upsert_river_model
        ccy = currency.upper()
        self._models[ccy]    = model
        self._n_trained[ccy] = n_trained
        upsert_river_model(ccy, model, n_trained, live_accuracy, feature_weights)

    def get_n_trained(self, currency: str) -> int:
        self.get(currency)  # ensure loaded
        return self._n_trained.get(currency.upper(), 0)

    def get_accuracy_tracker(self, currency: str):
        self.get(currency)
        return self._accuracy.get(currency.upper())

    def get_history(self, currency: str) -> deque:
        self.get(currency)
        return self._history.get(currency.upper(), deque(maxlen=_DRIFT_WINDOW))

    def push_history(self, currency: str, features: dict, outcome: int):
        self.get(currency)
        ccy = currency.upper()
        if ccy not in self._history:
            self._history[ccy] = deque(maxlen=_DRIFT_WINDOW)
        self._history[ccy].append((features, outcome))


_registry = _ModelRegistry()


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE DICT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def build_features(
    indicator_score:  float = 0.0,
    rate_diff_score:  float = 0.0,
    cot_score:        float = 0.0,
    sentiment_score:  float = 0.0,
) -> dict:
    """
    Build a feature dict for River from the four sub-scores.
    All inputs should be in [-1, +1].
    """
    return {
        "indicator_score":  float(indicator_score),
        "rate_diff_score":  float(rate_diff_score),
        "cot_score":        float(cot_score),
        "sentiment_score":  float(sentiment_score),
    }


def _features_to_class(features: dict) -> int:
    """
    Convert a feature dict to a synthetic binary class for warm-up seeding.
    Simple rule: if weighted average of features > 0 → 1 (bullish), else 0.
    Weights reflect the rough prior importance of each signal type.
    """
    weights = {
        "indicator_score":  0.40,
        "rate_diff_score":  0.30,
        "cot_score":        0.20,
        "sentiment_score":  0.10,
    }
    weighted = sum(features.get(k, 0.0) * w for k, w in weights.items())
    return 1 if weighted > 0 else 0


# ══════════════════════════════════════════════════════════════════════════════
# SEEDING — warm-start models with COT + rate differential priors
# ══════════════════════════════════════════════════════════════════════════════

def seed_models_with_priors() -> dict[str, int]:
    """
    Warm-start all 8 currency models using current COT + rate differential
    as the initial prior ("what the market already believes").

    Called once on first startup (when n_trained == 0 for a currency).
    Safe to call on subsequent startups — it checks n_trained first and
    skips currencies that have already been trained on real data.

    Returns dict[currency → samples_seeded].
    """
    from config.events import CURRENCIES
    from data_sources import get_rate_differential, rate_diff_to_score
    from sentiment import get_latest_cot, cot_to_score

    seeded: dict[str, int] = {}

    for ccy in CURRENCIES:
        n = _registry.get_n_trained(ccy)
        if n > 0:
            log.info("Skipping seed for %s — already has %d real training samples.", ccy, n)
            continue

        # Build prior features from COT + rate differential
        rate_diff = get_rate_differential(ccy)
        cot_result = get_latest_cot(ccy)

        rd_score  = rate_diff_to_score(rate_diff)
        cot_score = cot_to_score(cot_result)

        prior_features = build_features(
            indicator_score=0.0,       # no indicator data yet
            rate_diff_score=rd_score,
            cot_score=cot_score,
            sentiment_score=0.0,       # no sentiment yet
        )
        prior_class = _features_to_class(prior_features)

        model = _registry.get(ccy)
        for _ in range(_SEED_SAMPLES):
            model.learn_one(prior_features, prior_class)

        n_seeded = _SEED_SAMPLES
        _registry._n_trained[ccy] = n_seeded
        _registry.update(
            ccy, model, n_seeded,
            live_accuracy=None,
            feature_weights=json.dumps({k: 1.0 / len(FEATURE_NAMES) for k in FEATURE_NAMES}),
        )
        seeded[ccy] = n_seeded
        log.info(
            "Seeded %s with %d synthetic prior samples (rd=%.3f cot=%.3f class=%d).",
            ccy, n_seeded, rd_score, cot_score, prior_class,
        )

    return seeded


# ══════════════════════════════════════════════════════════════════════════════
# PREDICTION
# ══════════════════════════════════════════════════════════════════════════════

def get_model(currency: str):
    """Return the live ARFClassifier for a currency."""
    return _registry.get(currency.upper())


def predict_strength(currency: str, features: dict) -> StrengthPrediction:
    """
    Run a forward pass through the ARFClassifier for a currency.

    Returns StrengthPrediction with:
      strength_score  — maps P(bullish) to [-1, +1]:  2 * P(1) - 1
      confidence_pct  — max(P(0), P(1)) * 100, capped at 85
      predicted_class — 1 (bullish) or 0 (bearish)
    """
    ccy   = currency.upper()
    model = _registry.get(ccy)

    try:
        proba = model.predict_proba_one(features)  # {0: p_bear, 1: p_bull}
    except Exception as e:
        log.error("predict_proba_one failed for %s: %s", ccy, e)
        proba = {0: 0.5, 1: 0.5}

    p_bull = proba.get(1, 0.5)
    p_bear = proba.get(0, 0.5)

    # Map P(bullish) → [-1, +1]
    strength_score = round(2.0 * p_bull - 1.0, 4)

    # Confidence: scaled from max probability, capped at 85%
    raw_conf = max(p_bull, p_bear) * 100
    # Scale: 50% → 30, 100% → 85 (same epistemic humility as original indicators.py)
    confidence_pct = 30.0 + (raw_conf - 50.0) * (55.0 / 50.0)
    confidence_pct = round(max(30.0, min(85.0, confidence_pct)), 1)

    predicted_class = 1 if p_bull >= 0.5 else 0

    return StrengthPrediction(
        currency=ccy,
        strength_score=strength_score,
        confidence_pct=confidence_pct,
        predicted_class=predicted_class,
        feature_inputs=dict(features),
        n_trained=_registry.get_n_trained(ccy),
        model_version="river_arf_v1",
    )


# ══════════════════════════════════════════════════════════════════════════════
# ONLINE LEARNING — called after every graded prediction
# ══════════════════════════════════════════════════════════════════════════════

def learn_one(
    currency: str,
    features: dict,
    outcome: int,          # 1 = the currency strengthened (BEAT), 0 = weakened (MISS)
) -> dict:
    """
    Feed one labelled observation into the ARFClassifier for a currency.
    Called by scheduler.py after a prediction is graded.

    outcome convention:
      1 = event was a positive surprise for this currency (model should have predicted bullish)
      0 = event was a negative surprise (model should have predicted bearish)

    Returns a stats dict for logging/dashboard:
      { n_trained, live_accuracy, was_correct, feature_weights }
    """
    ccy   = currency.upper()
    model = _registry.get(ccy)

    # Record prediction before learning (for accuracy tracking)
    try:
        predicted_class = model.predict_one(features)
    except Exception:
        predicted_class = None

    # Incremental learn
    try:
        model.learn_one(features, outcome)
    except Exception as e:
        log.error("learn_one failed for %s: %s", ccy, e)
        return {}

    n_trained = _registry.get_n_trained(ccy) + 1
    _registry._n_trained[ccy] = n_trained

    # Update rolling accuracy tracker
    acc_tracker = _registry.get_accuracy_tracker(ccy)
    was_correct = False
    if predicted_class is not None and acc_tracker is not None:
        try:
            acc_tracker.update(outcome, predicted_class)
            was_correct = (predicted_class == outcome)
        except Exception:
            pass

    live_accuracy = None
    if acc_tracker is not None:
        try:
            live_accuracy = round(float(acc_tracker.get()), 4)
        except Exception:
            pass

    # Push to history for drift tracking
    _registry.push_history(ccy, features, outcome)

    # Compute feature importance drift from sliding window
    fw = _compute_feature_weights(ccy)
    fw_json = json.dumps(fw)

    # Persist updated model to DB
    _registry.update(ccy, model, n_trained, live_accuracy, fw_json)

    log.info(
        "learn_one %s: n=%d acc=%.1f%% correct=%s drift=%s",
        ccy, n_trained,
        (live_accuracy or 0) * 100,
        was_correct,
        {k: round(v, 3) for k, v in fw.items()},
    )

    return {
        "currency":       ccy,
        "n_trained":      n_trained,
        "live_accuracy":  live_accuracy,
        "was_correct":    was_correct,
        "feature_weights": fw,
    }


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE IMPORTANCE DRIFT TRACKING
# ══════════════════════════════════════════════════════════════════════════════

def _compute_feature_weights(currency: str) -> dict:
    """
    Estimate current feature importance by computing the Pearson correlation
    between each feature value and the correct-prediction indicator over the
    last _DRIFT_WINDOW outcomes.

    Returns dict[feature_name → normalised_weight] summing to 1.0.
    Falls back to equal weights if the window is too small.
    """
    history = list(_registry.get_history(currency))
    if len(history) < 5:
        equal = round(1.0 / len(FEATURE_NAMES), 4)
        return {k: equal for k in FEATURE_NAMES}

    import numpy as np

    feature_arrays: dict[str, list] = {k: [] for k in FEATURE_NAMES}
    outcomes: list[int] = []

    for features, outcome in history:
        for k in FEATURE_NAMES:
            feature_arrays[k].append(float(features.get(k, 0.0)))
        outcomes.append(int(outcome))

    y = np.array(outcomes, dtype=float)
    correlations: dict[str, float] = {}

    for k in FEATURE_NAMES:
        x = np.array(feature_arrays[k])
        if x.std() < 1e-8 or y.std() < 1e-8:
            correlations[k] = 0.0
        else:
            corr = float(np.corrcoef(x, y)[0, 1])
            correlations[k] = abs(corr)   # importance = magnitude of correlation

    total = sum(correlations.values())
    if total < 1e-8:
        equal = round(1.0 / len(FEATURE_NAMES), 4)
        return {k: equal for k in FEATURE_NAMES}

    return {k: round(v / total, 4) for k, v in correlations.items()}


def get_feature_importance_drift() -> dict[str, dict]:
    """
    Return feature importance weights for all 8 currencies from the DB.
    Used by the dashboard to show which signal type is currently most predictive.

    Returns:
      {
        "USD": {"indicator_score": 0.42, "rate_diff_score": 0.28, ...},
        "EUR": {...},
        ...
      }
    """
    from config.events import CURRENCIES
    from database import SessionLocal, RiverModelState

    result: dict[str, dict] = {}
    db = SessionLocal()
    try:
        for ccy in CURRENCIES:
            row = db.query(RiverModelState).filter_by(currency=ccy).first()
            if row and row.feature_weights:
                try:
                    result[ccy] = json.loads(row.feature_weights)
                    continue
                except Exception:
                    pass
            equal = round(1.0 / len(FEATURE_NAMES), 4)
            result[ccy] = {k: equal for k in FEATURE_NAMES}
    finally:
        db.close()
    return result


# ══════════════════════════════════════════════════════════════════════════════
# BATCH PREDICTIONS — all currencies at once
# ══════════════════════════════════════════════════════════════════════════════

def get_all_strengths(feature_map: dict[str, dict]) -> dict[str, StrengthPrediction]:
    """
    Run predict_strength() for all 8 currencies.

    feature_map: { "USD": {indicator_score:.., rate_diff_score:.., ...}, "EUR": {...}, ... }
    Missing currencies get a zero-feature prediction (neutral).

    Returns dict[currency → StrengthPrediction].
    """
    from config.events import CURRENCIES
    results: dict[str, StrengthPrediction] = {}
    for ccy in CURRENCIES:
        features = feature_map.get(ccy, build_features())
        results[ccy] = predict_strength(ccy, features)
    return results


# ══════════════════════════════════════════════════════════════════════════════
# PAIR BIAS COMPUTATION
# ══════════════════════════════════════════════════════════════════════════════

# XAUUSD historical beta: gold's response to negative USD strength
_XAUUSD_BETA = -0.85   # from config/events.py XAUUSD_USD_BETA


def compute_pair_bias(
    base:              str,
    quote:             str,
    strengths:         dict[str, StrengthPrediction],
) -> PairBias:
    """
    Compute directional bias for a currency pair.

    pair_bias = strength(base) - strength(quote)

    Special case: XAUUSD (base="XAU"):
      bias = -USD_strength × XAUUSD_BETA
      (gold moves inversely to USD, amplified by the beta coefficient)

    Direction thresholds:
      bias > +0.10 → BUY base  (e.g. BUY EURUSD if EUR stronger than USD)
      bias < -0.10 → SELL base (e.g. SELL EURUSD)
      else         → NEUTRAL
    """
    pair = f"{base}{quote}".upper()
    b    = base.upper()
    q    = quote.upper()

    if b == "XAU":
        usd_pred  = strengths.get("USD")
        usd_str   = usd_pred.strength_score if usd_pred else 0.0
        bias      = round(-usd_str * abs(_XAUUSD_BETA), 4)
        base_str  = bias
        quote_str = 0.0
        conf      = usd_pred.confidence_pct if usd_pred else 30.0
    else:
        base_pred  = strengths.get(b)
        quote_pred = strengths.get(q)
        base_str   = base_pred.strength_score  if base_pred  else 0.0
        quote_str  = quote_pred.strength_score if quote_pred else 0.0
        bias       = round(base_str - quote_str, 4)
        # Confidence: minimum of the two constituent model confidences
        conf = min(
            base_pred.confidence_pct  if base_pred  else 30.0,
            quote_pred.confidence_pct if quote_pred else 30.0,
        )

    if bias > 0.10:
        direction = "BUY"
    elif bias < -0.10:
        direction = "SELL"
    else:
        direction = "NEUTRAL"

    return PairBias(
        pair=pair,
        base=b,
        quote=q,
        base_strength=base_str,
        quote_strength=quote_str,
        bias=bias,
        direction=direction,
        confidence_pct=round(conf, 1),
    )


def compute_all_pair_biases(
    strengths: dict[str, StrengthPrediction],
) -> dict[str, PairBias]:
    """
    Compute PairBias for every canonical pair including XAUUSD.
    Returns dict[pair_symbol → PairBias].
    """
    from config.events import CANONICAL_PAIRS

    results: dict[str, PairBias] = {}
    for pair in CANONICAL_PAIRS:
        if pair == "XAUUSD":
            results[pair] = compute_pair_bias("XAU", "USD", strengths)
        elif len(pair) == 6:
            base  = pair[:3]
            quote = pair[3:]
            results[pair] = compute_pair_bias(base, quote, strengths)
    return results


# ══════════════════════════════════════════════════════════════════════════════
# OUTCOME CONVERSION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def lean_to_outcome(lean_direction: str, was_correct: bool) -> int:
    """
    Convert a prediction grading result into a River outcome label.

    lean_direction: "BEAT" | "MISS" | "INLINE"
    was_correct:    whether the lean matched the actual surprise direction

    Returns 1 (model predicted correctly → bullish outcome verified)
            or 0 (model was wrong → bearish outcome verified).

    INLINE predictions are treated as 0 (no strong signal was present).
    """
    if lean_direction == "INLINE":
        return 0
    if was_correct:
        return 1 if lean_direction == "BEAT" else 0
    else:
        return 0 if lean_direction == "BEAT" else 1
