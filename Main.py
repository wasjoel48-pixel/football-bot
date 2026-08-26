# ============================================================
# AGENT PRO FOOTBALL V4
# "LA BOUGIE DU PARIEUR"
#
# Architecture V4
#
# DATA
#   ↓
# FORM / HOME-AWAY / H2H
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
# CALIBRATION V4
#   ↓
# DECISION ENGINE
#   ↓
# PRE-MATCH
#   ↓
# LIVE ENGINE
#   ↓
# RESULT
#   ↓
# PERFORMANCE
#   ↓
# AUTO-CALIBRATION
#
# Variables d'environnement :
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
# MIN_VALUE=3
# DB_FILE=agent_pro_v4.db
#
# ============================================================

import os
import time
import math
import sqlite3
import logging
import threading
import statistics
import requests

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict


# ============================================================
# CONFIGURATION
# ============================================================

API_KEY = os.getenv("API_FOOTBALL_KEY")
TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID")

TZ = ZoneInfo("Africa/Douala")

API_BASE = "https://v3.football.api-sports.io"

ANALYSIS_INTERVAL = int(
    os.getenv("ANALYSIS_INTERVAL", "1800")
)

LIVE_INTERVAL = int(
    os.getenv("LIVE_INTERVAL", "60")
)

MAX_CANDIDATES = int(
    os.getenv("MAX_CANDIDATES", "15")
)

MIN_SCORE = float(
    os.getenv("MIN_SCORE", "70")
)

MIN_VALUE = float(
    os.getenv("MIN_VALUE", "3")
)

DB_FILE = os.getenv(
    "DB_FILE",
    "agent_pro_v4.db"
)

HEADERS = {
    "x-apisports-key": API_KEY or "",
    "Accept": "application/json"
}


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    )
)


# ============================================================
# GLOBALS
# ============================================================

API_LOCK = threading.Lock()

CACHE = {}

LIVE_STATE = {}

LAST_TELEGRAM = {}

MODEL_VERSION = "V4.0"


# ============================================================
# BASIC UTILITIES
# ============================================================

def now():
    return datetime.now(TZ)


def clamp(
    value,
    minimum=0,
    maximum=100
):

    try:

        return max(
            minimum,
            min(
                maximum,
                float(value)
            )
        )

    except Exception:

        return minimum


def safe_float(
    value,
    default=0.0
):

    try:

        if value is None:
            return default

        if isinstance(
            value,
            str
        ):

            value = (
                value
                .replace(
                    "%",
                    ""
                )
                .strip()
            )

        return float(value)

    except Exception:

        return default


def safe_int(
    value,
    default=0
):

    try:

        return int(value)

    except Exception:

        return default


def mean(
    values,
    default=0
):

    values = [
        safe_float(v)
        for v in values
        if v is not None
    ]

    if not values:
        return default

    return sum(values) / len(values)


# ============================================================
# CACHE
# ============================================================

def cache_get(key):

    item = CACHE.get(key)

    if not item:
        return None

    timestamp, data, ttl = item

    if time.time() - timestamp < ttl:

        return data

    return None


def cache_set(
    key,
    data,
    ttl
):

    CACHE[key] = (
        time.time(),
        data,
        ttl
    )


# ============================================================
# API ENGINE
# ============================================================

def api(
    endpoint,
    params=None,
    ttl=30
):

    params = params or {}

    key = (
        endpoint
        + "|"
        + str(
            sorted(
                params.items()
            )
        )
    )

    cached = cache_get(key)

    if cached is not None:

        return cached

    with API_LOCK:

        try:

            response = requests.get(
                API_BASE + endpoint,
                headers=HEADERS,
                params=params,
                timeout=25
            )

            if response.status_code != 200:

                logging.warning(
                    "API HTTP %s : %s",
                    response.status_code,
                    endpoint
                )

                return []

            payload = response.json()

            if payload.get("errors"):

                logging.warning(
                    "API errors: %s",
                    payload.get("errors")
                )

            result = payload.get(
                "response",
                []
            )

            cache_set(
                key,
                result,
                ttl
            )

            return result

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

def database():

    connection = sqlite3.connect(
        DB_FILE,
        check_same_thread=False
    )

    connection.row_factory = sqlite3.Row

    return connection


