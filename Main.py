# ============================================================
# AGENT PRO FOOTBALL V3
# "LA BOUGIE DU PARIEUR"
#
# Architecture :
#
# DATA
#   ↓
# FORM / HOME-AWAY / H2H / STRENGTH
#   ↓
# POISSON + API PREDICTION
#   ↓
# MARKET ENGINE
#   ↓
# VALUE ENGINE
#   ↓
# RISK ENGINE
#   ↓
# CONVERGENCE
#   ↓
# DECISION ENGINE
#   ↓
# PRE-MATCH
#   ↓
# LIVE ENGINE
#   ↓
# RESULT
#   ↓
# DATABASE / BACKTEST
#   ↓
# CALIBRATION
#
# Variables GitHub / Render / Railway :
#
# API_FOOTBALL_KEY
# TELEGRAM_TOKEN
# TELEGRAM_CHAT_ID
#
# Optionnelles :
#
# ANALYSIS_INTERVAL=1800
# LIVE_INTERVAL=60
# MAX_CANDIDATES=15
# MIN_SCORE=70
# DB_FILE=agent_pro.db
# ============================================================

import os
import time
import math
import sqlite3
import logging
import threading
import requests

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict


# ============================================================
# CONFIG
# ============================================================

API_KEY = os.getenv("API_FOOTBALL_KEY")
TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID")

TZ = ZoneInfo("Africa/Douala")

ANALYSIS_INTERVAL = int(os.getenv("ANALYSIS_INTERVAL", "1800"))
LIVE_INTERVAL = int(os.getenv("LIVE_INTERVAL", "60"))
MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "15"))
MIN_SCORE = int(os.getenv("MIN_SCORE", "70"))

DB_FILE = os.getenv("DB_FILE", "agent_pro.db")

API_BASE = "https://v3.football.api-sports.io"

