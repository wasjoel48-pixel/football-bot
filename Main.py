# ============================================================
# AGENT PRO FOOTBALL V2 — "LA BOUGIE DU PARIEUR"
# GitHub / Render / Railway compatible
#
# Variables d'environnement :
# API_FOOTBALL_KEY
# TELEGRAM_TOKEN
# TELEGRAM_CHAT_ID
#
# OPTIONNEL :
# ANALYSIS_INTERVAL=900
# LIVE_INTERVAL=60
# MAX_MATCHES=12
# MIN_SCORE=65
# ============================================================

import os
import time
import math
import logging
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict

# ============================================================
# CONFIGURATION
# ============================================================

API_KEY = os.getenv("API_FOOTBALL_KEY")
TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID")

TZ = ZoneInfo("Africa/Douala")

ANALYSIS_INTERVAL = int(os.getenv("ANALYSIS_INTERVAL", "900"))
LIVE_INTERVAL = int(os.getenv("LIVE_INTERVAL", "60"))
MAX_MATCHES = int(os.getenv("MAX_MATCHES", "12"))
MIN_SCORE = int(os.getenv("MIN_SCORE", "65"))

API_BASE = "https://v3.football.api-sports.io"

HEADERS = {
    "x-apisports-key": API_KEY or ""
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ============================================================
# CACHE
# ============================================================

CACHE = {}
LAST_MESSAGES = {}
LIVE_TRACKER = {}

# ============================================================
# OUTILS
# ============================================================

def now():
    return datetime.now(TZ)


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except:
        return default


def pct(value):
    return f"{value:.1f}%"


def clamp(value, minimum=0, maximum=100):
    return max(minimum, min(maximum, value))


def api(endpoint, params=None, cache_seconds=30):
    """
    Appel API-Football avec cache.
    """
    key = endpoint + str(params)

    cached = CACHE.get(key)

    if cached:
        timestamp, data = cached
        if time.time() - timestamp < cache_seconds:
            return data

    try:
        r = requests.get(
            f"{API_BASE}{endpoint}",
            headers=HEADERS,
            params=params or {},
            timeout=30
        )

        if r.status_code != 200:
            logging.warning(
                "API HTTP %s : %s",
                r.status_code,
                r.text[:300]
            )
            return []

        data = r.json().get("response", [])

        CACHE[key] = (time.time(), data)

        return data

    except Exception as e:
        logging.error("Erreur API : %s", e)
        return []


# ============================================================
# TELEGRAM
# ============================================================

def telegram(text):
    if not TG_TOKEN or not TG_CHAT:
        logging.warning("Telegram non configuré.")
        return False

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={
                "chat_id": TG_CHAT,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=20
        )

        return r.status_code == 200

    except Exception as e:
        logging.error("Telegram : %s", e)
        return False


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
        cache_seconds=60
    )


def get_upcoming():
    fixtures = get_today_fixtures()

    result = []

    for m in fixtures:
        status = m["fixture"]["status"]["short"]

        if status in ["NS", "TBD"]:
            result.append(m)

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
        cache_seconds=20
    )


# ============================================================
# FORM
# ============================================================

def get_form(team_id, last=10):

    fixtures = api(
        "/fixtures",
        {
            "team": team_id,
            "last": last,
            "timezone": "Africa/Douala"
        },
        cache_seconds=600
    )

    finished = []

    for m in fixtures:

        if m["fixture"]["status"]["short"] != "FT":
            continue

        finished.append(m)

    if not finished:
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

    W = D = L = 0
    GF = GA = 0

    over15 = over25 = over35 = btts = clean = 0

    form = []

    for m in finished:

        home_id = m["teams"]["home"]["id"]

        hg = m["goals"]["home"] or 0
        ag = m["goals"]["away"] or 0

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
# DOMICILE / EXTÉRIEUR
# ============================================================

