"""
sentiment.py — Sentiment scoring and COT positioning for all 8 currencies.

Sources:
  1. GDELT 2.0 DOC API  — https://api.gdeltproject.org/api/v2/doc/doc
     Free, no key, no rate-limit tier.  Used via gdeltdoc library.

  2. RSS feeds          — ForexLive, FXStreet, central bank speech pages.
     Parsed with the Python standard library. Feed URLs live in RSS_FEEDS.

  3. Central bank speech text — Fed, ECB, BoE, etc.
     Full text pulled from official RSS <description> / <content> fields.

  4. Local lexicon scorer — deterministic word-list scoring with no model download.

  5. CFTC COT reports   — via `cot_reports` library.
     Auto-downloads official CFTC weekly data; no manual file parsing.

Public interface:
  fetch_consensus_articles(currency, hours)  → list[str]  (article text snippets)
  score_sentiment(texts)                     → dict        (bullish/bearish/neutral pct + net)
  get_currency_sentiment(currency, hours)    → SentimentResult
  refresh_all_sentiment()                    → dict[str, SentimentResult]
  get_cot_positioning(currency)              → CotResult
  refresh_all_cot()                          → dict[str, CotResult]
  sentiment_to_score(result)                 → float  [-1, +1] for River
  cot_to_score(result)                       → float  [-1, +1] for River
"""

import logging
import html
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import requests

log = logging.getLogger("sentiment")

# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class SentimentResult:
    currency:        str
    window_hours:    int
    article_count:   int
    bullish_pct:     float   # 0.0 – 1.0
    bearish_pct:     float
    neutral_pct:     float
    net_score:       float   # bullish_pct - bearish_pct → [-1, +1]
    source_breakdown: dict   = field(default_factory=dict)  # {gdelt: n, rss: n, cb_speech: n}


@dataclass
class CotResult:
    currency:      str
    report_date:   str            # YYYY-MM-DD
    net_long:      Optional[int]
    open_interest: Optional[int]
    net_long_pct:  Optional[float]  # net_long / open_interest
    prev_net_long: Optional[int]
    positioning:   str            # "LONG" | "SHORT" | "NEUTRAL"


# ── Currency search keywords for GDELT / RSS filtering ───────────────────────
_CURRENCY_KEYWORDS: dict[str, list[str]] = {
    "USD": ["federal reserve", "fed", "fomc", "dollar", "usd", "us economy",
            "us inflation", "us jobs", "nonfarm payrolls"],
}


# ══════════════════════════════════════════════════════════════════════════════
# ARTICLE FETCHERS
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_gdelt_articles(currency: str, hours: int = 48) -> list[str]:
    """
    Pull article text snippets from GDELT 2.0 DOC API.
    Uses gdeltdoc library — free, no key, no rate-limit tiers.
    Returns a list of text snippets (up to 250 articles).
    """
    try:
        from gdeltdoc import GdeltDoc, Filters
    except ImportError:
        log.warning("gdeltdoc not installed — GDELT articles skipped.")
        return []

    keywords = _CURRENCY_KEYWORDS.get(currency.upper(), [])
    if not keywords:
        return []

    # Build a query from the top 3 most specific keywords
    query_str = " OR ".join(f'"{kw}"' for kw in keywords[:3])
    start_dt  = datetime.utcnow() - timedelta(hours=hours)

    try:
        gd = GdeltDoc()
        f  = Filters(
            keyword=query_str,
            start_date=start_dt.strftime("%Y-%m-%d %H:%M:%S"),
            end_date=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            num_records=250,
            output_format="artlist",
        )
        articles_df = gd.article_search(f)
        if articles_df is None or articles_df.empty:
            return []

        snippets: list[str] = []
        for _, row in articles_df.iterrows():
            title   = str(row.get("title",   "") or "")
            seendoc = str(row.get("seendate","") or "")
            # Titles are short inputs for the local term scorer.
            text = title.strip()
            if text:
                snippets.append(text)
        return snippets

    except Exception as e:
        log.warning("GDELT fetch failed for %s: %s", currency, e)
        return []