HEADERS = {
    "x-apisports-key": API_KEY or "",
    "Accept": "application/json"
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


# ============================================================
# GLOBAL STATE
# ============================================================

CACHE = {}
LIVE_STATE = {}
ANALYSIS_MEMORY = {}

API_LOCK = threading.Lock()


# ============================================================
# UTILITIES
# ============================================================

def now():
    return datetime.now(TZ)


def clamp(x, minimum=0, maximum=100):
    try:
        return max(minimum, min(maximum, float(x)))
    except Exception:
        return minimum


def safe_float(x, default=0.0):
    try:
        if x is None:
            return default

        if isinstance(x, str):
            x = x.replace("%", "").strip()

        return float(x)

    except Exception:
        return default


def safe_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default


def pct(x):
    return f"{x:.1f}%"


def cache_get(key):
    item = CACHE.get(key)

    if not item:
        return None

    timestamp, data, ttl = item

    if time.time() - timestamp < ttl:
        return data

    return None


def cache_set(key, data, ttl):
    CACHE[key] = (
        time.time(),
        data,
        ttl
    )


# ============================================================
# API FOOTBALL ENGINE
# ============================================================

def api(endpoint, params=None, ttl=30):

    key = endpoint + "|" + str(params or {})

    cached = cache_get(key)

    if cached is not None:
        return cached

    with API_LOCK:

        try:

            response = requests.get(
                API_BASE + endpoint,
                headers=HEADERS,
                params=params or {},
                timeout=25
            )

            if response.status_code != 200:

                logging.warning(
                    "API %s -> HTTP %s",
                    endpoint,
                    response.status_code
                )

                return []

            payload = response.json()

            errors = payload.get("errors")

            if errors:
                logging.warning(
                    "API errors: %s",
                    errors
                )

            data = payload.get(
                "response",
                []
            )

            cache_set(
                key,
                data,
                ttl
            )

            return data

        except Exception as e:

            logging.error(
                "API ERROR %s : %s",
                endpoint,
                e
            )

            return []


# ============================================================
# DATABASE
# ============================================================

def db():

    connection = sqlite3.connect(
        DB_FILE,
        check_same_thread=False
    )

    connection.row_factory = sqlite3.Row

    return connection


def init_database():

    connection = db()

    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS predictions (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            fixture_id INTEGER UNIQUE,

            created_at TEXT,

            kickoff TEXT,

            home TEXT,

            away TEXT,

            market TEXT,

            probability REAL,

            fair_odds REAL,

            bookmaker_odds REAL,

            value REAL,

            score REAL,

            risk REAL,

            convergence REAL,

            data_quality REAL,

            lambda_home REAL,

            lambda_away REAL,

            prediction TEXT,

            status TEXT DEFAULT 'PENDING',

            actual_result TEXT,

            profit REAL DEFAULT 0

        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS live_snapshots (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            fixture_id INTEGER,

            timestamp TEXT,

            minute INTEGER,

            home_goals INTEGER,

            away_goals INTEGER,

            possession_home REAL,

            possession_away REAL,

            shots_home REAL,

            shots_away REAL,

            shots_target_home REAL,

            shots_target_away REAL,

            corners_home REAL,

            corners_away REAL

        )
    """)

    connection.commit()

    connection.close()


def save_prediction(a):

    connection = db()

    cursor = connection.cursor()

    cursor.execute("""
        INSERT OR REPLACE INTO predictions (

            fixture_id,
            created_at,
            kickoff,
            home,
            away,
            market,
            probability,
            fair_odds,
            bookmaker_odds,
            value,
            score,
            risk,
            convergence,
            data_quality,
            lambda_home,
            lambda_away,
            prediction,
            status

        )

        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')

    """, (

        a["fixture_id"],
        now().isoformat(),
        a["kickoff"],
        a["home"],
        a["away"],
        a["market"],
        a["probability"],
        a["fair_odds"],
        a["odd"],
        a["value"],
        a["score"],
        a["risk"],
        a["convergence"],
        a["quality"],
        a["lambda_home"],
        a["lambda_away"],
        a["market"]

    ))

    connection.commit()
    connection.close()


# ============================================================
# FIXTURES
# ============================================================

def get_today_fixtures():

    date = now().date().isoformat()

    return api(
        "/fixtures",
        {
            "date": date,
            "timezone": "Africa/Douala"
        },
        ttl=60
    )


def get_upcoming():

    fixtures = get_today_fixtures()

    result = []

    for fixture in fixtures:

        status = fixture["fixture"]["status"]["short"]

        if status in [
            "NS",
            "TBD"
        ]:

            result.append(fixture)

    result.sort(
        key=lambda x: x["fixture"]["timestamp"]
    )

    return result


def get_live():

    return api(
        "/fixtures",
        {
            "live": "all"
        },
        ttl=15
    )


# ============================================================
# TEAM FORM ENGINE
# ============================================================

def get_form(team_id, last=10):

    fixtures = api(
        "/fixtures",
        {
            "team": team_id,
            "last": last,
            "timezone": "Africa/Douala"
        },
        ttl=900
    )

    finished = []

    for match in fixtures:

        if match["fixture"]["status"]["short"] == "FT":

            finished.append(match)

    if not finished:

        return empty_form()

    W = D = L = 0
    GF = GA = 0

    over15 = 0
    over25 = 0
    over35 = 0
    btts = 0
    clean = 0

    sequence = []

    weights = []

    for index, match in enumerate(finished):

        home_id = match["teams"]["home"]["id"]

        hg = safe_int(match["goals"]["home"])
        ag = safe_int(match["goals"]["away"])

        if home_id == team_id:

            gf = hg
            ga = ag

        else:

            gf = ag
            ga = hg

        # Plus le match est récent,
        # plus son poids est important.
        weight = max(
            1,
            len(finished) - index
        )

        weights.append(weight)

        GF += gf
        GA += ga

        if gf > ga:

            W += 1
            sequence.append("V")

        elif gf == ga:

            D += 1
            sequence.append("N")

        else:

            L += 1
            sequence.append("D")

        total = gf + ga

        if total >= 2:
            over15 += 1

        if total >= 3:
            over25 += 1

        if total >= 4:
            over35 += 1

        if gf > 0 and ga > 0:
            btts += 1

        if ga == 0:
            clean += 1

    n = len(finished)

    return {

        "matches": n,

        "W": W,
        "D": D,
        "L": L,

        "GF": GF,
        "GA": GA,

        "avg_gf": GF / n,
        "avg_ga": GA / n,

        "over15": over15 / n * 100,
        "over25": over25 / n * 100,
        "over35": over35 / n * 100,

        "btts": btts / n * 100,
        "clean": clean / n * 100,

        "form": "".join(sequence),

        "recent_weight": sum(weights)

    }


def empty_form():

    return {

        "matches": 0,

        "W": 0,
        "D": 0,
        "L": 0,

        "GF": 0,
        "GA": 0,

        "avg_gf": 0,
        "avg_ga": 0,

        "over15": 0,
        "over25": 0,
        "over35": 0,

        "btts": 0,
        "clean": 0,

        "form": "",

        "recent_weight": 0

    }


# ============================================================
# HOME / AWAY ENGINE
# ============================================================

def get_venue_form(team_id, venue):

    fixtures = api(
        "/fixtures",
        {
            "team": team_id,
            "last": 15,
            "timezone": "Africa/Douala"
        },
        ttl=900
    )

    selected = []

    for match in fixtures:

        if match["fixture"]["status"]["short"] != "FT":
            continue

        home_id = match["teams"]["home"]["id"]

        if venue == "home" and home_id == team_id:
            selected.append(match)

        elif venue == "away" and home_id != team_id:
            selected.append(match)

    selected = selected[:8]

    if not selected:

        return {
            "matches": 0,
            "W": 0,
            "D": 0,
            "L": 0,
            "GF": 0,
            "GA": 0,
            "avg_gf": 0,
            "avg_ga": 0
        }

    W = D = L = GF = GA = 0

    for match in selected:

        home_id = match["teams"]["home"]["id"]

        hg = safe_int(match["goals"]["home"])
        ag = safe_int(match["goals"]["away"])

        if home_id == team_id:

            gf = hg
            ga = ag

        else:

            gf = ag
            ga = hg

        GF += gf
        GA += ga

        if gf > ga:
            W += 1

        elif gf == ga:
            D += 1

        else:
            L += 1

    n = len(selected)

    return {

        "matches": n,

        "W": W,
        "D": D,
        "L": L,

        "GF": GF,
        "GA": GA,

        "avg_gf": GF / n,
        "avg_ga": GA / n

    }


# ============================================================
# H2H ENGINE
# ============================================================

def get_h2h(team1, team2):

    fixtures = api(
        "/fixtures/headtohead",
        {
            "h2h": f"{team1}-{team2}",
            "last": 10,
            "timezone": "Africa/Douala"
        },
        ttl=3600
    )

    result = {

        "matches": 0,

        "w1": 0,
        "w2": 0,
        "draw": 0,

        "gf": 0,
        "ga": 0,

        "over25": 0,
        "btts": 0

    }

    for match in fixtures:

        if match["fixture"]["status"]["short"] != "FT":
            continue

        result["matches"] += 1

        home_id = match["teams"]["home"]["id"]

        hg = safe_int(match["goals"]["home"])
        ag = safe_int(match["goals"]["away"])

        if home_id == team1:

            gf = hg
            ga = ag

        else:

            gf = ag
            ga = hg

        result["gf"] += gf
        result["ga"] += ga

        if gf > ga:
            result["w1"] += 1

        elif gf < ga:
            result["w2"] += 1

        else:
            result["draw"] += 1

        if gf + ga >= 3:
            result["over25"] += 1

        if gf > 0 and ga > 0:
            result["btts"] += 1

    return result


# ============================================================
# API-FOOTBALL PREDICTION ENGINE
# ============================================================

def get_api_prediction(fixture_id):

    data = api(
        "/predictions",
        {
            "fixture": fixture_id
        },
        ttl=3600
    )

    if not data:
        return {}

    try:

        item = data[0]

        prediction = item.get(
            "predictions",
            {}
        )

        percent = prediction.get(
            "percent",
            {}
        )

        return {

            "home": safe_float(
                percent.get("home")
            ),

            "draw": safe_float(
                percent.get("draw")
            ),

            "away": safe_float(
                percent.get("away")
            ),

            "winner": (
                prediction
                .get("winner")
                or {}
            )
            .get("name"),

            "advice": prediction.get(
                "advice"
            ),

            "under_over": prediction.get(
                "under_over"
            )

        }

    except Exception:

        return {}


# ============================================================
# ODDS ENGINE
# ============================================================

def parse_odds_response(data):

    result = {}

    for bookmaker in data:

        for book in bookmaker.get(
            "bookmakers",
            []
        ):

            bookmaker_name = book.get(
                "name",
                "Unknown"
            )

            for market in book.get(
                "bets",
                []
            ):

                market_name = market.get(
                    "name",
                    ""
                )

                for value in market.get(
                    "values",
                    []
                ):

                    label = value.get(
                        "value"
                    )

                    odd = safe_float(
                        value.get("odd")
                    )

                    if not label or odd <= 1:
                        continue

                    key = (
                        bookmaker_name,
                        market_name,
                        str(label)
                    )

                    result[key] = odd

    return result


def get_prematch_odds(fixture_id):

    data = api(
        "/odds",
        {
            "fixture": fixture_id
        },
        ttl=180
    )

    return parse_odds_response(data)


def get_live_odds(fixture_id):

    data = api(
        "/odds/live",
        {
            "fixture": fixture_id
        },
        ttl=15
    )

    return parse_odds_response(data)


def find_odd(odds, market):

    possible = []

    if market == "HOME":
        possible = [
            ("Match Winner", "Home"),
            ("Home/Away", "Home")
        ]

    elif market == "DRAW":
        possible = [
            ("Match Winner", "Draw"),
            ("Home/Away", "Draw")
        ]

    elif market == "AWAY":
        possible = [
            ("Match Winner", "Away"),
            ("Home/Away", "Away")
        ]

    elif market == "OVER15":
        possible = [
            ("Goals Over/Under", "Over 1.5")
        ]

    elif market == "OVER25":
        possible = [
            ("Goals Over/Under", "Over 2.5")
        ]

    elif market == "OVER35":
        possible = [
            ("Goals Over/Under", "Over 3.5")
        ]

    elif market == "BTTS":
        possible = [
            ("Both Teams Score", "Yes")
        ]

    for bookmaker in sorted(
        set(k[0] for k in odds.keys())
    ):

        for market_name, label in possible:

            key = (
                bookmaker,
                market_name,
                label
            )

            if key in odds:

                possible_odd = odds[key]

                if possible_odd > 1:

                    return possible_odd

    return None


# ============================================================
# POISSON ENGINE
# ============================================================

def poisson(k, lam):

    if lam <= 0:

        return 1.0 if k == 0 else 0.0

    return (
        math.exp(-lam)
        *
        lam ** k
        /
        math.factorial(k)
    )


def poisson_model(
    lambda_home,
    lambda_away
):

    matrix = {}

    for home_goals in range(0, 8):

        for away_goals in range(0, 8):

            probability = (

                poisson(
                    home_goals,
                    lambda_home
                )

                *

                poisson(
                    away_goals,
                    lambda_away
                )

            )

            matrix[
                home_goals,
                away_goals
            ] = probability

    home = 0
    draw = 0
    away = 0

    over15 = 0
    over25 = 0
    over35 = 0

    btts = 0

    scores = []

    for (
        h,
        a
    ), probability in matrix.items():

        if h > a:
            home += probability

        elif h == a:
            draw += probability

        else:
            away += probability

        if h + a >= 2:
            over15 += probability

        if h + a >= 3:
            over25 += probability

        if h + a >= 4:
            over35 += probability

        if h > 0 and a > 0:
            btts += probability

        scores.append(
            (
                probability,
                h,
                a
            )
        )

    scores.sort(
        reverse=True
    )

    return {

        "HOME": home * 100,
        "DRAW": draw * 100,
        "AWAY": away * 100,

        "OVER15": over15 * 100,
        "OVER25": over25 * 100,
        "OVER35": over35 * 100,

        "BTTS": btts * 100,

        "scores": scores[:5]

    }


# ============================================================
# STRENGTH ENGINE
# ============================================================

def calculate_lambda(
    home_form,
    away_form,
    home_venue,
    away_venue
):

    # Attaque domicile
    home_attack = (
        home_form["avg_gf"] * 0.45
        +
        home_venue["avg_gf"] * 0.55
    )

    # Défense extérieure adverse
    away_defense = (
        away_form["avg_ga"] * 0.45
        +
        away_venue["avg_ga"] * 0.55
    )

    # Attaque extérieure
    away_attack = (
        away_form["avg_gf"] * 0.45
        +
        away_venue["avg_gf"] * 0.55
    )

    # Défense domicile adverse
    home_defense = (
        home_form["avg_ga"] * 0.45
        +
        home_venue["avg_ga"] * 0.55
    )

    lambda_home = (
        home_attack * 0.60
        +
        away_defense * 0.40
    )

    lambda_away = (
        away_attack * 0.60
        +
        home_defense * 0.40
    )

    return (

        clamp(
            lambda_home,
            0.15,
            4.5
        ),

        clamp(
            lambda_away,
            0.15,
            4.5
        )

    )


# ============================================================
# FORM SCORE
# ============================================================

def form_score(form):

    if not form["matches"]:
        return 50

    result = (

        form["W"] * 3
        +
        form["D"]

    ) / (

        form["matches"] * 3

    ) * 100

    return clamp(result)


def venue_score(venue):

    if not venue["matches"]:
        return 50

    return clamp(

        (
            venue["W"] * 3
            +
            venue["D"]
        )

        /

        (
            venue["matches"] * 3
        )

        * 100

    )


# ============================================================
# DATA QUALITY
# ============================================================

def quality_score(
    home_form,
    away_form,
    home_venue,
    away_venue,
    h2h
):

    scores = []

    for obj in [
        home_form,
        away_form,
        home_venue,
        away_venue
    ]:

        matches = obj.get(
            "matches",
            0
        )

        if matches >= 8:
            scores.append(100)

        elif matches >= 5:
            scores.append(80)

        elif matches >= 3:
            scores.append(60)

        elif matches > 0:
            scores.append(40)

        else:
            scores.append(0)

    h2h_matches = h2h.get(
        "matches",
        0
    )

    if h2h_matches >= 8:
        scores.append(100)

    elif h2h_matches >= 5:
        scores.append(80)

    elif h2h_matches >= 3:
        scores.append(60)

    else:
        scores.append(40)

    return sum(scores) / len(scores)


# ============================================================
# CONVERGENCE ENGINE
# ============================================================

def convergence(
    poisson_probability,
    api_probability,
    form_signal,
    venue_signal
):

    values = [
        poisson_probability,
        form_signal,
        venue_signal
    ]

    if api_probability > 0:
        values.append(
            api_probability
        )

    average = sum(values) / len(values)

    deviation = sum(
        abs(
            value - average
        )
        for value in values
    ) / len(values)

    return clamp(
        100 - deviation
    )


# ============================================================
# MARKET ENGINE
# ============================================================

def build_market_probabilities(
    poisson,
    home_form,
    away_form
):

    return {

        "HOME": poisson["HOME"],

        "DRAW": poisson["DRAW"],

        "AWAY": poisson["AWAY"],

        "OVER15": poisson["OVER15"],

        "OVER25": poisson["OVER25"],

        "OVER35": poisson["OVER35"],

        "BTTS": poisson["BTTS"]

    }


def market_name(market):

    names = {

        "HOME": "Victoire domicile",
        "DRAW": "Match nul",
        "AWAY": "Victoire extérieur",

        "OVER15": "Over 1.5",
        "OVER25": "Over 2.5",
        "OVER35": "Over 3.5",

        "BTTS": "BTTS Oui"

    }

    return names.get(
        market,
        market
    )


# ============================================================
# RISK ENGINE
# ============================================================

def detect_risk(
    home_form,
    away_form,
    home_venue,
    away_venue,
    h2h,
    poisson,
    selected_market,
    quality
):

    traps = []

    favorite = None

    if (
        home_form["W"] >= 6
        and
        home_form["W"] >
        away_form["W"] + 2
    ):

        favorite = "HOME"

    elif (
        away_form["W"] >= 6
        and
        away_form["W"] >
        home_form["W"] + 2
    ):

        favorite = "AWAY"

    # --------------------------------------------------------
    # Favori extérieur
    # --------------------------------------------------------

    if favorite == "AWAY":

        if (
            home_venue["matches"] >= 5
            and
            home_venue["W"] >= 3
        ):

            traps.append(
                "Favori extérieur face à une équipe forte à domicile"
            )

    # --------------------------------------------------------
    # H2H contradictoire
    # --------------------------------------------------------

    if favorite == "HOME":

        if (
            h2h["matches"] >= 5
            and
            h2h["w2"] > h2h["w1"]
        ):

            traps.append(
                "H2H défavorable au favori"
            )

    if favorite == "AWAY":

        if (
            h2h["matches"] >= 5
            and
            h2h["w1"] > h2h["w2"]
        ):

            traps.append(
                "H2H défavorable au favori"
            )

    # --------------------------------------------------------
    # Poisson contradictoire
    # --------------------------------------------------------

    if (
        selected_market == "HOME"
        and
        poisson["HOME"] < 50
    ):

        traps.append(
            "Poisson ne confirme pas la victoire domicile"
        )

    if (
        selected_market == "AWAY"
        and
        poisson["AWAY"] < 50
    ):

        traps.append(
            "Poisson ne confirme pas la victoire extérieure"
        )

    # --------------------------------------------------------
    # Qualité faible
    # --------------------------------------------------------

    if quality < 60:

        traps.append(
            "Qualité des données insuffisante"
        )

    return traps


def calculate_risk(
    quality,
    convergence_score,
    probability,
    traps
):

    risk = (

        (100 - quality) * 0.35

        +

        (100 - convergence_score) * 0.30

        +

        (100 - probability) * 0.35

    )

    risk += len(traps) * 8

    return clamp(risk)


# ============================================================
# VALUE ENGINE
# ============================================================

def fair_odds(probability):

    if probability <= 0:
        return 999

    return 100 / probability


def implied_probability(odd):

    if not odd or odd <= 1:
        return 0

    return 100 / odd


def calculate_value(
    probability,
    odd
):

    if not odd or odd <= 1:
        return None

    market_probability = (
        implied_probability(odd)
    )

    return (
        probability
        -
        market_probability
    )


# ============================================================
# DECISION ENGINE
# ============================================================

def decision_engine(
    score,
    risk,
    value,
    quality,
    probability
):

    if quality < 55:
        return "⚫ NO DATA"

    if probability < 55:
        return "🔴 PASS"

    if risk >= 65:
        return "🔴 PASS"

    if (
        score >= 78
        and
        value is not None
        and
        value >= 4
    ):

        return "🟢 BET"

    if score >= MIN_SCORE:

        return "🟡 WATCH"

    return "🔴 PASS"


# ============================================================
# COMPLETE MATCH ANALYSIS
# ============================================================

def analyze_match(match):

    fixture_id = match["fixture"]["id"]

    home = match["teams"]["home"]
    away = match["teams"]["away"]

    home_id = home["id"]
    away_id = away["id"]

    logging.info(
        "Analyse %s vs %s",
        home["name"],
        away["name"]
    )

    # --------------------------------------------------------
    # DATA
    # --------------------------------------------------------

    home_form = get_form(
        home_id
    )

    away_form = get_form(
        away_id
    )

    home_venue = get_venue_form(
        home_id,
        "home"
    )

    away_venue = get_venue_form(
        away_id,
        "away"
    )

    h2h = get_h2h(
        home_id,
        away_id
    )

    # --------------------------------------------------------
    # STRENGTH
    # --------------------------------------------------------

    lambda_home, lambda_away = calculate_lambda(

        home_form,
        away_form,

        home_venue,
        away_venue

    )

    # --------------------------------------------------------
    # POISSON
    # --------------------------------------------------------

    poisson = poisson_model(
        lambda_home,
        lambda_away
    )

    # --------------------------------------------------------
    # API MODEL
    # --------------------------------------------------------

    api_prediction = get_api_prediction(
        fixture_id
    )

    # --------------------------------------------------------
    # MARKETS
    # --------------------------------------------------------

    probabilities = build_market_probabilities(

        poisson,

        home_form,
        away_form

    )

    # --------------------------------------------------------
    # Choix du meilleur marché
    # --------------------------------------------------------

    candidates = []

    for market, probability in probabilities.items():

        if probability >= 55:

            candidates.append(
                (
                    probability,
                    market
                )
            )

    if not candidates:

        selected_probability = max(
            probabilities.values()
        )

        selected_market = max(
            probabilities,
            key=probabilities.get
        )

    else:

        # Priorité à la probabilité,
        # mais on évite les marchés trop fragiles.
        candidates.sort(
            reverse=True
        )

        selected_probability = candidates[0][0]

        selected_market = candidates[0][1]

    # --------------------------------------------------------
    # API prediction comme deuxième opinion
    # --------------------------------------------------------

    api_probability = 0

    if selected_market == "HOME":
        api_probability = api_prediction.get(
            "home",
            0
        )

    elif selected_market == "DRAW":
        api_probability = api_prediction.get(
            "draw",
            0
        )

    elif selected_market == "AWAY":
        api_probability = api_prediction.get(
            "away",
            0
        )

    # --------------------------------------------------------
    # Form / venue signal
    # --------------------------------------------------------

    home_form_score = form_score(
        home_form
    )

    away_form_score = form_score(
        away_form
    )

    home_venue_score = venue_score(
        home_venue
    )

    away_venue_score = venue_score(
        away_venue
    )

    if selected_market == "HOME":

        form_signal = home_form_score

        venue_signal = home_venue_score

    elif selected_market == "AWAY":

        form_signal = away_form_score

        venue_signal = away_venue_score

    elif selected_market in [
        "OVER15",
        "OVER25",
        "OVER35",
        "BTTS"
    ]:

        form_signal = (
            home_form["over25"]
            +
            away_form["over25"]
        ) / 2

        venue_signal = (
            home_venue_score
            +
            away_venue_score
        ) / 2

    else:

        form_signal = 50
        venue_signal = 50

    # --------------------------------------------------------
    # QUALITY
    # --------------------------------------------------------

    quality = quality_score(

        home_form,
        away_form,

        home_venue,
        away_venue,

        h2h

    )

    # --------------------------------------------------------
    # CONVERGENCE
    # --------------------------------------------------------

    convergence_score = convergence(

        selected_probability,

        api_probability,

        form_signal,

        venue_signal

    )

    # --------------------------------------------------------
    # RISKS
    # --------------------------------------------------------

    traps = detect_risk(

        home_form,
        away_form,

        home_venue,
        away_venue,

        h2h,

        poisson,

        selected_market,

        quality

    )

    risk = calculate_risk(

        quality,
        convergence_score,
        selected_probability,
        traps

    )

    # --------------------------------------------------------
    # GLOBAL SCORE
    # --------------------------------------------------------

    score = (

        selected_probability * 0.35

        +

        convergence_score * 0.20

        +

        quality * 0.20

        +

        (100 - risk) * 0.15

        +

        form_signal * 0.10

    )

    score = clamp(score)

    # --------------------------------------------------------
    # ODDS
    # --------------------------------------------------------

    odds = get_prematch_odds(
        fixture_id
    )

    odd = find_odd(
        odds,
        selected_market
    )

    value = calculate_value(
        selected_probability,
        odd
    )

    if value is None:
        value_for_score = -10
    else:
        value_for_score = value

    # --------------------------------------------------------
    # DECISION
    # --------------------------------------------------------

    decision = decision_engine(

        score,
        risk,
        value,
        quality,
        selected_probability

    )

    # --------------------------------------------------------
    # SCORES
    # --------------------------------------------------------

    top_scores = []

    for probability, h, a in poisson["scores"][:3]:

        top_scores.append(
            {
                "score": f"{h}-{a}",
                "probability": probability * 100
            }
        )

    kickoff = datetime.fromtimestamp(
        match["fixture"]["timestamp"],
        TZ
    ).isoformat()

    result = {

        "fixture_id": fixture_id,

        "home": home["name"],
        "away": away["name"],

        "kickoff": kickoff,

        "market": selected_market,

        "market_name": market_name(
            selected_market
        ),

        "probability": selected_probability,

        "fair_odds": fair_odds(
            selected_probability
        ),

        "odd": odd,

        "value": (
            value
            if value is not None
            else -999
        ),

        "score": score,

        "risk": risk,

        "convergence": convergence_score,

        "quality": quality,

        "lambda_home": lambda_home,
        "lambda_away": lambda_away,

        "poisson": poisson,

        "api_prediction": api_prediction,

        "home_form": home_form,
        "away_form": away_form,

        "home_venue": home_venue,
        "away_venue": away_venue,

        "h2h": h2h,

        "traps": traps,

        "top_scores": top_scores,

        "decision": decision

    }

    return result


# ============================================================
# TELEGRAM
# ============================================================

def telegram(text):

    if not TG_TOKEN or not TG_CHAT:

        logging.warning(
            "Telegram non configuré"
        )

        return False

    try:

        response = requests.post(

            f"https://api.telegram.org/bot"
            f"{TG_TOKEN}/sendMessage",

            data={

                "chat_id": TG_CHAT,

                "text": text,

                "parse_mode": "HTML",

                "disable_web_page_preview": True

            },

            timeout=20

        )

        return response.status_code == 200

    except Exception as e:

        logging.error(
            "Telegram error: %s",
            e
        )

        return False


# ============================================================
# FORMAT PRE-MATCH
# ============================================================

def format_analysis(a):

    kickoff = datetime.fromisoformat(
        a["kickoff"]
    ).strftime("%H:%M")

    text = f"""
<b>🕯️ AGENT PRO V3</b>
<b>LA BOUGIE DU PARIEUR</b>

⏰ {kickoff}

⚽ <b>{a["home"]} vs {a["away"]}</b>

━━━━━━━━━━━━━━━━━━

<b>🎯 PRONOSTIC</b>

{a["market_name"]}

Probabilité :
<b>{a["probability"]:.1f}%</b>

Cote juste :
<b>{a["fair_odds"]:.2f}</b>
"""

    if a["odd"]:

        text += f"""
Cote bookmaker :
<b>{a["odd"]:.2f}</b>

Value :
<b>{a["value"]:+.1f}%</b>
"""

    else:

        text += """
Cote bookmaker :
<b>indisponible</b>
"""

    text += f"""
━━━━━━━━━━━━━━━━━━

<b>🧠 MOTEUR</b>

🧮 Poisson :
{a["poisson"]["HOME"]:.1f}% / \
{a["poisson"]["DRAW"]:.1f}% / \
{a["poisson"]["AWAY"]:.1f}%

⚽ Over 1.5 :
{a["poisson"]["OVER15"]:.1f}%

⚽ Over 2.5 :
{a["poisson"]["OVER25"]:.1f}%

🤝 BTTS :
{a["poisson"]["BTTS"]:.1f}%

λ :
{a["lambda_home"]:.2f} - \
{a["lambda_away"]:.2f}

━━━━━━━━━━━━━━━━━━

<b>🕯️ BOUGIE</b>

🎯 Score :
<b>{a["score"]:.0f}/100</b>

⚠️ Risque :
<b>{a["risk"]:.0f}/100</b>

🔗 Convergence :
<b>{a["convergence"]:.0f}/100</b>

📚 Données :
<b>{a["quality"]:.0f}/100</b>

━━━━━━━━━━━━━━━━━━

<b>🎯 TOP SCORES</b>
"""

    for item in a["top_scores"]:

        text += (
            f'• {item["score"]} — '
            f'{item["probability"]:.1f}%\n'
        )

    if a["traps"]:

        text += "\n<b>🚨 RISQUES</b>\n"

        for trap in a["traps"]:

            text += (
                f"• {trap}\n"
            )

    text += f"""
━━━━━━━━━━━━━━━━━━

<b>🤖 DÉCISION :
{a["decision"]}</b>

<i>Probabilité ≠ garantie.</i>
"""

    return text


# ============================================================
# PRE-MATCH ENGINE
# ============================================================

def run_pre_match():

    fixtures = get_upcoming()

    if not fixtures:

        logging.info(
            "Aucun match disponible"
        )

        return

    candidates = fixtures[
        :MAX_CANDIDATES
    ]

    analyses = []

    for match in candidates:

        try:

            result = analyze_match(
                match
            )

            analyses.append(
                result
            )

            time.sleep(0.3)

        except Exception as e:

            logging.exception(
                "Analyse match : %s",
                e
            )

    if not analyses:
        return

    # --------------------------------------------------------
    # Classement intelligent
    # --------------------------------------------------------

    analyses.sort(

        key=lambda a: (

            a["decision"] == "🟢 BET",

            a["score"],

            a["value"]

        ),

        reverse=True

    )

    top = analyses[:7]

    message = f"""
<b>🕯️ AGENT PRO V3 — BRIEFING</b>

📅 {now().strftime("%d/%m/%Y")}
⏰ {now().strftime("%H:%M")}

<b>Architecture :</b>

DATA
→ POISSON
→ VALUE
→ RISQUE
→ CONVERGENCE
→ DÉCISION

━━━━━━━━━━━━━━━━━━

<b>🏆 TOP DU JOUR</b>
"""

    for index, a in enumerate(
        top,
        1
    ):

        value_text = (
            f"{a['value']:+.1f}%"
            if a["value"] != -999
            else "N/A"
        )

        message += f"""

<b>{index}. {a["home"]} vs {a["away"]}</b>

🎯 {a["market_name"]}
📊 {a["probability"]:.1f}%
🕯️ {a["score"]:.0f}/100
⚠️ {a["risk"]:.0f}/100
💰 Value : {value_text}

<b>{a["decision"]}</b>
"""

    message += """

━━━━━━━━━━━━━━━━━━

<i>Le système peut analyser beaucoup
de matchs et décider de n'en retenir
aucun lorsque le rapport probabilité /
risque / valeur est insuffisant.</i>
"""

    telegram(
        message
    )

    # --------------------------------------------------------
    # Sauvegarde
    # --------------------------------------------------------

    for a in analyses:

        save_prediction(
            a
        )

    # --------------------------------------------------------
    # Détails des meilleurs
    # --------------------------------------------------------

    for a in top:

        if a["decision"] in [
            "🟢 BET",
            "🟡 WATCH"
        ]:

            telegram(
                format_analysis(a)
            )

            time.sleep(1)


# ============================================================
# LIVE STATISTICS
# ============================================================

def parse_statistics(
    fixture_id
):

    data = api(

        "/fixtures/statistics",

        {
            "fixture": fixture_id
        },

        ttl=45

    )

    result = {

        "home": {},
        "away": {}

    }

    for team_block in data:

        team = team_block.get(
            "team",
            {}
        )

        team_id = team.get(
            "id"
        )

        side = None

        # Le nom du côté sera associé plus tard.
        # On conserve l'ID.
        result[
            str(team_id)
        ] = {}

        for stat in team_block.get(
            "statistics",
            []
        ):

            name = stat.get(
                "type"
            )

            value = stat.get(
                "value"
            )

            if isinstance(
                value,
                str
            ):

                value = value.replace(
                    "%",
                    ""
                )

            result[
                str(team_id)
            ][name] = safe_float(
                value
            )

    return result


# ============================================================
# LIVE SNAPSHOT
# ============================================================

def save_live_snapshot(
    fixture,
    stats
):

    fixture_id = fixture["fixture"]["id"]

    home_id = fixture[
        "teams"
    ]["home"]["id"]

    away_id = fixture[
        "teams"
    ]["away"]["id"]

    h = stats.get(
        str(home_id),
        {}
    )

    a = stats.get(
        str(away_id),
        {}
    )

    connection = db()

    cursor = connection.cursor()

    cursor.execute("""

        INSERT INTO live_snapshots (

            fixture_id,
            timestamp,
            minute,

            home_goals,
            away_goals,

            possession_home,
            possession_away,

            shots_home,
            shots_away,

            shots_target_home,
            shots_target_away,

            corners_home,
            corners_away

        )

        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

    """, (

        fixture_id,

        now().isoformat(),

        safe_int(
            fixture["fixture"]["status"].get(
                "elapsed"
            )
        ),

        safe_int(
            fixture["goals"]["home"]
        ),

        safe_int(
            fixture["goals"]["away"]
        ),

        h.get(
            "Ball Possession",
            0
        ),

        a.get(
            "Ball Possession",
            0
        ),

        h.get(
            "Total Shots",
            0
        ),

        a.get(
            "Total Shots",
            0
        ),

        h.get(
            "Shots on Goal",
            0
        ),

        a.get(
            "Shots on Goal",
            0
        ),

        h.get(
            "Corner Kicks",
            0
        ),

        a.get(
            "Corner Kicks",
            0
        )

    ))

    connection.commit()
    connection.close()


# ============================================================
# LIVE ENGINE
# ============================================================

def live_probability_adjustment(
    base_analysis,
    fixture,
    stats
):

    probability = base_analysis[
        "probability"
    ]

    fixture_id = fixture[
        "fixture"
    ]["id"]

    home_id = fixture[
        "teams"
    ]["home"]["id"]

    away_id = fixture[
        "teams"
    ]["away"]["id"]

    home_stats = stats.get(
        str(home_id),
        {}
    )

    away_stats = stats.get(
        str(away_id),
        {}

    )

    minute = safe_int(
        fixture[
            "fixture"
        ]["status"].get(
            "elapsed"
        )
    )

    hg = safe_int(
        fixture["goals"]["home"]
    )

    ag = safe_int(
        fixture["goals"]["away"]
    )

    # --------------------------------------------------------
    # Ajustement basé sur tirs cadrés
    # --------------------------------------------------------

    h_target = safe_float(
        home_stats.get(
            "Shots on Goal"
        )
    )

    a_target = safe_float(
        away_stats.get(
            "Shots on Goal"
        )
    )

    target_total = (
        h_target
        +
        a_target
    )

    # --------------------------------------------------------
    # Ajustement rythme
    # --------------------------------------------------------

    adjustment = 0

    if target_total >= 8:
        adjustment += 6

    elif target_total >= 5:
        adjustment += 3

    elif target_total <= 1 and minute >= 45:
        adjustment -= 5

    # --------------------------------------------------------
    # Score
    # --------------------------------------------------------

    if base_analysis["market"] == "HOME":

        if hg > ag:
            adjustment += 8

        elif hg < ag:
            adjustment -= 12

    elif base_analysis["market"] == "AWAY":

        if ag > hg:
            adjustment += 8

        elif ag < hg:
            adjustment -= 12

    elif base_analysis["market"] in [
        "OVER15",
        "OVER25",
        "OVER35"
    ]:

        total_goals = hg + ag

        if total_goals >= 2:
            adjustment += 10

        elif total_goals == 1 and minute < 60:
            adjustment += 3

        elif total_goals == 0 and minute >= 60:
            adjustment -= 12

    elif base_analysis["market"] == "BTTS":

        if hg > 0 and ag > 0:
            adjustment += 15

        elif (
            minute >= 70
            and
            (hg == 0 or ag == 0)
        ):

            adjustment -= 15

    live_probability = clamp(
        probability + adjustment,
        1,
        99
    )

    return live_probability


def live_update(
    fixture
):

    fixture_id = fixture[
        "fixture"
    ]["id"]

    status = fixture[
        "fixture"
    ]["status"]["short"]

    if status not in [
        "1H",
        "HT",
        "2H",
        "ET"
    ]:

        return

    connection = db()

    cursor = connection.cursor()

    cursor.execute("""

        SELECT *

        FROM predictions

        WHERE fixture_id = ?

    """, (
        fixture_id,
    ))

    row = cursor.fetchone()

    connection.close()

    if not row:

        return

    base_analysis = dict(row)

    stats = parse_statistics(
        fixture_id
    )

    save_live_snapshot(
        fixture,
        stats
    )

    live_probability = live_probability_adjustment(
        base_analysis,
        fixture,
        stats
    )

    old = LIVE_STATE.get(
        fixture_id
    )

    minute = safe_int(
        fixture[
            "fixture"
        ]["status"].get(
            "elapsed"
        )
    )

    hg = safe_int(
        fixture["goals"]["home"]
    )

    ag = safe_int(
        fixture["goals"]["away"]
    )

    current = {

        "minute": minute,

        "home_goals": hg,

        "away_goals": ag,

        "probability": live_probability

    }

    LIVE_STATE[
        fixture_id
    ] = current

    # --------------------------------------------------------
    # Première détection
    # --------------------------------------------------------

    if old is None:

        telegram(f"""
<b>🔴 LIVE ACTIVÉ</b>

⚽ <b>{base_analysis["home"]}
{hg} - {ag}
{base_analysis["away"]}</b>

⏱️ {minute}'

🎯 Marché initial :
<b>{base_analysis["market"]}</b>

📊 Probabilité initiale :
{base_analysis["probability"]:.1f}%

📡 Surveillance statistique activée.
""")

        return

    # --------------------------------------------------------
    # BUT
    # --------------------------------------------------------

    if (
        old["home_goals"] != hg
        or
        old["away_goals"] != ag
    ):

        telegram(f"""
<b>⚡ BUT — AGENT PRO LIVE</b>

⚽ <b>{base_analysis["home"]}
{hg} - {ag}
{base_analysis["away"]}</b>

⏱️ {minute}'

🎯 Marché :
{base_analysis["market"]}

📊 Nouvelle probabilité :
<b>{live_probability:.1f}%</b>
""")

    # --------------------------------------------------------
    # Changement important de probabilité
    # --------------------------------------------------------

    probability_change = (
        live_probability
        -
        old["probability"]
    )

    if abs(probability_change) >= 8:

        direction = (
            "📈 RENFORCEMENT"
            if probability_change > 0
            else
            "📉 DÉGRADATION"
        )

        telegram(f"""
<b>🕯️ BOUGIE LIVE</b>

⚽ {base_analysis["home"]}
<b>{hg}-{ag}</b>
{base_analysis["away"]}

⏱️ {minute}'

{direction}

Probabilité :
<b>{live_probability:.1f}%</b>

Variation :
{probability_change:+.1f} points

🎯 Marché :
{base_analysis["market"]}
""")

    # --------------------------------------------------------
    # Update périodique
    # --------------------------------------------------------

    if minute > 0 and minute % 15 == 0:

        telegram(f"""
<b>📡 RAPPORT LIVE</b>

⚽ {base_analysis["home"]}
<b>{hg}-{ag}</b>
{base_analysis["away"]}

⏱️ {minute}'

🎯 {base_analysis["market"]}

Avant :
{base_analysis["probability"]:.1f}%

LIVE :
<b>{live_probability:.1f}%</b>

🕯️ Score initial :
{base_analysis["score"]:.0f}/100
""")


# ============================================================
# LIVE ENGINE
# ============================================================

def run_live():

    matches = get_live()

    for fixture in matches:

        try:

            live_update(
                fixture
            )

        except Exception as e:

            logging.exception(
                "LIVE ERROR : %s",
                e
            )


# ============================================================
# RESULT ENGINE
# ============================================================

def settle_finished_predictions():

    connection = db()

    cursor = connection.cursor()

    cursor.execute("""

        SELECT *

        FROM predictions

        WHERE status = 'PENDING'

    """)

    predictions = cursor.fetchall()

    connection.close()

    if not predictions:
        return

    for prediction in predictions:

        kickoff = prediction[
            "kickoff"
        ]

        try:

            kickoff_dt = datetime.fromisoformat(
                kickoff
            )

        except:

            continue

        if now() < kickoff_dt + timedelta(
            minutes=130
        ):

            continue

        fixture_id = prediction[
            "fixture_id"
        ]

        data = api(
            "/fixtures",
            {
                "id": fixture_id
            },
            ttl=60
        )

        if not data:
            continue

        fixture = data[0]

        status = fixture[
            "fixture"
        ]["status"]["short"]

        if status not in [
            "FT",
            "AET",
            "PEN"
        ]:

            continue

        hg = safe_int(
            fixture["goals"]["home"]
        )

        ag = safe_int(
            fixture["goals"]["away"]
        )

        market = prediction[
            "market"
        ]

        won = False

        if market == "HOME":
            won = hg > ag

        elif market == "DRAW":
            won = hg == ag

        elif market == "AWAY":
            won = ag > hg

        elif market == "OVER15":
            won = hg + ag >= 2

        elif market == "OVER25":
            won = hg + ag >= 3

        elif market == "OVER35":
            won = hg + ag >= 4

        elif market == "BTTS":
            won = hg > 0 and ag > 0

        odd = prediction[
            "bookmaker_odds"
        ]

        if odd and odd > 1:

            profit = (
                odd - 1
                if won
                else -1
            )

        else:

            profit = (
                1
                if won
                else -1
            )

        result = (
            "WIN"
            if won
            else
            "LOSS"
        )

        connection = db()

        cursor = connection.cursor()

        cursor.execute("""

            UPDATE predictions

            SET

                status = 'SETTLED',

                actual_result = ?,

                profit = ?

            WHERE fixture_id = ?

        """, (

            result,

            profit,

            fixture_id

        ))

        connection.commit()
        connection.close()

        telegram(f"""
<b>🏁 RÉSULTAT</b>

⚽ {prediction["home"]}
{hg} - {ag}
{prediction["away"]}

🎯 {prediction["market"]}

Résultat :
<b>{result}</b>

Profit unité :
{profit:+.2f}

🕯️ Score initial :
{prediction["score"]:.0f}/100
""")


# ============================================================
# BACKTEST ENGINE
# ============================================================

def performance_report():

    connection = db()

    cursor = connection.cursor()

    cursor.execute("""

        SELECT

            COUNT(*) AS total,

            SUM(
                CASE
                    WHEN status = 'SETTLED'
                    THEN 1
                    ELSE 0
                END
            ) AS settled,

            SUM(
                CASE
                    WHEN actual_result = 'WIN'
                    THEN 1
                    ELSE 0
                END
            ) AS wins,

            SUM(profit) AS profit

        FROM predictions

    """)

    row = cursor.fetchone()

    cursor.execute("""

        SELECT

            market,

            COUNT(*) AS total,

            SUM(
                CASE
                    WHEN actual_result = 'WIN'
                    THEN 1
                    ELSE 0
                END
            ) AS wins,

            SUM(profit) AS profit

        FROM predictions

        WHERE status = 'SETTLED'

        GROUP BY market

        ORDER BY profit DESC

    """)

    markets = cursor.fetchall()

    connection.close()

    total = row["total"] or 0
    settled = row["settled"] or 0
    wins = row["wins"] or 0
    profit = row["profit"] or 0

    if settled:

        hit_rate = wins / settled * 100

    else:

        hit_rate = 0

    message = f"""
<b>📊 AGENT PRO — PERFORMANCE</b>

━━━━━━━━━━━━━━━━━━

Prédictions :
<b>{total}</b>

Settled :
<b>{settled}</b>

Wins :
<b>{wins}</b>

Taux de réussite :
<b>{hit_rate:.1f}%</b>

Profit unité :
<b>{profit:+.2f}</b>

━━━━━━━━━━━━━━━━━━

<b>📈 PAR MARCHÉ</b>
"""

    for market in markets:

        market_total = market["total"] or 0
        market_wins = market["wins"] or 0
        market_profit = market["profit"] or 0

        rate = (
            market_wins
            /
            market_total
            *
            100
            if market_total
            else 0
        )

        message += f"""

{market_name(market["market"])}

Matchs : {market_total}
Winrate : {rate:.1f}%
Profit : {market_profit:+.2f}
"""

    telegram(
        message
    )


# ============================================================
# CALIBRATION ENGINE
# ============================================================

def calibration_report():

    connection = db()

    cursor = connection.cursor()

    cursor.execute("""

        SELECT

            probability,

            actual_result

        FROM predictions

        WHERE status = 'SETTLED'

    """)

    rows = cursor.fetchall()

    connection.close()

    buckets = defaultdict(
        lambda: {
            "total": 0,
            "wins": 0
        }
    )

    for row in rows:

        probability = row[
            "probability"
        ]

        if probability < 50:
            bucket = "50-59"

        elif probability < 60:
            bucket = "60-69"

        elif probability < 70:
            bucket = "70-79"

        elif probability < 80:
            bucket = "80-89"

        else:
            bucket = "90-99"

        buckets[
            bucket
        ]["total"] += 1

        if row[
            "actual_result"
        ] == "WIN":

            buckets[
                bucket
            ]["wins"] += 1

    message = """
<b>🧪 CALIBRATION DU MODÈLE</b>

Le bot compare ce qu'il annonçait
avec ce qui s'est réellement produit.

"""

    for bucket in [
        "50-59",
        "60-69",
        "70-79",
        "80-89",
        "90-99"
    ]:

        total = buckets[
            bucket
        ]["total"]

        wins = buckets[
            bucket
        ]["wins"]

        if total:

            real_rate = (
                wins
                /
                total
                *
                100
            )

            message += (
                f"\n<b>{bucket}% annoncés</b>"
                f"\nMatchs : {total}"
                f"\nRéussite réelle : "
                f"{real_rate:.1f}%\n"
            )

    telegram(
        message
    )


# ============================================================
# COMMANDES TELEGRAM
# ============================================================

def get_updates(offset=None):

    if not TG_TOKEN:
        return []

    try:

        params = {
            "timeout": 5
        }

        if offset:
            params["offset"] = offset

        response = requests.get(

            f"https://api.telegram.org/"
            f"bot{TG_TOKEN}/getUpdates",

            params=params,

            timeout=10

        )

        return response.json().get(
            "result",
            []
        )

    except:

        return []


def command_loop():

    offset = None

    while True:

        updates = get_updates(
            offset
        )

        for update in updates:

            offset = (
                update["update_id"]
                + 1
            )

            message = update.get(
                "message",
                {}
            )

            text = (
                message
                .get("text", "")
                .strip()
                .lower()
            )

            if text == "/analyse":

                run_pre_match()

            elif text == "/live":

                run_live()

            elif text == "/stats":

                performance_report()

            elif text == "/calibration":

                calibration_report()

            elif text == "/status":

                telegram(f"""
<b>🟢 AGENT PRO ACTIF</b>

⏰ {now().strftime("%H:%M:%S")}

📡 API : OK
🧮 Poisson : OK
💰 Value : OK
⚠️ Risk : OK
🔴 Live : OK
💾 Database : OK

Matchs live suivis :
{len(LIVE_STATE)}
""")

            elif text == "/start":

                telegram("""
<b>🕯️ AGENT PRO V3</b>

<b>LA BOUGIE DU PARIEUR</b>

Commandes :

/analyse
→ analyse pré-match

/live
→ analyse live

/stats
→ performance

/calibration
→ calibration du modèle

/status
→ état du bot
""")

        time.sleep(1)


# ============================================================
# SCHEDULER
# ============================================================

def scheduler():

    last_analysis = 0
    last_live = 0
    last_settlement = 0
    last_report = 0

    while True:

        current = time.time()

        # ----------------------------------------------------
        # PRE-MATCH
        # ----------------------------------------------------

        if (
            current - last_analysis
            >= ANALYSIS_INTERVAL
        ):

            try:

                run_pre_match()

            except Exception:

                logging.exception(
                    "PREMATCH ERROR"
                )

            last_analysis = current

        # ----------------------------------------------------
        # LIVE
        # ----------------------------------------------------

        if (
            current - last_live
            >= LIVE_INTERVAL
        ):

            try:

                run_live()

            except Exception:

                logging.exception(
                    "LIVE ERROR"
                )

            last_live = current

        # ----------------------------------------------------
        # SETTLEMENT
        # ----------------------------------------------------

        if (
            current - last_settlement
            >= 300
        ):

            try:

                settle_finished_predictions()

            except Exception:

                logging.exception(
                    "SETTLEMENT ERROR"
                )

            last_settlement = current

        # ----------------------------------------------------
        # PERFORMANCE REPORT
        # ----------------------------------------------------

        if (
            current - last_report
            >= 86400
        ):

            try:

                performance_report()
                calibration_report()

            except Exception:

                logging.exception(
                    "REPORT ERROR"
                )

            last_report = current

        time.sleep(2)


# ============================================================
# MAIN
# ============================================================

def main():

    if not API_KEY:

        raise RuntimeError(
            "API_FOOTBALL_KEY manquante"
        )

    if not TG_TOKEN:

        raise RuntimeError(
            "TELEGRAM_TOKEN manquante"
        )

    if not TG_CHAT:

        raise RuntimeError(
            "TELEGRAM_CHAT_ID manquante"
        )

    init_database()

    telegram(f"""
<b>🕯️ AGENT PRO FOOTBALL V3</b>

<b>LA BOUGIE DU PARIEUR</b>

━━━━━━━━━━━━━━━━━━

🟢 DATA ENGINE
🟢 FORM ENGINE
🟢 HOME/AWAY ENGINE
🟢 H2H ENGINE
🟢 STRENGTH ENGINE
🟢 POISSON ENGINE
🟢 MARKET ENGINE
🟢 VALUE ENGINE
🟢 RISK ENGINE
🟢 CONVERGENCE ENGINE
🟢 LIVE ENGINE
🟢 BACKTEST ENGINE
🟢 CALIBRATION ENGINE
🟢 DATABASE

━━━━━━━━━━━━━━━━━━

📡 Pré-match :
toutes les {ANALYSIS_INTERVAL}s

🔴 Live :
toutes les {LIVE_INTERVAL}s

🎯 Score minimum :
{MIN_SCORE}/100

━━━━━━━━━━━━━━━━━━

<i>
Données
→ Probabilité
→ Value
→ Risque
→ Décision
→ Résultat
→ Calibration
</i>
""")

    # --------------------------------------------------------
    # Telegram commands
    # --------------------------------------------------------

    command_thread = threading.Thread(
        target=command_loop,
        daemon=True
    )

    command_thread.start()

    # --------------------------------------------------------
    # Scheduler
    # --------------------------------------------------------

    scheduler()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