def init_database():

    connection = database()

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

            market_name TEXT,

            probability REAL,

            raw_probability REAL,

            calibrated_probability REAL,

            fair_odds REAL,

            bookmaker_odds REAL,

            value REAL,

            score REAL,

            risk REAL,

            convergence REAL,

            quality REAL,

            lambda_home REAL,

            lambda_away REAL,

            prediction TEXT,

            decision TEXT,

            model_version TEXT,

            status TEXT DEFAULT 'PENDING',

            actual_result TEXT,

            actual_home_goals INTEGER,

            actual_away_goals INTEGER,

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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_calibration (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            created_at TEXT,

            bucket TEXT,

            predictions INTEGER,

            wins INTEGER,

            observed_rate REAL,

            expected_rate REAL,

            calibration_error REAL

        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_events (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            created_at TEXT,

            event_type TEXT,

            description TEXT,

            value REAL

        )
    """)

    connection.commit()

    connection.close()


# ============================================================
# FIXTURE ENGINE
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


def get_upcoming_fixtures():

    fixtures = get_today_fixtures()

    upcoming = []

    for fixture in fixtures:

        status = (
            fixture
            .get("fixture", {})
            .get("status", {})
            .get("short")
        )

        if status in [
            "NS",
            "TBD"
        ]:

            upcoming.append(
                fixture
            )

    upcoming.sort(
        key=lambda x:
        x["fixture"]["timestamp"]
    )

    return upcoming


def get_live_fixtures():

    return api(
        "/fixtures",
        {
            "live": "all"
        },
        ttl=15
    )


# ============================================================
# FORM ENGINE
# ============================================================

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

        "form": ""

    }


def get_form(
    team_id,
    last=10
):

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

        status = (
            match
            .get("fixture", {})
            .get("status", {})
            .get("short")
        )

        if status == "FT":

            finished.append(
                match
            )

    if not finished:

        return empty_form()

    W = 0
    D = 0
    L = 0

    GF = 0
    GA = 0

    over15 = 0
    over25 = 0
    over35 = 0
    btts = 0
    clean = 0

    form = []

    for match in finished:

        home_id = (
            match["teams"]["home"]["id"]
        )

        hg = safe_int(
            match["goals"]["home"]
        )

        ag = safe_int(
            match["goals"]["away"]
        )

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
            form.append("V")

        elif gf == ga:

            D += 1
            form.append("N")

        else:

            L += 1
            form.append("D")

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

        "form": "".join(form)

    }


# ============================================================
# HOME / AWAY ENGINE
# ============================================================

def get_venue_form(
    team_id,
    venue,
    last=15
):

    fixtures = api(
        "/fixtures",
        {
            "team": team_id,
            "last": last,
            "timezone": "Africa/Douala"
        },
        ttl=900
    )

    selected = []

    for match in fixtures:

        if (
            match
            .get("fixture", {})
            .get("status", {})
            .get("short")
            != "FT"
        ):

            continue

        home_id = (
            match["teams"]["home"]["id"]
        )

        if (
            venue == "home"
            and
            home_id == team_id
        ):

            selected.append(
                match
            )

        elif (
            venue == "away"
            and
            home_id != team_id
        ):

            selected.append(
                match
            )

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

    W = D = L = 0

    GF = GA = 0

    for match in selected:

        home_id = (
            match["teams"]["home"]["id"]
        )

        hg = safe_int(
            match["goals"]["home"]
        )

        ag = safe_int(
            match["goals"]["away"]
        )

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

def get_h2h(
    team1,
    team2
):

    fixtures = api(
        "/fixtures/headtohead",
        {
            "h2h":
                f"{team1}-{team2}",
            "last": 10,
            "timezone":
                "Africa/Douala"
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

        if (
            match
            .get("fixture", {})
            .get("status", {})
            .get("short")
            != "FT"
        ):

            continue

        result["matches"] += 1

        home_id = (
            match["teams"]["home"]["id"]
        )

        hg = safe_int(
            match["goals"]["home"]
        )

        ag = safe_int(
            match["goals"]["away"]
        )

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
# API PREDICTION
# ============================================================

def get_api_prediction(
    fixture_id
):

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

        prediction = (
            data[0]
            .get(
                "predictions",
                {}
            )
        )

        percent = prediction.get(
            "percent",
            {}
        )

        winner = (
            prediction
            .get("winner")
            or {}
        )

        return {

            "home":
                safe_float(
                    percent.get("home")
                ),

            "draw":
                safe_float(
                    percent.get("draw")
                ),

            "away":
                safe_float(
                    percent.get("away")
                ),

            "winner":
                winner.get("name"),

            "advice":
                prediction.get(
                    "advice"
                ),

            "under_over":
                prediction.get(
                    "under_over"
                )

        }

    except Exception:

        return {}


# ============================================================
# ODDS ENGINE
# ============================================================

def parse_odds(
    data
):

    odds = {}

    for bookmaker in data:

        for book in bookmaker.get(
            "bookmakers",
            []
        ):

            bookmaker_name = book.get(
                "name",
                "Unknown"
            )

            for bet in book.get(
                "bets",
                []
            ):

                market = bet.get(
                    "name",
                    ""
                )

                for value in bet.get(
                    "values",
                    []
                ):

                    label = value.get(
                        "value"
                    )

                    odd = safe_float(
                        value.get(
                            "odd"
                        )
                    )

                    if (
                        not label
                        or
                        odd <= 1
                    ):

                        continue

                    odds[(
                        bookmaker_name,
                        market,
                        str(label)
                    )] = odd

    return odds


def get_odds(
    fixture_id,
    live=False
):

    endpoint = (
        "/odds/live"
        if live
        else
        "/odds"
    )

    return parse_odds(
        api(
            endpoint,
            {
                "fixture":
                    fixture_id
            },
            ttl=15 if live else 180
        )
    )


def find_odd(
    odds,
    market
):

    mapping = {

        "HOME": [
            (
                "Match Winner",
                "Home"
            )
        ],

        "DRAW": [
            (
                "Match Winner",
                "Draw"
            )
        ],

        "AWAY": [
            (
                "Match Winner",
                "Away"
            )
        ],

        "OVER15": [
            (
                "Goals Over/Under",
                "Over 1.5"
            )
        ],

        "OVER25": [
            (
                "Goals Over/Under",
                "Over 2.5"
            )
        ],

        "OVER35": [
            (
                "Goals Over/Under",
                "Over 3.5"
            )
        ],

        "BTTS": [
            (
                "Both Teams Score",
                "Yes"
            )
        ]

    }

    targets = mapping.get(
        market,
        []
    )

    candidates = []

    for (
        bookmaker,
        market_name_,
        label
    ), odd in odds.items():

        for (
            target_market,
            target_label
        ) in targets:

            if (
                market_name_
                == target_market
                and
                label
                == target_label
            ):

                candidates.append(
                    odd
                )

    if not candidates:

        return None

    # On utilise la meilleure cote disponible.
    return max(
        candidates
    )


# ============================================================
# POISSON
# ============================================================

def poisson(
    goals,
    lam
):

    if lam <= 0:

        return (
            1
            if goals == 0
            else 0
        )

    return (

        math.exp(-lam)

        *

        lam ** goals

        /

        math.factorial(goals)

    )


def poisson_model(
    lambda_home,
    lambda_away
):

    matrix = {}

    for h in range(8):

        for a in range(8):

            matrix[
                h,
                a
            ] = (

                poisson(
                    h,
                    lambda_home
                )

                *

                poisson(
                    a,
                    lambda_away
                )

            )

    probabilities = {

        "HOME": 0,
        "DRAW": 0,
        "AWAY": 0,

        "OVER15": 0,
        "OVER25": 0,
        "OVER35": 0,

        "BTTS": 0

    }

    scores = []

    for (
        (h, a),
        probability
    ) in matrix.items():

        if h > a:

            probabilities[
                "HOME"
            ] += probability

        elif h == a:

            probabilities[
                "DRAW"
            ] += probability

        else:

            probabilities[
                "AWAY"
            ] += probability

        if h + a >= 2:

            probabilities[
                "OVER15"
            ] += probability

        if h + a >= 3:

            probabilities[
                "OVER25"
            ] += probability

        if h + a >= 4:

            probabilities[
                "OVER35"
            ] += probability

        if h > 0 and a > 0:

            probabilities[
                "BTTS"
            ] += probability

        scores.append(
            (
                probability,
                h,
                a
            )
        )

    for market in probabilities:

        probabilities[
            market
        ] *= 100

    scores.sort(
        reverse=True
    )

    return {

        "probabilities":
            probabilities,

        "scores":
            scores[:5]

    }


# ============================================================
# LAMBDA ENGINE
# ============================================================

def calculate_lambda(
    home_form,
    away_form,
    home_venue,
    away_venue
):

    home_attack = (

        home_form["avg_gf"]
        * 0.40

        +

        home_venue["avg_gf"]
        * 0.60

    )

    away_defense = (

        away_form["avg_ga"]
        * 0.40

        +

        away_venue["avg_ga"]
        * 0.60

    )

    away_attack = (

        away_form["avg_gf"]
        * 0.40

        +

        away_venue["avg_gf"]
        * 0.60

    )

    home_defense = (

        home_form["avg_ga"]
        * 0.40

        +

        home_venue["avg_ga"]
        * 0.60

    )

    lambda_home = (

        home_attack
        * 0.60

        +

        away_defense
        * 0.40

        +

        0.15

    )

    lambda_away = (

        away_attack
        * 0.60

        +

        home_defense
        * 0.40

    )

    return (

        clamp(
            lambda_home,
            0.10,
            4.50
        ),

        clamp(
            lambda_away,
            0.10,
            4.50
        )

    )


# ============================================================
# CALIBRATION V4
# ============================================================

def calibration_bucket(
    probability
):

    probability = safe_float(
        probability
    )

    if probability < 50:
        return "40-49"

    if probability < 60:
        return "50-59"

    if probability < 70:
        return "60-69"

    if probability < 80:
        return "70-79"

    if probability < 90:
        return "80-89"

    return "90-99"


def get_calibration_stats():

    connection = database()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            probability,
            actual_result
        FROM predictions
        WHERE
            status = 'SETTLED'
            AND actual_result IS NOT NULL
    """)

    rows = cursor.fetchall()

    connection.close()

    buckets = defaultdict(
        lambda: {
            "total": 0,
            "wins": 0,
            "expected": []
        }
    )

    for row in rows:

        probability = safe_float(
            row["probability"]
        )

        bucket = calibration_bucket(
            probability
        )

        buckets[
            bucket
        ]["total"] += 1

        buckets[
            bucket
        ]["expected"].append(
            probability
        )

        if row["actual_result"] == "WIN":

            buckets[
                bucket
            ]["wins"] += 1

    return buckets


