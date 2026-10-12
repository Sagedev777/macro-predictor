"""
learning.py — Online/continuous learning engine using River's Adaptive Random Forest.

Architecture:
  - One ARFClassifier for USD (the only tracked currency)
  - Each model takes 4 feature signals as input:
        indicator_score   float [-1, +1]  — z-score aggregate from indicators.py
        rate_diff_score   float [-1, +1]  — yield spread from data_sources.py
        cot_score         float [-1, +1]  — COT net-long from sentiment.py
        sentiment_score   float [-1, +1]  — local sentiment score from sentiment.py
  - Output: predicted class (1=bullish, 0=bearish) + probability → strength score
  - ARF has native concept-drift detection (ADWIN per tree) — no manual decay needed

Seeding strategy:
  - Synthetic seeding disabled — n_trained starts at 0 and increments only from
    real pre-release graded USD predictions via learn_one().

Persistence:
  - Model state serialised via pickle and stored in river_model_state table
  - database.upsert_river_model() / load_river_model() handle the DB I/O

Feature importance drift:
  - ARF does not expose built-in feature importances the way sklearn does
  - We track drift by logging the rolling correlation of each feature with
    correct predictions over the last N outcomes (sliding window)
  - Stored as JSON in river_model_state.feature_weights for dashboard display
  - Labelled "estimated" because it is Pearson-correlation-based, not native RF
    feature importance; and shown only when n >= 5 real outcomes exist.

Public interface:
  get_model(currency)                         -> ARFClassifier (loads from DB or creates fresh)
  predict_strength(currency, features)        -> StrengthPrediction
  learn_one(currency, features, outcome)      -> updated model stats
  seed_models_with_priors()                   -> no-op (seeding disabled)
  get_all_strengths(feature_dict)             -> dict[currency, StrengthPrediction]
  compute_pair_bias(base, quote, features)    -> PairBias
  get_feature_importance_drift()              -> dict[str, dict]
"""

import json
import logging
import pickle
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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
_SEED_SAMPLES = 0   # synthetic warm-up seeding disabled — n_trained starts at 0


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
        self._stored_weights: dict[str, dict]         = {}  # currency → last persisted feature_weights

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
        # Restore last-known feature weights from DB so they survive restarts
        if feature_weights:
            try:
                self._stored_weights[ccy] = json.loads(feature_weights) if isinstance(feature_weights, str) else feature_weights
            except Exception:
                pass
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
_release_training_lock = threading.Lock()
_trained_release_moments: set[str] = set()
_last_rebuild_summary: dict = {
    "n_trained": 0,
    "release_moments_used": [],
    "excluded_predictions_without_snapshot": 0,
    "missing_snapshot_prediction_ids": [],
}


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


def capture_prediction_features(currency: str, indicator_score: float) -> dict:
    """Capture the exact feature values available when a prediction is created."""
    from data_sources import get_rate_differential, rate_diff_to_score
    from sentiment import (
        get_latest_cot,
        get_latest_sentiment,
        cot_to_score,
        sentiment_to_score,
    )

    rate_diff = get_rate_differential(currency)
    cot = get_latest_cot(currency)
    sentiment = get_latest_sentiment(currency)
    return build_features(
        indicator_score=indicator_score,
        rate_diff_score=rate_diff_to_score(rate_diff),
        cot_score=cot_to_score(cot),
        sentiment_score=sentiment_to_score(sentiment),
    )


def save_prediction_feature_snapshot(db, prediction, features: dict) -> None:
    """Persist prediction-time River inputs in indicator_snapshots."""
    from database import IndicatorSnapshot

    db.add(IndicatorSnapshot(
        pulled_at=prediction.created_at or datetime.utcnow(),
        fred_series="PREDICTION_INPUTS",
        prediction_id=prediction.id,
        indicator_score=float(features["indicator_score"]),
        rate_diff_score=float(features["rate_diff_score"]),
        cot_score=float(features["cot_score"]),
        sentiment_score=float(features["sentiment_score"]),
    ))