def get_home_away_form(team_id, venue):

    fixtures = api(
        "/fixtures",
        {
            "team": team_id,
            "last": 15,
            "timezone": "Africa/Douala"
        },
        cache_seconds=600
    )

    selected = []

    for m in fixtures:

        if m["fixture"]["status"]["short"] != "FT":
            continue

        home_id = m["teams"]["home"]["id"]

        if venue == "home" and home_id == team_id:
            selected.append(m)

        elif venue == "away" and home_id != team_id:
            selected.append(m)

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

    for m in selected:

        home_id = m["teams"]["home"]["id"]

        hg = m["goals"]["home"] or 0
        ag = m["goals"]["away"] or 0

        if home_id == team_id:
            gf, ga = hg, ag
        else:
            gf, ga = ag, hg

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
# H2H
# ============================================================

def get_h2h(team1, team2):

    fixtures = api(
        "/fixtures/headtohead",
        {
            "h2h": f"{team1}-{team2}",
            "last": 10,
            "timezone": "Africa/Douala"
        },
        cache_seconds=1800
    )

    data = {
        "matches": 0,
        "w1": 0,
        "w2": 0,
        "draw": 0,
        "gf": 0,
        "ga": 0,
        "over25": 0,
        "btts": 0
    }

    for m in fixtures:

        if m["fixture"]["status"]["short"] != "FT":
            continue

        data["matches"] += 1

        home_id = m["teams"]["home"]["id"]

        hg = m["goals"]["home"] or 0
        ag = m["goals"]["away"] or 0

        if home_id == team1:
            gf, ga = hg, ag
        else:
            gf, ga = ag, hg

        data["gf"] += gf
        data["ga"] += ga

        if gf > ga:
            data["w1"] += 1
        elif gf < ga:
            data["w2"] += 1
        else:
            data["draw"] += 1

        if gf + ga >= 3:
            data["over25"] += 1

        if gf > 0 and ga > 0:
            data["btts"] += 1

    return data


# ============================================================
# ODDS
# ============================================================

def get_odds(fixture_id):

    data = api(
        "/odds",
        {
            "fixture": fixture_id
        },
        cache_seconds=120
    )

    result = {}

    for bookmaker in data:

        for bet in bookmaker.get("bookmakers", []):

            for market in bet.get("bets", []):

                name = market.get("name", "")

                for value in market.get("values", []):

                    label = value.get("value")
                    odd = safe_float(value.get("odd"))

                    if label and odd > 1:
                        result[f"{name}:{label}"] = odd

    return result


# ============================================================
# POISSON
# ============================================================

def poisson(k, lamb):

    if lamb <= 0:
        return 1.0 if k == 0 else 0.0

    return (
        math.exp(-lamb)
        * (lamb ** k)
        / math.factorial(k)
    )


def poisson_matrix(lambda_home, lambda_away, max_goals=7):

    matrix = {}

    for h in range(max_goals + 1):

        for a in range(max_goals + 1):

            p = (
                poisson(h, lambda_home)
                *
                poisson(a, lambda_away)
            )

            matrix[(h, a)] = p

    return matrix


def poisson_markets(lambda_home, lambda_away):

    matrix = poisson_matrix(
        lambda_home,
        lambda_away
    )

    home_win = 0
    draw = 0
    away_win = 0

    over15 = 0
    over25 = 0
    over35 = 0

    btts = 0

    scores = []

    for (h, a), p in matrix.items():

        if h > a:
            home_win += p
        elif h == a:
            draw += p
        else:
            away_win += p

        if h + a >= 2:
            over15 += p

        if h + a >= 3:
            over25 += p

        if h + a >= 4:
            over35 += p

        if h > 0 and a > 0:
            btts += p

        scores.append(
            (
                p,
                h,
                a
            )
        )

    scores.sort(reverse=True)

    return {
        "home": home_win * 100,
        "draw": draw * 100,
        "away": away_win * 100,
        "over15": over15 * 100,
        "over25": over25 * 100,
        "over35": over35 * 100,
        "btts": btts * 100,
        "scores": scores[:5]
    }


# ============================================================
# MOTEUR DE BUTS
# ============================================================