def calibrated_probability(
    raw_probability
):

    raw_probability = clamp(
        raw_probability,
        1,
        99
    )

    buckets = get_calibration_stats()

    bucket = calibration_bucket(
        raw_probability
    )

    data = buckets.get(
        bucket
    )

    # Pas assez d'historique :
    # on conserve le modèle brut.
    if not data or data["total"] < 10:

        return raw_probability

    observed = (
        data["wins"]
        /
        data["total"]
        *
        100
    )

    expected = mean(
        data["expected"],
        raw_probability
    )

    # Correction douce.
    correction = (
        observed - expected
    )

    correction = clamp(
        correction,
        -12,
        12
    )

    calibrated = (
        raw_probability
        +
        correction * 0.65
    )

    return clamp(
        calibrated,
        1,
        99
    )


# ============================================================
# FORM SCORE
# ============================================================

def form_score(
    form
):

    if not form["matches"]:

        return 50

    return clamp(

        (
            form["W"] * 3
            +
            form["D"]
        )

        /

        (
            form["matches"] * 3
        )

        * 100

    )


def venue_score(
    venue
):

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

def data_quality(
    home_form,
    away_form,
    home_venue,
    away_venue,
    h2h,
    api_prediction
):

    scores = []

    for data in [
        home_form,
        away_form,
        home_venue,
        away_venue
    ]:

        n = data.get(
            "matches",
            0
        )

        if n >= 8:
            score = 100

        elif n >= 5:
            score = 80

        elif n >= 3:
            score = 60

        elif n >= 1:
            score = 40

        else:
            score = 0

        scores.append(
            score
        )

    h2h_n = h2h.get(
        "matches",
        0
    )

    if h2h_n >= 8:

        scores.append(100)

    elif h2h_n >= 5:

        scores.append(80)

    elif h2h_n >= 3:

        scores.append(60)

    else:

        scores.append(40)

    if api_prediction:

        scores.append(100)

    else:

        scores.append(50)

    return mean(
        scores,
        50
    )


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

    average = mean(
        values
    )

    dispersion = mean(
        [
            abs(
                value
                -
                average
            )
            for value in values
        ]
    )

    return clamp(
        100
        -
        dispersion
    )


# ============================================================
# RISK ENGINE
# ============================================================

def detect_traps(
    home,
    away,
    home_form,
    away_form,
    home_venue,
    away_venue,
    h2h,
    poisson_probs,
    market
):

    traps = []

    home_w = home_form["W"]
    away_w = away_form["W"]

    favorite = None

    if (
        home_w >= 6
        and
        home_w > away_w + 2
    ):

        favorite = "HOME"

    elif (
        away_w >= 6
        and
        away_w > home_w + 2
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
                "Favori extérieur "
                "face à un adversaire "
                "fort à domicile"
            )

    # --------------------------------------------------------
    # H2H
    # --------------------------------------------------------

    if (
        favorite == "HOME"
        and
        h2h["matches"] >= 5
        and
        h2h["w2"] > h2h["w1"]
    ):

        traps.append(
            "H2H contraire au favori"
        )

    if (
        favorite == "AWAY"
        and
        h2h["matches"] >= 5
        and
        h2h["w1"] > h2h["w2"]
    ):

        traps.append(
            "H2H contraire au favori"
        )

    # --------------------------------------------------------
    # Poisson
    # --------------------------------------------------------

    if (
        market == "HOME"
        and
        poisson_probs["HOME"] < 50
    ):

        traps.append(
            "Poisson ne confirme "
            "pas la victoire domicile"
        )

    if (
        market == "AWAY"
        and
        poisson_probs["AWAY"] < 50
    ):

        traps.append(
            "Poisson ne confirme "
            "pas la victoire extérieure"
        )

    # --------------------------------------------------------
    # Match trop équilibré
    # --------------------------------------------------------

    if (
        market in [
            "HOME",
            "AWAY"
        ]
        and
        abs(
            poisson_probs["HOME"]
            -
            poisson_probs["AWAY"]
        ) < 8
    ):

        traps.append(
            "Écart de force faible"
        )

    return traps


def risk_score(
    quality,
    convergence_score,
    probability,
    traps
):

    risk = (

        (100 - quality)
        * 0.35

        +

        (100 - convergence_score)
        * 0.30

        +

        (100 - probability)
        * 0.35

    )

    risk += (
        len(traps)
        * 8
    )

    return clamp(
        risk
    )


# ============================================================
# MARKET ENGINE
# ============================================================

MARKET_NAMES = {

    "HOME":
        "Victoire domicile",

    "DRAW":
        "Match nul",

    "AWAY":
        "Victoire extérieur",

    "OVER15":
        "Over 1.5",

    "OVER25":
        "Over 2.5",

    "OVER35":
        "Over 3.5",

    "BTTS":
        "BTTS Oui"

}


def market_name(
    market
):

    return MARKET_NAMES.get(
        market,
        market
    )


def choose_market(
    probabilities
):

    # On ne choisit pas seulement
    # la probabilité maximale.
    #
    # On donne priorité aux marchés
    # dont la probabilité est robuste.

    priority = [

        "OVER15",
        "BTTS",
        "OVER25",
        "HOME",
        "AWAY",
        "OVER35",
        "DRAW"

    ]

    candidates = []

    for market in priority:

        probability = safe_float(
            probabilities.get(
                market
            )
        )

        if probability >= 55:

            candidates.append(
                (
                    probability,
                    market
                )
            )

    if not candidates:

        market = max(
            probabilities,
            key=probabilities.get
        )

        return (
            market,
            probabilities[market]
        )

    # Probabilité dominante.
    candidates.sort(
        reverse=True
    )

    return candidates[0][1], candidates[0][0]


# ============================================================
# VALUE ENGINE
# ============================================================

def fair_odds(
    probability
):

    if probability <= 0:

        return 999

    return 100 / probability


def implied_probability(
    odd
):

    if not odd or odd <= 1:

        return 0

    return 100 / odd


def value_percentage(
    probability,
    odd
):

    if not odd or odd <= 1:

        return None

    market_probability = (
        implied_probability(
            odd
        )
    )

    return (
        probability
        -
        market_probability
    )


# ============================================================
# DECISION ENGINE
# ============================================================

