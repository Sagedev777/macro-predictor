import random
import unittest

import pandas as pd

from price_data import _calculate_atr


class AtrCompatibilityTests(unittest.TestCase):
    def test_wilder_atr_matches_pandas_ta_baseline_to_six_decimals(self):
        rng = random.Random(913)
        candles = []
        close = 1.085
        for _ in range(60):
            open_price = close
            close = max(0.8, open_price + rng.uniform(-0.004, 0.004))
            candles.append({
                "open": open_price,
                "high": max(open_price, close) + rng.uniform(0.0001, 0.002),
                "low": min(open_price, close) - rng.uniform(0.0001, 0.002),
                "close": close,
            })
        frame = pd.DataFrame(candles)

        atr = _calculate_atr(
            frame["high"], frame["low"], frame["close"], period=14
        ).dropna().iloc[-1]
        pandas_ta_baseline = 0.004012600637474

        print(
            "ATR parity (60 deterministic candles): "
            f"pandas-ta={pandas_ta_baseline:.15f}; pandas={atr:.15f}; "
            f"abs_diff={abs(pandas_ta_baseline - atr):.15g}; "
            f"rounded6={pandas_ta_baseline:.6f}/{atr:.6f}"
        )
        self.assertEqual(round(float(atr), 6), round(pandas_ta_baseline, 6))


if __name__ == "__main__":
    unittest.main()
