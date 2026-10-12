"""
events.py — Event definitions, leading indicator weights, and pair-routing
logic for the USD-only strength architecture.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SIGN CONVENTION (per-currency indicators)
  +1: Indicator UP is economically positive for that currency (bullish)
  -1: Indicator UP is economically negative for that currency (bearish)

IMPACT TIERS
  "red"    — high-impact (was the only tier tracked previously)
  "orange" — medium-impact (now tracked; contributes smaller feature weight)

CURRENCY STRENGTH FORMULA (see learning.py)
  strength(CCY) = ARFClassifier output using:
      1. indicator_score   — weighted z-score aggregate of this file's indicators
      2. rate_diff_score   — local benchmark yield spread vs US 10Y
      3. cot_score         — CFTC COT net-long % of OI
      4. sentiment_score   — 48-hour local lexicon net score

PAIR BIAS
  pair_bias(BASE/QUOTE) = strength(BASE) - strength(QUOTE)
  XAUUSD: treated as -USD_strength adjusted by real-yield correlation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

# ── Currency metadata ─────────────────────────────────────────────────────────
# All tradeable pairs derived from the 8 core currencies + XAUUSD.
# Each entry: (base, quote) — bias = strength(base) - strength(quote).

CURRENCIES = ["USD"]

# Canonical pairs the dashboard shows per-event — USD majors only.
CANONICAL_PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "XAUUSD",
]

# XAUUSD: Gold is priced inversely to USD real yields.
# Modelled as base="XAU" with strength derived from -USD_strength × real_yield_beta.
XAUUSD_USD_BETA = -0.85   # historical average; River will refine this over time

# Central bank benchmark yield series used for rate-differential computation.
# Values are (ecb_sdw_series_key_or_fred_id, source) — fetched by data_sources.py.
RATE_SERIES = {
    "USD": ("DGS10", "fred"),   # US 10Y Treasury — FRED
}

# CFTC COT futures ticker codes (used by cot_reports library).
COT_CODES = {
    "USD": "US DOLLAR INDEX - ICE FUTURES U.S.",
}

# RSS feeds for sentiment.py — central bank speech pages + forex media
RSS_FEEDS = {
    "USD": [
        "https://www.federalreserve.gov/feeds/speeches.xml",
        "https://www.forexlive.com/feed/news/",
        "https://www.fxstreet.com/rss/news",
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# EVENT DEFINITIONS
# Each event definition includes:
#   display_name   — human label
#   currency       — the currency this event directly moves
#   impact         — "red" | "orange"
#   history_series — primary data series ID for historical grading
#   indicators     — list of (series_id, weight, sign, description)
#                    series_id prefix:
#                      "FRED:"  → FRED API
#                      "ECB:"   → ECB SDW REST
#                      "ONS:"   → ONS API
#                      "BOE:"   → BoE database CSV
#                      "ESTAT:" → Eurostat API
#                      "OECD:"  → OECD SDMX-JSON
#                    (no prefix = FRED, for backward compatibility)
#   event_labels / explanations / trade_signals — kept for Telegram alert text
# ══════════════════════════════════════════════════════════════════════════════

EVENTS = {

    # ═════════════════════════════════════════════════════════════════════════
    # USD EVENTS — original definitions preserved verbatim
    # ═════════════════════════════════════════════════════════════════════════

    "NFP": {
        "display_name": "Non-Farm Payrolls",
        "currency": "USD",
        "impact": "red",
        "history_series": "PAYEMS",
        "event_labels": {
            "BULLISH": "BEAT (Strong Hiring)",
            "BEARISH": "MISS (Weak Hiring)",
            "INLINE": "INLINE (Neutral)",
        },
        "explanations": {
            "BULLISH": "Leading job indicators lean strong vs consensus. A hot payroll print typically drives Treasury yields and USD higher. Favor selling EURUSD & Gold, buying USDJPY.",
            "BEARISH": "Leading job indicators lean soft vs consensus. A weak print typically sparks Fed easing bets, pulling USD lower. Favor buying EURUSD & Gold, selling USDJPY.",
            "INLINE": "Employment signals are mixed. Wait for the actual release print before establishing directional bias.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("ADPWNUSNERSA", 0.30, +1, "ADP Private Payrolls — direct private jobs proxy"),
            ("IC4WSA",       0.25, -1, "4-Week Avg Initial Jobless Claims — rising = soft labor"),
            ("MANEMP",       0.20, +1, "ISM Mfg Employment Sub-index — factory hiring"),
            ("SRVPRD",       0.15, +1, "Services Employment — services hiring proxy"),
            ("JTSLDL",       0.10, -1, "Layoffs & Discharges — corporate layoffs signal"),
        ],
    },

    "CPI_MM": {
        "display_name": "CPI m/m",
        "currency": "USD",
        "impact": "red",
        "history_series": "CPIAUCSL",
        "event_labels": {
            "BULLISH": "HOT PRINT (Sticky Inflation m/m)",
            "BEARISH": "COOL PRINT (Disinflation m/m)",
            "INLINE": "INLINE (Expected)",
        },
        "explanations": {
            "BULLISH": "Energy, commodity, and services pipeline inflation lean elevated m/m. Hot monthly CPI reinforces hawkish Fed policy, supporting USD upside.",
            "BEARISH": "Leading monthly price indicators indicate easing pressure. Soft CPI increases Fed rate cut expectations, weakening USD.",
            "INLINE": "Monthly inflation signals are balanced. Market likely to react strictly to the decimal surprise against consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / RANGE BOUND"],
        },
        "indicators": [
            ("GASREGCOVW",     0.25, +1, "Weekly US Retail Gasoline — primary energy CPI driver"),
            ("MHHNGSP",        0.15, +1, "Henry Hub Natural Gas — utility bills component"),
            ("PPIFES",         0.20, +1, "PPI Final Demand Services — services sticky inflation"),
            ("PPIACO",         0.25, +1, "PPI All Commodities — producer input costs passed to CPI"),
            ("CUSR0000SETB01", 0.15, +1, "CPI Used Cars & Trucks — secondary goods component"),
        ],
    },

    "CPI_YY": {
        "display_name": "CPI y/y",
        "currency": "USD",
        "impact": "red",
        "history_series": "CPIAUCSL",
        "event_labels": {
            "BULLISH": "HOT PRINT (Sticky Inflation y/y)",
            "BEARISH": "COOL PRINT (Disinflation y/y)",
            "INLINE": "INLINE (Expected)",
        },
        "explanations": {
            "BULLISH": "Annualized energy, commodity, and services inflation lean elevated y/y. Hot headline CPI reinforces hawkish Fed policy, supporting USD upside.",
            "BEARISH": "Annualized price indicators indicate continuing disinflation y/y. Soft CPI accelerates Fed easing bets, weakening USD.",
            "INLINE": "Annual inflation signals are balanced with consensus. Market reacts strictly to deviation.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / RANGE BOUND"],
        },
        "indicators": [
            ("GASREGCOVW",     0.25, +1, "Weekly US Retail Gasoline — primary energy CPI driver"),
            ("MHHNGSP",        0.15, +1, "Henry Hub Natural Gas — utility bills component"),
            ("PPIFES",         0.20, +1, "PPI Final Demand Services — services sticky inflation"),
            ("PPIACO",         0.25, +1, "PPI All Commodities — producer input costs passed to CPI"),
            ("CUSR0000SETB01", 0.15, +1, "CPI Used Cars & Trucks — secondary goods component"),
        ],
    },

    "CPI": {
        "display_name": "Consumer Price Index (CPI)",
        "currency": "USD",
        "impact": "red",
        "history_series": "CPIAUCSL",
        "event_labels": {
            "BULLISH": "HOT PRINT (Sticky Inflation)",
            "BEARISH": "COOL PRINT (Disinflation)",
            "INLINE": "INLINE (Expected)",
        },
        "explanations": {
            "BULLISH": "Energy, commodity, and services pipeline inflation lean elevated. Hot CPI reinforces hawkish Fed policy, supporting USD upside and pressuring Gold.",
            "BEARISH": "Leading price indicators indicate easing pressure. Soft CPI increases Fed rate cut expectations, weakening USD and propelling Gold & EURUSD.",
            "INLINE": "Inflation signals are balanced. Market likely to react strictly to the decimal surprise against consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / RANGE BOUND"],
        },
        "indicators": [
            ("GASREGCOVW",     0.25, +1, "Weekly US Retail Gasoline — primary energy CPI driver"),
            ("MHHNGSP",        0.15, +1, "Henry Hub Natural Gas — utility bills component"),
            ("PPIFES",         0.20, +1, "PPI Final Demand Services — services sticky inflation"),
            ("PPIACO",         0.25, +1, "PPI All Commodities — producer input costs passed to CPI"),
            ("CUSR0000SETB01", 0.15, +1, "CPI Used Cars & Trucks — secondary goods component"),
        ],
    },

    "CORE_CPI_MM": {
        "display_name": "Core CPI m/m",
        "currency": "USD",
        "impact": "red",
        "history_series": "CPILFESL",
        "event_labels": {
            "BULLISH": "HOT CORE (Services Stickiness m/m)",
            "BEARISH": "COOL CORE (Disinflationary m/m)",
            "INLINE": "INLINE (Neutral)",
        },
        "explanations": {
            "BULLISH": "Shelter and services pipeline metrics remain firm m/m. Persistent core inflation strengthens the US Dollar as rate cuts are pushed back.",
            "BEARISH": "Core components indicate cooling shelter and services momentum m/m. Disinflation supports risk assets while weighing on the USD.",
            "INLINE": "Core metrics are aligned with market consensus m/m.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("CUSR0000SEHA",  0.30, +1, "CPI Rent of Primary Residence — ~34% of core basket"),
            ("CUSR0000SEHC",  0.25, +1, "CPI Owner's Equivalent Rent (OER)"),
            ("PPIFES",        0.20, +1, "PPI Final Demand Services — services price pressures"),
            ("PPIFIS",        0.15, +1, "PPI Final Demand — pipeline pricing pressure"),
            ("PPIACO",        0.10, +1, "PPI All Commodities — feeds goods inflation"),
        ],
    },

    "CORE_CPI_YY": {
        "display_name": "Core CPI y/y",
        "currency": "USD",
        "impact": "red",
        "history_series": "CPILFESL",
        "event_labels": {
            "BULLISH": "HOT CORE (Services Stickiness y/y)",
            "BEARISH": "COOL CORE (Disinflationary y/y)",
            "INLINE": "INLINE (Neutral)",
        },
        "explanations": {
            "BULLISH": "Shelter and services pipeline metrics remain firm y/y. Persistent annualized core inflation strengthens the US Dollar.",
            "BEARISH": "Annual core metrics indicate sustained shelter disinflation y/y, reducing USD support.",
            "INLINE": "Annual core metrics are aligned with market consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("CUSR0000SEHA",  0.30, +1, "CPI Rent of Primary Residence — ~34% of core basket"),
            ("CUSR0000SEHC",  0.25, +1, "CPI Owner's Equivalent Rent (OER)"),
            ("PPIFES",        0.20, +1, "PPI Final Demand Services — services price pressures"),
            ("PPIFIS",        0.15, +1, "PPI Final Demand — pipeline pricing pressure"),
            ("PPIACO",        0.10, +1, "PPI All Commodities — feeds goods inflation"),
        ],
    },

    "CORE_CPI": {
        "display_name": "Core CPI (ex. Food & Energy)",
        "currency": "USD",
        "impact": "red",
        "history_series": "CPILFESL",
        "event_labels": {
            "BULLISH": "HOT CORE (Services Stickiness)",
            "BEARISH": "COOL CORE (Disinflationary)",
            "INLINE": "INLINE (Neutral)",
        },
        "explanations": {
            "BULLISH": "Shelter and services pipeline metrics remain firm. Persistent core inflation strengthens the US Dollar as rate cuts are pushed back.",
            "BEARISH": "Core components indicate cooling shelter and services momentum. Disinflation supports risk assets and Gold while weighing on the USD.",
            "INLINE": "Core metrics are aligned with market consensus. Monitor headline CPI flow.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("CUSR0000SEHA",  0.30, +1, "CPI Rent of Primary Residence — ~34% of core basket"),
            ("CUSR0000SEHC",  0.25, +1, "CPI Owner's Equivalent Rent (OER)"),
            ("PPIFES",        0.20, +1, "PPI Final Demand Services — services price pressures"),
            ("PPIFIS",        0.15, +1, "PPI Final Demand — pipeline pricing pressure"),
            ("PPIACO",        0.10, +1, "PPI All Commodities — feeds goods inflation"),
        ],
    },

    "PPI": {
        "display_name": "Producer Price Index (PPI)",
        "currency": "USD",
        "impact": "red",
        "history_series": "PPIACO",
        "event_labels": {
            "BULLISH": "HOT PPI (Upstream Pressure)",
            "BEARISH": "COOL PPI (Easing Input Costs)",
            "INLINE": "INLINE (Neutral)",
        },
        "explanations": {
            "BULLISH": "Crude inputs and producer margins are running hot. Upstream inflation flows into consumer CPI, boosting USD yields.",
            "BEARISH": "Producer costs are decelerating. Easing wholesale inflation relieves Fed tightening pressure, softening USD.",
            "INLINE": "Producer costs are stable. Little directional momentum expected.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / WATCH CPI FLOW"],
        },
        "indicators": [
            ("DCOILWTICO",  0.30, +1, "WTI Crude Oil — dominant cost input for producers"),
            ("PCUOMFGOMFG", 0.20, +1, "PPI Manufacturing — upstream goods pressure"),
            ("PPIFES",      0.20, +1, "PPI Final Demand Services — service-sector costs"),
            ("MANEMP",      0.15, +1, "ISM Mfg Employment — capacity utilization proxy"),
            ("PPICRM",      0.15, +1, "PPI Crude Materials — raw material pipeline"),
        ],
    },

    "INITIAL_JOBLESS_CLAIMS": {
        "display_name": "Initial Jobless Claims",
        "currency": "USD",
        "impact": "red",
        "history_series": "ICSA",
        "event_labels": {
            "BULLISH": "FEWER CLAIMS (Resilient Labor)",
            "BEARISH": "HIGHER CLAIMS (Labor Weakness)",
            "INLINE": "INLINE (Stable Claims)",
        },
        "explanations": {
            "BULLISH": "Initial claims trends remain muted. Low claims demonstrate labor market resilience, supporting USD strength.",
            "BEARISH": "Rising initial claims point to labor softening. Higher claims accelerate rate-cut bets, weakening the USD.",
            "INLINE": "Initial claims are tracking consensus. No immediate directional bias.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("IC4WSA",  0.40, -1, "4-Week Claims Moving Average — falling claims = bullish USD"),
            ("CCSA",    0.35, -1, "Continued Claims — lower continuing claims = strong labor"),
            ("JTSLDL",  0.25, -1, "Layoffs & Discharges — low layoffs = resilient economy"),
        ],
    },

    "CONTINUING_JOBLESS_CLAIMS": {
        "display_name": "Continuing Jobless Claims",
        "currency": "USD",
        "impact": "red",
        "history_series": "CCSA",
        "event_labels": {
            "BULLISH": "FEWER CONTINUING CLAIMS (Tight Labor)",
            "BEARISH": "HIGHER CONTINUING CLAIMS (Harder To Find Work)",
            "INLINE": "INLINE (Stable Claims)",
        },
        "explanations": {
            "BULLISH": "Continuing claims drop shows unemployed workers quickly finding new employment. Bullish USD.",
            "BEARISH": "Continuing claims rise indicates extended duration of unemployment. Bearish USD.",
            "INLINE": "Continuing claims meet expectations. Neutral impact.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("CCSA",    0.50, -1, "Continued Claims — lower continuing claims = strong labor"),
            ("IC4WSA",  0.30, -1, "4-Week Claims Moving Average — falling claims = bullish USD"),
            ("UEMPMEAN", 0.20, -1, "Average Weeks Unemployed — lower duration = tight labor"),
        ],
    },

    "JOBLESS_CLAIMS": {
        "display_name": "Weekly Initial Jobless Claims",
        "currency": "USD",
        "impact": "red",
        "history_series": "ICSA",
        "event_labels": {
            "BULLISH": "FEWER CLAIMS (Resilient Labor)",
            "BEARISH": "HIGHER CLAIMS (Labor Weakness)",
            "INLINE": "INLINE (Stable Claims)",
        },
        "explanations": {
            "BULLISH": "Layoffs and claims trends remain muted. Low claims demonstrate labor market resilience, supporting USD strength.",
            "BEARISH": "Rising claims and layoff warnings point to labor softening. Higher claims accelerate rate-cut bets, weakening the USD.",
            "INLINE": "Claims are tracking consensus. No immediate directional bias.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("IC4WSA",  0.35, -1, "4-Week Claims Moving Average — falling claims = bullish USD"),
            ("CCSA",    0.30, -1, "Continued Claims — lower continuing claims = strong labor"),
            ("JTSLDL",  0.20, -1, "Layoffs & Discharges — low layoffs = resilient economy"),
            ("MANEMP",  0.15, +1, "ISM Mfg Employment — active hiring demand"),
        ],
    },

    "UNEMPLOYMENT_RATE": {
        "display_name": "Unemployment Rate (U3)",
        "currency": "USD",
        "impact": "red",
        "history_series": "UNRATE",
        "event_labels": {
            "BULLISH": "LOWER RATE (Tight Labor)",
            "BEARISH": "HIGHER RATE (Labor Softening)",
            "INLINE": "STEADY RATE (Neutral)",
        },
        "explanations": {
            "BULLISH": "Claims and hiring proxies indicate tight employment. A steady/lower jobless rate reinforces economic strength, pushing USD higher.",
            "BEARISH": "Rising corporate layoffs and claims momentum suggest higher unemployment. Weakness triggers Fed easing, causing USD downside.",
            "INLINE": "Jobless rate expected to match forecast. Headline NFP will dominate price action.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / WATCH NFP HEADLINE"],
        },
        "indicators": [
            ("IC4WSA",    0.30, -1, "4-Week Jobless Claims Avg — lower claims = lower unemployment"),
            ("CCSA",      0.25, -1, "Continued Jobless Claims — low duration = healthy labor"),
            ("JTSLDL",    0.20, -1, "Layoffs & Discharges — fewer layoffs = lower unemployment"),
            ("MANEMP",    0.15, +1, "ISM Mfg Employment — hiring lowers rate"),
            ("TEMPHELPS", 0.10, +1, "Temporary Help Services — leading hiring gauge"),
        ],
    },

    "CONSUMER_CONFIDENCE": {
        "display_name": "Consumer Confidence & Sentiment",
        "currency": "USD",
        "impact": "red",
        "history_series": "CSCICP03USM665S",
        "event_labels": {
            "BULLISH": "HIGH CONFIDENCE (Spending Appetite)",
            "BEARISH": "LOW CONFIDENCE (Cautious Consumer)",
            "INLINE": "INLINE (Neutral)",
        },
        "explanations": {
            "BULLISH": "Equity market gains and stable gasoline prices support consumer optimism. Upbeat sentiment boosts USD and domestic equity indices.",
            "BEARISH": "High pump costs and job concerns dampen consumer mood. Weak confidence weighs on USD and equities.",
            "INLINE": "Consumer sentiment is tracking expectations.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / RANGE BOUND"],
        },
        "indicators": [
            ("UMCSENT",    0.35, +1, "Univ. of Michigan Consumer Sentiment Index"),
            ("GASREGCOVW", 0.25, -1, "Retail Gasoline Prices — lower pump costs = higher confidence"),
            ("IC4WSA",     0.20, -1, "Initial Jobless Claims — low claims = high job confidence"),
            ("SP500",      0.20, +1, "S&P 500 Index — stock market wealth effect"),
        ],
    },

    "FOMC": {
        "display_name": "FOMC Rate Decision / Policy",
        "currency": "USD",
        "impact": "red",
        "history_series": "FEDFUNDS",
        "event_labels": {
            "BULLISH": "HAWKISH HOLD/HIKE (Tight Policy)",
            "BEARISH": "DOVISH PIVOT/CUT (Easing Policy)",
            "INLINE": "INLINE / AS EXPECTED",
        },
        "explanations": {
            "BULLISH": "Sticky core inflation and firm labor data force the Fed to maintain restrictive rates. Higher-for-longer policy drives USD upside.",
            "BEARISH": "Decelerating inflation and rising jobless metrics increase Fed easing pressure. A dovish stance triggers USD selling and gold buying.",
            "INLINE": "Rate decision expected to be fully priced. Volatility will center on the press conference.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / LISTEN TO PRESS CONFERENCE"],
        },
        "indicators": [
            ("CPILFESL", 0.30, +1, "Core CPI — persistent sticky inflation keeps Fed hawkish"),
            ("T10Y2Y",   0.25, -1, "10Y-2Y Yield Curve — recession signal / cut pressure"),
            ("UNRATE",   0.25, -1, "Unemployment Rate — higher rate triggers Fed easing"),
            ("PCEPILFE", 0.20, +1, "Core PCE Price Index — Fed's official target metric"),
        ],
    },

    "RETAIL_SALES": {
        "display_name": "Retail Sales",
        "currency": "USD",
        "impact": "red",
        "history_series": "RSXFS",
        "event_labels": {
            "BULLISH": "STRONG SALES (Robust Demand)",
            "BEARISH": "WEAK SALES (Spending Slowdown)",
            "INLINE": "INLINE (Steady)",
        },
        "explanations": {
            "BULLISH": "Consumer sentiment and credit momentum show strong spending appetite (70% of US GDP). Bullish for USD and Treasury yields.",
            "BEARISH": "Spending is cooling as consumers pull back. Soft retail sales point to economic deceleration, bearish for USD.",
            "INLINE": "Sales growth is tracking consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("UMCSENT",         0.35, +1, "U. Michigan Consumer Sentiment — spending intent"),
            ("GASREGCOVW",      0.20, -1, "Gasoline Prices — lower gas frees up retail spending"),
            ("IC4WSA",          0.25, -1, "Initial Jobless Claims — low claims boost retail confidence"),
            ("CSCICP03USM665S", 0.20, +1, "Consumer Confidence Index — forward spending signal"),
        ],
    },

    "ISM_MFG": {
        "display_name": "ISM Manufacturing PMI",
        "currency": "USD",
        "impact": "red",
        "history_series": "MANEMP",
        "event_labels": {
            "BULLISH": "EXPANDING PMI (Factory Growth)",
            "BEARISH": "CONTRACTING PMI (Factory Slowdown)",
            "INLINE": "INLINE (Neutral)",
        },
        "explanations": {
            "BULLISH": "Factory orders and production proxies signal industrial expansion. Positive for USD and US Equities (US30).",
            "BEARISH": "Factory orders and employment sub-indices signal industrial contraction. Pressure on USD and cyclical stocks.",
            "INLINE": "Manufacturing activity is matching forecast.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / RANGE BOUND"],
        },
        "indicators": [
            ("AMTMNO", 0.35, +1, "Mfg New Orders — direct leading indicator for ISM"),
            ("IPMAN",  0.30, +1, "Industrial Production Mfg — actual physical factory output"),
            ("MANEMP", 0.20, +1, "Mfg Employment Sub-index — capacity demand signal"),
            ("PPICRM", 0.15, -1, "PPI Crude Materials — rising input costs compress margins"),
        ],
    },

    "GDP": {
        "display_name": "GDP Growth Rate",
        "currency": "USD",
        "impact": "red",
        "history_series": "A191RL1Q225SBEA",
        "event_labels": {
            "BULLISH": "STRONG GROWTH (Economic Expansion)",
            "BEARISH": "WEAK GROWTH (Economic Deceleration)",
            "INLINE": "INLINE (Steady Growth)",
        },
        "explanations": {
            "BULLISH": "Industrial production, consumer spending, and employment all point to solid economic output. Bullish for USD and US500.",
            "BEARISH": "Leading output proxies signal an economic slowdown. Bearish for USD as Fed easing bets rise.",
            "INLINE": "GDP growth is tracking consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO DIRECTIONAL BIAS"],
        },
        "indicators": [
            ("INDPRO",  0.30, +1, "Industrial Production Index — real output proxy"),
            ("RSXFS",   0.25, +1, "Retail Sales ex-Food — consumer spending (70% of GDP)"),
            ("PAYEMS",  0.20, +1, "Nonfarm Payrolls — labor income drives consumption"),
            ("UMCSENT", 0.15, +1, "Consumer Sentiment — forward-looking demand signal"),
            ("AMTMNO",  0.10, +1, "Mfg New Orders — business capital investment proxy"),
        ],
    },

    "CORE_PPI": {
        "display_name": "Core PPI (ex. Food & Energy)",
        "currency": "USD",
        "impact": "red",
        "history_series": "PPIFES",
        "event_labels": {
            "BULLISH": "HOT CORE PPI (Producer Pressure)",
            "BEARISH": "COOL CORE PPI (Easing Upstream Costs)",
            "INLINE": "INLINE (Neutral)",
        },
        "explanations": {
            "BULLISH": "Core producer prices lean elevated. Upstream pricing pressure feeds into core consumer inflation, supporting USD.",
            "BEARISH": "Core wholesale inflation decelerates, relieving Fed rate pressure and softening USD.",
            "INLINE": "Core producer costs remain in line with consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("PPIFES",      0.35, +1, "PPI Final Demand ex Food & Energy"),
            ("DCOILWTICO",  0.25, +1, "WTI Crude Oil — baseline cost input"),
            ("PPIFIS",      0.20, +1, "PPI Final Demand — pipeline pricing"),
            ("PCUOMFGOMFG", 0.20, +1, "PPI Manufacturing Output"),
        ],
    },

    "CORE_RETAIL_SALES": {
        "display_name": "Core Retail Sales (ex. Auto & Gas)",
        "currency": "USD",
        "impact": "red",
        "history_series": "RSXFS",
        "event_labels": {
            "BULLISH": "STRONG CORE CONSUMPTION",
            "BEARISH": "COOLING CORE CONSUMPTION",
            "INLINE": "INLINE CONSUMPTION",
        },
        "explanations": {
            "BULLISH": "Core consumer spending excluding volatile auto/gas stays resilient, reinforcing USD yields.",
            "BEARISH": "Core retail sales pull back, signaling household spending fatigue.",
            "INLINE": "Core sales track market expectations.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("UMCSENT", 0.40, +1, "Consumer Sentiment — underlying spending appetite"),
            ("IC4WSA",  0.30, -1, "4-Week Jobless Claims — employment stability"),
            ("RSXFS",   0.30, +1, "Retail Sales ex Food Services"),
        ],
    },

    "ISM_SERVICES": {
        "display_name": "ISM Services PMI (Non-Mfg)",
        "currency": "USD",
        "impact": "red",
        "history_series": "PPIFES",
        "event_labels": {
            "BULLISH": "EXPANDING SERVICES (Hot Services)",
            "BEARISH": "CONTRACTING SERVICES (Services Slowdown)",
            "INLINE": "INLINE SERVICES",
        },
        "explanations": {
            "BULLISH": "Services sector expansion (~80% of US GDP) points to solid growth and sticky inflation, bullish for USD.",
            "BEARISH": "Services PMI deceleration signals broader economic slowdown, weighing on USD.",
            "INLINE": "Services activity aligns with expectations.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("PPIFES",  0.35, +1, "PPI Final Demand Services"),
            ("SRVPRD",  0.35, +1, "Service-Providing Employment"),
            ("UMCSENT", 0.30, +1, "Consumer Sentiment"),
        ],
    },

    "AVG_HOURLY_EARNINGS": {
        "display_name": "Average Hourly Earnings m/m",
        "currency": "USD",
        "impact": "red",
        "history_series": "CES0500000003",
        "event_labels": {
            "BULLISH": "HOT WAGE GROWTH (Wage Inflation)",
            "BEARISH": "COOLING WAGE GROWTH (Easing Inflation)",
            "INLINE": "INLINE WAGE GROWTH",
        },
        "explanations": {
            "BULLISH": "Accelerating wage growth sparks fears of wage-price spiral inflation, strengthening USD and Treasury yields.",
            "BEARISH": "Decelerating wage pressure relieves inflation concerns, weighing on USD.",
            "INLINE": "Wage growth tracks consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / WATCH HEADLINE NFP"],
        },
        "indicators": [
            ("CES0500000003", 0.40, +1, "Average Hourly Earnings Total Private"),
            ("MANEMP",        0.30, +1, "ISM Mfg Employment"),
            ("IC4WSA",        0.30, -1, "4-Week Avg Jobless Claims"),
        ],
    },

    "ADP_NFP": {
        "display_name": "ADP Non-Farm Employment Change",
        "currency": "USD",
        "impact": "orange",
        "history_series": "ADPWNUSNERSA",
        "event_labels": {
            "BULLISH": "STRONG PRIVATE HIRING",
            "BEARISH": "WEAK PRIVATE HIRING",
            "INLINE": "INLINE ADP HIRING",
        },
        "explanations": {
            "BULLISH": "Solid private payrolls additions signal robust private sector hiring ahead of NFP, supporting USD.",
            "BEARISH": "Soft ADP payrolls indicate private hiring deceleration, dragging USD lower.",
            "INLINE": "ADP private payrolls match expectations.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / WATCH OFFICIAL NFP"],
        },
        "indicators": [
            ("ADPWNUSNERSA", 0.50, +1, "ADP Private Employment"),
            ("IC4WSA",       0.30, -1, "4-Week Avg Jobless Claims"),
            ("JTSLDL",       0.20, -1, "Layoffs & Discharges"),
        ],
    },

    "JOLTS": {
        "display_name": "JOLTS Job Openings",
        "currency": "USD",
        "impact": "orange",
        "history_series": "JTSJOL",
        "event_labels": {
            "BULLISH": "HIGH JOB OPENINGS (Tight Labor)",
            "BEARISH": "FALLING JOB OPENINGS (Cooling Labor)",
            "INLINE": "STEADY JOB OPENINGS",
        },
        "explanations": {
            "BULLISH": "Elevated job openings demonstrate strong worker demand, supporting USD strength.",
            "BEARISH": "Declining job vacancies signal labor demand normalization, weighing on USD.",
            "INLINE": "Job openings track expectations.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("IC4WSA",  0.40, -1, "4-Week Avg Jobless Claims"),
            ("MANEMP",  0.30, +1, "ISM Mfg Employment"),
            ("JTSLDL",  0.30, -1, "Layoffs & Discharges"),
        ],
    },

    "CORE_PCE": {
        "display_name": "Core PCE Price Index (Fed Preferred Inflation)",
        "currency": "USD",
        "impact": "red",
        "history_series": "PCEPILFE",
        "event_labels": {
            "BULLISH": "HOT CORE PCE (Hawkish Fed)",
            "BEARISH": "COOL CORE PCE (Fed Easing)",
            "INLINE": "INLINE CORE PCE",
        },
        "explanations": {
            "BULLISH": "The Fed's official benchmark inflation metric leans hot. Sticky core PCE forces the Fed to hold rates higher for longer, boosting USD yields.",
            "BEARISH": "Core PCE price index decelerates toward the 2% target, strengthening Fed rate cut bets and pressuring USD.",
            "INLINE": "Core PCE matches market consensus exactly.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("PCEPILFE",  0.35, +1, "Core PCE Price Index — Fed target series"),
            ("CPILFESL",  0.30, +1, "Core Consumer Price Index — consumer core proxy"),
            ("PPIFES",    0.20, +1, "PPI Final Demand Services — service inflation driver"),
            ("PPIACO",    0.15, +1, "PPI All Commodities — producer input cost"),
        ],
    },

    "PCE": {
        "display_name": "PCE Price Index (Headline)",
        "currency": "USD",
        "impact": "red",
        "history_series": "PCEPI",
        "event_labels": {
            "BULLISH": "HOT HEADLINE PCE",
            "BEARISH": "COOL HEADLINE PCE",
            "INLINE": "INLINE HEADLINE PCE",
        },
        "explanations": {
            "BULLISH": "Headline PCE inflation runs hot due to energy and services input pressure, driving USD upside.",
            "BEARISH": "Headline PCE decelerates, relieving tightening pressure and weakening USD.",
            "INLINE": "PCE headline tracks expectations.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("PCEPI",      0.35, +1, "Headline PCE Price Index"),
            ("GASREGCOVW", 0.30, +1, "Retail Gasoline Prices — energy component"),
            ("PPIFES",     0.20, +1, "PPI Final Demand Services"),
            ("PPIACO",     0.15, +1, "PPI All Commodities"),
        ],
    },

    # ── USD orange-folder events (medium impact) ──────────────────────────────

    "BUILDING_PERMITS": {
        "display_name": "Building Permits",
        "currency": "USD",
        "impact": "orange",
        "history_series": "PERMIT",
        "event_labels": {
            "BULLISH": "HIGH PERMITS (Construction Boom)",
            "BEARISH": "LOW PERMITS (Construction Slowdown)",
            "INLINE": "INLINE PERMITS",
        },
        "explanations": {
            "BULLISH": "Rising permit issuance signals construction investment growth, a positive leading indicator for GDP.",
            "BEARISH": "Declining permits suggest housing-sector weakness, weighing on broader economic outlook.",
            "INLINE": "Permits track consensus; limited directional impact.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("PERMIT",   0.50, +1, "Building Permits — housing sector leading indicator"),
            ("HOUST",    0.30, +1, "Housing Starts — construction activity"),
            ("UMCSENT",  0.20, +1, "Consumer Sentiment — housing demand proxy"),
        ],
    },

    "HOUSING_STARTS": {
        "display_name": "Housing Starts",
        "currency": "USD",
        "impact": "orange",
        "history_series": "HOUST",
        "event_labels": {
            "BULLISH": "STRONG STARTS (Construction Momentum)",
            "BEARISH": "WEAK STARTS (Housing Contraction)",
            "INLINE": "INLINE STARTS",
        },
        "explanations": {
            "BULLISH": "Robust housing starts confirm real estate expansion, positive for economic growth outlook.",
            "BEARISH": "Falling starts signal a housing-led slowdown.",
            "INLINE": "Housing starts match expectations.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("HOUST",   0.50, +1, "Housing Starts"),
            ("PERMIT",  0.30, +1, "Building Permits — lead indicator for starts"),
            ("MORTGAGE30US", 0.20, -1, "30Y Mortgage Rate — higher rates suppress starts"),
        ],
    },

    "DURABLE_GOODS": {
        "display_name": "Durable Goods Orders m/m",
        "currency": "USD",
        "impact": "orange",
        "history_series": "DGORDER",
        "event_labels": {
            "BULLISH": "STRONG ORDERS (Business Investment)",
            "BEARISH": "WEAK ORDERS (CapEx Pullback)",
            "INLINE": "INLINE DURABLE GOODS",
        },
        "explanations": {
            "BULLISH": "Broad durable goods orders beat, signaling rising business capital investment — USD positive.",
            "BEARISH": "Orders miss, pointing to a pullback in manufacturing investment.",
            "INLINE": "Orders track consensus; watch ex-transportation for core signal.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("AMTMNO",  0.40, +1, "Mfg New Orders — CapEx proxy"),
            ("IPMAN",   0.35, +1, "Industrial Production Mfg"),
            ("MANEMP",  0.25, +1, "ISM Mfg Employment"),
        ],
    },

    "TRADE_BALANCE": {
        "display_name": "US Trade Balance",
        "currency": "USD",
        "impact": "orange",
        "history_series": "BOPGSTB",
        "event_labels": {
            "BULLISH": "NARROWING DEFICIT (Stronger Exports)",
            "BEARISH": "WIDENING DEFICIT (Weaker Exports)",
            "INLINE": "INLINE TRADE BALANCE",
        },
        "explanations": {
            "BULLISH": "A narrowing trade deficit implies stronger export demand for US goods, mildly supportive for USD.",
            "BEARISH": "A widening deficit reflects weakening external demand and import acceleration.",
            "INLINE": "Trade balance meets consensus; limited market impact expected.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("BOPGSTB",    0.50, +1, "US Trade Balance — narrowing = positive"),
            ("INDPRO",     0.30, +1, "Industrial Production — export capacity"),
            ("DCOILWTICO", 0.20, -1, "WTI Crude — high oil = wider energy import deficit"),
        ],
    },

    "INDUSTRIAL_PRODUCTION": {
        "display_name": "Industrial Production m/m",
        "currency": "USD",
        "impact": "orange",
        "history_series": "INDPRO",
        "event_labels": {
            "BULLISH": "STRONG OUTPUT (Factory Expansion)",
            "BEARISH": "WEAK OUTPUT (Factory Contraction)",
            "INLINE": "INLINE PRODUCTION",
        },
        "explanations": {
            "BULLISH": "Industrial output growth confirms manufacturing expansion, supporting USD and equities.",
            "BEARISH": "Contracting production adds to recession concerns.",
            "INLINE": "Industrial output tracks consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("INDPRO",  0.50, +1, "Industrial Production Index"),
            ("IPMAN",   0.30, +1, "Industrial Production Mfg"),
            ("MANEMP",  0.20, +1, "ISM Mfg Employment"),
        ],
    },

    "EMPIRE_STATE": {
        "display_name": "Empire State Manufacturing Index",
        "currency": "USD",
        "impact": "orange",
        "history_series": "GACDISA066MSFRBNY",
        "event_labels": {
            "BULLISH": "EXPANDING NY FACTORY SECTOR",
            "BEARISH": "CONTRACTING NY FACTORY SECTOR",
            "INLINE": "INLINE EMPIRE STATE",
        },
        "explanations": {
            "BULLISH": "A positive Empire State index reading points to northeastern manufacturing expansion, an early-month leading indicator.",
            "BEARISH": "A negative reading signals contraction in the NY Fed district.",
            "INLINE": "Empire State index meets expectations.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("AMTMNO",  0.50, +1, "Mfg New Orders"),
            ("IPMAN",   0.30, +1, "Industrial Production Mfg"),
            ("MANEMP",  0.20, +1, "ISM Mfg Employment"),
        ],
    },

    "PHILLY_FED": {
        "display_name": "Philadelphia Fed Manufacturing Index",
        "currency": "USD",
        "impact": "orange",
        "history_series": "MANEMP",
        "event_labels": {
            "BULLISH": "EXPANDING PHILLY FED",
            "BEARISH": "CONTRACTING PHILLY FED",
            "INLINE": "INLINE PHILLY FED",
        },
        "explanations": {
            "BULLISH": "Philly Fed expansion signals Mid-Atlantic manufacturing strength, positive for USD.",
            "BEARISH": "Philly Fed contraction adds to industrial slowdown concern.",
            "INLINE": "Philly Fed meets expectations.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("AMTMNO",  0.50, +1, "Mfg New Orders"),
            ("IPMAN",   0.30, +1, "Industrial Production Mfg"),
            ("MANEMP",  0.20, +1, "ISM Mfg Employment"),
        ],
    },

    "GDP_DEFLATOR": {
        "display_name": "GDP Price Index / Deflator",
        "currency": "USD",
        "impact": "orange",
        "history_series": "GDPDEF",
        "event_labels": {
            "BULLISH": "RISING DEFLATOR (Broad Inflation)",
            "BEARISH": "FALLING DEFLATOR (Disinflation)",
            "INLINE": "INLINE DEFLATOR",
        },
        "explanations": {
            "BULLISH": "A rising GDP deflator indicates broad-based price growth across the entire economy, reinforcing hawkish Fed bias.",
            "BEARISH": "Falling deflator suggests economy-wide disinflation.",
            "INLINE": "Deflator meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "BUY USDCHF", "BUY USDCAD", "SELL EURUSD", "SELL GBPUSD", "SELL AUDUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL USDCHF", "SELL USDCAD", "BUY EURUSD", "BUY GBPUSD", "BUY AUDUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("GDPDEF",   0.40, +1, "GDP Implicit Price Deflator"),
            ("PCEPI",    0.30, +1, "Headline PCE — demand-side inflation"),
            ("PPIACO",   0.30, +1, "PPI All Commodities — supply-side costs"),
        ],
    },

    # ═════════════════════════════════════════════════════════════════════════
    # END OF EVENTS (USD-only)
    # ═════════════════════════════════════════════════════════════════════════
}


# ══════════════════════════════════════════════════════════════════════════════
# LOOKUP HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_event_config(event_code: str) -> dict:
    """Return event configuration with dynamic fallback for any unlisted code."""
    code = (event_code or "").upper()
    if code in EVENTS:
        return EVENTS[code]

    # Dynamic fallback — USD assumed for unmapped FF events
    return {
        "display_name": code.replace("_", " ").title(),
        "currency": "USD",
        "impact": "orange",
        "history_series": "INDPRO",
        "event_labels": {
            "BULLISH": f"BULLISH SURPRISE ({code})",
            "BEARISH": f"BEARISH SURPRISE ({code})",
            "INLINE": f"INLINE ({code})",
        },
        "explanations": {
            "BULLISH": f"Leading indicators point to economic upside for {code}.",
            "BEARISH": f"Leading indicators point to economic downside for {code}.",
            "INLINE": f"{code} signals are balanced. Monitor actual release.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "SELL EURUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "BUY EURUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("INDPRO",  0.35, +1, "Industrial Production Index"),
            ("IC4WSA",  0.35, -1, "4-Week Jobless Claims Avg"),
            ("UMCSENT", 0.30, +1, "Consumer Sentiment"),
        ],
    }


def get_events_for_currency(currency: str) -> dict:
    """Return all event definitions for a given currency code."""
    ccy = currency.upper()
    return {k: v for k, v in EVENTS.items() if v.get("currency") == ccy}


def get_events_by_impact(impact: str) -> dict:
    """Return all event definitions matching 'red' or 'orange'."""
    return {k: v for k, v in EVENTS.items() if v.get("impact") == impact.lower()}


def get_affected_pairs(base_currency: str) -> list[str]:
    """
    Return the canonical pairs where this currency is base or quote.
    Used by api.py to build the per-event affected-pair list.
    """
    ccy = base_currency.upper()
    return [p for p in CANONICAL_PAIRS if p.startswith(ccy) or p.endswith(ccy)]