def _fetch_rss_articles(currency: str, hours: int = 48) -> list[str]:
    """
    Pull and filter RSS feed entries for a currency.
    Parses RSS and Atom XML with the Python standard library.
    Returns a list of text snippets (title + summary).
    """
    from config.events import RSS_FEEDS
    feeds = RSS_FEEDS.get(currency.upper(), [])
    keywords = [kw.lower() for kw in _CURRENCY_KEYWORDS.get(currency.upper(), [])]
    cutoff = datetime.utcnow().replace(tzinfo=timezone.utc) - timedelta(hours=hours)

    snippets: list[str] = []
    for feed_url in feeds:
        try:
            response = requests.get(feed_url, timeout=15)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            for entry in root.iter():
                if entry.tag.rsplit("}", 1)[-1].lower() not in ("item", "entry"):
                    continue

                fields = {
                    child.tag.rsplit("}", 1)[-1].lower(): "".join(child.itertext())
                    for child in entry
                }
                published_text = (
                    fields.get("published")
                    or fields.get("pubdate")
                    or fields.get("updated")
                    or fields.get("date")
                )
                published = None
                if published_text:
                    try:
                        published = parsedate_to_datetime(published_text)
                    except (TypeError, ValueError, OverflowError):
                        try:
                            published = datetime.fromisoformat(
                                published_text.replace("Z", "+00:00")
                            )
                        except ValueError:
                            published = None
                    if published is not None and published.tzinfo is None:
                        published = published.replace(tzinfo=timezone.utc)
                if published and published < cutoff:
                    continue   # too old

                title = html.unescape(fields.get("title", "") or "")
                summary = html.unescape(
                    fields.get("summary")
                    or fields.get("description")
                    or fields.get("content")
                    or ""
                )
                summary = re.sub(r"<[^>]+>", " ", summary)
                text    = f"{title} {summary}".strip().lower()

                # Filter: must mention at least one currency keyword
                if any(kw in text for kw in keywords):
                    snippet = f"{title} {summary}".strip()
                    if snippet:
                        snippets.append(snippet[:600])

        except Exception as e:
            log.warning("RSS fetch failed [%s] for %s: %s", feed_url, currency, e)

    return snippets


def fetch_consensus_articles(currency: str, hours: int = 48) -> list[str]:
    """
    Aggregate article text from all sources (GDELT + RSS feeds) for a currency.
    Returns a deduplicated list of text snippets for local lexicon scoring.
    """
    gdelt_articles = _fetch_gdelt_articles(currency, hours)
    rss_articles   = _fetch_rss_articles(currency, hours)

    # Simple deduplication by lowercased prefix
    seen:     set[str]  = set()
    combined: list[str] = []
    for text in gdelt_articles + rss_articles:
        key = text.lower()[:80]
        if key not in seen:
            seen.add(key)
            combined.append(text)

    log.info(
        "Articles fetched for %s: %d GDELT + %d RSS = %d unique",
        currency, len(gdelt_articles), len(rss_articles), len(combined),
    )
    return combined


# ══════════════════════════════════════════════════════════════════════════════
# LOCAL LEXICON SENTIMENT
# ══════════════════════════════════════════════════════════════════════════════

_POSITIVE_TERMS = {
    "accelerate", "beat", "benefit", "bullish", "ease", "expand", "gain",
    "growth", "improve", "increase", "optimistic", "positive", "rise",
    "strong", "surge", "upgrade",
}
_NEGATIVE_TERMS = {
    "bearish", "contract", "decline", "decrease", "downturn", "fall",
    "negative", "pressure", "recession", "risk", "slow", "slump", "weak",
    "worsen",
}


def score_sentiment(texts: list[str]) -> dict:
    """
    Score each text by counting local positive and negative finance terms.

    Returns:
      {
        "bullish_pct":  float,   # 0.0–1.0
        "bearish_pct":  float,
        "neutral_pct":  float,
        "net_score":    float,   # bullish_pct - bearish_pct → [-1, +1]
        "scored_count": int,
      }

    Texts without lexicon hits are neutral. This intentionally lightweight
    heuristic is not a contextual financial-language model.
    """
    neutral_result = {
        "bullish_pct":  0.0,
        "bearish_pct":  0.0,
        "neutral_pct":  1.0,
        "net_score":    0.0,
        "scored_count": 0,
    }

    label_counts: dict[str, int] = {"positive": 0, "negative": 0, "neutral": 0}
    for text in texts:
        words = set(re.findall(r"[a-z]+", text.lower()))
        positive = len(words & _POSITIVE_TERMS)
        negative = len(words & _NEGATIVE_TERMS)
        label = (
            "positive" if positive > negative else
            "negative" if negative > positive else
            "neutral"
        )
        label_counts[label] += 1

    total = sum(label_counts.values())
    if total == 0:
        return neutral_result

    bullish = label_counts["positive"] / total
    bearish = label_counts["negative"] / total
    neutral = label_counts["neutral"]  / total

    return {
        "bullish_pct":  round(bullish, 4),
        "bearish_pct":  round(bearish, 4),
        "neutral_pct":  round(neutral, 4),
        "net_score":    round(bullish - bearish, 4),
        "scored_count": total,
    }