def calculate_expected_goals(home_form, away_form, home_venue, away_venue):

    h_attack = home_form["avg_gf"]
    h_defense = home_form["avg_ga"]

    a_attack = away_form["avg_gf"]
    a_defense = away_form["avg_ga"]

    home_strength = (
        h_attack * 0.55
        +
        home_venue["avg_gf"] * 0.45
    )

    away_strength = (
        a_attack * 0.55
        +
        away_venue["avg_gf"] * 0.45
    )

    home_def = (
        h_defense * 0.55
        +
        home_venue["avg_ga"] * 0.45
    )

    away_def = (
        a_defense * 0.55
        +
        away_venue["avg_ga"] * 0.45
    )

    lambda_home = (
        home_strength * 0.65
        +
        away_def * 0.35
    )

    lambda_away = (
        away_strength * 0.65
        +
        home_def * 0.35
    )

    return (
        clamp(lambda_home, 0.15, 4.5),
        clamp(lambda_away, 0.15, 4.5)
    )


# ============================================================
# SCORE FORME
# ============================================================

def form_score(form):

    if not form["matches"]:
        return 50

    points = (
        form["W"] * 3
        +
        form["D"]
    )

    maximum = form["matches"] * 3

    result = points / maximum * 100

    return clamp(result)


# ============================================================
# SCORE DOMICILE / EXTÉRIEUR
# ============================================================

def venue_score(data):

    if not data["matches"]:
        return 50

    points = (
        data["W"] * 3
        +
        data["D"]
    )

    return clamp(
        points / (data["matches"] * 3) * 100
    )


# ============================================================
# CONVERGENCE
# ============================================================

def convergence(values):

    if not values:
        return 0

    average = sum(values) / len(values)

    distance = sum(
        abs(x - average)
        for x in values
    ) / len(values)

    score = 100 - distance

    return clamp(score)


# ============================================================
# QUALITÉ DES DONNÉES
# ============================================================

def data_quality(*objects):

    total = 0
    valid = 0

    for obj in objects:

        total += 1

        if isinstance(obj, dict):

            matches = obj.get("matches", 0)

            if matches >= 5:
                valid += 1

    if total == 0:
        return 0

    return valid / total * 100


# ============================================================
# VALUE
# ============================================================

def implied_probability(odd):

    if not odd or odd <= 1:
        return 0

    return 100 / odd


def fair_odds(probability):

    if probability <= 0:
        return 999

    return 100 / probability


def value_score(probability, odd):

    if not odd or odd <= 1:
        return 0

    market_probability = implied_probability(odd)

    edge = probability - market_probability

    return edge


# ============================================================
# DÉTECTION DE PIÈGE
# ============================================================

def detect_trap(
    home,
    away,
    home_form,
    away_form,
    home_venue,
    away_venue,
    h2h,
    poisson
):

    traps = []

    # Favori statistique
    favorite = None

    if home_form["W"] >= 6 and home_form["W"] > away_form["W"] + 2:
        favorite = "home"

    elif away_form["W"] >= 6 and away_form["W"] > home_form["W"] + 2:
        favorite = "away"

    # Favori extérieur
    if favorite == "away":

        if (
            home_venue["W"] >= 3
            and home_venue["matches"] >= 5
        ):
            traps.append(
                "Favori extérieur face à un adversaire solide à domicile"
            )

    # H2H contraire
    if favorite == "home":

        if (
            h2h["matches"] >= 5
            and h2h["w2"] > h2h["w1"]
        ):
            traps.append(
                "H2H défavorable au favori"
            )

    if favorite == "away":

        if (
            h2h["matches"] >= 5
            and h2h["w1"] > h2h["w2"]
        ):
            traps.append(
                "H2H défavorable au favori"
            )

    # Contradiction Poisson
    if favorite == "home" and poisson["home"] < 50:
        traps.append(
            "Poisson ne confirme pas le favori"
        )

    if favorite == "away" and poisson["away"] < 50:
        traps.append(
            "Poisson ne confirme pas le favori"
        )

    return traps


# ============================================================
# ANALYSE D'UN MATCH
# ============================================================