def decision(
    score,
    risk,
    value,
    quality,
    probability,
    traps
):

    if quality < 55:

        return "⚫ NO DATA"

    if probability < 55:

        return "🔴 PASS"

    if risk >= 65:

        return "🔴 PASS"

    # Sans cote :
    # WATCH au lieu de BET.
    if value is None:

        if score >= MIN_SCORE:

            return "🟡 WATCH"

        return "🔴 PASS"

    if (
        score >= 78
        and
        value >= MIN_VALUE
        and
        risk < 45
    ):

        return "🟢 BET"

    if (
        score >= MIN_SCORE
        and
        value >= 0
    ):

        return "🟡 WATCH"

    return "🔴 PASS"


# ============================================================
# COMPLETE ANALYSIS
# ============================================================

def analyze_match(
    fixture
):

    fixture_id = fixture[
        "fixture"
    ]["id"]

    home = fixture[
        "teams"
    ]["home"]

    away = fixture[
        "teams"
    ]["away"]

    home_id = home["id"]
    away_id = away["id"]

    logging.info(
        "Analyse : %s vs %s",
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

    api_prediction = get_api_prediction(
        fixture_id
    )

    # --------------------------------------------------------
    # LAMBDA
    # --------------------------------------------------------

    lambda_home, lambda_away = (
        calculate_lambda(
            home_form,
            away_form,
            home_venue,
            away_venue
        )
    )

    # --------------------------------------------------------
    # POISSON
    # --------------------------------------------------------

    poisson_result = poisson_model(
        lambda_home,
        lambda_away
    )

    poisson_probs = (
        poisson_result[
            "probabilities"
        ]
    )

    # --------------------------------------------------------
    # MARKET
    # --------------------------------------------------------

    selected_market, raw_probability = (
        choose_market(
            poisson_probs
        )
    )

    # --------------------------------------------------------
    # API PROBABILITY
    # --------------------------------------------------------

    api_probability = 0

    if selected_market == "HOME":

        api_probability = (
            api_prediction
            .get(
                "home",
                0
            )
        )

    elif selected_market == "DRAW":

        api_probability = (
            api_prediction
            .get(
                "draw",
                0
            )
        )

    elif selected_market == "AWAY":

        api_probability = (
            api_prediction
            .get(
                "away",
                0
            )
        )

    # --------------------------------------------------------
    # SIGNALS
    # --------------------------------------------------------

    home_form_signal = form_score(
        home_form
    )

    away_form_signal = form_score(
        away_form
    )

    home_venue_signal = venue_score(
        home_venue
    )

    away_venue_signal = venue_score(
        away_venue
    )

    if selected_market == "HOME":

        form_signal = (
            home_form_signal
        )

        venue_signal = (
            home_venue_signal
        )

    elif selected_market == "AWAY":

        form_signal = (
            away_form_signal
        )

        venue_signal = (
            away_venue_signal
        )

    elif selected_market in [
        "OVER15",
        "OVER25",
        "OVER35",
        "BTTS"
    ]:

        form_signal = mean(
            [
                home_form["over25"],
                away_form["over25"]
            ]
        )

        venue_signal = mean(
            [
                home_venue_signal,
                away_venue_signal
            ]
        )

    else:

        form_signal = mean(
            [
                home_form_signal,
                away_form_signal
            ]
        )

        venue_signal = mean(
            [
                home_venue_signal,
                away_venue_signal
            ]
        )

    # --------------------------------------------------------
    # QUALITY
    # --------------------------------------------------------

    quality = data_quality(
        home_form,
        away_form,
        home_venue,
        away_venue,
        h2h,
        api_prediction
    )

    # --------------------------------------------------------
    # CONVERGENCE
    # --------------------------------------------------------

    convergence_score = convergence(
        raw_probability,
        api_probability,
        form_signal,
        venue_signal
    )

    # --------------------------------------------------------
    # TRAPS
    # --------------------------------------------------------

    traps = detect_traps(

        home,
        away,

        home_form,
        away_form,

        home_venue,
        away_venue,

        h2h,

        poisson_probs,

        selected_market

    )

    # --------------------------------------------------------
    # CALIBRATION V4
    # --------------------------------------------------------

    calibrated = calibrated_probability(
        raw_probability
    )

    # --------------------------------------------------------
    # RISK
    # --------------------------------------------------------

    risk = risk_score(

        quality,

        convergence_score,

        calibrated,

        traps

    )

    # --------------------------------------------------------
    # GLOBAL SCORE
    # --------------------------------------------------------

    score = (

        calibrated
        * 0.35

        +

        convergence_score
        * 0.20

        +

        quality
        * 0.20

        +

        (100 - risk)
        * 0.15

        +

        form_signal
        * 0.10

    )

    score = clamp(
        score
    )

    # --------------------------------------------------------
    # ODDS
    # --------------------------------------------------------

    odds = get_odds(
        fixture_id
    )

    odd = find_odd(
        odds,
        selected_market
    )

    value = value_percentage(
        calibrated,
        odd
    )

    # --------------------------------------------------------
    # DECISION
    # --------------------------------------------------------

    final_decision = decision(

        score,

        risk,

        value,

        quality,

        calibrated,

        traps

    )

    # --------------------------------------------------------
    # TOP SCORES
    # --------------------------------------------------------

    top_scores = []

    for probability, h, a in (
        poisson_result["scores"][:3]
    ):

        top_scores.append(
            {
                "score":
                    f"{h}-{a}",

                "probability":
                    probability * 100
            }
        )

    kickoff = datetime.fromtimestamp(
        fixture["fixture"]["timestamp"],
        TZ
    ).isoformat()

    return {

        "fixture_id":
            fixture_id,

        "home":
            home["name"],

        "away":
            away["name"],

        "kickoff":
            kickoff,

        "market":
            selected_market,

        "market_name":
            market_name(
                selected_market
            ),

        "probability":
            calibrated,

        "raw_probability":
            raw_probability,

        "fair_odds":
            fair_odds(
                calibrated
            ),

        "odd":
            odd,

        "value":
            value,

        "score":
            score,

        "risk":
            risk,

        "convergence":
            convergence_score,

        "quality":
            quality,

        "lambda_home":
            lambda_home,

        "lambda_away":
            lambda_away,

        "poisson":
            poisson_probs,

        "api_prediction":
            api_prediction,

        "home_form":
            home_form,

        "away_form":
            away_form,

        "home_venue":
            home_venue,

        "away_venue":
            away_venue,

        "h2h":
            h2h,

        "traps":
            traps,

        "top_scores":
            top_scores,

        "decision":
            final_decision,

        "model_version":
            MODEL_VERSION

    }


# ============================================================
# SAVE PREDICTION
# ============================================================

def save_prediction(
    analysis
):

    connection = database()

    cursor = connection.cursor()

    cursor.execute("""
        INSERT OR REPLACE INTO predictions (

            fixture_id,

            created_at,

            kickoff,

            home,

            away,

            market,

            market_name,

            probability,

            raw_probability,

            calibrated_probability,

            fair_odds,

            bookmaker_odds,

            value,

            score,

            risk,

            convergence,

            quality,

            lambda_home,

            lambda_away,

            prediction,

            decision,

            model_version,

            status

        )

        VALUES (

            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, 'PENDING'

        )
    """, (

        analysis["fixture_id"],

        now().isoformat(),

        analysis["kickoff"],

        analysis["home"],

        analysis["away"],

        analysis["market"],

        analysis["market_name"],

        analysis["probability"],

        analysis["raw_probability"],

        analysis["probability"],

        analysis["fair_odds"],

        analysis["odd"],

        (
            analysis["value"]
            if analysis["value"]
            is not None
            else None
        ),

        analysis["score"],

        analysis["risk"],

        analysis["convergence"],

        analysis["quality"],

        analysis["lambda_home"],

        analysis["lambda_away"],

        analysis["market"],

        analysis["decision"],

        MODEL_VERSION

    ))

    connection.commit()

    connection.close()


# ============================================================
# TELEGRAM
# ============================================================

def telegram(
    text
):

    if not TG_TOKEN or not TG_CHAT:

        logging.warning(
            "Telegram non configuré"
        )

        return False

    try:

        response = requests.post(

            (
                "https://api.telegram.org/"
                f"bot{TG_TOKEN}/sendMessage"
            ),

            data={

                "chat_id":
                    TG_CHAT,

                "text":
                    text,

                "parse_mode":
                    "HTML",

                "disable_web_page_preview":
                    True

            },

            timeout=20

        )

        if response.status_code != 200:

            logging.warning(
                "Telegram HTTP %s",
                response.status_code
            )

            return False

        return True

    except Exception as e:

        logging.error(
            "Telegram ERROR : %s",
            e
        )

        return False


# ============================================================
# PREMATCH FORMAT
# ============================================================

def format_analysis(
    a
):

    kickoff = datetime.fromisoformat(
        a["kickoff"]
    ).strftime("%H:%M")

    value = a["value"]

    value_text = (
        f"{value:+.1f}%"
        if value is not None
        else "N/A"
    )

    text = f"""
<b>🕯️ AGENT PRO V4</b>
<b>LA BOUGIE DU PARIEUR</b>

⏰ {kickoff}

⚽ <b>{a["home"]} vs {a["away"]}</b>

━━━━━━━━━━━━━━━━━━

<b>🎯 PRONOSTIC</b>

<b>{a["market_name"]}</b>

Probabilité brute :
{a["raw_probability"]:.1f}%

Probabilité calibrée :
<b>{a["probability"]:.1f}%</b>

Cote juste :
<b>{a["fair_odds"]:.2f}</b>

Cote disponible :
<b>{
    f"{a['odd']:.2f}"
    if a["odd"]
    else "N/A"
}</b>

Value :
<b>{value_text}</b>

━━━━━━━━━━━━━━━━━━

<b>🧠 MOTEUR</b>

Poisson :

🏠 {a["poisson"]["HOME"]:.1f}%
🤝 {a["poisson"]["DRAW"]:.1f}%
✈️ {a["poisson"]["AWAY"]:.1f}%

Over 1.5 :
{a["poisson"]["OVER15"]:.1f}%

Over 2.5 :
{a["poisson"]["OVER25"]:.1f}%

Over 3.5 :
{a["poisson"]["OVER35"]:.1f}%

BTTS :
{a["poisson"]["BTTS"]:.1f}%

λ :
{a["lambda_home"]:.2f}
-
{a["lambda_away"]:.2f}

━━━━━━━━━━━━━━━━━━

<b>🕯️ BOUGIE</b>

Score :
<b>{a["score"]:.0f}/100</b>

Risque :
<b>{a["risk"]:.0f}/100</b>

Convergence :
<b>{a["convergence"]:.0f}/100</b>

Qualité données :
<b>{a["quality"]:.0f}/100</b>

━━━━━━━━━━━━━━━━━━

<b>🎯 TOP SCORES</b>
"""

    for item in a["top_scores"]:

        text += (

            f'\n• '
            f'{item["score"]} '
            f'→ '
            f'{item["probability"]:.1f}%'

        )

    if a["traps"]:

        text += (
            "\n\n<b>🚨 ALERTES</b>"
        )

        for trap in a["traps"]:

            text += (
                f"\n• {trap}"
            )

    text += f"""

━━━━━━━━━━━━━━━━━━

<b>DÉCISION :
{a["decision"]}</b>

🤖 Modèle :
{MODEL_VERSION}

<i>
Le bot mesure une probabilité,
pas une certitude.
</i>
"""

    return text


# ============================================================
# PREMATCH ENGINE
# ============================================================

def run_prematch():

    fixtures = (
        get_upcoming_fixtures()
    )

    if not fixtures:

        logging.info(
            "Aucun match à analyser."
        )

        return

    fixtures = fixtures[
        :MAX_CANDIDATES
    ]

    analyses = []

    for fixture in fixtures:

        try:

            analysis = analyze_match(
                fixture
            )

            analyses.append(
                analysis
            )

            save_prediction(
                analysis
            )

            time.sleep(0.5)

        except Exception:

            logging.exception(
                "Erreur analyse"
            )

    if not analyses:

        return

    # --------------------------------------------------------
    # Classement
    # --------------------------------------------------------

    analyses.sort(

        key=lambda a: (

            a["decision"]
            == "🟢 BET",

            a["score"],

            (
                a["value"]
                if a["value"] is not None
                else -999
            )

        ),

        reverse=True

    )

    selected = [
        a
        for a in analyses
        if a["decision"]
        in [
            "🟢 BET",
            "🟡 WATCH"
        ]
    ]

    # --------------------------------------------------------
    # Briefing
    # --------------------------------------------------------

    message = f"""
<b>🕯️ AGENT PRO V4</b>
<b>BRIEFING DU JOUR</b>

📅 {now().strftime("%d/%m/%Y")}
⏰ {now().strftime("%H:%M")}

Matchs analysés :
<b>{len(analyses)}</b>

Opportunités :
<b>{len(selected)}</b>

━━━━━━━━━━━━━━━━━━
"""

    for index, a in enumerate(
        analyses[:7],
        1
    ):

        value = a["value"]

        value_text = (
            f"{value:+.1f}%"
            if value is not None
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

<b>Architecture V4</b>

DATA
→ POISSON
→ CALIBRATION
→ VALUE
→ RISK
→ CONVERGENCE
→ DECISION
→ LIVE
→ RESULT
→ APPRENTISSAGE

<i>
Aucun pari n'est garanti.
Le système peut volontairement
recommander PASS.
</i>
"""

    telegram(
        message
    )

    # --------------------------------------------------------
    # Détails uniquement pour
    # les meilleures opportunités.
    # --------------------------------------------------------

    for analysis in analyses[:5]:

        if analysis["decision"] in [
            "🟢 BET",
            "🟡 WATCH"
        ]:

            telegram(
                format_analysis(
                    analysis
                )
            )

            time.sleep(1)


# ============================================================
# LIVE STATISTICS
# ============================================================

def get_live_statistics(
    fixture_id
):

    data = api(
        "/fixtures/statistics",
        {
            "fixture":
                fixture_id
        },
        ttl=45
    )

    result = {}

    for team_block in data:

        team_id = (
            team_block
            .get("team", {})
            .get("id")
        )

        if not team_id:
            continue

        result[
            str(team_id)
        ] = {}

        for statistic in (
            team_block
            .get(
                "statistics",
                []
            )
        ):

            name = statistic.get(
                "type"
            )

            value = statistic.get(
                "value"
            )

            result[
                str(team_id)
            ][name] = safe_float(
                value
            )

    return result


# ============================================================
# SAVE LIVE SNAPSHOT
# ============================================================

def save_live_snapshot(
    fixture,
    stats
):

    fixture_id = (
        fixture["fixture"]["id"]
    )

    home_id = (
        fixture["teams"]
        ["home"]["id"]
    )

    away_id = (
        fixture["teams"]
        ["away"]["id"]
    )

    home_stats = stats.get(
        str(home_id),
        {}
    )

    away_stats = stats.get(
        str(away_id),
        {}
    )

    minute = safe_int(
        fixture["fixture"]
        ["status"]
        .get("elapsed")
    )

    connection = database()

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

        VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?
        )
    """, (

        fixture_id,

        now().isoformat(),

        minute,

        safe_int(
            fixture["goals"]["home"]
        ),

        safe_int(
            fixture["goals"]["away"]
        ),

        home_stats.get(
            "Ball Possession",
            0
        ),

        away_stats.get(
            "Ball Possession",
            0
        ),

        home_stats.get(
            "Total Shots",
            0
        ),

        away_stats.get(
            "Total Shots",
            0
        ),

        home_stats.get(
            "Shots on Goal",
            0
        ),

        away_stats.get(
            "Shots on Goal",
            0
        ),

        home_stats.get(
            "Corner Kicks",
            0
        ),

        away_stats.get(
            "Corner Kicks",
            0
        )

    ))

    connection.commit()

    connection.close()


# ============================================================
# LIVE PROBABILITY ENGINE
# ============================================================

def live_adjustment(
    prediction,
    fixture,
    stats
):

    base_probability = safe_float(
        prediction["probability"]
    )

    market = prediction[
        "market"
    ]

    fixture_status = (
        fixture["fixture"]
        ["status"]
    )

    minute = safe_int(
        fixture_status.get(
            "elapsed"
        )
    )

    hg = safe_int(
        fixture["goals"]["home"]
    )

    ag = safe_int(
        fixture["goals"]["away"]
    )

    home_id = (
        fixture["teams"]
        ["home"]["id"]
    )

    away_id = (
        fixture["teams"]
        ["away"]["id"]
    )

    hs = stats.get(
        str(home_id),
        {}
    )

    aws = stats.get(
        str(away_id),
        {}
    )

    home_target = safe_float(
        hs.get(
            "Shots on Goal"
        )
    )

    away_target = safe_float(
        aws.get(
            "Shots on Goal"
        )
    )

    home_shots = safe_float(
        hs.get(
            "Total Shots"
        )
    )

    away_shots = safe_float(
        aws.get(
            "Total Shots"
        )
    )

    adjustment = 0

    # --------------------------------------------------------
    # Score
    # --------------------------------------------------------

    if market == "HOME":

        if hg > ag:

            adjustment += 10

        elif hg < ag:

            adjustment -= 15

    elif market == "AWAY":

        if ag > hg:

            adjustment += 10

        elif ag < hg:

            adjustment -= 15

    elif market == "BTTS":

        if hg > 0 and ag > 0:

            adjustment += 15

        elif (
            minute >= 70
            and
            (
                hg == 0
                or
                ag == 0
            )
        ):

            adjustment -= 18

    elif market == "OVER15":

        if hg + ag >= 2:

            adjustment += 12

        elif (
            minute >= 70
            and
            hg + ag == 0
        ):

            adjustment -= 15

    elif market == "OVER25":

        if hg + ag >= 3:

            adjustment += 15

        elif (
            minute >= 70
            and
            hg + ag < 2
        ):

            adjustment -= 15

    elif market == "OVER35":

        if hg + ag >= 4:

            adjustment += 15

        elif (
            minute >= 70
            and
            hg + ag < 3
        ):

            adjustment -= 15

    # --------------------------------------------------------
    # Intensité
    # --------------------------------------------------------

    shots_target = (
        home_target
        +
        away_target
    )

    total_shots = (
        home_shots
        +
        away_shots
    )

    if shots_target >= 8:

        adjustment += 6

    elif shots_target >= 5:

        adjustment += 3

    elif (
        shots_target <= 1
        and
        minute >= 45
    ):

        adjustment -= 5

    if total_shots >= 20:

        adjustment += 3

    # --------------------------------------------------------
    # Fatigue temporelle
    # --------------------------------------------------------

    if minute >= 80:

        adjustment *= 1.15

    live_probability = clamp(

        base_probability
        +
        adjustment,

        1,
        99

    )

    return live_probability


# ============================================================
# LIVE ALERT ENGINE
# ============================================================

def live_update(
    fixture
):

    fixture_id = (
        fixture["fixture"]["id"]
    )

    status = (
        fixture["fixture"]
        ["status"]
        ["short"]
    )

    if status not in [
        "1H",
        "HT",
        "2H",
        "ET"
    ]:

        return

    connection = database()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM predictions
        WHERE fixture_id = ?
    """, (
        fixture_id,
    ))

    prediction = cursor.fetchone()

    connection.close()

    if not prediction:

        return

    prediction = dict(
        prediction
    )

    stats = get_live_statistics(
        fixture_id
    )

    save_live_snapshot(
        fixture,
        stats
    )

    live_probability = (
        live_adjustment(
            prediction,
            fixture,
            stats
        )
    )

    minute = safe_int(
        fixture["fixture"]
        ["status"]
        .get("elapsed")
    )

    hg = safe_int(
        fixture["goals"]["home"]
    )

    ag = safe_int(
        fixture["goals"]["away"]
    )

    previous = LIVE_STATE.get(
        fixture_id
    )

    current = {

        "minute":
            minute,

        "home_goals":
            hg,

        "away_goals":
            ag,

        "probability":
            live_probability

    }

    LIVE_STATE[
        fixture_id
    ] = current

    # --------------------------------------------------------
    # Première entrée
    # --------------------------------------------------------

    if previous is None:

        telegram(f"""
<b>🔴 LIVE — AGENT PRO V4</b>

⚽ <b>{prediction["home"]}
{hg} - {ag}
{prediction["away"]}</b>

⏱️ {minute}'

🎯 Marché :
<b>{prediction["market_name"]}</b>

📊 Probabilité :
<b>{live_probability:.1f}%</b>

📡 Surveillance activée.
""")

        return

    # --------------------------------------------------------
    # BUT
    # --------------------------------------------------------

    goal_changed = (

        previous["home_goals"]
        != hg

        or

        previous["away_goals"]
        != ag

    )

    if goal_changed:

        telegram(f"""
<b>⚡ BUT — AGENT PRO LIVE</b>

⚽ <b>{prediction["home"]}
{hg} - {ag}
{prediction["away"]}</b>

⏱️ {minute}'

🎯 {prediction["market_name"]}

📊 Probabilité LIVE :
<b>{live_probability:.1f}%</b>
""")

    # --------------------------------------------------------
    # Gros mouvement
    # --------------------------------------------------------

    change = (
        live_probability
        -
        previous["probability"]
    )

    if abs(change) >= 8:

        direction = (
            "📈 RENFORCEMENT"
            if change > 0
            else
            "📉 DÉGRADATION"
        )

        telegram(f"""
<b>🕯️ BOUGIE LIVE</b>

⚽ {prediction["home"]}
<b>{hg}-{ag}</b>
{prediction["away"]}

⏱️ {minute}'

{direction}

Probabilité :
<b>{live_probability:.1f}%</b>

Variation :
{change:+.1f} points

🎯 {prediction["market_name"]}
""")

    # --------------------------------------------------------
    # Rapport toutes les 15 minutes
    # --------------------------------------------------------

    if (
        minute > 0
        and
        minute % 15 == 0
        and
        (
            fixture_id
            not in LAST_TELEGRAM
            or
            LAST_TELEGRAM[
                fixture_id
            ] != minute
        )
    ):

        LAST_TELEGRAM[
            fixture_id
        ] = minute

        telegram(f"""
<b>📡 RAPPORT LIVE V4</b>

⚽ {prediction["home"]}
<b>{hg}-{ag}</b>
{prediction["away"]}

⏱️ {minute}'

🎯 {prediction["market_name"]}

Pré-match :
{prediction["probability"]:.1f}%

LIVE :
<b>{live_probability:.1f}%</b>

Variation :
{change:+.1f}

🕯️ Score initial :
{prediction["score"]:.0f}/100
""")


# ============================================================
# LIVE ENGINE
# ============================================================

def run_live():

    fixtures = get_live_fixtures()

    for fixture in fixtures:

        try:

            live_update(
                fixture
            )

        except Exception:

            logging.exception(
                "LIVE ERROR"
            )


# ============================================================
# RESULT ENGINE
# ============================================================

def market_won(
    market,
    hg,
    ag
):

    if market == "HOME":

        return hg > ag

    if market == "DRAW":

        return hg == ag

    if market == "AWAY":

        return ag > hg

    if market == "OVER15":

        return hg + ag >= 2

    if market == "OVER25":

        return hg + ag >= 3

    if market == "OVER35":

        return hg + ag >= 4

    if market == "BTTS":

        return (
            hg > 0
            and
            ag > 0
        )

    return False


def settle_predictions():

    connection = database()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT *
        FROM predictions
        WHERE status = 'PENDING'
    """)

    predictions = cursor.fetchall()

    connection.close()

    for prediction in predictions:

        try:

            kickoff = datetime.fromisoformat(
                prediction["kickoff"]
            )

        except Exception:

            continue

        if (
            now()
            <
            kickoff
            +
            timedelta(
                minutes=140
            )
        ):

            continue

        fixture_id = (
            prediction["fixture_id"]
        )

        fixtures = api(
            "/fixtures",
            {
                "id":
                    fixture_id
            },
            ttl=60
        )

        if not fixtures:

            continue

        fixture = fixtures[0]

        status = (
            fixture["fixture"]
            ["status"]
            ["short"]
        )

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

        won = market_won(

            prediction["market"],

            hg,

            ag

        )

        odd = safe_float(
            prediction[
                "bookmaker_odds"
            ]
        )

        if odd > 1:

            profit = (
                odd - 1
                if won
                else
                -1
            )

        else:

            profit = (
                1
                if won
                else
                -1
            )

        result = (
            "WIN"
            if won
            else
            "LOSS"
        )

        connection = database()

        cursor = connection.cursor()

        cursor.execute("""
            UPDATE predictions
            SET
                status = 'SETTLED',
                actual_result = ?,
                actual_home_goals = ?,
                actual_away_goals = ?,
                profit = ?
            WHERE fixture_id = ?
        """, (

            result,

            hg,

            ag,

            profit,

            fixture_id

        ))

        connection.commit()

        connection.close()

        telegram(f"""
<b>🏁 RÉSULTAT — AGENT PRO V4</b>

⚽ {prediction["home"]}
<b>{hg} - {ag}</b>
{prediction["away"]}

🎯 {prediction["market_name"]}

Résultat :
<b>{result}</b>

Profit unité :
{profit:+.2f}

Probabilité annoncée :
{prediction["probability"]:.1f}%

Score :
{prediction["score"]:.0f}/100
""")