def _group_price_graded_predictions():
    """Build one price-graded observation per eligible release time."""
    from database import IndicatorSnapshot, Prediction, SessionLocal, is_pre_release_prediction

    db = SessionLocal()
    try:
        candidates = (
            db.query(Prediction)
            .filter(
                (Prediction.currency == "USD") | Prediction.currency.is_(None),
                Prediction.is_sample.is_(False),
                Prediction.price_graded_at.isnot(None),
                Prediction.result_15m.in_(("CORRECT", "INCORRECT")),
                Prediction.usd_move_15m.in_(("UP", "DOWN")),
                Prediction.lean_direction.in_(("BEAT", "MISS")),
            )
            .order_by(Prediction.created_at.asc(), Prediction.id.asc())
            .all()
        )
        candidates = [p for p in candidates if is_pre_release_prediction(p)]
        prediction_ids = [p.id for p in candidates]
        snapshots = {}
        if prediction_ids:
            snapshots = {
                s.prediction_id: s
                for s in db.query(IndicatorSnapshot)
                .filter(IndicatorSnapshot.prediction_id.in_(prediction_ids))
                .all()
            }

        by_release: dict[str, list] = {}
        for prediction in candidates:
            by_release.setdefault(prediction.release_time_utc, []).append(prediction)

        moments = []
        missing_snapshot_ids = []
        for release_time, predictions in sorted(by_release.items()):
            moves = {p.usd_move_15m.upper() for p in predictions}
            if len(moves) != 1:
                log.warning(
                    "Excluding release moment %s: conflicting price-graded moves %s",
                    release_time, sorted(moves),
                )
                continue

            stored_features = []
            usable_predictions = []
            for prediction in predictions:
                snapshot = snapshots.get(prediction.id)
                if snapshot is None:
                    missing_snapshot_ids.append(prediction.id)
                    continue
                values = (
                    snapshot.indicator_score,
                    snapshot.rate_diff_score,
                    snapshot.cot_score,
                    snapshot.sentiment_score,
                )
                if any(value is None for value in values):
                    missing_snapshot_ids.append(prediction.id)
                    continue
                stored_features.append(build_features(*values))
                usable_predictions.append(prediction)

            group_features = None
            if stored_features:
                group_features = {
                    name: sum(features[name] for features in stored_features) / len(stored_features)
                    for name in FEATURE_NAMES
                }
            hits = sum(1 for p in predictions if p.result_15m == "CORRECT")
            misses = sum(1 for p in predictions if p.result_15m == "INCORRECT")
            moments.append({
                "release_time_utc": release_time,
                "features": group_features,
                "outcome": 1 if next(iter(moves)) == "UP" else 0,
                "hit": hits > misses if hits != misses else None,
                "predictions": predictions,
                "usable_predictions": usable_predictions,
                "confidence_pct": (
                    sum(float(p.confidence_pct or 0.0) for p in predictions) / len(predictions)
                ),
                "event_codes": sorted({p.event_code for p in predictions}),
            })

        return moments, missing_snapshot_ids
    finally:
        db.close()


def get_grouped_release_moments() -> list[dict]:
    """Return one price-graded record per release moment for accuracy views."""
    moments, _ = _group_price_graded_predictions()
    return moments


def get_last_rebuild_summary() -> dict:
    """Return the most recent startup rebuild counts and release timestamps."""
    return dict(_last_rebuild_summary)


