"""
events.py — Event definitions with leading indicator weights, directional signs,
and macroeconomic trade recommendations.

Sign convention:
  +1: Indicator UP is positive for the US economy / USD (BULLISH USD).
  -1: Indicator UP is negative for the US economy / USD (BEARISH USD).

Trade signal convention:
  BULLISH: Positive economic surprise → USD strengthens
           Trade: BUY USDJPY, SELL EURUSD, SELL GBPUSD, SELL XAUUSD
  BEARISH: Negative economic surprise → USD weakens
           Trade: SELL USDJPY, BUY EURUSD, BUY GBPUSD, BUY XAUUSD
"""

EVENTS = {
    "NFP": {
        "display_name": "Non-Farm Payrolls",
        "currency": "USD",
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
            "BULLISH": ["BUY USDJPY", "SELL EURUSD", "SELL GBPUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "BUY EURUSD", "BUY GBPUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("ADPWNUSNERSA", 0.30, +1, "ADP Private Payrolls — direct private jobs proxy"),
            ("IC4WSA",      0.25, -1, "4-Week Avg Initial Jobless Claims — rising = soft labor"),
            ("MANEMP",      0.20, +1, "ISM Mfg Employment Sub-index — factory hiring"),
            ("SRVPRD",      0.15, +1, "Services Employment — services hiring proxy"),
            ("JTSLDL",      0.10, -1, "Layoffs & Discharges — corporate layoffs signal"),
        ],
    },
    "CPI": {
        "display_name": "Consumer Price Index (CPI)",
        "currency": "USD",
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
            "BULLISH": ["BUY USDJPY", "SELL EURUSD", "SELL XAUUSD", "SELL GBPUSD"],
            "BEARISH": ["SELL USDJPY", "BUY EURUSD", "BUY XAUUSD", "BUY GBPUSD"],
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
            "BULLISH": ["BUY USDJPY", "SELL EURUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "BUY EURUSD", "BUY XAUUSD"],
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
            "BULLISH": ["SELL EURUSD", "BUY USDJPY", "SELL XAUUSD"],
            "BEARISH": ["BUY EURUSD", "SELL USDJPY", "BUY XAUUSD"],
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
        "history_series": "ICSA",
        "event_labels": {
            "BULLISH": "FEWER CLAIMS (Resilient Labor)",
            "BEARISH": "HIGHER CLAIMS (Labor Weakness)",
            "INLINE": "INLINE (Stable Claims)",
        },
        "explanations": {
            "BULLISH": "Layoffs and claims trends remain muted. Low claims demonstrate labor market resilience, supporting USD strength (Buy USDJPY, Sell EURUSD & Gold).",
            "BEARISH": "Rising claims and layoff warnings point to labor softening. Higher claims accelerate rate-cut bets, weakening the USD (Sell USDJPY, Buy EURUSD & Gold).",
            "INLINE": "Claims are tracking consensus. No immediate directional bias.",
        },
        "trade_signals": {
            "BULLISH": ["BUY USDJPY", "SELL EURUSD", "SELL XAUUSD", "SELL GBPUSD"],
            "BEARISH": ["SELL USDJPY", "BUY EURUSD", "BUY XAUUSD", "BUY GBPUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("IC4WSA",      0.35, -1, "4-Week Claims Moving Average — falling claims = bullish USD"),
            ("CCSA",        0.30, -1, "Continued Claims — lower continuing claims = strong labor"),
            ("JTSLDL",      0.20, -1, "Layoffs & Discharges — low layoffs = resilient economy"),
            ("MANEMP",      0.15, +1, "ISM Mfg Employment — active hiring demand"),
        ],
    },
    "UNEMPLOYMENT_RATE": {
        "display_name": "Unemployment Rate (U3)",
        "currency": "USD",
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
            "BULLISH": ["BUY USDJPY", "SELL EURUSD", "SELL GBPUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "BUY EURUSD", "BUY GBPUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / WATCH NFP HEADLINE"],
        },
        "indicators": [
            ("IC4WSA",      0.30, -1, "4-Week Jobless Claims Avg — lower claims = lower unemployment"),
            ("CCSA",        0.25, -1, "Continued Jobless Claims — low duration = healthy labor"),
            ("JTSLDL",      0.20, -1, "Layoffs & Discharges — fewer layoffs = lower unemployment"),
            ("MANEMP",      0.15, +1, "ISM Mfg Employment — hiring lowers rate"),
            ("TEMPHELPS",   0.10, +1, "Temporary Help Services — leading hiring gauge"),
        ],
    },
    "CONSUMER_CONFIDENCE": {
        "display_name": "Consumer Confidence & Sentiment",
        "currency": "USD",
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
            "BULLISH": ["BUY USDJPY", "BUY US500", "SELL EURUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "SELL US500", "BUY EURUSD", "BUY XAUUSD"],
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
            "BULLISH": ["BUY USDJPY", "SELL EURUSD", "SELL XAUUSD", "SELL US500"],
            "BEARISH": ["SELL USDJPY", "BUY EURUSD", "BUY XAUUSD", "BUY US500"],
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
            "BULLISH": ["BUY USDJPY", "SELL EURUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "BUY EURUSD", "BUY XAUUSD"],
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
            "BULLISH": ["BUY USDJPY", "SELL EURUSD", "BUY US30"],
            "BEARISH": ["SELL USDJPY", "BUY EURUSD", "SELL US30"],
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
            "BULLISH": ["BUY USDJPY", "SELL EURUSD", "BUY US500", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "BUY EURUSD", "SELL US500", "BUY XAUUSD"],
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
            "BULLISH": ["BUY USDJPY", "SELL EURUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "BUY EURUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("PPIFES",       0.35, +1, "PPI Final Demand ex Food & Energy"),
            ("DCOILWTICO",   0.25, +1, "WTI Crude Oil — baseline cost input"),
            ("PPIFIS",       0.20, +1, "PPI Final Demand — pipeline pricing"),
            ("PCUOMFGOMFG",  0.20, +1, "PPI Manufacturing Output"),
        ],
    },
    "CORE_RETAIL_SALES": {
        "display_name": "Core Retail Sales (ex. Auto & Gas)",
        "currency": "USD",
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
            "BULLISH": ["BUY USDJPY", "SELL EURUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "BUY EURUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("UMCSENT",  0.40, +1, "Consumer Sentiment — underlying spending appetite"),
            ("IC4WSA",   0.30, -1, "4-Week Jobless Claims — employment stability"),
            ("RSXFS",    0.30, +1, "Retail Sales ex Food Services"),
        ],
    },
    "ISM_SERVICES": {
        "display_name": "ISM Services PMI (Non-Mfg)",
        "currency": "USD",
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
            "BULLISH": ["BUY USDJPY", "SELL EURUSD", "BUY US500"],
            "BEARISH": ["SELL USDJPY", "BUY EURUSD", "SELL US500"],
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
            "BULLISH": ["BUY USDJPY", "SELL EURUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "BUY EURUSD", "BUY XAUUSD"],
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
            "BULLISH": ["BUY USDJPY", "SELL EURUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "BUY EURUSD", "BUY XAUUSD"],
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
            "BULLISH": ["BUY USDJPY", "SELL EURUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "BUY EURUSD", "BUY XAUUSD"],
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
            "BULLISH": ["BUY USDJPY", "SELL EURUSD", "SELL XAUUSD", "SELL GBPUSD"],
            "BEARISH": ["SELL USDJPY", "BUY EURUSD", "BUY XAUUSD", "BUY GBPUSD"],
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
            "BULLISH": ["BUY USDJPY", "SELL EURUSD", "SELL XAUUSD"],
            "BEARISH": ["SELL USDJPY", "BUY EURUSD", "BUY XAUUSD"],
            "INLINE": ["WAIT / NO BIAS"],
        },
        "indicators": [
            ("PCEPI",      0.35, +1, "Headline PCE Price Index"),
            ("GASREGCOVW", 0.30, +1, "Retail Gasoline Prices — energy component"),
            ("PPIFES",     0.20, +1, "PPI Final Demand Services"),
            ("PPIACO",     0.15, +1, "PPI All Commodities"),
        ],
    },
}


def get_event_config(event_code: str) -> dict:
    """Return event configuration with dynamic fallback for any unlisted code."""
    code = (event_code or "").upper()
    if code in EVENTS:
        return EVENTS[code]

    # Dynamic fallback configuration for unlisted red folder events
    return {
        "display_name": code.replace("_", " ").title(),
        "currency": "USD",
        "history_series": "INDPRO",
        "event_labels": {
            "BULLISH": f"BULLISH SURPRISE ({code})",
            "BEARISH": f"BEARISH SURPRISE ({code})",
            "INLINE": f"INLINE ({code})",
        },
        "explanations": {
            "BULLISH": f"Leading indicators point to economic upside for {code}. Positive USD bias.",
            "BEARISH": f"Leading indicators point to economic downside for {code}. Soft USD bias.",
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

