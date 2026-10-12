"""Send one explicit Telegram connectivity test message."""

import os
import sys

from alerts import send_test_message


def main() -> int:
    if not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID"):
        print(
            "Telegram is not configured; set TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID in .env.",
            file=sys.stderr,
        )
        return 1
    if not send_test_message():
        print("Telegram test message failed; inspect the application log.", file=sys.stderr)
        return 1
    print("Telegram test message sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