def analyze_match(match):

    fixture_id = match["fixture"]["id"]

    home = match["teams"]["home"]
    away = match["teams"]["away"]

    hid = home["id"]
    aid = away["id"]

    logging.info(
        "Analyse : %s vs %s",
        home["name"],
        away["name"]
    )

    home_form = get_form(hid)
    time.sleep(0.2)

    away_form = get_form(aid)
    time.sleep(0.2)

    home_venue = get_home_away_form(hid, "home")
    time.sleep(0.2)

    away_venue = get_home_away_form(aid, "away")
    time.sleep(0.2)

    h2h = get_h2h(hid, aid)

    lambda_home, lambda_away = calculate_expected_goals(
        home_form,
        away_form,
        home_venue,
        away_venue
    )

    poisson = poisson_markets(
        lambda_home,
        lambda_away
    )

    odds = get_odds(fixture_id)

    # Scores
    fs_home = form_score(home_form)
    fs_away = form_score(away_form)

    vs_home = venue_score(home_venue)
    vs_away = venue_score(away_venue)

    home_power = (
        fs_home * 0.55
        +
        vs_home * 0.45
    )

    away_power = (
        fs_away * 0.55
        +
        vs_away * 0.45
    )

    # Pronostic principal
    markets = {
        "Victoire domicile": poisson["home"],
        "Match nul": poisson["draw"],
        "Victoire extérieur": poisson["away"],
        "Over 1.5": poisson["over15"],
        "Over 2.5": poisson["over25"],
        "Over 3.5": poisson["over35"],
        "BTTS Oui": poisson["btts"]
    }

    best_market = max(
        markets,
        key=markets.get
    )

    best_probability = markets[best_market]

    # Si 1X2 faible mais Over 1.5 très fort,
    # privilégier le marché de buts.
    if poisson["over15"] >= 75:
        best_market = "Over 1.5"
        best_probability = poisson["over15"]

    elif poisson["btts"] >= 68:
        best_market = "BTTS Oui"
        best_probability = poisson["btts"]

    elif poisson["over25"] >= 68:
        best_market = "Over 2.5"
        best_probability = poisson["over25"]

    # Convergence
    selected_values = [
        best_probability,
        max(
            poisson["over25"],
            poisson["btts"],
            poisson["home"],
            poisson["away"]
        )
    ]

    conv = convergence(selected_values)

    quality = data_quality(
        home_form,
        away_form,
        home_venue,
        away_venue
    )

    traps = detect_trap(
        home,
        away,
        home_form,
        away_form,
        home_venue,
        away_venue,
        h2h,
        poisson
    )

    # Risque
    risk = 100 - (
        quality * 0.45
        +
        conv * 0.35
        +
        min(best_probability, 100) * 0.20
    )

    risk += len(traps) * 10

    risk = clamp(risk)

    # Score AGENT
    score = (
        best_probability * 0.40
        +
        quality * 0.20
        +
        conv * 0.20
        +
        (100 - risk) * 0.20
    )

    score = clamp(score)

    # Value
    odd = None

    if best_market == "Victoire domicile":
        odd = odds.get("Match Winner:Home")

    elif best_market == "Victoire extérieur":
        odd = odds.get("Match Winner:Away")

    elif best_market == "Match nul":
        odd = odds.get("Match Winner:Draw")

    elif best_market == "Over 1.5":
        odd = odds.get("Goals Over/Under:Over 1.5")

    elif best_market == "Over 2.5":
        odd = odds.get("Goals Over/Under:Over 2.5")

    elif best_market == "Over 3.5":
        odd = odds.get("Goals Over/Under:Over 3.5")

    elif best_market == "BTTS Oui":
        odd = odds.get("Both Teams Score:Yes")

    value = value_score(
        best_probability,
        odd
    )

    # Décision
    if quality < 45:
        decision = "⚫ NO DATA"

    elif risk >= 65:
        decision = "🔴 PASS"

    elif score >= 75 and value >= 3:
        decision = "🟢 BET"

    elif score >= MIN_SCORE:
        decision = "🟡 WATCH"

    else:
        decision = "🔴 PASS"

    # Scores probables
    top_scores = []

    for p, h, a in poisson["scores"][:3]:

        top_scores.append(
            f"{h}-{a} ({p * 100:.1f}%)"
        )

    return {
        "fixture_id": fixture_id,
        "home": home["name"],
        "away": away["name"],
        "home_id": hid,
        "away_id": aid,
        "home_form": home_form,
        "away_form": away_form,
        "home_venue": home_venue,
        "away_venue": away_venue,
        "h2h": h2h,
        "lambda_home": lambda_home,
        "lambda_away": lambda_away,
        "poisson": poisson,
        "odds": odds,
        "market": best_market,
        "probability": best_probability,
        "odd": odd,
        "fair_odd": fair_odds(best_probability),
        "value": value,
        "quality": quality,
        "convergence": conv,
        "risk": risk,
        "score": score,
        "traps": traps,
        "decision": decision,
        "top_scores": top_scores
    }