# ============================================================
# PERFORMANCE
# ============================================================

def performance_report():

    connection = database()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            COUNT(*) total,
            SUM(
                CASE
                    WHEN status='SETTLED'
                    THEN 1
                    ELSE 0
                END
            ) settled,
            SUM(
                CASE
                    WHEN actual_result='WIN'
                    THEN 1
                    ELSE 0
                END
            ) wins,
            COALESCE(
                SUM(profit),
                0
            ) profit
        FROM predictions
    """)

    overall = cursor.fetchone()

    cursor.execute("""
        SELECT
            market,
            COUNT(*) total,
            SUM(
                CASE
                    WHEN actual_result='WIN'
                    THEN 1
                    ELSE 0
                END
            ) wins,
            COALESCE(
                SUM(profit),
                0
            ) profit
        FROM predictions
        WHERE status='SETTLED'
        GROUP BY market
        ORDER BY profit DESC
    """)

    markets = cursor.fetchall()

    connection.close()

    total = overall["total"] or 0
    settled = overall["settled"] or 0
    wins = overall["wins"] or 0
    profit = overall["profit"] or 0

    winrate = (
        wins
        /
        settled
        *
        100
        if settled
        else 0
    )

    message = f"""
<b>📊 AGENT PRO V4 — PERFORMANCE</b>