# ══════════════════════════════════════════════════════════════════════════════
# AGGREGATED CURRENCY SENTIMENT
# ══════════════════════════════════════════════════════════════════════════════

def get_currency_sentiment(currency: str, hours: int = 48) -> SentimentResult:
    """
    Fetch articles, score with the local word list, persist and return the result.
    """
    from database import SentimentSnapshot, SessionLocal
    import json

    ccy      = currency.upper()
    gdelt_texts = _fetch_gdelt_articles(ccy, hours)
    rss_texts   = _fetch_rss_articles(ccy, hours)

    # Deduplicate combined
    seen:     set[str]  = set()
    combined: list[str] = []
    for text in gdelt_texts + rss_texts:
        key = text.lower()[:80]
        if key not in seen:
            seen.add(key)
            combined.append(text)

    scores = score_sentiment(combined)

    source_breakdown = {
        "gdelt":     len(gdelt_texts),
        "rss":       len(rss_texts),
        "cb_speech": 0,   # CB speeches come through RSS feeds — counted above
    }

    result = SentimentResult(
        currency=ccy,
        window_hours=hours,
        article_count=scores["scored_count"],
        bullish_pct=scores["bullish_pct"],
        bearish_pct=scores["bearish_pct"],
        neutral_pct=scores["neutral_pct"],
        net_score=scores["net_score"],
        source_breakdown=source_breakdown,
    )

    # Persist to DB
    db = SessionLocal()
    try:
        row = SentimentSnapshot(
            recorded_at     = datetime.utcnow(),
            currency        = ccy,
            article_count   = result.article_count,
            bullish_pct     = result.bullish_pct,
            bearish_pct     = result.bearish_pct,
            neutral_pct     = result.neutral_pct,
            net_score       = result.net_score,
            source_breakdown= json.dumps(source_breakdown),
        )
        db.add(row)
        db.commit()
        log.info(
            "Sentiment %s: bullish=%.1f%% bearish=%.1f%% net=%.3f (%d articles)",
            ccy,
            result.bullish_pct * 100,
            result.bearish_pct * 100,
            result.net_score,
            result.article_count,
        )
    except Exception as e:
        log.error("Failed to persist sentiment for %s: %s", ccy, e)
        db.rollback()
    finally:
        db.close()

    return result


def refresh_all_sentiment(hours: int = 48) -> dict[str, SentimentResult]:
    """
    Refresh sentiment for all 8 currencies sequentially.
    Called by scheduler.py on its daily sentiment cycle.
    Returns dict[currency → SentimentResult].
    """
    from config.events import CURRENCIES
    results: dict[str, SentimentResult] = {}
    for ccy in CURRENCIES:
        try:
            results[ccy] = get_currency_sentiment(ccy, hours)
        except Exception as e:
            log.error("Sentiment refresh failed for %s: %s", ccy, e)
    return results


def get_latest_sentiment(currency: str) -> Optional[SentimentResult]:
    """
    Return the most recent SentimentResult for a currency from the DB
    (without fetching articles again). Returns None if no data exists.
    """
    from database import SentimentSnapshot, SessionLocal
    import json

    db = SessionLocal()
    try:
        row = (
            db.query(SentimentSnapshot)
            .filter_by(currency=currency.upper())
            .order_by(SentimentSnapshot.recorded_at.desc())
            .first()
        )
        if row is None:
            return None
        breakdown = {}
        try:
            breakdown = json.loads(row.source_breakdown or "{}")
        except Exception:
            pass
        return SentimentResult(
            currency=row.currency,
            window_hours=48,
            article_count=row.article_count or 0,
            bullish_pct=row.bullish_pct or 0.0,
            bearish_pct=row.bearish_pct or 0.0,
            neutral_pct=row.neutral_pct or 1.0,
            net_score=row.net_score or 0.0,
            source_breakdown=breakdown,
        )
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# COT (CFTC COMMITMENT OF TRADERS)
# ══════════════════════════════════════════════════════════════════════════════