# ============================================================
# FORMATAGE
# ============================================================

def format_analysis(a):

    p = a["poisson"]

    heure = ""

    if a.get("timestamp"):
        heure = datetime.fromtimestamp(
            a["timestamp"],
            TZ
        ).strftime("%H:%M")

    text = f"""
<b>🕯️ AGENT PRO — BOUGIE DU PARIEUR</b>

⏰ {heure}
⚽ <b>{a["home"]} vs {a["away"]}</b>

━━━━━━━━━━━━━━━━━━

<b>📊 FORME</b>

{a["home"]} :
{a["home_form"]["form"]}
{a["home_form"]["W"]}V {a["home_form"]["D"]}N {a["home_form"]["L"]}D
⚽ {a["home_form"]["avg_gf"]:.2f} marqués
🛡️ {a["home_form"]["avg_ga"]:.2f} encaissés

{a["away"]} :
{a["away_form"]["form"]}
{a["away_form"]["W"]}V {a["away_form"]["D"]}N {a["away_form"]["L"]}D
⚽ {a["away_form"]["avg_gf"]:.2f} marqués
🛡️ {a["away_form"]["avg_ga"]:.2f} encaissés

━━━━━━━━━━━━━━━━━━

<b>🏠 DOMICILE / EXTÉRIEUR</b>

{a["home"]} domicile :
{a["home_venue"]["W"]}V {a["home_venue"]["D"]}N {a["home_venue"]["L"]}D

{a["away"]} extérieur :
{a["away_venue"]["W"]}V {a["away_venue"]["D"]}N {a["away_venue"]["L"]}D

━━━━━━━━━━━━━━━━━━

<b>🧮 POISSON</b>

1️⃣ {p["home"]:.1f}%
❌ {p["draw"]:.1f}%
2️⃣ {p["away"]:.1f}%

⚽ Over 1.5 : {p["over15"]:.1f}%
⚽ Over 2.5 : {p["over25"]:.1f}%
⚽ Over 3.5 : {p["over35"]:.1f}%
🤝 BTTS : {p["btts"]:.1f}%

λ domicile : {a["lambda_home"]:.2f}
λ extérieur : {a["lambda_away"]:.2f}

<b>🎯 TOP SCORES</b>
"""

    for score in a["top_scores"]:
        text += f"• {score}\n"

    text += f"""
━━━━━━━━━━━━━━━━━━

<b>🕯️ INDICATEURS</b>

🎯 Score AGENT : <b>{a["score"]:.0f}/100</b>
⚠️ Risque : <b>{a["risk"]:.0f}/100</b>
🔗 Convergence : <b>{a["convergence"]:.0f}/100</b>
📚 Qualité données : <b>{a["quality"]:.0f}/100</b>

━━━━━━━━━━━━━━━━━━

<b>💰 VALUE</b>

🎯 Marché : <b>{a["market"]}</b>
📊 Probabilité : <b>{a["probability"]:.1f}%</b>
📐 Cote juste : <b>{a["fair_odd"]:.2f}</b>
"""

    if a["odd"]:
        text += (
            f"💵 Cote bookmaker : <b>{a['odd']:.2f}</b>\n"
            f"📈 Value : <b>{a['value']:+.1f}%</b>\n"
        )
    else:
        text += "💵 Cote bookmaker : indisponible\n"

    if a["traps"]:

        text += "\n<b>🚨 PIÈGES DÉTECTÉS</b>\n"

        for trap in a["traps"]:
            text += f"• {trap}\n"

    text += f"""
━━━━━━━━━━━━━━━━━━

<b>🤖 DÉCISION : {a["decision"]}</b>

🎯 Pronostic : <b>{a["market"]}</b>

<i>Le système mesure une probabilité et un risque.
Aucun résultat n'est garanti.</i>
"""

    return text