━━━━━━━━━━━━━━━━━━

Prédictions :
<b>{total}</b>

Settled :
<b>{settled}</b>

Wins :
<b>{wins}</b>

Winrate :
<b>{winrate:.1f}%</b>

Profit unité :
<b>{profit:+.2f}</b>

━━━━━━━━━━━━━━━━━━

<b>📈 MARCHÉS</b>
"""

    for market in markets:

        total_market = (
            market["total"]
            or 0
        )

        wins_market = (
            market["wins"]
            or 0
        )

        profit_market = (
            market["profit"]
            or 0
        )

        rate = (

            wins_market
            /
            total_market
            *
            100

            if total_market
            else 0

        )

        message += f"""

<b>{market_name(
    market["market"]
)}</b>

Matchs : {total_market}
Winrate : {rate:.1f}%
Profit : {profit_market:+.2f}
"""

    telegram(
        message
    )


# ============================================================
# CALIBRATION REPORT
# ============================================================

def calibration_report():

    buckets = (
        get_calibration_stats()
    )

    message = """
<b>🧪 CALIBRATION V4</b>

Le modèle compare :

PROBABILITÉ ANNONCÉE
VS
RÉSULTAT RÉEL

━━━━━━━━━━━━━━━━━━
"""

    ordered = [
        "40-49",
        "50-59",
        "60-69",
        "70-79",
        "80-89",
        "90-99"
    ]

    for bucket in ordered:

        data = buckets.get(
            bucket
        )

        if not data:

            continue

        total = data[
            "total"
        ]

        wins = data[
            "wins"
        ]

        observed = (
            wins
            /
            total
            *
            100
        )

        expected = mean(
            data[
                "expected"
            ]
        )

        error = (
            observed
            -
            expected
        )

        message += f"""

