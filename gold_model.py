"""A separate, point-in-time XAU/USD reaction learner for U.S. releases."""

import json
import logging
import math
import pickle
import re
import threading
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.exc import IntegrityError

from database import (
    CotSnapshot,
    ConsensusSnapshot,
    GoldForecast,
    GoldModelTraining,
    IndicatorSnapshot,
    Prediction,
    RiverModelState,
    SentimentSnapshot,
    SessionLocal,
    stable_release_moment_id,
    upsert_river_model,
    load_river_model,
)

log = logging.getLogger("gold_model")

HORIZON_MINUTES = 5
MIN_FORECAST_TRAINING_MOMENTS = 10
_FEATURE_FAMILIES = ("nfp", "cpi", "fomc", "pce", "ism", "gdp", "retail", "other")
_MODEL_VERSION = "gold_arf_v1"
_GOLD_MODEL_CURRENCY_KEY = "GOLD"  # Key used in river_model_state table

# In-process lock to prevent duplicate training within the same process
_gold_training_lock = threading.Lock()
# Track which release moments were trained in this process session
_gold_trained_moments: set = set()


def _parse_utc(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def event_family_for(events: Sequence[dict]) -> str:
    text = " ".join(
        "%s %s" % (event.get("event_code") or "", event.get("event_name") or "")
        for event in events
    ).upper()
    if any(word in text for word in ("NONFARM", "NFP", "PAYROLL", "UNEMPLOYMENT RATE", "AVERAGE HOURLY")):
        return "nfp"
    if "CPI" in text or "CONSUMER PRICE" in text:
        return "cpi"
    if "FOMC" in text or "FEDERAL FUNDS RATE" in text or "FED RATE" in text:
        return "fomc"
    if "PCE" in text or "PERSONAL CONSUMPTION" in text:
        return "pce"
    if "ISM" in text or "PURCHASING MANAGERS" in text:
        return "ism"
    if "GDP" in text or "GROSS DOMESTIC PRODUCT" in text:
        return "gdp"
    if "RETAIL SALES" in text:
        return "retail"
    return "other"


def classify_gold_return(
    change_pct: float,
    prior_comparable_changes: Sequence[float],
) -> Tuple[Optional[str], Optional[float]]:
    """Classify a return using only earlier comparable release reactions."""
    if not prior_comparable_changes:
        return None, None
    threshold = 0.5 * median(abs(value) for value in prior_comparable_changes)
    if not math.isfinite(threshold):
        return None, None
    if change_pct >= threshold and change_pct > 0:
        return "BULLISH", threshold
    if change_pct <= -threshold and change_pct < 0:
        return "BEARISH", threshold
    return "NEUTRAL", threshold


def _record(
    value: Optional[float],
    source: str,
    captured_at: datetime,
    observed_at: Optional[datetime] = None,
    published_at: Optional[datetime] = None,
    status: Optional[str] = None,
    available_at: Optional[datetime] = None,
    revision_status: Optional[str] = None,
) -> dict:
    return {
        "value": value,
        "source": source,
        "observed_at": observed_at.isoformat() if observed_at else None,
        "published_at": published_at.isoformat() if published_at else None,
        "captured_at": captured_at.isoformat(),
        "available_at": (available_at or captured_at).isoformat(),
        "status": status or ("available" if value is not None else "unavailable"),
        "staleness_status": (
            "missing" if value is None else
            "stale" if status and "stale" in status else
            "current"
        ),
        "revision_status": revision_status or "unknown",
    }


def _finite_number(value) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _make_features(snapshot: dict, event_family: str) -> dict:
    """Build numeric River inputs without converting missing values to zero."""
    features = {}
    for family in _FEATURE_FAMILIES:
        features["event_family_%s" % family] = 1.0 if family == event_family else 0.0
    for name, item in snapshot.items():
        value = _finite_number(item.get("value"))
        features["available_%s" % name] = 1.0 if value is not None else 0.0
        if value is not None and item.get("status") in (
            "available",
            "available_source_timestamp_missing",
            "available_publication_time_unavailable",
        ):
            features[name] = value
    return features


def _add_consensus_features(db, events: Sequence[dict], captured_at: datetime, snapshot: dict) -> None:
    for event in events:
        code = event.get("event_code")
        release_time = event.get("release_time_utc")
        if not code or not release_time:
            continue
        stored = (
            db.query(ConsensusSnapshot)
            .filter(
                ConsensusSnapshot.event_code == code,
                ConsensusSnapshot.release_time_utc == release_time,
                ConsensusSnapshot.captured_at <= captured_at.replace(tzinfo=None),
            )
            .order_by(ConsensusSnapshot.captured_at.desc(), ConsensusSnapshot.id.desc())
            .first()
        )
        token = re.sub(r"[^A-Z0-9]+", "_", code.upper()).strip("_").lower()
        if stored is None:
            snapshot["consensus_%s_forecast" % token] = _record(
                None, "consensus_snapshots", captured_at, status="missing_stored_snapshot"
            )
            snapshot["consensus_%s_previous" % token] = _record(
                None, "consensus_snapshots", captured_at, status="missing_stored_snapshot"
            )
            continue
        as_of = stored.data_as_of
        forecast = _finite_number(stored.forecast)
        previous = _finite_number(stored.previous)
        revised = _finite_number(stored.previous_revised)
        snapshot["consensus_%s_forecast" % token] = _record(
            forecast, "Forex Factory consensus snapshot", captured_at, as_of,
            available_at=stored.captured_at,
            revision_status="original_or_current_snapshot",
        )
        snapshot["consensus_%s_previous" % token] = _record(
            previous, "Forex Factory consensus snapshot", captured_at, as_of,
            available_at=stored.captured_at,
            revision_status="original_or_current_snapshot",
        )
        snapshot["consensus_%s_previous_revised" % token] = _record(
            revised, "Forex Factory consensus snapshot", captured_at, as_of,
            available_at=stored.captured_at,
            revision_status="revised" if revised is not None else "not_revised",
        )
        if forecast is not None and previous is not None:
            snapshot["consensus_%s_forecast_minus_previous" % token] = _record(
                forecast - previous, "Forex Factory consensus snapshot", captured_at, as_of
            )


def _add_stored_prediction_features(
    db, events: Sequence[dict], captured_at: datetime, snapshot: dict
) -> None:
    for event in events:
        code = event.get("event_code")
        release_time = event.get("release_time_utc")
        if not code or not release_time:
            continue
        prediction = (
            db.query(Prediction)
            .filter(
                Prediction.event_code == code,
                Prediction.release_time_utc == release_time,
                Prediction.created_at <= captured_at.replace(tzinfo=None),
                Prediction.is_sample.is_(False),
            )
            .order_by(Prediction.created_at.asc(), Prediction.id.asc())
            .first()
        )
        row = None
        if prediction:
            row = (
                db.query(IndicatorSnapshot)
                .filter(IndicatorSnapshot.prediction_id == prediction.id)
                .first()
            )
        snapshot.setdefault(
            "stored_indicator_score",
            _record(
                _finite_number(getattr(row, "indicator_score", None)),
                "indicator_snapshots.indicator_score",
                captured_at,
                observed_at=None,
                status=(
                    "available_source_timestamp_missing"
                    if row and row.indicator_score is not None
                    else "missing_prediction_snapshot"
                ),
            ),
        )
        snapshot.setdefault(
            "stored_rate_diff_score",
            _record(
                None,
                "USD self-comparison rate differential is not a Fed-policy feature",
                captured_at,
                status="not_applicable",
            ),
        )

        sentiment = (
            db.query(SentimentSnapshot)
            .filter(
                SentimentSnapshot.currency == (event.get("currency") or "USD"),
                SentimentSnapshot.recorded_at <= captured_at.replace(tzinfo=None),
            )
            .order_by(SentimentSnapshot.recorded_at.desc())
            .first()
        )
        sentiment_age = (
            captured_at.replace(tzinfo=None) - sentiment.recorded_at
            if sentiment and sentiment.recorded_at else None
        )
        sentiment_fresh = (
            row is not None
            and sentiment is not None
            and sentiment_age is not None
            and timedelta(0) <= sentiment_age <= timedelta(hours=48)
        )
        snapshot.setdefault(
            "stored_sentiment_score",
            _record(
                _finite_number(getattr(row, "sentiment_score", None))
                if sentiment_fresh else None,
                "indicator_snapshots.sentiment_score / sentiment_snapshots",
                captured_at,
                observed_at=sentiment.recorded_at if sentiment else None,
                status="available" if sentiment_fresh else "stale_or_unavailable",
            ),
        )

        usd_cot = _latest_cot(db, "USD", prediction.created_at if prediction else captured_at)
        cot_fresh = bool(usd_cot and row and row.cot_score is not None)
        snapshot.setdefault(
            "stored_usd_cot_score",
            _record(
                _finite_number(row.cot_score) if cot_fresh else None,
                "indicator_snapshots.cot_score / CFTC USD COT",
                captured_at,
                observed_at=(
                    datetime.strptime(usd_cot.report_date, "%Y-%m-%d")
                    if usd_cot else None
                ),
                published_at=usd_cot.published_at if usd_cot else None,
                status=(
                    "available_publication_time_unavailable"
                    if cot_fresh and usd_cot.published_at is None
                    else "available" if cot_fresh
                    else "stale_or_unavailable"
                ),
            ),
        )


def _latest_cot(db, currency: str, as_of: datetime):
    as_of_naive = (
        as_of.astimezone(timezone.utc).replace(tzinfo=None)
        if as_of.tzinfo else as_of
    )
    rows = (
        db.query(CotSnapshot)
        .filter(
            CotSnapshot.currency == currency,
            CotSnapshot.captured_at.isnot(None),
            CotSnapshot.captured_at <= as_of_naive,
        )
        .order_by(CotSnapshot.report_date.desc(), CotSnapshot.id.desc())
        .all()
    )
    for row in rows:
        if row.published_at and row.published_at > as_of_naive:
            continue
        try:
            report_date = datetime.strptime(row.report_date, "%Y-%m-%d")
        except (TypeError, ValueError):
            continue
        if timedelta(0) <= as_of_naive - report_date <= timedelta(days=10):
            return row
    return None


def _add_gold_market_features(captured_at: datetime, snapshot: dict) -> None:
    try:
        from price_data import fetch_ohlc

        candles = fetch_ohlc("XAUUSD", interval="1min", bars=241)
    except Exception:
        log.exception("Could not read XAU/USD candles for gold forecast features")
        candles = None

    if candles is not None and not candles.empty and len(candles) >= 31:
        close = candles["close"].astype(float)
        observed = candles.index[-1].to_pydatetime()
        age = captured_at.replace(tzinfo=None) - observed.replace(tzinfo=None)
        stale = age > timedelta(minutes=5) or age < timedelta(minutes=-2)
        values = {
            "gold_return_5m": (close.iloc[-1] / close.iloc[-6] - 1.0) * 100.0,
            "gold_return_30m": (close.iloc[-1] / close.iloc[-31] - 1.0) * 100.0,
            "gold_realized_volatility_30m": (
                close.pct_change().tail(30).dropna().std(ddof=0) * math.sqrt(30) * 100.0
            ),
        }
        for name, value in values.items():
            snapshot[name] = _record(
                _finite_number(value) if not stale else None,
                "Twelve Data XAU/USD 1-minute candles",
                captured_at,
                observed_at=observed,
                status="stale" if stale else "available",
            )
    else:
        for name in ("gold_return_5m", "gold_return_30m", "gold_realized_volatility_30m"):
            snapshot[name] = _record(
                None, "Twelve Data XAU/USD 1-minute candles", captured_at,
                status="unavailable",
            )

    try:
        from database import SessionLocal

        db = SessionLocal()
        try:
            gold_cot = _latest_cot(db, "XAU", captured_at)
        finally:
            db.close()
    except Exception:
        log.exception("Could not load the point-in-time COMEX gold COT snapshot")
        gold_cot = None
    gold_cot_value = _finite_number(gold_cot.net_long_pct) if gold_cot else None
    gold_cot_date = None
    if gold_cot:
        try:
            gold_cot_date = datetime.strptime(gold_cot.report_date, "%Y-%m-%d")
        except (TypeError, ValueError):
            gold_cot_value = None
    snapshot["gold_cot_net_long_pct"] = _record(
        gold_cot_value,
        "CFTC COMEX gold COT",
        captured_at,
        observed_at=gold_cot_date,
        published_at=gold_cot.published_at if gold_cot else None,
        status=(
            "available_publication_time_unavailable"
            if gold_cot_value is not None and gold_cot.published_at is None
            else "available" if gold_cot_value is not None
            else "no_fresh_point_in_time_report"
        ),
    )

    for name, source in (
        ("fedwatch_probability", "CME FedWatch"),
        ("gold_options_implied_volatility", "CME gold options"),
    ):
        snapshot[name] = _record(None, source, captured_at, status="provider_not_integrated")

    try:
        from data_sources import fetch_series

        for feature, series_id in (
            ("treasury_2y_yield", "DGS2"),
            ("real_treasury_10y_yield", "DFII10"),
        ):
            series = fetch_series(series_id, months=3)
            if series is None or series.dropna().empty:
                snapshot[feature] = _record(
                    None, "FRED/%s" % series_id, captured_at, status="unavailable"
                )
                continue
            valid = series.dropna()
            value = _finite_number(valid.iloc[-1])
            _raw_idx = valid.index[-1]
            observed = (
                _raw_idx.to_pydatetime()
                if hasattr(_raw_idx, "to_pydatetime")
                else datetime.fromisoformat(str(_raw_idx))
            )
            if observed.tzinfo is not None:
                observed = observed.astimezone(timezone.utc).replace(tzinfo=None)
            stale = captured_at.replace(tzinfo=None) - observed > timedelta(days=7)
            snapshot[feature] = _record(
                value if not stale else None,
                "FRED/%s" % series_id,
                captured_at,
                observed_at=observed,
                status="stale" if stale else "available",
            )
    except Exception:
        log.exception("Could not read FRED yield context for gold forecast")
        for feature in ("treasury_2y_yield", "real_treasury_10y_yield"):
            snapshot.setdefault(
                feature,
                _record(None, "FRED", captured_at, status="unavailable"),
            )


def _outcomes_before(
    db,
    release_time_utc: str,
    event_family: Optional[str] = None,
    available_by: Optional[datetime] = None,
) -> List[GoldForecast]:
    rows = (
        db.query(GoldForecast)
        .filter(
            GoldForecast.outcome_recorded_at.isnot(None),
            GoldForecast.gold_change_5m_pct.isnot(None),
        )
        .all()
    )
    release_dt = _parse_utc(release_time_utc)
    earlier = []
    for row in rows:
        row_dt = _parse_utc(row.release_time_utc)
        if row_dt is None or release_dt is None or row_dt >= release_dt:
            continue
        if available_by is not None and row.outcome_recorded_at > available_by.replace(tzinfo=None):
            continue
        if event_family and row.event_family != event_family:
            continue
        earlier.append(row)
    return sorted(earlier, key=lambda item: _parse_utc(item.release_time_utc))


def _labeled_training_rows(db, before: datetime) -> list:
    rows = (
        db.query(GoldForecast)
        .filter(
            GoldForecast.outcome_recorded_at.isnot(None),
            GoldForecast.gold_change_5m_pct.isnot(None),
            GoldForecast.outcome_recorded_at <= before.replace(tzinfo=None),
            GoldForecast.created_at < before.replace(tzinfo=None),
        )
        .all()
    )
    rows = sorted(
        (
            row for row in rows
            if _parse_utc(row.release_time_utc) is not None
            and _parse_utc(row.release_time_utc) < before.astimezone(timezone.utc)
        ),
        key=lambda item: _parse_utc(item.release_time_utc),
    )
    prior_by_family: Dict[str, List[GoldForecast]] = {}
    training = []
    for row in rows:
        prior = prior_by_family.setdefault(row.event_family, [])
        release_dt = _parse_utc(row.release_time_utc)
        if release_dt is None:
            continue
        available_prior = [
            item.gold_change_5m_pct
            for item in prior
            if item.outcome_recorded_at <= release_dt.replace(tzinfo=None)
        ]
        label, _threshold = classify_gold_return(
            row.gold_change_5m_pct, available_prior
        )
        prior.append(row)
        if label is None:
            continue
        features = json.loads(row.model_features)
        training.append((features, label))
    return training


def _build_model(training: Sequence[Tuple[dict, str]]):
    from river.forest import ARFClassifier

    model = ARFClassifier(
        n_models=10,
        seed=42,
        grace_period=10,
    )
    for features, label in training:
        model.learn_one(features, label)
    return model


def create_gold_forecast(
    db,
    events: Sequence[dict],
    now: Optional[datetime] = None,
) -> Optional[dict]:
    """Create at most one immutable forecast for a simultaneous release moment."""
    numeric = [
        event for event in events
        if event.get("event_code")
        and event.get("release_time_utc")
        and (event.get("currency") or "USD") == "USD"
        and event.get("forecast") is not None
    ]
    if not numeric:
        return None
    release_time = numeric[0]["release_time_utc"]
    if any(event.get("release_time_utc") != release_time for event in numeric):
        raise ValueError("Gold forecast group must contain one release moment")
    moment = _parse_utc(release_time)
    captured_at = now or datetime.now(timezone.utc)
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    if moment is None or moment <= captured_at.astimezone(timezone.utc):
        return None

    release_moment_id = stable_release_moment_id(
        release_time,
        [event.get("event_code") for event in numeric],
    )
    existing = db.query(GoldForecast).filter(
        (GoldForecast.release_time_utc == release_time)
        | (GoldForecast.release_moment_id == release_moment_id)
    ).first()
    if existing:
        return serialize_gold_forecast(existing, db)

    event_family = event_family_for(numeric)
    feature_snapshot = {}
    _add_consensus_features(db, numeric, captured_at, feature_snapshot)
    _add_stored_prediction_features(db, numeric, captured_at, feature_snapshot)
    _add_gold_market_features(captured_at, feature_snapshot)
    prior_rows = _outcomes_before(
        db, release_time, event_family, available_by=captured_at
    )
    prior_returns = [float(row.gold_change_5m_pct) for row in prior_rows]
    prior_classes = []
    historical_by_family = []
    for prior_row in prior_rows:
        prior_label, _ = classify_gold_return(
            prior_row.gold_change_5m_pct,
            [float(item.gold_change_5m_pct) for item in historical_by_family],
        )
        historical_by_family.append(prior_row)
        if prior_label:
            prior_classes.append(prior_label)
    for name, value in (
        ("historical_same_family_count", float(len(prior_rows))),
        (
            "historical_median_abs_5m_pct",
            median(abs(value) for value in prior_returns) if prior_returns else None,
        ),
        (
            "historical_bullish_rate",
            prior_classes.count("BULLISH") / float(len(prior_classes))
            if prior_classes else None,
        ),
        (
            "historical_bearish_rate",
            prior_classes.count("BEARISH") / float(len(prior_classes))
            if prior_classes else None,
        ),
        (
            "historical_neutral_rate",
            prior_classes.count("NEUTRAL") / float(len(prior_classes))
            if prior_classes else None,
        ),
    ):
        latest = max(
            (item.outcome_recorded_at for item in prior_rows if item.outcome_recorded_at),
            default=None,
        )
        feature_snapshot[name] = _record(
            value,
            "Earlier XAU/USD outcomes for %s releases" % event_family,
            captured_at,
            observed_at=latest,
            status="available" if value is not None else "insufficient_history",
        )
    training = _labeled_training_rows(db, captured_at)
    n_trained = len(training)
    probs = None
    direction = None
    status = "warming_up"
    expected_move_pct = None
    threshold = 0.5 * median(abs(value) for value in prior_returns) if prior_returns else None

    model_features = _make_features(feature_snapshot, event_family)
    class_counts = {
        label: sum(item_label == label for _features, item_label in training)
        for label in ("BULLISH", "BEARISH", "NEUTRAL")
    }
    if (
        n_trained >= MIN_FORECAST_TRAINING_MOMENTS
        and all(count >= 2 for count in class_counts.values())
    ):
        model = _build_model(training)
        raw_probs = model.predict_proba_one(model_features)
        keys = ("BULLISH", "BEARISH", "NEUTRAL")
        raw_values = [raw_probs.get(key, 0.0) for key in keys]
        if all(
            isinstance(value, (int, float))
            and math.isfinite(float(value))
            and 0.0 <= float(value) <= 1.0
            for value in raw_values
        ):
            total = sum(float(value) for value in raw_values)
        else:
            total = 0.0
        if total > 0.0:
            probs = {
                key.lower(): float(value) / total
                for key, value in zip(keys, raw_values)
            }
            direction = max(probs, key=probs.get).upper()
            status = "provisional"
        else:
            status = "invalid_probabilities"

    row = GoldForecast(
        release_moment_id=release_moment_id,
        release_time_utc=release_time,
        event_family=event_family,
        event_codes_json=json.dumps([event.get("event_code") for event in numeric]),
        event_names_json=json.dumps([
            event.get("display_name") or event.get("event_name") or event.get("event_code")
            for event in numeric
        ]),
        created_at=captured_at.astimezone(timezone.utc).replace(tzinfo=None),
        horizon_minutes=HORIZON_MINUTES,
        feature_snapshot=json.dumps(feature_snapshot, sort_keys=True),
        model_features=json.dumps(model_features, sort_keys=True),
        forecast_status=status,
        forecast_direction=direction,
        probabilities_json=json.dumps(probs, sort_keys=True) if probs is not None else None,
        expected_move_pct=expected_move_pct,
        n_trained=n_trained,
        training_class_counts_json=json.dumps(class_counts, sort_keys=True),
        threshold_pct=threshold,
        model_version=_MODEL_VERSION,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = db.query(GoldForecast).filter(
            (GoldForecast.release_time_utc == release_time)
            | (GoldForecast.release_moment_id == release_moment_id)
        ).first()
        if row is None:
            raise
    else:
        db.refresh(row)
    return serialize_gold_forecast(row, db)


def record_gold_outcome(db, release_time_utc: str, candles) -> bool:
    """Persist XAU/USD returns and five-minute excursions from stored candles."""
    row = db.query(GoldForecast).filter_by(release_time_utc=release_time_utc).first()
    if row is None or row.outcome_recorded_at is not None or candles is None or candles.empty:
        return False
    release = _parse_utc(release_time_utc)
    if release is None:
        return False
    index = candles.index
    if getattr(index, "tz", None) is not None:
        index = index.tz_convert("UTC").tz_localize(None)
    frame = candles.copy()
    frame.index = index
    frame = frame.sort_index()
    release_naive = release.replace(tzinfo=None)

    def nearest_close(target: datetime):
        distances = [abs((item.to_pydatetime() - target).total_seconds()) for item in frame.index]
        if not distances:
            return None
        position = min(range(len(distances)), key=distances.__getitem__)
        if distances[position] > 120:
            return None
        candle_time = frame.index[position].to_pydatetime()
        price = _finite_number(frame.iloc[position]["close"])
        return (price, candle_time, distances[position]) if price is not None else None

    targets = {
        "release": release_naive - timedelta(minutes=1),
        "1m": release_naive + timedelta(minutes=1),
        "5m": release_naive + timedelta(minutes=5),
        "15m": release_naive + timedelta(minutes=15),
        "30m": release_naive + timedelta(minutes=30),
    }
    prices = {name: nearest_close(target) for name, target in targets.items()}
    missing_targets = [name for name, value in prices.items() if value is None]
    if missing_targets or prices["release"][0] <= 0:
        row.outcome_status = "unavailable"
        row.outcome_data_quality_json = json.dumps({
            "source": "Twelve Data",
            "price_type": "1-minute candle close",
            "status": "unavailable",
            "missing_targets": missing_targets,
            "tolerance_seconds": 120,
        }, sort_keys=True)
        db.commit()
        return False
    base = prices["release"][0]
    changes = {
        name: (prices[name][0] / base - 1.0) * 100.0
        for name in ("1m", "5m", "15m", "30m")
    }
    window = frame[
        (frame.index >= release_naive)
        & (frame.index <= release_naive + timedelta(minutes=5))
    ]
    if window.empty:
        row.outcome_status = "unavailable"
        row.outcome_data_quality_json = json.dumps({
            "source": "Twelve Data",
            "price_type": "1-minute OHLC candles",
            "status": "unavailable",
            "missing_targets": ["five_minute_excursion_window"],
            "tolerance_seconds": 120,
        }, sort_keys=True)
        db.commit()
        return False
    max_up = (float(window["high"].max()) / base - 1.0) * 100.0
    max_down = (float(window["low"].min()) / base - 1.0) * 100.0
    if row.forecast_direction == "BULLISH":
        favorable, adverse = max(0.0, max_up), max(0.0, -max_down)
    elif row.forecast_direction == "BEARISH":
        favorable, adverse = max(0.0, -max_down), max(0.0, max_up)
    else:
        favorable = adverse = None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    prior = _outcomes_before(
        db, release_time_utc, row.event_family, available_by=now
    )
    label, threshold = classify_gold_return(
        changes["5m"], [float(item.gold_change_5m_pct) for item in prior]
    )
    row.gold_price_at_release = base
    row.gold_change_1m_pct = changes["1m"]
    row.gold_change_5m_pct = changes["5m"]
    row.gold_change_15m_pct = changes["15m"]
    row.gold_change_30m_pct = changes["30m"]
    row.max_up_5m_pct = max_up
    row.max_down_5m_pct = max_down
    row.max_favorable_5m_pct = favorable
    row.max_adverse_5m_pct = adverse
    row.outcome_label = label
    row.outcome_threshold_pct = threshold
    release_snapshots = (
        db.query(ConsensusSnapshot)
        .filter(ConsensusSnapshot.release_time_utc == release_time_utc)
        .order_by(ConsensusSnapshot.event_code.asc(), ConsensusSnapshot.captured_at.desc())
        .all()
    )
    first_by_code = {}
    for snapshot in release_snapshots:
        if snapshot.actual is not None and snapshot.event_code not in first_by_code:
            first_by_code[snapshot.event_code] = {
                "event_code": snapshot.event_code,
                "forecast": snapshot.forecast,
                "previous": snapshot.previous,
                "previous_revised": snapshot.previous_revised,
                "actual": snapshot.actual,
                "actual_first_seen_at": (
                    snapshot.actual_first_seen_at.isoformat()
                    if snapshot.actual_first_seen_at else None
                ),
                "actual_source": snapshot.actual_source,
            }
    row.actual_release_json = json.dumps(list(first_by_code.values()), sort_keys=True)
    row.outcome_data_quality_json = json.dumps({
        "source": "Twelve Data",
        "price_type": "1-minute candle close; high/low for excursion",
        "reference_target_utc": (release_naive - timedelta(minutes=1)).isoformat(),
        "endpoint_targets_utc": {
            name: target.isoformat()
            for name, target in targets.items()
        },
        "selected_candles_utc": {
            name: prices[name][1].isoformat()
            for name in prices
        },
        "selected_candle_offset_seconds": {
            name: prices[name][2]
            for name in prices
        },
        "tolerance_seconds": 120,
        "excursion_window_utc": [
            release_naive.isoformat(),
            (release_naive + timedelta(minutes=5)).isoformat(),
        ],
        "status": "ok",
        "missing_targets": [],
    }, sort_keys=True)
    row.outcome_status = "ok"
    row.outcome_recorded_at = now
    db.commit()
    return True


def _performance_summary(db) -> dict:
    rows = (
        db.query(GoldForecast)
        .filter(
            GoldForecast.probabilities_json.isnot(None),
            GoldForecast.outcome_label.isnot(None),
            GoldForecast.outcome_recorded_at.isnot(None),
        )
        .order_by(GoldForecast.release_time_utc.asc())
        .all()
    )
    groups = {}
    for row in rows:
        groups.setdefault(row.event_family, []).append(row)

    def summarize(items):
        if not items:
            return {
                "n": 0,
                "accuracy_pct": None,
                "brier_score": None,
                "confidence_bands": [],
            }
        hits = 0
        brier_scores = []
        confidence_rows = []
        for item in items:
            probs = json.loads(item.probabilities_json)
            predicted = max(probs, key=probs.get).upper()
            correct = predicted == item.outcome_label
            hits += correct
            confidence_rows.append((max(probs.values()), correct))
            brier_scores.append(
                sum(
                    (probs.get(label.lower(), 0.0) - (1.0 if label == item.outcome_label else 0.0)) ** 2
                    for label in ("BULLISH", "BEARISH", "NEUTRAL")
                ) / 3.0
            )
        band_ranges = ((0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01))
        bands = []
        for lower, upper in band_ranges:
            members = [
                (confidence, correct)
                for confidence, correct in confidence_rows
                if lower <= confidence < upper
            ]
            if members:
                bands.append({
                    "range_pct": "%d-%d" % (round(lower * 100), min(100, round(upper * 100))),
                    "n": len(members),
                    "mean_confidence_pct": 100.0 * sum(item[0] for item in members) / len(members),
                    "accuracy_pct": 100.0 * sum(item[1] for item in members) / len(members),
                })
        return {
            "n": len(items),
            "accuracy_pct": 100.0 * hits / len(items),
            "brier_score": sum(brier_scores) / len(brier_scores),
            "confidence_bands": bands,
        }

    return {
        "overall": summarize(rows),
        "by_event_family": {
            family: summarize(items) for family, items in sorted(groups.items())
        },
        "interpretation": "Out-of-sample scores use forecasts stored before release and labels built from earlier same-family reactions. Brier is mean squared error per class; confidence bands show predicted top-class confidence versus observed accuracy.",
    }


def get_model_status(db) -> dict:
    now = datetime.now(timezone.utc)
    training = _labeled_training_rows(db, now)
    class_counts = {
        label: sum(item_label == label for _features, item_label in training)
        for label in ("BULLISH", "BEARISH", "NEUTRAL")
    }
    forecast_count = db.query(GoldForecast).count()
    outcome_count = (
        db.query(GoldForecast)
        .filter(GoldForecast.outcome_recorded_at.isnot(None))
        .count()
    )
    return {
        "model": "XAU/USD release reaction",
        "model_version": _MODEL_VERSION,
        "horizon_minutes": HORIZON_MINUTES,
        "status": (
            "provisional"
            if len(training) >= MIN_FORECAST_TRAINING_MOMENTS
            and all(count >= 2 for count in class_counts.values())
            else "warming_up"
        ),
        "n_forecasts": forecast_count,
        "n_trained": len(training),
        "n_outcomes": outcome_count,
        "training_class_counts": class_counts,
        "probabilities_available": (
            len(training) >= MIN_FORECAST_TRAINING_MOMENTS
            and all(count >= 2 for count in class_counts.values())
        ),
        "expected_return_5m_status": "not_available_until_validated",
        "out_of_sample_performance": _performance_summary(db),
    }


def get_data_quality_summary(db) -> dict:
    rows = db.query(GoldForecast).order_by(GoldForecast.release_time_utc.desc()).all()
    feature_statuses = {}
    forecasts_without_outcomes = 0
    unavailable_outcomes = 0
    for row in rows:
        if row.outcome_recorded_at is None:
            forecasts_without_outcomes += 1
        if row.outcome_status == "unavailable":
            unavailable_outcomes += 1
        for name, item in json.loads(row.feature_snapshot or "{}").items():
            status = item.get("status", "unknown")
            feature_statuses.setdefault(name, {})
            feature_statuses[name][status] = feature_statuses[name].get(status, 0) + 1
    return {
        "forecast_count": len(rows),
        "outcome_count": len(rows) - forecasts_without_outcomes,
        "forecasts_without_outcomes": forecasts_without_outcomes,
        "unavailable_outcomes": unavailable_outcomes,
        "feature_status_counts": feature_statuses,
        "limitations": [
            "Historical source publication times are not recoverable for all inputs.",
            "CME FedWatch probabilities and gold options-implied volatility are not integrated.",
        ],
    }


def serialize_gold_forecast(row: GoldForecast, db=None) -> dict:
    features = json.loads(row.feature_snapshot or "{}")
    probabilities = (
        json.loads(row.probabilities_json)
        if row.probabilities_json else None
    )
    if probabilities is not None:
        probability_values = [
            probabilities.get(label) for label in ("bullish", "bearish", "neutral")
        ]
        valid = all(
            isinstance(value, (int, float))
            and math.isfinite(float(value))
            and 0.0 <= float(value) <= 1.0
            for value in probability_values
        )
        valid = valid and math.isclose(
            sum(float(value) for value in probability_values),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        if not valid:
            probabilities = None
    missing_features = [
        name for name, item in features.items()
        if item.get("value") is None
        or item.get("status") not in (
            "available",
            "available_source_timestamp_missing",
            "available_publication_time_unavailable",
        )
    ]
    cutoff = row.created_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    available = sum(
        item.get("value") is not None
        and str(item.get("status", "")).startswith("available")
        for item in features.values()
    )
    result = {
        "release_moment_id": row.release_moment_id,
        "release_time_utc": row.release_time_utc,
        "forecast_cutoff_utc": cutoff,
        "status": row.forecast_status,
        "confidence_status": row.forecast_status,
        "direction": row.forecast_direction,
        "predicted_direction": row.forecast_direction,
        "probabilities": probabilities,
        "p_bullish": probabilities.get("bullish") if probabilities else None,
        "p_bearish": probabilities.get("bearish") if probabilities else None,
        "p_neutral": probabilities.get("neutral") if probabilities else None,
        "expected_return_5m": None,
        "expected_move_pct": None,
        "horizon_minutes": row.horizon_minutes,
        "n_trained": row.n_trained,
        "threshold_pct": row.threshold_pct,
        "event_family": row.event_family,
        "model_version": row.model_version,
        "missing_features": missing_features,
        "feature_provenance": features,
        "training_class_counts": json.loads(row.training_class_counts_json or "{}"),
        "feature_coverage": {
            "available": available,
            "total": len(features),
            "inputs": features,
        },
        "validation_note": (
            "Provisional model output; not yet calibrated on enough out-of-sample gold outcomes."
            if row.forecast_status == "provisional"
            else "Probabilities are withheld until enough prior release-moment outcomes are available."
        ),
        "outcome": (
            {
                "label": row.outcome_label,
                "gold_price_at_release": row.gold_price_at_release,
                "change_1m_pct": row.gold_change_1m_pct,
                "change_5m_pct": row.gold_change_5m_pct,
                "change_15m_pct": row.gold_change_15m_pct,
                "change_30m_pct": row.gold_change_30m_pct,
                "max_up_5m_pct": row.max_up_5m_pct,
                "max_down_5m_pct": row.max_down_5m_pct,
                "max_favorable_5m_pct": row.max_favorable_5m_pct,
                "max_adverse_5m_pct": row.max_adverse_5m_pct,
                "threshold_pct": row.outcome_threshold_pct,
                "actual_releases": json.loads(row.actual_release_json or "[]"),
                "data_quality": json.loads(row.outcome_data_quality_json or "{}"),
            }
            if row.outcome_recorded_at is not None
            else None
        ),
    }
    if db is not None:
        result["out_of_sample_performance"] = _performance_summary(db)
    return result


# =============================================================================
# INCREMENTAL GOLD MODEL LEARNING
# =============================================================================

def _make_fresh_gold_model():
    from river.forest import ARFClassifier
    from river.drift import ADWIN
    return ARFClassifier(
        n_models=10,
        lambda_value=6,
        grace_period=10,
        drift_detector=ADWIN(delta=1e-5),
        warning_detector=ADWIN(delta=1e-4),
        seed=42,
    )


def _get_or_load_gold_model():
    model, n_trained, _acc, _fw = load_river_model(_GOLD_MODEL_CURRENCY_KEY)
    if model is None:
        log.info("No saved gold model found — creating fresh ARFClassifier.")
        model = _make_fresh_gold_model()
        n_trained = 0
    return model, n_trained or 0


def train_gold_outcome(release_time_utc: str) -> dict:
    """
    Feed one labelled gold-outcome observation into the live River ARFClassifier.

    Idempotent via GoldModelTraining PRIMARY KEY constraint and _gold_training_lock.
    The label is always GoldForecast.outcome_label (BULLISH/BEARISH/NEUTRAL) set
    by record_gold_outcome() from XAU/USD candle data only — never from whether
    the USD economic forecast was correct.

    Returns stats dict or {} if already trained / no eligible outcome.
    """
    with _gold_training_lock:
        if release_time_utc in _gold_trained_moments:
            return {}

        db = SessionLocal()
        try:
            marker = db.get(GoldModelTraining, release_time_utc)
            if marker and marker.trained_at is not None:
                _gold_trained_moments.add(release_time_utc)
                return {}

            # Stale in-progress claim guard (10-minute window)
            if (
                marker
                and marker.claimed_at is not None
                and marker.trained_at is None
                and (datetime.utcnow() - marker.claimed_at).total_seconds() < 600
            ):
                return {}

            gold_row = db.query(GoldForecast).filter_by(
                release_time_utc=release_time_utc
            ).first()
            if gold_row is None:
                return {}
            if gold_row.outcome_label is None or gold_row.outcome_recorded_at is None:
                return {}
            if gold_row.gold_change_5m_pct is None:
                return {}
            if not gold_row.model_features:
                log.warning(
                    "Gold row for %s has no stored model_features — skipping",
                    release_time_utc,
                )
                return {}

            outcome_label = gold_row.outcome_label

            try:
                features = json.loads(gold_row.model_features)
            except (TypeError, ValueError):
                log.error("Could not parse model_features for %s", release_time_utc)
                return {}

            if not features:
                return {}

            # Claim training slot
            if marker is None:
                marker = GoldModelTraining(
                    release_time_utc=release_time_utc,
                    claimed_at=datetime.utcnow(),
                    n_examples=1,
                )
                db.add(marker)
            else:
                marker.claimed_at = datetime.utcnow()
                marker.n_examples = 1
            try:
                db.commit()
            except Exception:
                db.rollback()
                log.exception("Failed to claim gold training slot for %s", release_time_utc)
                return {}
        finally:
            db.close()

    try:
        model, n_trained = _get_or_load_gold_model()
        model.learn_one(features, outcome_label)
        n_trained += 1
        upsert_river_model(_GOLD_MODEL_CURRENCY_KEY, model, n_trained, None, None)

        db2 = SessionLocal()
        try:
            m2 = db2.get(GoldModelTraining, release_time_utc)
            if m2 is None:
                m2 = GoldModelTraining(
                    release_time_utc=release_time_utc,
                    claimed_at=datetime.utcnow(),
                    n_examples=1,
                )
                db2.add(m2)
            m2.trained_at = datetime.utcnow()
            db2.commit()
        except Exception:
            db2.rollback()
            log.exception("Failed to mark gold training complete for %s", release_time_utc)
            raise
        finally:
            db2.close()

        _gold_trained_moments.add(release_time_utc)
        log.info(
            "Gold model trained once for %s: label=%s n_trained=%d",
            release_time_utc, outcome_label, n_trained,
        )
        return {
            "release_time_utc": release_time_utc,
            "n_trained": n_trained,
            "outcome_label": outcome_label,
            "was_trained": True,
        }

    except Exception:
        rollback_db = SessionLocal()
        try:
            m = rollback_db.get(GoldModelTraining, release_time_utc)
            if m and m.trained_at is None:
                rollback_db.delete(m)
                rollback_db.commit()
        except Exception:
            rollback_db.rollback()
        finally:
            rollback_db.close()
        log.exception("Gold model training failed for %s; claim rolled back", release_time_utc)
        return {}


def rebuild_gold_model_from_history() -> dict:
    """
    Discard the persisted gold model and replay all eligible labeled outcomes.
    Called on startup (analogous to rebuild_model_from_history in learning.py).
    """
    global _gold_trained_moments

    db = SessionLocal()
    try:
        rows = (
            db.query(GoldForecast)
            .filter(
                GoldForecast.outcome_label.isnot(None),
                GoldForecast.gold_change_5m_pct.isnot(None),
                GoldForecast.outcome_recorded_at.isnot(None),
            )
            .order_by(GoldForecast.release_time_utc.asc())
            .all()
        )
    finally:
        db.close()

    with _gold_training_lock:
        model = _make_fresh_gold_model()
        n_trained = 0
        skipped = 0
        trained_moments = []

        for row in rows:
            if not row.model_features:
                skipped += 1
                continue
            try:
                features = json.loads(row.model_features)
            except (TypeError, ValueError):
                skipped += 1
                continue
            if not features:
                skipped += 1
                continue
            model.learn_one(features, row.outcome_label)
            n_trained += 1
            trained_moments.append(row.release_time_utc)

        upsert_river_model(_GOLD_MODEL_CURRENCY_KEY, model, n_trained, None, None)

        db3 = SessionLocal()
        try:
            db3.query(GoldModelTraining).delete()
            now_dt = datetime.utcnow()
            for rt_utc in trained_moments:
                db3.add(GoldModelTraining(
                    release_time_utc=rt_utc,
                    claimed_at=now_dt,
                    trained_at=now_dt,
                    n_examples=1,
                ))
            db3.commit()
        except Exception:
            db3.rollback()
            log.exception("Failed to rebuild gold_model_training table")
            raise
        finally:
            db3.close()

        _gold_trained_moments = set(trained_moments)

    summary = {
        "n_trained": n_trained,
        "n_skipped_no_features": skipped,
        "trained_moments": trained_moments,
    }
    log.info("Gold model rebuild complete: n_trained=%d skipped=%d", n_trained, skipped)
    return summary


def get_walkforward_evaluation() -> dict:
    """
    Chronological walk-forward evaluation of the gold model.

    For each eligible GoldForecast row (chronological order):
      - Train on all prior rows first
      - Predict BEFORE updating the model with the current row
      - Compare prediction to actual outcome_label
    Features used are the stored point-in-time model_features snapshots.
    Returns overall/per-family accuracy, Brier score, and n.
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(GoldForecast)
            .filter(
                GoldForecast.outcome_label.isnot(None),
                GoldForecast.gold_change_5m_pct.isnot(None),
                GoldForecast.outcome_recorded_at.isnot(None),
                GoldForecast.model_features.isnot(None),
            )
            .order_by(GoldForecast.release_time_utc.asc())
            .all()
        )
    finally:
        db.close()

    if len(rows) < 2:
        return {
            "n_evaluated": 0,
            "overall": {"accuracy_pct": None, "brier_score": None, "n": 0},
            "by_event_family": {},
            "note": (
                f"Walk-forward requires at least 2 labeled outcomes; {len(rows)} available."
            ),
        }

    eligible = []
    for row in rows:
        try:
            feats = json.loads(row.model_features)
            if feats:
                eligible.append((row, feats))
        except (TypeError, ValueError):
            continue

    if len(eligible) < 2:
        return {
            "n_evaluated": 0,
            "overall": {"accuracy_pct": None, "brier_score": None, "n": 0},
            "by_event_family": {},
            "note": "Insufficient rows with parseable features for walk-forward.",
        }

    model = _make_fresh_gold_model()
    all_keys = ("BULLISH", "BEARISH", "NEUTRAL")
    results = []
    by_family: Dict[str, list] = {}

    for i, (row, feats) in enumerate(eligible):
        if i >= 1:
            try:
                raw_probs = model.predict_proba_one(feats)
                raw_vals = [raw_probs.get(k, 0.0) for k in all_keys]
                total = sum(float(v) for v in raw_vals)
                if total > 0:
                    probs = {k.lower(): float(v) / total for k, v in zip(all_keys, raw_vals)}
                    predicted = max(probs, key=probs.get).upper()
                    correct = predicted == row.outcome_label
                    brier = sum(
                        (probs.get(lbl.lower(), 0.0) - (1.0 if lbl == row.outcome_label else 0.0)) ** 2
                        for lbl in all_keys
                    ) / 3.0
                    results.append({"correct": correct, "brier": brier, "family": row.event_family})
                    by_family.setdefault(row.event_family, []).append((correct, brier))
            except Exception:
                log.exception("Walk-forward predict failed at row %d", i)
        model.learn_one(feats, row.outcome_label)

    if not results:
        return {
            "n_evaluated": 0,
            "overall": {"accuracy_pct": None, "brier_score": None, "n": 0},
            "by_event_family": {},
            "note": "No walk-forward predictions generated.",
        }

    n = len(results)
    hits = sum(1 for r in results if r["correct"])
    mean_brier = sum(r["brier"] for r in results) / n
    family_summary = {}
    for family, items in by_family.items():
        fn = len(items)
        fhits = sum(1 for c, _ in items if c)
        fbrier = sum(b for _, b in items) / fn
        family_summary[family] = {
            "n": fn,
            "accuracy_pct": round(100.0 * fhits / fn, 1),
            "brier_score": round(fbrier, 4),
        }

    class_counts = {}
    for r, _ in eligible:
        class_counts[r.outcome_label] = class_counts.get(r.outcome_label, 0) + 1
    majority_class = max(class_counts, key=class_counts.get) if class_counts else "NEUTRAL"
    majority_hits = sum(1 for r, _ in eligible[1:] if r.outcome_label == majority_class)
    baseline_acc = round(100.0 * majority_hits / n, 1) if n > 0 else 0.0

    stat_note = (
        " Statistical significance is not yet established (n < 20)."
        if n < 20 else ""
    )

    return {
        "n_evaluated": n,
        "overall": {
            "n": n,
            "accuracy_pct": round(100.0 * hits / n, 1),
            "brier_score": round(mean_brier, 4),
            "baseline_majority_class": majority_class,
            "baseline_accuracy_pct": baseline_acc,
        },
        "by_event_family": family_summary,
        "note": (
            "Chronological walk-forward: each prediction uses only outcomes from "
            "earlier releases. Features are point-in-time snapshots from forecast "
            f"creation time. Labels are XAU/USD 5-minute reaction classes.{stat_note}"
        ),
    }