# ============================================================
# BOUGIE LIVE
# ============================================================

def get_live_statistics(fixture_id):

    data = api(
        "/fixtures/statistics",
        {
            "fixture": fixture_id
        },
        cache_seconds=20
    )

    return data


def get_live_events(fixture_id):

    return api(
        "/fixtures/events",
        {
            "fixture": fixture_id
        },
        cache_seconds=20
    )


def live_update(match):

    fixture = match["fixture"]
    fixture_id = fixture["id"]

    home = match["teams"]["home"]["name"]
    away = match["teams"]["away"]["name"]

    minute = fixture["status"].get("elapsed") or 0

    hg = match["goals"]["home"] or 0
    ag = match["goals"]["away"] or 0

    score = f"{hg}-{ag}"

    old = LIVE_TRACKER.get(fixture_id)

    state = {
        "minute": minute,
        "home_goals": hg,
        "away_goals": ag,
        "score": score
    }

    LIVE_TRACKER[fixture_id] = state

    # Première apparition
    if old is None:
        telegram(
            f"""
<b>🔴 MATCH LIVE</b>

⚽ <b>{home} vs {away}</b>

⏱️ {minute}'
📊 Score : <b>{score}</b>

🕯️ Le moteur LIVE commence le suivi.
"""
        )
        return

    # But détecté
    if (
        old["home_goals"] != hg
        or old["away_goals"] != ag
    ):

        telegram(
            f"""
<b>⚡ BUT — LIVE</b>

⚽ <b>{home} {hg} - {ag} {away}</b>

⏱️ {minute}'

🕯️ Le marché doit être réévalué.
"""
        )

    # Toutes les 10 minutes
    if minute > 0 and minute % 10 == 0:

        telegram(
            f"""
<b>📡 UPDATE LIVE</b>

⚽ {home} <b>{hg}-{ag}</b> {away}

⏱️ {minute}'

🕯️ BOUGIE LIVE

Situation actuelle :
<b>{home} {hg}-{ag} {away}</b>

Le moteur surveille l'évolution du scénario.
"""
        )


# ============================================================
# ANALYSE AVANT MATCH
# ============================================================

def run_pre_match():

    fixtures = get_upcoming()

    if not fixtures:
        logging.info("Aucun match à venir.")
        return

    # On ne prend pas seulement les premiers :
    # on analyse puis on sélectionne les meilleurs.
    candidates = fixtures[:MAX_MATCHES]

    results = []

    for match in candidates:

        try:

            analysis = analyze_match(match)

            analysis["timestamp"] = match["fixture"]["timestamp"]

            results.append(analysis)

        except Exception as e:

            logging.error(
                "Analyse impossible : %s",
                e
            )

    if not results:
        return

    # Classement
    results.sort(
        key=lambda x: (
            x["decision"] == "🟢 BET",
            x["score"],
            x["value"]
        ),
        reverse=True
    )

    # TOP opportunités
    top = results[:5]

    header = f"""
<b>🕯️ AGENT PRO FOOTBALL V2</b>
<b>LA BOUGIE DU PARIEUR</b>

📅 {now().strftime("%d/%m/%Y")}
⏰ {now().strftime("%H:%M")} — Cameroun

━━━━━━━━━━━━━━━━━━

<b>🎯 TOP OPPORTUNITÉS</b>
"""

    for i, a in enumerate(top, 1):

        header += f"""
<b>{i}. {a["home"]} vs {a["away"]}</b>
🎯 {a["market"]}
📊 {a["probability"]:.1f}%
🕯️ Score {a["score"]:.0f}/100
⚠️ Risque {a["risk"]:.0f}/100
💰 Value {a["value"]:+.1f}%
👉 {a["decision"]}

"""

    header += """
━━━━━━━━━━━━━━━━━━
<b>🚨 RÈGLE DU SYSTÈME</b>

Le bot ne cherche pas le plus grand nombre de paris.

Il cherche les situations où :
<b>PROBABILITÉ + VALUE + CONVERGENCE</b>
dépassent le risque.

🟢 BET
🟡 WATCH
🔴 PASS
⚫ NO DATA
"""

    telegram(header)

    # Envoyer les analyses détaillées uniquement
    # des meilleurs signaux.
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
# SURVEILLANCE LIVE
# ============================================================

