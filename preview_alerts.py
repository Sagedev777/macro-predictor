"""Print sample Telegram alerts using the same formatters as production."""

from types import SimpleNamespace
import sys

from alerts import _format_prediction_message
from scheduler import (
    _format_actual_posted_message,
    _format_price_result_message,
)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    prediction = {
        "event_code": "NFP",
        "lean_direction": "BEAT",
        "confidence_pct": 68,
        "forecast": 180000,
        "previous": 150000,
        "indicator_breakdown": [],
    }
    release_time = "12:30 UTC"
    result = SimpleNamespace(
        event_code="NFP",
        event_display_name="Nonfarm Payrolls",
        release_time_utc="2026-10-02T12:30:00Z",
        lean_direction="BEAT",
        confidence_pct=68,
        actual=220000,
        forecast=180000,
        result_15m="CORRECT",
        usd_move_15m="UP",
        price_graded_at="sample",
    )

    print("=== PRE-RELEASE ===")
    print(_format_prediction_message(prediction, release_time))
    print("\n=== ACTUAL_POSTED ===")
    print(_format_actual_posted_message(result, 220000, 180000))
    print("\n=== PRICE_RESULT ===")
    print(_format_price_result_message(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