# COT report positioning thresholds for LONG/SHORT/NEUTRAL classification
_COT_THRESHOLD = 0.10   # |net_long_pct| > 10% = directional

# Map our currency codes to cot_reports contract names
# These match the strings used by the cot_reports library
_COT_CONTRACT_NAMES: dict[str, str] = {
    "USD": "US DOLLAR INDEX - ICE FUTURES U.S.",
    "XAU": "GOLD - COMMODITY EXCHANGE INC.",
}

# In-process COT cache: currency → (timestamp, CotResult)
_cot_cache: dict[str, tuple[float, CotResult]] = {}
_COT_CACHE_TTL = 7 * 24 * 3600   # COT data is weekly; cache for 7 days


def get_cot_positioning(currency: str) -> CotResult:
    """
    Return the latest CFTC COT net-long positioning for a currency using
    the `cot_reports` library (auto-downloads official CFTC data).

    Returns CotResult with positioning = "LONG" | "SHORT" | "NEUTRAL".
    Falls back to NEUTRAL if cot_reports is unavailable or data is missing.
    """
    ccy = currency.upper()
    now_ts = time.time()

    # Serve from in-process cache if fresh
    cached = _cot_cache.get(ccy)
    if cached and (now_ts - cached[0]) < _COT_CACHE_TTL:
        return cached[1]

    neutral = CotResult(
        currency=ccy,
        report_date="unknown",
        net_long=None,
        open_interest=None,
        net_long_pct=None,
        prev_net_long=None,
        positioning="NEUTRAL",
    )

    contract_name = _COT_CONTRACT_NAMES.get(ccy)
    if not contract_name:
        return neutral

    try:
        import cot_reports as cot
        import pandas as pd

        # cot_reports downloads and returns a DataFrame of the latest report
        # report_type="legacy_fut" covers the standard futures-only COT
        df: pd.DataFrame = cot.cot_year(
            year=datetime.utcnow().year,
            cot_report_type="legacy_fut",
        )

        if df is None or df.empty:
            log.warning("COT: empty DataFrame returned for year %d", datetime.utcnow().year)
            return neutral

        # Column names vary slightly by report type; normalise to lower-case
        df.columns = [str(c).strip() for c in df.columns]

        # Filter to our contract
        name_col = next(
            (c for c in df.columns if "market and exchange names" in c.lower()
             or "market_and_exchange_names" in c.lower()
             or c.lower() == "market"),
            None,
        )
        if name_col is None:
            log.warning("COT: cannot find contract name column")
            return neutral

        mask = df[name_col].str.upper().str.strip() == contract_name.upper()
        contract_df = df[mask].copy()

        if contract_df.empty:
            log.warning("COT: no data found for contract '%s'", contract_name)
            return neutral

        # Sort by report date descending
        date_col = next(
            (c for c in contract_df.columns if "as_of" in c.lower() or "date" in c.lower()),
            None,
        )
        if date_col:
            contract_df = contract_df.sort_values(date_col, ascending=False)

        latest = contract_df.iloc[0]
        prev   = contract_df.iloc[1] if len(contract_df) > 1 else None

        # Extract non-commercial long/short and open interest
        def _col(fragments: list[str]) -> Optional[str]:
            for frag in fragments:
                match = next(
                    (c for c in contract_df.columns if frag.lower() in c.lower()), None
                )
                if match:
                    return match
            return None

        long_col  = _col(["noncomm_positions_long_all",  "non_comm_long",  "nc_long"])
        short_col = _col(["noncomm_positions_short_all", "non_comm_short", "nc_short"])
        oi_col    = _col(["open_interest_all", "open_interest"])

        nc_long  = int(latest[long_col])  if long_col  and pd.notna(latest[long_col])  else None
        nc_short = int(latest[short_col]) if short_col and pd.notna(latest[short_col]) else None
        oi       = int(latest[oi_col])    if oi_col    and pd.notna(latest[oi_col])    else None

        net_long = (nc_long - nc_short) if (nc_long is not None and nc_short is not None) else None
        prev_nl  = None
        if prev is not None and long_col and short_col:
            pl = prev[long_col] if pd.notna(prev[long_col]) else None
            ps = prev[short_col] if pd.notna(prev[short_col]) else None
            if pl is not None and ps is not None:
                prev_nl = int(pl) - int(ps)

        net_long_pct: Optional[float] = None
        if net_long is not None and oi and oi > 0:
            net_long_pct = round(net_long / oi, 4)

        # Classify positioning
        if net_long_pct is not None:
            if net_long_pct > _COT_THRESHOLD:
                positioning = "LONG"
            elif net_long_pct < -_COT_THRESHOLD:
                positioning = "SHORT"
            else:
                positioning = "NEUTRAL"
        else:
            positioning = "NEUTRAL"

        # Parse report date
        report_date_str = "unknown"
        if date_col and pd.notna(latest[date_col]):
            try:
                report_date_str = str(latest[date_col])[:10]
            except Exception:
                pass

        result = CotResult(
            currency=ccy,
            report_date=report_date_str,
            net_long=net_long,
            open_interest=oi,
            net_long_pct=net_long_pct,
            prev_net_long=prev_nl,
            positioning=positioning,
        )

        # Persist to DB
        _persist_cot(result)

        # Cache
        _cot_cache[ccy] = (now_ts, result)

        log.info(
            "COT %s: net_long=%s oi=%s net_pct=%.2f%% positioning=%s date=%s",
            ccy, net_long, oi,
            (net_long_pct or 0) * 100,
            positioning,
            report_date_str,
        )
        return result

    except ImportError:
        log.warning("cot_reports not installed — COT positioning disabled for %s.", ccy)
        return neutral
    except Exception as e:
        log.error("COT fetch failed for %s: %s", ccy, e)
        return neutral