<b>{bucket}%</b>

Échantillon :
{total}

Réussite réelle :
{observed:.1f}%

Moyenne annoncée :
{expected:.1f}%

Erreur :
{error:+.1f} pts
"""

    telegram(
        message
    )


# ============================================================
# MODEL HEALTH
# ============================================================

def model_health():

    connection = database()

    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            probability,
            actual_result,
            score,
            risk,
            value
        FROM predictions
        WHERE status='SETTLED'
        ORDER BY id DESC
        LIMIT 100
    """)

    rows = cursor.fetchall()

    connection.close()

    if len(rows) < 10:

        return {

            "sample":
                len(rows),

            "health":
                "INSUFFICIENT DATA",

            "winrate":
                0,

            "avg_score":
                0

        }

    wins = sum(

        1
        for row in rows
        if row["actual_result"]
        == "WIN"

    )

    winrate = (
        wins
        /
        len(rows)
        *
        100
    )

    avg_score = mean(
        [
            row["score"]
            for row in rows
        ]
    )

    return {

        "sample":
            len(rows),

        "health":
            (
                "GOOD"
                if winrate >= 55
                else
                "WATCH"
            ),

        "winrate":
            winrate,

        "avg_score":
            avg_score

    }


# ============================================================
# MODEL HEALTH TELEGRAM
# ============================================================

