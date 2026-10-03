"""
events.py — Event definitions, leading indicator weights, currency metadata,
and pair-routing logic for the multi-currency strength architecture.

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
      4. sentiment_score   — FinBERT 48h net score

PAIR BIAS
  pair_bias(BASE/QUOTE) = strength(BASE) - strength(QUOTE)
  XAUUSD: treated as -USD_strength adjusted by real-yield correlation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

# ── Currency metadata ─────────────────────────────────────────────────────────
# All tradeable pairs derived from the 8 core currencies + XAUUSD.
# Each entry: (base, quote) — bias = strength(base) - strength(quote).

CURRENCIES = ["USD", "EUR", "GBP", "JPY", "AUD", "CHF", "CAD", "NZD"]

# Canonical pairs the dashboard shows per-event.
# Derived dynamically in api.py but listed here as the display priority order.
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

# XAUUSD: Gold is priced inversely to USD real yields.
# Modelled as base="XAU" with strength derived from -USD_strength × real_yield_beta.
XAUUSD_USD_BETA = -0.85   # historical average; River will refine this over time

# Central bank benchmark yield series used for rate-differential computation.
# Values are (ecb_sdw_series_key_or_fred_id, source) — fetched by data_sources.py.
RATE_SERIES = {
    "USD": ("DGS10",          "fred"),        # US 10Y Treasury — FRED
    "EUR": ("IRS.M.U2.L.L40.CI.0000.EUR.N",  "ecb_sdw"),   # EA 10Y swap rate proxy
    "GBP": ("IUDMNZC",        "boe"),         # UK Gilt nominal zero coupon 10Y — BoE
    "JPY": ("IRS.M.JP.L.L40.CI.0000.JPY.N",  "ecb_sdw"),   # JPY 10Y IRS (ECB mirrors)
    "AUD": ("IR3TIB01AUM156N","fred"),         # Australia 3M interbank (FRED proxies)
    "CHF": ("IRS.M.CH.L.L40.CI.0000.CHF.N",  "ecb_sdw"),   # CHF 10Y IRS
    "CAD": ("IR3TIB01CAM156N","fred"),         # Canada 3M interbank — FRED
    "NZD": ("IR3TIB01NZM156N","fred"),         # NZ 3M interbank — FRED
}

# CFTC COT futures ticker codes (used by cot_reports library).
COT_CODES = {
    "USD": "US DOLLAR INDEX - ICE FUTURES U.S.",
    "EUR": "EURO FX - CHICAGO MERCANTILE EXCHANGE",
    "GBP": "BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE",
    "JPY": "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE",
    "AUD": "AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",
    "CHF": "SWISS FRANC - CHICAGO MERCANTILE EXCHANGE",
    "CAD": "CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",
    "NZD": "NZ DOLLAR - CHICAGO MERCANTILE EXCHANGE",
}

# RSS feeds for sentiment.py — central bank speech pages + forex media
RSS_FEEDS = {
    "USD": [
        "https://www.federalreserve.gov/feeds/speeches.xml",
        "https://www.forexlive.com/feed/news/",
        "https://www.fxstreet.com/rss/news",
    ],
    "EUR": [
        "https://www.ecb.europa.eu/rss/fservices/speeches.xml",
        "https://www.forexlive.com/feed/news/",
    ],
    "GBP": [
        "https://www.bankofengland.co.uk/rss/speeches",
        "https://www.forexlive.com/feed/news/",
    ],
    "JPY": [
        "https://www.boj.or.jp/en/announcements/release_2024/rss/index.xml",
        "https://www.forexlive.com/feed/news/",
    ],
    "AUD": [
        "https://www.rba.gov.au/rss/rss-cb-speeches.xml",
        "https://www.forexlive.com/feed/news/",
    ],
    "CHF": [
        "https://www.snb.ch/en/rss/news",
        "https://www.forexlive.com/feed/news/",
    ],
    "CAD": [
        "https://www.bankofcanada.ca/feeds/news/",
        "https://www.forexlive.com/feed/news/",
    ],
    "NZD": [
        "https://www.rbnz.govt.nz/hub/news/rss",
        "https://www.forexlive.com/feed/news/",
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
    # EUR EVENTS
    # Indicators: ECB SDW (prefix "ECB:"), Eurostat (prefix "ESTAT:"),
    #             OECD (prefix "OECD:"), FRED where available
    # ═════════════════════════════════════════════════════════════════════════

    "EUR_CPI": {
        "display_name": "Eurozone HICP Inflation (Flash / Final)",
        "currency": "EUR",
        "impact": "red",
        "history_series": "ECB:ICP.M.U2.N.000000.4.ANR",
        "event_labels": {
            "BULLISH": "HOT HICP (Hawkish ECB)",
            "BEARISH": "COOL HICP (Dovish ECB)",
            "INLINE": "INLINE HICP",
        },
        "explanations": {
            "BULLISH": "Eurozone headline HICP runs above ECB target. Hot print delays ECB cuts, boosting EUR.",
            "BEARISH": "Cooling HICP accelerates ECB easing expectations, weighing on EUR.",
            "INLINE": "HICP meets consensus; limited EUR move.",
        },
        "trade_signals": {
            "BULLISH": ["BUY EURUSD", "BUY EURGBP", "BUY EURJPY", "BUY EURCHF", "BUY EURAUD", "BUY EURCAD", "BUY EURNZD"],
            "BEARISH": ["SELL EURUSD", "SELL EURGBP", "SELL EURJPY", "SELL EURCHF", "SELL EURAUD", "SELL EURCAD", "SELL EURNZD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("ECB:ICP.M.U2.N.000000.4.ANR",  0.35, +1, "EA HICP All-Items YoY — ECB SDW"),
            ("ECB:ICP.M.U2.N.XEF000.4.ANR",  0.30, +1, "EA HICP ex. Energy & Food (Core) — ECB SDW"),
            ("ECB:ICP.M.U2.N.IGXE0000.4.ANR",0.20, +1, "EA HICP Services — sticky component"),
            ("ESTAT:prc_hicp_manr",           0.15, +1, "Eurostat HICP MoM — EU-wide cross-check"),
        ],
    },

    "EUR_CORE_CPI": {
        "display_name": "Eurozone Core HICP (ex. Energy & Food)",
        "currency": "EUR",
        "impact": "red",
        "history_series": "ECB:ICP.M.U2.N.XEF000.4.ANR",
        "event_labels": {
            "BULLISH": "STICKY CORE (ECB Cautious)",
            "BEARISH": "COOLING CORE (ECB Easing)",
            "INLINE": "INLINE CORE",
        },
        "explanations": {
            "BULLISH": "Core HICP remaining elevated forces ECB to stay cautious on cuts, EUR bullish.",
            "BEARISH": "Core HICP declining gives ECB room to cut, EUR bearish.",
            "INLINE": "Core HICP in line; ECB likely on hold.",
        },
        "trade_signals": {
            "BULLISH": ["BUY EURUSD", "BUY EURGBP", "BUY EURJPY", "BUY EURCHF", "BUY EURAUD", "BUY EURCAD", "BUY EURNZD"],
            "BEARISH": ["SELL EURUSD", "SELL EURGBP", "SELL EURJPY", "SELL EURCHF", "SELL EURAUD", "SELL EURCAD", "SELL EURNZD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("ECB:ICP.M.U2.N.XEF000.4.ANR",   0.40, +1, "EA Core HICP YoY — ECB SDW"),
            ("ECB:ICP.M.U2.N.IGXE0000.4.ANR",  0.35, +1, "EA HICP Services — persistent services inflation"),
            ("ESTAT:prc_hicp_manr",             0.25, +1, "Eurostat HICP — EU-wide confirmation"),
        ],
    },

    "EUR_GDP": {
        "display_name": "Eurozone GDP Growth (Flash / Final)",
        "currency": "EUR",
        "impact": "red",
        "history_series": "ECB:MNA.Q.Y.I8.W0.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.GY",
        "event_labels": {
            "BULLISH": "ABOVE-TREND GROWTH",
            "BEARISH": "CONTRACTION / STAGNATION",
            "INLINE": "INLINE GDP",
        },
        "explanations": {
            "BULLISH": "Eurozone growth beats consensus, reducing need for further ECB easing — EUR bullish.",
            "BEARISH": "Growth miss increases ECB cut pressure, EUR bearish.",
            "INLINE": "GDP meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY EURUSD", "BUY EURGBP", "BUY EURJPY", "BUY EURCHF", "BUY EURAUD", "BUY EURCAD", "BUY EURNZD"],
            "BEARISH": ["SELL EURUSD", "SELL EURGBP", "SELL EURJPY", "SELL EURCHF", "SELL EURAUD", "SELL EURCAD", "SELL EURNZD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("ECB:MNA.Q.Y.I8.W0.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.GY", 0.35, +1, "EA GDP QoQ — ECB SDW"),
            ("ESTAT:namq_10_gdp",     0.30, +1, "Eurostat GDP QoQ — EU-level confirmation"),
            ("ECB:ICP.M.U2.N.000000.4.ANR", 0.20, +1, "EA HICP — growth-inflation mix"),
            ("OECD:QNA/EA19.B1_GE.GYSA.Q", 0.15, +1, "OECD EA GDP YoY growth — cross-country check"),
        ],
    },

    "ECB_RATE": {
        "display_name": "ECB Interest Rate Decision",
        "currency": "EUR",
        "impact": "red",
        "history_series": "ECB:FM.M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA",
        "event_labels": {
            "BULLISH": "HAWKISH HOLD / HIKE",
            "BEARISH": "DOVISH CUT / GUIDANCE",
            "INLINE": "AS EXPECTED",
        },
        "explanations": {
            "BULLISH": "ECB holds or signals prolonged restrictive policy. EUR strengthens as rate differential narrows vs peers.",
            "BEARISH": "ECB cuts or signals forthcoming easing. EUR weakens broadly.",
            "INLINE": "Decision in line with market pricing.",
        },
        "trade_signals": {
            "BULLISH": ["BUY EURUSD", "BUY EURGBP", "BUY EURJPY", "BUY EURCHF", "BUY EURAUD", "BUY EURCAD", "BUY EURNZD"],
            "BEARISH": ["SELL EURUSD", "SELL EURGBP", "SELL EURJPY", "SELL EURCHF", "SELL EURAUD", "SELL EURCAD", "SELL EURNZD"],
            "INLINE": ["WAIT / LISTEN TO LAGARDE"],
        },
        "indicators": [
            ("ECB:ICP.M.U2.N.000000.4.ANR",  0.35, +1, "EA HICP — inflation mandate pressure"),
            ("ECB:ICP.M.U2.N.XEF000.4.ANR",  0.30, +1, "EA Core HICP — persistent core pressure"),
            ("ESTAT:namq_10_gdp",             0.20, -1, "EA GDP — weak growth = pressure to cut"),
            ("ECB:FM.M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA", 0.15, +1, "Euribor 3M — market rate expectations"),
        ],
    },

    "EUR_PMI_MFG": {
        "display_name": "Eurozone Manufacturing PMI (Flash)",
        "currency": "EUR",
        "impact": "red",
        "history_series": "ECB:STS.M.I8.Y.PROD.NS0010.4.000",
        "event_labels": {
            "BULLISH": "EXPANDING EA MANUFACTURING",
            "BEARISH": "CONTRACTING EA MANUFACTURING",
            "INLINE": "INLINE EA PMI",
        },
        "explanations": {
            "BULLISH": "Flash PMI above 50 signals factory expansion across the Eurozone, EUR supportive.",
            "BEARISH": "Sub-50 reading confirms manufacturing contraction, EUR bearish.",
            "INLINE": "PMI meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY EURUSD", "BUY EURGBP", "BUY EURJPY", "BUY EURCHF", "BUY EURAUD", "BUY EURCAD", "BUY EURNZD"],
            "BEARISH": ["SELL EURUSD", "SELL EURGBP", "SELL EURJPY", "SELL EURCHF", "SELL EURAUD", "SELL EURCAD", "SELL EURNZD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("ECB:STS.M.I8.Y.PROD.NS0010.4.000", 0.40, +1, "EA Industrial Production — ECB SDW"),
            ("ESTAT:sts_inpr_m",                  0.35, +1, "Eurostat Industrial Output MoM"),
            ("ECB:ICP.M.U2.N.000000.4.ANR",       0.25, -1, "HICP — high inflation = margin squeeze"),
        ],
    },

    "EUR_PMI_SERVICES": {
        "display_name": "Eurozone Services PMI (Flash)",
        "currency": "EUR",
        "impact": "red",
        "history_series": "ECB:STS.M.I8.Y.EMPL.NS0200.4.000",
        "event_labels": {
            "BULLISH": "EXPANDING EA SERVICES",
            "BEARISH": "CONTRACTING EA SERVICES",
            "INLINE": "INLINE EA SERVICES PMI",
        },
        "explanations": {
            "BULLISH": "Services expansion in the Eurozone supports consumer spending and EUR.",
            "BEARISH": "Services contraction signals broad economic weakness in the bloc.",
            "INLINE": "Services PMI meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY EURUSD", "BUY EURGBP", "BUY EURJPY", "BUY EURCHF", "BUY EURAUD", "BUY EURCAD", "BUY EURNZD"],
            "BEARISH": ["SELL EURUSD", "SELL EURGBP", "SELL EURJPY", "SELL EURCHF", "SELL EURAUD", "SELL EURCAD", "SELL EURNZD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("ECB:STS.M.I8.Y.EMPL.NS0200.4.000", 0.40, +1, "EA Services Employment — ECB SDW"),
            ("ECB:ICP.M.U2.N.IGXE0000.4.ANR",    0.35, +1, "EA HICP Services — sticky services inflation"),
            ("ESTAT:namq_10_gdp",                 0.25, +1, "EA GDP — services-led growth"),
        ],
    },

    "EUR_UNEMPLOYMENT": {
        "display_name": "Eurozone Unemployment Rate",
        "currency": "EUR",
        "impact": "orange",
        "history_series": "ECB:STS.M.I8.S.UNEH.RTT000.4.000",
        "event_labels": {
            "BULLISH": "FALLING UNEMPLOYMENT",
            "BEARISH": "RISING UNEMPLOYMENT",
            "INLINE": "STEADY UNEMPLOYMENT",
        },
        "explanations": {
            "BULLISH": "Tightening EA labor market reduces ECB cut pressure, EUR supportive.",
            "BEARISH": "Rising unemployment increases pressure for ECB to cut rates.",
            "INLINE": "Unemployment in line.",
        },
        "trade_signals": {
            "BULLISH": ["BUY EURUSD", "BUY EURGBP", "BUY EURJPY", "BUY EURCHF", "BUY EURAUD", "BUY EURCAD", "BUY EURNZD"],
            "BEARISH": ["SELL EURUSD", "SELL EURGBP", "SELL EURJPY", "SELL EURCHF", "SELL EURAUD", "SELL EURCAD", "SELL EURNZD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("ECB:STS.M.I8.S.UNEH.RTT000.4.000", 0.50, -1, "EA Unemployment Rate — lower = bullish EUR"),
            ("ESTAT:une_rt_m",                    0.30, -1, "Eurostat Unemployment Rate"),
            ("ECB:STS.M.I8.Y.EMPL.NS0200.4.000", 0.20, +1, "EA Employment — rising = bullish EUR"),
        ],
    },

    "GERMAN_IFO": {
        "display_name": "German Ifo Business Climate",
        "currency": "EUR",
        "impact": "orange",
        "history_series": "DBUSINESS",
        "event_labels": {
            "BULLISH": "IMPROVING BUSINESS CLIMATE",
            "BEARISH": "DETERIORATING BUSINESS CLIMATE",
            "INLINE": "INLINE IFO",
        },
        "explanations": {
            "BULLISH": "Ifo index improvement signals German (and by extension EA) economic confidence strengthening, EUR positive.",
            "BEARISH": "Declining Ifo reflects falling business expectations in Europe's largest economy.",
            "INLINE": "Ifo meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY EURUSD", "BUY EURGBP", "BUY EURJPY", "BUY EURCHF", "BUY EURAUD", "BUY EURCAD", "BUY EURNZD"],
            "BEARISH": ["SELL EURUSD", "SELL EURGBP", "SELL EURJPY", "SELL EURCHF", "SELL EURAUD", "SELL EURCAD", "SELL EURNZD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("ESTAT:sts_inpr_m",               0.40, +1, "Eurostat Industrial Output — business activity"),
            ("ECB:ICP.M.U2.N.000000.4.ANR",   0.30, -1, "HICP — high inflation = business cost pressure"),
            ("ESTAT:namq_10_gdp",              0.30, +1, "EA GDP — business cycle confirmation"),
        ],
    },

    "GERMAN_ZEW": {
        "display_name": "German ZEW Economic Sentiment",
        "currency": "EUR",
        "impact": "orange",
        "history_series": "DBUSINESS",
        "event_labels": {
            "BULLISH": "POSITIVE ANALYST EXPECTATIONS",
            "BEARISH": "NEGATIVE ANALYST EXPECTATIONS",
            "INLINE": "INLINE ZEW",
        },
        "explanations": {
            "BULLISH": "ZEW above zero reflects investor optimism for Germany's 6-month economic outlook, EUR supportive.",
            "BEARISH": "Negative ZEW signals investor pessimism for the German/EA economic outlook.",
            "INLINE": "ZEW meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY EURUSD", "BUY EURGBP", "BUY EURJPY", "BUY EURCHF", "BUY EURAUD", "BUY EURCAD", "BUY EURNZD"],
            "BEARISH": ["SELL EURUSD", "SELL EURGBP", "SELL EURJPY", "SELL EURCHF", "SELL EURAUD", "SELL EURCAD", "SELL EURNZD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("ESTAT:sts_inpr_m",   0.40, +1, "Eurostat Industrial Output"),
            ("ESTAT:namq_10_gdp",  0.35, +1, "EA GDP — growth outlook"),
            ("ECB:ICP.M.U2.N.000000.4.ANR", 0.25, -1, "HICP — inflation drag on expectations"),
        ],
    },

    # ═════════════════════════════════════════════════════════════════════════
    # GBP EVENTS
    # Indicators: ONS API (prefix "ONS:"), BoE database (prefix "BOE:")
    # ═════════════════════════════════════════════════════════════════════════

    "GBP_CPI": {
        "display_name": "UK CPI Inflation (YoY / MoM)",
        "currency": "GBP",
        "impact": "red",
        "history_series": "ONS:MM23/L55O",
        "event_labels": {
            "BULLISH": "HOT UK INFLATION (Hawkish BoE)",
            "BEARISH": "COOL UK INFLATION (Dovish BoE)",
            "INLINE": "INLINE UK CPI",
        },
        "explanations": {
            "BULLISH": "UK CPI runs hot, keeping BoE restrictive — GBP bullish.",
            "BEARISH": "UK inflation cools, accelerating BoE cut timeline — GBP bearish.",
            "INLINE": "UK CPI matches consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY GBPUSD", "BUY GBPJPY", "BUY GBPCHF", "BUY GBPAUD", "BUY GBPCAD", "BUY GBPNZD", "SELL EURGBP"],
            "BEARISH": ["SELL GBPUSD", "SELL GBPJPY", "SELL GBPCHF", "SELL GBPAUD", "SELL GBPCAD", "SELL GBPNZD", "BUY EURGBP"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("ONS:MM23/L55O",   0.40, +1, "UK CPI All Items YoY — ONS API"),
            ("ONS:MM23/L55Q",   0.30, +1, "UK Core CPI YoY ex. Energy/Food — ONS API"),
            ("ONS:MM23/L55R",   0.20, +1, "UK CPIH Services inflation — sticky component"),
            ("BOE:IUDMNZC",     0.10, +1, "UK Gilt 10Y yield — market inflation expectations"),
        ],
    },

    "GBP_CORE_CPI": {
        "display_name": "UK Core CPI (ex. Energy, Food, Tobacco)",
        "currency": "GBP",
        "impact": "red",
        "history_series": "ONS:MM23/L55Q",
        "event_labels": {
            "BULLISH": "STICKY UK CORE (BoE Cautious)",
            "BEARISH": "COOLING UK CORE (BoE Easing)",
            "INLINE": "INLINE UK CORE CPI",
        },
        "explanations": {
            "BULLISH": "Persistent UK core inflation prevents BoE from cutting, GBP supported.",
            "BEARISH": "UK core disinflation gives BoE room to ease, GBP weakens.",
            "INLINE": "UK core CPI meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY GBPUSD", "BUY GBPJPY", "BUY GBPCHF", "BUY GBPAUD", "BUY GBPCAD", "BUY GBPNZD", "SELL EURGBP"],
            "BEARISH": ["SELL GBPUSD", "SELL GBPJPY", "SELL GBPCHF", "SELL GBPAUD", "SELL GBPCAD", "SELL GBPNZD", "BUY EURGBP"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("ONS:MM23/L55Q",  0.50, +1, "UK Core CPI — ONS"),
            ("ONS:MM23/L55R",  0.30, +1, "UK CPIH Services"),
            ("BOE:IUDMNZC",    0.20, +1, "UK Gilt 10Y — rate expectations"),
        ],
    },

    "GBP_GDP": {
        "display_name": "UK GDP Growth (Monthly / Quarterly)",
        "currency": "GBP",
        "impact": "red",
        "history_series": "ONS:IHYQ/IHYQ",
        "event_labels": {
            "BULLISH": "ABOVE-TREND UK GROWTH",
            "BEARISH": "UK CONTRACTION / STAGNATION",
            "INLINE": "INLINE UK GDP",
        },
        "explanations": {
            "BULLISH": "UK GDP beats expectation, reducing BoE easing urgency — GBP bullish.",
            "BEARISH": "GDP miss increases pressure for BoE to cut — GBP bearish.",
            "INLINE": "GDP meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY GBPUSD", "BUY GBPJPY", "BUY GBPCHF", "BUY GBPAUD", "BUY GBPCAD", "BUY GBPNZD", "SELL EURGBP"],
            "BEARISH": ["SELL GBPUSD", "SELL GBPJPY", "SELL GBPCHF", "SELL GBPAUD", "SELL GBPCAD", "SELL GBPNZD", "BUY EURGBP"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("ONS:IHYQ/IHYQ",   0.35, +1, "UK GDP QoQ — ONS"),
            ("ONS:MM23/L55O",   0.25, +1, "UK CPI — growth-inflation interaction"),
            ("OECD:QNA/GBR.B1_GE.GYSA.Q", 0.25, +1, "OECD UK GDP YoY — cross-check"),
            ("BOE:IUDMNZC",     0.15, +1, "UK Gilt yield — market growth expectations"),
        ],
    },

    "BOE_RATE": {
        "display_name": "Bank of England Rate Decision (MPC Vote)",
        "currency": "GBP",
        "impact": "red",
        "history_series": "BOE:IUMABEDR",
        "event_labels": {
            "BULLISH": "HAWKISH HOLD / HIKE (Tight Policy)",
            "BEARISH": "DOVISH CUT / GUIDANCE",
            "INLINE": "AS EXPECTED",
        },
        "explanations": {
            "BULLISH": "BoE holds or votes hawkish — restrictive policy supports GBP.",
            "BEARISH": "BoE cuts or signals further easing — GBP weakens across the board.",
            "INLINE": "Decision in line with market expectations.",
        },
        "trade_signals": {
            "BULLISH": ["BUY GBPUSD", "BUY GBPJPY", "BUY GBPCHF", "BUY GBPAUD", "BUY GBPCAD", "BUY GBPNZD", "SELL EURGBP"],
            "BEARISH": ["SELL GBPUSD", "SELL GBPJPY", "SELL GBPCHF", "SELL GBPAUD", "SELL GBPCAD", "SELL GBPNZD", "BUY EURGBP"],
            "INLINE": ["WAIT / LISTEN TO BAILEY"],
        },
        "indicators": [
            ("ONS:MM23/L55O",  0.35, +1, "UK CPI — inflation mandate"),
            ("ONS:MM23/L55Q",  0.25, +1, "UK Core CPI — persistent core"),
            ("ONS:IHYQ/IHYQ",  0.25, -1, "UK GDP — weak growth = pressure to cut"),
            ("BOE:IUDMNZC",    0.15, +1, "Gilt 10Y — market rate expectations"),
        ],
    },

    "GBP_EMPLOYMENT": {
        "display_name": "UK Employment Change / Unemployment Rate",
        "currency": "GBP",
        "impact": "red",
        "history_series": "ONS:LMS/MGSX",
        "event_labels": {
            "BULLISH": "STRONG UK LABOR MARKET",
            "BEARISH": "WEAKENING UK LABOR MARKET",
            "INLINE": "INLINE UK EMPLOYMENT",
        },
        "explanations": {
            "BULLISH": "UK employment growth and falling unemployment reinforce BoE hawkish hold, GBP bullish.",
            "BEARISH": "Rising UK unemployment accelerates BoE easing timeline, GBP bearish.",
            "INLINE": "UK labor data meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY GBPUSD", "BUY GBPJPY", "BUY GBPCHF", "BUY GBPAUD", "BUY GBPCAD", "BUY GBPNZD", "SELL EURGBP"],
            "BEARISH": ["SELL GBPUSD", "SELL GBPJPY", "SELL GBPCHF", "SELL GBPAUD", "SELL GBPCAD", "SELL GBPNZD", "BUY EURGBP"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("ONS:LMS/MGSX",   0.40, -1, "UK Unemployment Rate — lower = bullish GBP"),
            ("ONS:LMS/MGRN",   0.35, +1, "UK Employment Level — higher = bullish GBP"),
            ("ONS:MM23/L55O",  0.25, +1, "UK CPI — wage pressure proxy"),
        ],
    },

    "GBP_PMI_MFG": {
        "display_name": "UK Manufacturing PMI (Flash / Final)",
        "currency": "GBP",
        "impact": "orange",
        "history_series": "ONS:MM23/L55O",
        "event_labels": {
            "BULLISH": "EXPANDING UK MANUFACTURING",
            "BEARISH": "CONTRACTING UK MANUFACTURING",
            "INLINE": "INLINE UK PMI",
        },
        "explanations": {
            "BULLISH": "UK manufacturing PMI above 50 signals factory expansion, GBP supportive.",
            "BEARISH": "Sub-50 UK manufacturing PMI adds to growth concern.",
            "INLINE": "UK PMI meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY GBPUSD", "BUY GBPJPY", "BUY GBPCHF", "BUY GBPAUD", "BUY GBPCAD", "BUY GBPNZD", "SELL EURGBP"],
            "BEARISH": ["SELL GBPUSD", "SELL GBPJPY", "SELL GBPCHF", "SELL GBPAUD", "SELL GBPCAD", "SELL GBPNZD", "BUY EURGBP"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("ONS:IHYQ/IHYQ",  0.50, +1, "UK GDP — macro context"),
            ("ONS:MM23/L55O",  0.30, -1, "UK CPI — cost pressure on margins"),
            ("BOE:IUDMNZC",    0.20, +1, "Gilt yield — growth expectations"),
        ],
    },

    "GBP_RETAIL_SALES": {
        "display_name": "UK Retail Sales m/m",
        "currency": "GBP",
        "impact": "orange",
        "history_series": "ONS:DRSI/J5EK",
        "event_labels": {
            "BULLISH": "STRONG UK RETAIL",
            "BEARISH": "WEAK UK RETAIL",
            "INLINE": "INLINE UK RETAIL",
        },
        "explanations": {
            "BULLISH": "UK retail sales beat, pointing to consumer resilience — GBP bullish.",
            "BEARISH": "Retail sales miss signals UK consumer weakness.",
            "INLINE": "UK retail sales meet consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY GBPUSD", "BUY GBPJPY", "BUY GBPCHF", "BUY GBPAUD", "BUY GBPCAD", "BUY GBPNZD", "SELL EURGBP"],
            "BEARISH": ["SELL GBPUSD", "SELL GBPJPY", "SELL GBPCHF", "SELL GBPAUD", "SELL GBPCAD", "SELL GBPNZD", "BUY EURGBP"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("ONS:DRSI/J5EK",  0.50, +1, "UK Retail Sales MoM — ONS"),
            ("ONS:MM23/L55O",  0.30, -1, "UK CPI — higher prices suppress volume"),
            ("ONS:LMS/MGSX",   0.20, -1, "UK Unemployment — employment supports spending"),
        ],
    },

    # ═════════════════════════════════════════════════════════════════════════
    # JPY EVENTS
    # Indicators: OECD, ECB SDW (mirrors JPY IRS), FRED
    # ═════════════════════════════════════════════════════════════════════════

    "JPY_CPI": {
        "display_name": "Japan National CPI (YoY)",
        "currency": "JPY",
        "impact": "red",
        "history_series": "OECD:MEI/JPN.CPALTT01.IXNBSA.M",
        "event_labels": {
            "BULLISH": "HOT JAPAN CPI (BoJ Hawkish)",
            "BEARISH": "COOL JAPAN CPI (BoJ Dovish)",
            "INLINE": "INLINE JAPAN CPI",
        },
        "explanations": {
            "BULLISH": "Japan CPI sustainably above 2% gives BoJ more room to normalise (hike), boosting JPY.",
            "BEARISH": "Japan CPI softening reduces BoJ normalisation pressure, JPY weakens.",
            "INLINE": "Japan CPI meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["SELL USDJPY", "SELL EURJPY", "SELL GBPJPY", "SELL AUDJPY", "SELL CADJPY", "SELL CHFJPY", "SELL NZDJPY"],
            "BEARISH": ["BUY USDJPY", "BUY EURJPY", "BUY GBPJPY", "BUY AUDJPY", "BUY CADJPY", "BUY CHFJPY", "BUY NZDJPY"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("OECD:MEI/JPN.CPALTT01.IXNBSA.M",  0.45, +1, "Japan CPI All Items — OECD"),
            ("OECD:MEI/JPN.CPALTT01.IXNBSA.M",  0.30, +1, "Japan core CPI proxy — OECD"),
            ("IRS.M.JP.L.L40.CI.0000.JPY.N",    0.25, +1, "JPY 10Y IRS — rate expectations (ECB SDW)"),
        ],
    },

    "BOJ_RATE": {
        "display_name": "Bank of Japan Rate Decision",
        "currency": "JPY",
        "impact": "red",
        "history_series": "OECD:MEI/JPN.IRLT.ST.A",
        "event_labels": {
            "BULLISH": "HAWKISH BoJ (Hike / YCC Tweak)",
            "BEARISH": "DOVISH BoJ (Hold / Easing Bias)",
            "INLINE": "AS EXPECTED",
        },
        "explanations": {
            "BULLISH": "BoJ rate hike or YCC adjustment tightens domestic financial conditions, JPY strengthens sharply.",
            "BEARISH": "BoJ maintains ultra-loose stance, keeping JPY under downward pressure.",
            "INLINE": "BoJ decision priced in; watch Ueda press conference for forward guidance.",
        },
        "trade_signals": {
            "BULLISH": ["SELL USDJPY", "SELL EURJPY", "SELL GBPJPY", "SELL AUDJPY", "SELL CADJPY", "SELL CHFJPY", "SELL NZDJPY"],
            "BEARISH": ["BUY USDJPY", "BUY EURJPY", "BUY GBPJPY", "BUY AUDJPY", "BUY CADJPY", "BUY CHFJPY", "BUY NZDJPY"],
            "INLINE": ["WAIT / WATCH BOJ STATEMENT"],
        },
        "indicators": [
            ("OECD:MEI/JPN.CPALTT01.IXNBSA.M",  0.40, +1, "Japan CPI — BoJ inflation mandate"),
            ("IRS.M.JP.L.L40.CI.0000.JPY.N",     0.35, +1, "JPY IRS 10Y — market rate expectations"),
            ("OECD:MEI/JPN.IRLT.ST.A",            0.25, -1, "Japan long-term rate — divergence signal"),
        ],
    },

    "JAPAN_GDP": {
        "display_name": "Japan GDP Growth (Preliminary / Final)",
        "currency": "JPY",
        "impact": "red",
        "history_series": "OECD:QNA/JPN.B1_GE.GYSA.Q",
        "event_labels": {
            "BULLISH": "ABOVE-TREND JAPAN GROWTH",
            "BEARISH": "JAPAN CONTRACTION",
            "INLINE": "INLINE JAPAN GDP",
        },
        "explanations": {
            "BULLISH": "Japan GDP beat signals domestic economic strength, supporting BoJ normalisation and JPY.",
            "BEARISH": "Japan GDP miss reduces BoJ scope to tighten, JPY bearish.",
            "INLINE": "Japan GDP meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["SELL USDJPY", "SELL EURJPY", "SELL GBPJPY", "SELL AUDJPY", "SELL CADJPY", "SELL CHFJPY", "SELL NZDJPY"],
            "BEARISH": ["BUY USDJPY", "BUY EURJPY", "BUY GBPJPY", "BUY AUDJPY", "BUY CADJPY", "BUY CHFJPY", "BUY NZDJPY"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("OECD:QNA/JPN.B1_GE.GYSA.Q",       0.50, +1, "Japan GDP YoY — OECD"),
            ("OECD:MEI/JPN.CPALTT01.IXNBSA.M",  0.30, +1, "Japan CPI — growth-inflation mix"),
            ("IRS.M.JP.L.L40.CI.0000.JPY.N",    0.20, +1, "JPY 10Y IRS — expectations"),
        ],
    },

    "JAPAN_TANKAN": {
        "display_name": "Japan Tankan Large Manufacturers Index",
        "currency": "JPY",
        "impact": "red",
        "history_series": "OECD:MEI/JPN.BSCICP02.IXNBSA.Q",
        "event_labels": {
            "BULLISH": "IMPROVING BUSINESS CONDITIONS",
            "BEARISH": "DETERIORATING BUSINESS CONDITIONS",
            "INLINE": "INLINE TANKAN",
        },
        "explanations": {
            "BULLISH": "Positive Tankan signals improving corporate earnings and business confidence in Japan, JPY supportive.",
            "BEARISH": "Negative Tankan reflects deteriorating business conditions, JPY bearish.",
            "INLINE": "Tankan meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["SELL USDJPY", "SELL EURJPY", "SELL GBPJPY", "SELL AUDJPY", "SELL CADJPY", "SELL CHFJPY", "SELL NZDJPY"],
            "BEARISH": ["BUY USDJPY", "BUY EURJPY", "BUY GBPJPY", "BUY AUDJPY", "BUY CADJPY", "BUY CHFJPY", "BUY NZDJPY"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("OECD:MEI/JPN.BSCICP02.IXNBSA.Q",  0.50, +1, "Japan Business Confidence — OECD"),
            ("OECD:MEI/JPN.CPALTT01.IXNBSA.M",  0.30, +1, "Japan CPI"),
            ("IRS.M.JP.L.L40.CI.0000.JPY.N",    0.20, +1, "JPY IRS 10Y"),
        ],
    },

    # ═════════════════════════════════════════════════════════════════════════
    # AUD EVENTS
    # Indicators: OECD, FRED (Australian proxies available on FRED)
    # ═════════════════════════════════════════════════════════════════════════

    "AUD_CPI": {
        "display_name": "Australia CPI (Quarterly / Monthly Indicator)",
        "currency": "AUD",
        "impact": "red",
        "history_series": "OECD:MEI/AUS.CPALTT01.IXNBSA.Q",
        "event_labels": {
            "BULLISH": "HOT AUSTRALIA CPI (RBA Hawkish)",
            "BEARISH": "COOL AUSTRALIA CPI (RBA Dovish)",
            "INLINE": "INLINE AUSTRALIA CPI",
        },
        "explanations": {
            "BULLISH": "Australia inflation above RBA target reduces rate cut expectations, AUD bullish.",
            "BEARISH": "Cooling CPI gives RBA room to cut, AUD bearish.",
            "INLINE": "Australia CPI meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY AUDUSD", "BUY AUDJPY", "BUY AUDCAD", "BUY AUDCHF", "BUY AUDNZD", "SELL EURAUD", "SELL GBPAUD"],
            "BEARISH": ["SELL AUDUSD", "SELL AUDJPY", "SELL AUDCAD", "SELL AUDCHF", "SELL AUDNZD", "BUY EURAUD", "BUY GBPAUD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("OECD:MEI/AUS.CPALTT01.IXNBSA.Q",  0.50, +1, "Australia CPI — OECD quarterly"),
            ("IR3TIB01AUM156N",                   0.30, +1, "Australia 3M interbank rate — FRED"),
            ("DCOILWTICO",                        0.20, +1, "WTI Crude — energy cost proxy"),
        ],
    },

    "RBA_RATE": {
        "display_name": "Reserve Bank of Australia Rate Decision",
        "currency": "AUD",
        "impact": "red",
        "history_series": "IR3TIB01AUM156N",
        "event_labels": {
            "BULLISH": "HAWKISH RBA (Hold / Hike)",
            "BEARISH": "DOVISH RBA (Cut / Guidance)",
            "INLINE": "AS EXPECTED",
        },
        "explanations": {
            "BULLISH": "RBA holds rates or signals prolonged restrictive stance, AUD strengthens.",
            "BEARISH": "RBA cuts or flags upcoming easing, AUD weakens.",
            "INLINE": "Decision in line with market expectations.",
        },
        "trade_signals": {
            "BULLISH": ["BUY AUDUSD", "BUY AUDJPY", "BUY AUDCAD", "BUY AUDCHF", "BUY AUDNZD", "SELL EURAUD", "SELL GBPAUD"],
            "BEARISH": ["SELL AUDUSD", "SELL AUDJPY", "SELL AUDCAD", "SELL AUDCHF", "SELL AUDNZD", "BUY EURAUD", "BUY GBPAUD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("OECD:MEI/AUS.CPALTT01.IXNBSA.Q",  0.45, +1, "Australia CPI — RBA mandate"),
            ("IR3TIB01AUM156N",                   0.35, +1, "Australia 3M rate — market expectations"),
            ("DCOILWTICO",                        0.20, +1, "Commodities — AUD commodity link"),
        ],
    },

    "AUD_EMPLOYMENT": {
        "display_name": "Australia Employment Change / Unemployment Rate",
        "currency": "AUD",
        "impact": "red",
        "history_series": "OECD:MEI/AUS.LRHUTTTT.STSA.M",
        "event_labels": {
            "BULLISH": "STRONG AUSTRALIA LABOR",
            "BEARISH": "WEAKENING AUSTRALIA LABOR",
            "INLINE": "INLINE AUSTRALIA LABOR",
        },
        "explanations": {
            "BULLISH": "Strong Australian employment reduces RBA cut pressure, AUD bullish.",
            "BEARISH": "Rising unemployment gives RBA reason to ease, AUD bearish.",
            "INLINE": "Employment data meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY AUDUSD", "BUY AUDJPY", "BUY AUDCAD", "BUY AUDCHF", "BUY AUDNZD", "SELL EURAUD", "SELL GBPAUD"],
            "BEARISH": ["SELL AUDUSD", "SELL AUDJPY", "SELL AUDCAD", "SELL AUDCHF", "SELL AUDNZD", "BUY EURAUD", "BUY GBPAUD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("OECD:MEI/AUS.LRHUTTTT.STSA.M",    0.50, -1, "Australia Unemployment Rate — OECD"),
            ("OECD:MEI/AUS.CPALTT01.IXNBSA.Q",  0.30, +1, "Australia CPI — wage pressure"),
            ("IR3TIB01AUM156N",                   0.20, +1, "Australia 3M rate"),
        ],
    },

    "AUD_RETAIL_SALES": {
        "display_name": "Australia Retail Sales m/m",
        "currency": "AUD",
        "impact": "orange",
        "history_series": "OECD:MEI/AUS.SLRTTO01.IXNBSA.M",
        "event_labels": {
            "BULLISH": "STRONG AUSTRALIA CONSUMER",
            "BEARISH": "WEAK AUSTRALIA CONSUMER",
            "INLINE": "INLINE RETAIL SALES",
        },
        "explanations": {
            "BULLISH": "Strong retail sales confirm consumer resilience, AUD positive.",
            "BEARISH": "Weak retail sales signal consumer retrenchment.",
            "INLINE": "Retail sales meet consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY AUDUSD", "BUY AUDJPY", "BUY AUDCAD", "BUY AUDCHF", "BUY AUDNZD", "SELL EURAUD", "SELL GBPAUD"],
            "BEARISH": ["SELL AUDUSD", "SELL AUDJPY", "SELL AUDCAD", "SELL AUDCHF", "SELL AUDNZD", "BUY EURAUD", "BUY GBPAUD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("OECD:MEI/AUS.SLRTTO01.IXNBSA.M",  0.55, +1, "Australia Retail Sales — OECD"),
            ("OECD:MEI/AUS.LRHUTTTT.STSA.M",    0.25, -1, "Australia Unemployment — consumer income"),
            ("DCOILWTICO",                        0.20, -1, "Oil — energy cost drag on spending"),
        ],
    },

    # ═════════════════════════════════════════════════════════════════════════
    # CAD EVENTS
    # ═════════════════════════════════════════════════════════════════════════

    "CAD_CPI": {
        "display_name": "Canada CPI (YoY / MoM)",
        "currency": "CAD",
        "impact": "red",
        "history_series": "OECD:MEI/CAN.CPALTT01.IXNBSA.M",
        "event_labels": {
            "BULLISH": "HOT CANADA CPI (Hawkish BoC)",
            "BEARISH": "COOL CANADA CPI (Dovish BoC)",
            "INLINE": "INLINE CANADA CPI",
        },
        "explanations": {
            "BULLISH": "Hot Canadian inflation reduces BoC cut urgency, CAD bullish.",
            "BEARISH": "Cooling Canadian CPI accelerates BoC easing expectations, CAD bearish.",
            "INLINE": "Canada CPI meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["SELL USDCAD", "SELL EURCAD", "SELL GBPCAD", "SELL AUDCAD", "SELL NZDCAD", "BUY CADJPY", "BUY CADCHF"],
            "BEARISH": ["BUY USDCAD", "BUY EURCAD", "BUY GBPCAD", "BUY AUDCAD", "BUY NZDCAD", "SELL CADJPY", "SELL CADCHF"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("OECD:MEI/CAN.CPALTT01.IXNBSA.M",  0.45, +1, "Canada CPI — OECD"),
            ("IR3TIB01CAM156N",                   0.30, +1, "Canada 3M interbank — FRED"),
            ("DCOILWTICO",                        0.25, +1, "WTI Crude — Canada is major oil exporter"),
        ],
    },

    "BOC_RATE": {
        "display_name": "Bank of Canada Rate Decision",
        "currency": "CAD",
        "impact": "red",
        "history_series": "IR3TIB01CAM156N",
        "event_labels": {
            "BULLISH": "HAWKISH BoC (Hold / Hike)",
            "BEARISH": "DOVISH BoC (Cut / Guidance)",
            "INLINE": "AS EXPECTED",
        },
        "explanations": {
            "BULLISH": "BoC holds rates at restrictive levels, CAD strengthens.",
            "BEARISH": "BoC cuts or signals easing path, CAD weakens.",
            "INLINE": "BoC decision fully priced.",
        },
        "trade_signals": {
            "BULLISH": ["SELL USDCAD", "SELL EURCAD", "SELL GBPCAD", "SELL AUDCAD", "SELL NZDCAD", "BUY CADJPY", "BUY CADCHF"],
            "BEARISH": ["BUY USDCAD", "BUY EURCAD", "BUY GBPCAD", "BUY AUDCAD", "BUY NZDCAD", "SELL CADJPY", "SELL CADCHF"],
            "INLINE": ["WAIT / WATCH MACKLEM"],
        },
        "indicators": [
            ("OECD:MEI/CAN.CPALTT01.IXNBSA.M",  0.45, +1, "Canada CPI — BoC mandate"),
            ("IR3TIB01CAM156N",                   0.30, +1, "Canada 3M rate — expectations"),
            ("DCOILWTICO",                        0.25, +1, "WTI Crude — CAD/oil correlation"),
        ],
    },

    "CAD_EMPLOYMENT": {
        "display_name": "Canada Employment Change / Unemployment Rate",
        "currency": "CAD",
        "impact": "red",
        "history_series": "OECD:MEI/CAN.LRHUTTTT.STSA.M",
        "event_labels": {
            "BULLISH": "STRONG CANADA LABOR",
            "BEARISH": "WEAKENING CANADA LABOR",
            "INLINE": "INLINE CANADA LABOR",
        },
        "explanations": {
            "BULLISH": "Strong Canadian job creation reduces BoC easing pressure, CAD bullish.",
            "BEARISH": "Rising Canadian unemployment accelerates BoC cut expectations, CAD bearish.",
            "INLINE": "Labor data meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["SELL USDCAD", "SELL EURCAD", "SELL GBPCAD", "SELL AUDCAD", "SELL NZDCAD", "BUY CADJPY", "BUY CADCHF"],
            "BEARISH": ["BUY USDCAD", "BUY EURCAD", "BUY GBPCAD", "BUY AUDCAD", "BUY NZDCAD", "SELL CADJPY", "SELL CADCHF"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("OECD:MEI/CAN.LRHUTTTT.STSA.M",    0.50, -1, "Canada Unemployment Rate — OECD"),
            ("OECD:MEI/CAN.CPALTT01.IXNBSA.M",  0.30, +1, "Canada CPI — wage inflation"),
            ("DCOILWTICO",                        0.20, +1, "WTI — oil-sector employment"),
        ],
    },

    "CAD_GDP": {
        "display_name": "Canada GDP Growth (Monthly / Quarterly)",
        "currency": "CAD",
        "impact": "orange",
        "history_series": "OECD:QNA/CAN.B1_GE.GYSA.Q",
        "event_labels": {
            "BULLISH": "ABOVE-TREND CANADA GROWTH",
            "BEARISH": "CANADA CONTRACTION",
            "INLINE": "INLINE CANADA GDP",
        },
        "explanations": {
            "BULLISH": "Canada GDP beat reduces BoC cut urgency, CAD bullish.",
            "BEARISH": "GDP miss increases BoC easing pressure.",
            "INLINE": "GDP meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["SELL USDCAD", "SELL EURCAD", "SELL GBPCAD", "SELL AUDCAD", "SELL NZDCAD", "BUY CADJPY", "BUY CADCHF"],
            "BEARISH": ["BUY USDCAD", "BUY EURCAD", "BUY GBPCAD", "BUY AUDCAD", "BUY NZDCAD", "SELL CADJPY", "SELL CADCHF"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("OECD:QNA/CAN.B1_GE.GYSA.Q",       0.50, +1, "Canada GDP YoY — OECD"),
            ("DCOILWTICO",                        0.30, +1, "WTI — energy sector contribution"),
            ("IR3TIB01CAM156N",                   0.20, +1, "Canada 3M rate"),
        ],
    },

    # ═════════════════════════════════════════════════════════════════════════
    # NZD EVENTS
    # ═════════════════════════════════════════════════════════════════════════

    "NZD_CPI": {
        "display_name": "New Zealand CPI (Quarterly)",
        "currency": "NZD",
        "impact": "red",
        "history_series": "OECD:MEI/NZL.CPALTT01.IXNBSA.Q",
        "event_labels": {
            "BULLISH": "HOT NZ CPI (Hawkish RBNZ)",
            "BEARISH": "COOL NZ CPI (Dovish RBNZ)",
            "INLINE": "INLINE NZ CPI",
        },
        "explanations": {
            "BULLISH": "NZ inflation above RBNZ target reduces rate-cut urgency, NZD bullish.",
            "BEARISH": "Cooling NZ CPI accelerates RBNZ easing, NZD bearish.",
            "INLINE": "NZ CPI meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY NZDUSD", "BUY NZDJPY", "BUY NZDCAD", "BUY NZDCHF", "SELL EURNZD", "SELL GBPNZD", "SELL AUDNZD"],
            "BEARISH": ["SELL NZDUSD", "SELL NZDJPY", "SELL NZDCAD", "SELL NZDCHF", "BUY EURNZD", "BUY GBPNZD", "BUY AUDNZD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("OECD:MEI/NZL.CPALTT01.IXNBSA.Q",  0.55, +1, "New Zealand CPI — OECD"),
            ("IR3TIB01NZM156N",                   0.30, +1, "NZ 3M interbank — FRED"),
            ("DCOILWTICO",                        0.15, +1, "WTI — energy import cost"),
        ],
    },

    "RBNZ_RATE": {
        "display_name": "RBNZ Official Cash Rate Decision",
        "currency": "NZD",
        "impact": "red",
        "history_series": "IR3TIB01NZM156N",
        "event_labels": {
            "BULLISH": "HAWKISH RBNZ (Hold / Hike)",
            "BEARISH": "DOVISH RBNZ (Cut / Guidance)",
            "INLINE": "AS EXPECTED",
        },
        "explanations": {
            "BULLISH": "RBNZ holds or signals prolonged tightening, NZD strengthens.",
            "BEARISH": "RBNZ cuts or guides lower, NZD weakens.",
            "INLINE": "RBNZ decision priced in.",
        },
        "trade_signals": {
            "BULLISH": ["BUY NZDUSD", "BUY NZDJPY", "BUY NZDCAD", "BUY NZDCHF", "SELL EURNZD", "SELL GBPNZD", "SELL AUDNZD"],
            "BEARISH": ["SELL NZDUSD", "SELL NZDJPY", "SELL NZDCAD", "SELL NZDCHF", "BUY EURNZD", "BUY GBPNZD", "BUY AUDNZD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("OECD:MEI/NZL.CPALTT01.IXNBSA.Q",  0.55, +1, "NZ CPI — RBNZ mandate"),
            ("IR3TIB01NZM156N",                   0.45, +1, "NZ 3M rate"),
        ],
    },

    "NZD_EMPLOYMENT": {
        "display_name": "New Zealand Employment Change / Unemployment Rate",
        "currency": "NZD",
        "impact": "red",
        "history_series": "OECD:MEI/NZL.LRHUTTTT.STSA.Q",
        "event_labels": {
            "BULLISH": "STRONG NZ LABOR",
            "BEARISH": "WEAKENING NZ LABOR",
            "INLINE": "INLINE NZ LABOR",
        },
        "explanations": {
            "BULLISH": "Strong NZ employment reduces RBNZ easing pressure, NZD bullish.",
            "BEARISH": "Rising NZ unemployment accelerates RBNZ cuts, NZD bearish.",
            "INLINE": "NZ labor data meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["BUY NZDUSD", "BUY NZDJPY", "BUY NZDCAD", "BUY NZDCHF", "SELL EURNZD", "SELL GBPNZD", "SELL AUDNZD"],
            "BEARISH": ["SELL NZDUSD", "SELL NZDJPY", "SELL NZDCAD", "SELL NZDCHF", "BUY EURNZD", "BUY GBPNZD", "BUY AUDNZD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("OECD:MEI/NZL.LRHUTTTT.STSA.Q",    0.55, -1, "NZ Unemployment Rate — OECD"),
            ("OECD:MEI/NZL.CPALTT01.IXNBSA.Q",  0.45, +1, "NZ CPI"),
        ],
    },

    # ═════════════════════════════════════════════════════════════════════════
    # CHF EVENTS
    # ═════════════════════════════════════════════════════════════════════════

    "CHF_CPI": {
        "display_name": "Switzerland CPI (YoY / MoM)",
        "currency": "CHF",
        "impact": "red",
        "history_series": "OECD:MEI/CHE.CPALTT01.IXNBSA.M",
        "event_labels": {
            "BULLISH": "HOT SWISS CPI (SNB Hawkish)",
            "BEARISH": "COOL SWISS CPI (SNB Dovish)",
            "INLINE": "INLINE SWISS CPI",
        },
        "explanations": {
            "BULLISH": "Swiss inflation rising toward or above 2% gives SNB reason to tighten, CHF bullish.",
            "BEARISH": "Swiss CPI falling back reinforces SNB easing, CHF bearish.",
            "INLINE": "Swiss CPI meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["SELL USDCHF", "SELL EURCHF", "SELL GBPCHF", "SELL AUDCHF", "SELL CADCHF", "SELL NZDCHF", "BUY CHFJPY"],
            "BEARISH": ["BUY USDCHF", "BUY EURCHF", "BUY GBPCHF", "BUY AUDCHF", "BUY CADCHF", "BUY NZDCHF", "SELL CHFJPY"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("OECD:MEI/CHE.CPALTT01.IXNBSA.M",   0.55, +1, "Switzerland CPI — OECD"),
            ("IRS.M.CH.L.L40.CI.0000.CHF.N",      0.45, +1, "CHF 10Y IRS — ECB SDW"),
        ],
    },

    "SNB_RATE": {
        "display_name": "Swiss National Bank Policy Rate Decision",
        "currency": "CHF",
        "impact": "red",
        "history_series": "OECD:MEI/CHE.IRLT.ST.A",
        "event_labels": {
            "BULLISH": "HAWKISH SNB (Hold / Hike)",
            "BEARISH": "DOVISH SNB (Cut / Negative Rate Risk)",
            "INLINE": "AS EXPECTED",
        },
        "explanations": {
            "BULLISH": "SNB holds rates or indicates tightening bias — CHF strengthens.",
            "BEARISH": "SNB cuts rates or returns to negative territory — CHF weakens broadly.",
            "INLINE": "Decision fully priced by FX market.",
        },
        "trade_signals": {
            "BULLISH": ["SELL USDCHF", "SELL EURCHF", "SELL GBPCHF", "SELL AUDCHF", "SELL CADCHF", "SELL NZDCHF", "BUY CHFJPY"],
            "BEARISH": ["BUY USDCHF", "BUY EURCHF", "BUY GBPCHF", "BUY AUDCHF", "BUY CADCHF", "BUY NZDCHF", "SELL CHFJPY"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("OECD:MEI/CHE.CPALTT01.IXNBSA.M",   0.50, +1, "Switzerland CPI"),
            ("IRS.M.CH.L.L40.CI.0000.CHF.N",      0.30, +1, "CHF 10Y IRS"),
            ("OECD:MEI/CHE.IRLT.ST.A",             0.20, +1, "Switzerland long-term rate"),
        ],
    },

    "CHF_UNEMPLOYMENT": {
        "display_name": "Switzerland Unemployment Rate",
        "currency": "CHF",
        "impact": "orange",
        "history_series": "OECD:MEI/CHE.LRHUTTTT.STSA.M",
        "event_labels": {
            "BULLISH": "FALLING SWISS UNEMPLOYMENT",
            "BEARISH": "RISING SWISS UNEMPLOYMENT",
            "INLINE": "STEADY SWISS UNEMPLOYMENT",
        },
        "explanations": {
            "BULLISH": "Tightening Swiss labor market supports SNB caution on cuts, CHF bullish.",
            "BEARISH": "Rising unemployment increases SNB easing pressure.",
            "INLINE": "Swiss unemployment meets consensus.",
        },
        "trade_signals": {
            "BULLISH": ["SELL USDCHF", "SELL EURCHF", "SELL GBPCHF", "SELL AUDCHF", "SELL CADCHF", "SELL NZDCHF", "BUY CHFJPY"],
            "BEARISH": ["BUY USDCHF", "BUY EURCHF", "BUY GBPCHF", "BUY AUDCHF", "BUY CADCHF", "BUY NZDCHF", "SELL CHFJPY"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("OECD:MEI/CHE.LRHUTTTT.STSA.M",   0.60, -1, "Switzerland Unemployment Rate — OECD"),
            ("OECD:MEI/CHE.CPALTT01.IXNBSA.M", 0.40, +1, "Switzerland CPI"),
        ],
    },
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