def _persist_cot(result: CotResult) -> None:
    """Persist a CotResult to the cot_snapshots table."""
    from database import CotSnapshot, SessionLocal
    db = SessionLocal()
    try:
        row = CotSnapshot(
            report_date   = result.report_date,
            currency      = result.currency,
            net_long      = result.net_long,
            open_interest = result.open_interest,
            net_long_pct  = result.net_long_pct,
            prev_net_long = result.prev_net_long,
            positioning   = result.positioning,
        )
        db.add(row)
        db.commit()
    except Exception as e:
        log.error("COT persist failed for %s: %s", result.currency, e)
        db.rollback()
    finally:
        db.close()


def refresh_all_cot() -> dict[str, CotResult]:
    """
    Refresh COT positioning for configured currencies and COMEX gold (XAU).
    Called by scheduler.py once per week (Friday after CFTC release).
    """
    from config.events import CURRENCIES
    results: dict[str, CotResult] = {}
    for ccy in list(CURRENCIES) + ["XAU"]:
        try:
            results[ccy] = get_cot_positioning(ccy)
        except Exception as e:
            log.error("COT refresh failed for %s: %s", ccy, e)
    return results


def get_latest_cot(currency: str) -> Optional[CotResult]:
    """
    Return the most recent CotResult from the DB without re-downloading.
    """
    from database import CotSnapshot, SessionLocal
    db = SessionLocal()
    try:
        row = (
            db.query(CotSnapshot)
            .filter_by(currency=currency.upper())
            .order_by(CotSnapshot.report_date.desc())
            .first()
        )
        if row is None:
            return None
        return CotResult(
            currency=row.currency,
            report_date=row.report_date,
            net_long=row.net_long,
            open_interest=row.open_interest,
            net_long_pct=row.net_long_pct,
            prev_net_long=row.prev_net_long,
            positioning=row.positioning or "NEUTRAL",
        )
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# SCORE NORMALISATION FOR RIVER FEATURES
# ══════════════════════════════════════════════════════════════════════════════

def sentiment_to_score(result: Optional[SentimentResult]) -> float:
    """
    Normalise a SentimentResult to a [-1, +1] feature value.
    net_score is already in [-1, +1]; we just return it directly.
    Returns 0.0 if result is None or no articles were scored.
    """
    if result is None or result.article_count == 0:
        return 0.0
    return float(result.net_score)


def cot_to_score(result: Optional[CotResult]) -> float:
    """
    Normalise a CotResult net_long_pct to a [-1, +1] feature value.

    Mapping:
      net_long_pct >= +0.30  → +1.0 (very crowded long)
      net_long_pct <= -0.30  → -1.0 (very crowded short)
      Linear interpolation between ±0.30.
      Returns 0.0 if result is None or net_long_pct is unknown.

    Note: COT positioning is a "market consensus" signal.  A very crowded
    long can mean the market already expects bullish — the River model learns
    whether that positioning is predictive or contrarian over time.
    """
    if result is None or result.net_long_pct is None:
        return 0.0
    clamped = max(-0.30, min(0.30, result.net_long_pct))
    return round(clamped / 0.30, 4)