def rebuild_model_from_history() -> dict:
    """Discard the saved USD model and replay only grouped, snapshotted outcomes."""
    global _last_rebuild_summary

    moments, missing_snapshot_ids = _group_price_graded_predictions()
    from database import (
        ReleaseMomentTraining,
        SessionLocal,
        upsert_river_model,
    )

    with _release_training_lock:
        model = _registry._make_fresh_model()
        _registry._models["USD"] = model
        _registry._n_trained["USD"] = 0
        _registry._accuracy["USD"] = _registry._make_fresh_accuracy()
        _registry._history["USD"] = deque(maxlen=_DRIFT_WINDOW)
        _registry._stored_weights.pop("USD", None)
        _registry._loaded.add("USD")
        _trained_release_moments.clear()

        for moment in moments:
            if moment["features"] is not None:
                stats = learn_one("USD", moment["features"], moment["outcome"])
                if not stats:
                    raise RuntimeError(
                        f"Failed rebuilding River model for {moment['release_time_utc']}"
                    )
                _trained_release_moments.add(moment["release_time_utc"])

        trained_moments = [moment for moment in moments if moment["features"] is not None]
        if not trained_moments:
            upsert_river_model(
                "USD",
                model,
                0,
                None,
                json.dumps({name: 0.25 for name in FEATURE_NAMES}),
            )
        marker_db = SessionLocal()
        try:
            marker_db.query(ReleaseMomentTraining).filter_by(currency="USD").delete()
            for moment in trained_moments:
                marker_db.add(ReleaseMomentTraining(
                    release_time_utc=moment["release_time_utc"],
                    currency="USD",
                    claimed_at=datetime.utcnow(),
                    trained_at=datetime.utcnow(),
                    n_predictions=len(moment["usable_predictions"]),
                ))
            marker_db.commit()
        except Exception:
            marker_db.rollback()
            raise
        finally:
            marker_db.close()

        _last_rebuild_summary = {
            "n_trained": _registry.get_n_trained("USD"),
            "release_moments_used": [
                moment["release_time_utc"] for moment in trained_moments
            ],
            "excluded_predictions_without_snapshot": len(missing_snapshot_ids),
            "missing_snapshot_prediction_ids": sorted(set(missing_snapshot_ids)),
        }
        log.info(
            "Rebuilt USD River model: n_trained=%d release_moments_used=%s "
            "excluded_without_snapshot=%d prediction_ids=%s",
            _last_rebuild_summary["n_trained"],
            _last_rebuild_summary["release_moments_used"],
            _last_rebuild_summary["excluded_predictions_without_snapshot"],
            _last_rebuild_summary["missing_snapshot_prediction_ids"],
        )
        return dict(_last_rebuild_summary)


