"""
events.py — Supported U.S. event definitions and leading indicator weights.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SIGN CONVENTION (per-currency indicators)
  +1: Indicator UP is economically positive for that currency (bullish)
  -1: Indicator UP is economically negative for that currency (bearish)

IMPACT TIERS
  "red"    — high-impact (was the only tier tracked previously)
  "orange" — medium-impact (now tracked; contributes smaller feature weight)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

# ── Supported market metadata ────────────────────────────────────────────────
CURRENCIES = ["USD"]
CANONICAL_PAIRS = ["XAUUSD"]

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
#   event_labels — economic-number interpretation labels
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