def health_report():

    health = model_health()

    telegram(f"""
<b>🩺 SANTÉ DU MODÈLE V4</b>

Échantillon :
<b>{health["sample"]}</b>

Winrate récent :
<b>{health["winrate"]:.1f}%</b>

Score moyen :
<b>{health["avg_score"]:.1f}/100</b>

État :
<b>{health["health"]}</b>

Version :
<b>{MODEL_VERSION}</b>
""")


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

def get_updates(
    offset=None
):

    if not TG_TOKEN:

        return []

    try:

        params = {
            "timeout": 5
        }

        if offset is not None:

            params[
                "offset"
            ] = offset

        response = requests.get(

            (
                "https://api.telegram.org/"
                f"bot{TG_TOKEN}/getUpdates"
            ),

            params=params,

            timeout=10

        )

        return response.json().get(
            "result",
            []
        )

    except Exception:

        return []


def command_loop():

    offset = None

    while True:

        updates = get_updates(
            offset
        )

        for update in updates:

            offset = (
                update[
                    "update_id"
                ]
                +
                1
            )

            message = update.get(
                "message",
                {}
            )

            text = (
                message
                .get(
                    "text",
                    ""
                )
                .strip()
                .lower()
            )

            if text == "/analyse":

                telegram(
                    "🧠 Analyse V4 lancée..."
                )

                run_prematch()

            elif text == "/live":

                telegram(
                    "📡 Scan LIVE lancé..."
                )

                run_live()

            elif text == "/stats":

                performance_report()

            elif text == "/calibration":

                calibration_report()

            elif text == "/health":

                health_report()

            elif text == "/status":

                health = (
                    model_health()
                )

                telegram(f"""
<b>🟢 AGENT PRO V4 ACTIF</b>

🧮 Poisson : OK
📊 Calibration : OK
💰 Value : OK
⚠️ Risk : OK
🔴 Live : OK
💾 Database : OK

Matchs LIVE :
<b>{len(LIVE_STATE)}</b>

Historique :
<b>{health["sample"]}</b>

Winrate récent :
<b>{health["winrate"]:.1f}%</b>
""")

            elif text == "/start":

                telegram("""
<b>🕯️ AGENT PRO FOOTBALL V4</b>

<b>LA BOUGIE DU PARIEUR</b>

Commandes :

/analyse
→ Analyse pré-match

/live
→ Scan live

/stats
→ Performance

/calibration
→ Calibration

/health
→ Santé du modèle

/status
→ État du système
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
    last_health = 0

    while True:

        current = time.time()

        # ----------------------------------------------------
        # PREMATCH
        # ----------------------------------------------------

        if (
            current
            -
            last_analysis
            >=
            ANALYSIS_INTERVAL
        ):

            try:

                run_prematch()

            except Exception:

                logging.exception(
                    "PREMATCH ERROR"
                )

            last_analysis = current

        # ----------------------------------------------------
        # LIVE
        # ----------------------------------------------------

        if (
            current
            -
            last_live
            >=
            LIVE_INTERVAL
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
            current
            -
            last_settlement
            >=
            300
        ):

            try:

                settle_predictions()

            except Exception:

                logging.exception(
                    "SETTLEMENT ERROR"
                )

            last_settlement = current

        # ----------------------------------------------------
        # DAILY REPORT
        # ----------------------------------------------------

        if (
            current
            -
            last_report
            >=
            86400
        ):

            try:

                performance_report()
                calibration_report()

            except Exception:

                logging.exception(
                    "DAILY REPORT ERROR"
                )

            last_report = current

        # ----------------------------------------------------
        # HEALTH
        # ----------------------------------------------------

        if (
            current
            -
            last_health
            >=
            21600
        ):

            try:

                health_report()

            except Exception:

                logging.exception(
                    "HEALTH ERROR"
                )

            last_health = current

        time.sleep(2)


# ============================================================
# STARTUP
# ============================================================

def startup_message():

    return f"""
<b>🕯️ AGENT PRO FOOTBALL V4</b>

<b>LA BOUGIE DU PARIEUR</b>

━━━━━━━━━━━━━━━━━━

🟢 DATA ENGINE
🟢 FORM ENGINE
🟢 HOME/AWAY ENGINE
🟢 H2H ENGINE
🟢 POISSON ENGINE
🟢 MARKET ENGINE
🟢 VALUE ENGINE
🟢 RISK ENGINE
🟢 CONVERGENCE ENGINE
🟢 CALIBRATION ENGINE
🟢 DECISION ENGINE
🟢 LIVE ENGINE
🟢 RESULT ENGINE
🟢 PERFORMANCE ENGINE
🟢 MODEL HEALTH

━━━━━━━━━━━━━━━━━━

<b>V4 =</b>

Données
↓
Probabilité
↓
Calibration
↓
Value
↓
Risque
↓
Décision
↓
Live
↓
Résultat
↓
Apprentissage

━━━━━━━━━━━━━━━━━━

⏱️ Pré-match :
{ANALYSIS_INTERVAL}s

🔴 Live :
{LIVE_INTERVAL}s

🎯 Score minimum :
{MIN_SCORE}/100

💰 Value minimum :
{MIN_VALUE} pts

🤖 Version :
{MODEL_VERSION}

<i>
Le système peut dire PASS.
C'est une fonctionnalité,
pas un échec.
</i>
"""


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
            "TELEGRAM_CHAT_ID manquant"
        )

    # --------------------------------------------------------
    # Database
    # --------------------------------------------------------

    init_database()

    # --------------------------------------------------------
    # Startup
    # --------------------------------------------------------

    telegram(
        startup_message()
    )

    # --------------------------------------------------------
    # Telegram commands
    # --------------------------------------------------------

    command_thread = (
        threading.Thread(
            target=command_loop,
            daemon=True
        )
    )

    command_thread.start()

    # --------------------------------------------------------
    # Scheduler principal
    # --------------------------------------------------------

    scheduler()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