def train_release_moment(release_time_utc: str) -> dict:
    """Train at most once on the fully price-graded predictions for a release."""
    from database import (
        Prediction,
        ReleaseMomentTraining,
        SessionLocal,
        is_pre_release_prediction,
    )

    with _release_training_lock:
        db = SessionLocal()
        try:
            marker = db.get(ReleaseMomentTraining, (release_time_utc, "USD"))
            if marker and marker.trained_at is not None:
                _trained_release_moments.add(release_time_utc)
                return {}
            if marker and marker.claimed_at > datetime.utcnow() - timedelta(minutes=10):
                return {}

            predictions = (
                db.query(Prediction)
                .filter(
                    Prediction.release_time_utc == release_time_utc,
                    (Prediction.currency == "USD") | Prediction.currency.is_(None),
                    Prediction.is_sample.is_(False),
                )
                .all()
            )
            eligible = [p for p in predictions if is_pre_release_prediction(p)]
            if not eligible or any(p.price_graded_at is None for p in eligible):
                return {}
            if marker is None:
                marker = ReleaseMomentTraining(
                    release_time_utc=release_time_utc,
                    currency="USD",
                    claimed_at=datetime.utcnow(),
                    n_predictions=len(eligible),
                )
                db.add(marker)
            else:
                marker.claimed_at = datetime.utcnow()
                marker.n_predictions = len(eligible)
            db.commit()
        finally:
            db.close()

        moments, missing_snapshot_ids = _group_price_graded_predictions()
        moment = next(
            (item for item in moments if item["release_time_utc"] == release_time_utc),
            None,
        )
        if moment is None:
            if missing_snapshot_ids:
                log.warning(
                    "Excluded release moment %s from River training; no complete "
                    "stored feature snapshot (missing prediction ids=%s)",
                    release_time_utc, missing_snapshot_ids,
                )
            return {}

        if moment["features"] is None:
            log.warning(
                "Excluded release moment %s from River training; no stored feature snapshot",
                release_time_utc,
            )
            return {}
        try:
            stats = learn_one("USD", moment["features"], moment["outcome"])
            if not stats:
                raise RuntimeError("River learn_one did not return training statistics")
            marker_db = SessionLocal()
            try:
                marker = marker_db.get(
                    ReleaseMomentTraining, (release_time_utc, "USD")
                )
                if marker is None:
                    raise RuntimeError(
                        f"Training claim disappeared for {release_time_utc}"
                    )
                marker.trained_at = datetime.utcnow()
                marker_db.commit()
            finally:
                marker_db.close()
        except Exception:
            rollback_db = SessionLocal()
            try:
                marker = rollback_db.get(
                    ReleaseMomentTraining, (release_time_utc, "USD")
                )
                if marker and marker.trained_at is None:
                    rollback_db.delete(marker)
                    rollback_db.commit()
            finally:
                rollback_db.close()
            raise
        _trained_release_moments.add(release_time_utc)
        log.info(
            "Trained USD River model once for release_time_utc=%s n_trained=%d",
            release_time_utc, stats["n_trained"],
        )
        return stats


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
    Synthetic seeding stopped per data-integrity requirement.
    Models start at n_trained = 0 and learn strictly from real graded predictions.
    """
    return {}


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

    # Compute weights before and after update to track real weight shift
    fw_before = _compute_feature_weights(ccy)

    # Push to history for drift tracking
    _registry.push_history(ccy, features, outcome)

    # Compute feature importance drift from sliding window
    fw = _compute_feature_weights(ccy)
    fw_json = json.dumps(fw)

    # Persist updated model to DB
    _registry.update(ccy, model, n_trained, live_accuracy, fw_json)

    weight_shift_str = format_weight_shift(fw_before, fw, len(_registry.get_history(ccy)))

    log.info(
        "learn_one %s: n=%d acc=%.1f%% correct=%s drift=%s shift=%s",
        ccy, n_trained,
        (live_accuracy or 0) * 100,
        was_correct,
        {k: round(v, 3) for k, v in fw.items()},
        weight_shift_str,
    )

    return {
        "currency":          ccy,
        "n_trained":         n_trained,
        "live_accuracy":     live_accuracy,
        "was_correct":       was_correct,
        "feature_weights":   fw,
        "weight_shift_str":  weight_shift_str,
    }


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE IMPORTANCE DRIFT TRACKING
# ══════════════════════════════════════════════════════════════════════════════

SHORT_FEATURE_NAMES = {
    "indicator_score": "Ind",
    "rate_diff_score": "Rates",
    "cot_score": "COT",
    "sentiment_score": "Sent",
}


def format_weight_shift(fw_before: dict, fw_after: dict, n_history: int) -> str:
    """
    Format the estimated change in feature weights from an update.
    Returns 'not enough data' text until n_history >= 5 real outcomes.
    All figures are labelled 'estimated' because they derive from Pearson
    correlation over a sliding window, not native RF feature importance.
    """
    if n_history < 5:
        return f"Not enough data — estimated weights shown after 5 real outcomes ({n_history}/5 so far)"
    deltas = []
    for k in FEATURE_NAMES:
        before = fw_before.get(k, 0.25)
        after  = fw_after.get(k, 0.25)
        diff   = round(after - before, 4)
        short  = SHORT_FEATURE_NAMES.get(k, k)
        if abs(diff) >= 0.001:
            sign = "+" if diff > 0 else ""
            deltas.append(f"{short} {sign}{diff * 100:.1f}%")
    if deltas:
        return "Estimated: " + ", ".join(deltas)
    return "Estimated: No significant weight shift (<0.1%)"


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
        # Use last persisted weights from DB if available — better than equal fallback
        ccy = currency.upper()
        stored = _registry._stored_weights.get(ccy)
        if stored and len(stored) == len(FEATURE_NAMES):
            return stored
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
    Return feature importance weights for USD from the DB.
    USD-only: only one row exists in river_model_state.

    Returns:
      {
        "USD": {"indicator_score": 0.42, "rate_diff_score": 0.28, ...},
      }
    """
    from database import SessionLocal, RiverModelState

    result: dict[str, dict] = {}
    db = SessionLocal()
    try:
        row = db.query(RiverModelState).filter_by(currency="USD").first()
        if row and row.feature_weights:
            try:
                result["USD"] = json.loads(row.feature_weights)
                return result
            except Exception:
                pass
        equal = round(1.0 / len(FEATURE_NAMES), 4)
        result["USD"] = {k: equal for k in FEATURE_NAMES}
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