def run_live():

    matches = get_live()

    if not matches:
        return

    for match in matches:

        try:

            status = match["fixture"]["status"]["short"]

            if status in [
                "1H",
                "HT",
                "2H",
                "ET"
            ]:

                live_update(match)

        except Exception as e:

            logging.error(
                "Erreur LIVE : %s",
                e
            )


# ============================================================
# COMMANDES TELEGRAM
# ============================================================

def telegram_get_updates(offset=None):

    if not TG_TOKEN:
        return []

    try:

        params = {
            "timeout": 5
        }

        if offset:
            params["offset"] = offset

        r = requests.get(
            f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
            params=params,
            timeout=10
        )

        return r.json().get(
            "result",
            []
        )

    except:
        return []


def process_commands():

    offset = None

    while True:

        updates = telegram_get_updates(offset)

        for update in updates:

            offset = update["update_id"] + 1

            message = update.get("message", {})

            text = message.get("text", "").lower().strip()

            if text == "/start":

                telegram(
                    """
<b>🕯️ AGENT PRO FOOTBALL V2</b>

La Bougie du Parieur est active.

Commandes :

/analyse — analyse les prochains matchs
/live — état du moteur LIVE
/status — état du système
"""
                )

            elif text == "/analyse":

                run_pre_match()

            elif text == "/live":

                run_live()

            elif text == "/status":

                telegram(
                    f"""
<b>🟢 AGENT PRO ACTIF</b>

⏰ {now().strftime("%H:%M:%S")}

📡 API : {'OK' if API_KEY else 'ABSENTE'}
📱 Telegram : {'OK' if TG_TOKEN else 'ABSENT'}

🔴 Matchs LIVE suivis :
{len(LIVE_TRACKER)}
"""
                )

        time.sleep(1)


# ============================================================
# BOUCLE PRINCIPALE
# ============================================================

def main():

    if not API_KEY:

        logging.error(
            "API_FOOTBALL_KEY manquante."
        )
        return

    if not TG_TOKEN or not TG_CHAT:

        logging.error(
            "TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID manquant."
        )
        return

    telegram(
        f"""
<b>🕯️ AGENT PRO FOOTBALL V2</b>

<b>LA BOUGIE DU PARIEUR</b>

🟢 Système démarré

📡 Données : OK
🧮 Poisson : OK
🚨 Risk Engine : OK
💰 Value Engine : OK
🔴 Live Engine : OK
📱 Telegram : OK

⏰ {now().strftime("%d/%m/%Y %H:%M:%S")}

<i>Analyse → Probabilité → Value → Risque → Décision</i>
"""
    )

    last_analysis = 0
    last_live = 0

    while True:

        current = time.time()

        # Analyse pré-match
        if current - last_analysis >= ANALYSIS_INTERVAL:

            try:
                run_pre_match()
            except Exception as e:
                logging.exception(
                    "Erreur pré-match : %s",
                    e
                )

            last_analysis = current

        # Live
        if current - last_live >= LIVE_INTERVAL:

            try:
                run_live()
            except Exception as e:
                logging.exception(
                    "Erreur LIVE : %s",
                    e
                )

            last_live = current

        time.sleep(2)


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":

    main()
