# ============================================================
# ARGENT FOURMI V5
# MOTEUR EDGE FOOTBALL
# ============================================================
#
# Architecture :
#
# DONNEES
#    ↓
# FORM / DOMICILE / H2H / POISSON / ODDS
#    ↓
# PROBABILITE MODELE
#    ↓
# PROBABILITE MARCHE
#    ↓
# EDGE
#    ↓
# FILTRES DE QUALITE
#    ↓
# BET / SURVEILLANCE / NO BET
#    ↓
# SQLITE
#    ↓
# EVALUATION DES RESULTATS
#
# Variables d'environnement :
#
# API_FOOTBALL_KEY
# TELEGRAM_TOKEN
# TELEGRAM_CHAT_ID
#
# ============================================================

import os
import time
import math
import sqlite3
import threading
import requests

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


# ============================================================
# CONFIG
# ============================================================

API_KEY = os.getenv("API_FOOTBALL_KEY")
TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID")

API_URL = "https://v3.football.api-sports.io"

TZ = ZoneInfo("Africa/Douala")

DB_FILE = "argent_fourmi_v5.db"

ANALYSIS_EVERY = 2 * 60 * 60

# Surveillance LIVE
LIVE_EVERY = 3 * 60

# Nombre maximum de matchs analysés par cycle
MAX_MATCHES = 10

# Derniers matchs utilisés
FORM_MATCHES = 10
H2H_MATCHES = 8

# Edge minimum
MIN_EDGE = 0.05

# Edge fort
STRONG_EDGE = 0.08

# Probabilité minimum
MIN_MODEL_PROB = 0.55

# ============================================================
# SESSION HTTP
# ============================================================

session = requests.Session()

session.headers.update({
    "x-apisports-key": API_KEY or ""
})


# ============================================================
# TELEGRAM
# ============================================================

def telegram(text):

    if not TG_TOKEN or not TG_CHAT:
        print(text)
        return

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{TG_TOKEN}/sendMessage"
        )

        r = requests.post(
            url,
            data={
                "chat_id": TG_CHAT,
                "text": text,
                "parse_mode": "Markdown"
            },
            timeout=30
        )

        if r.status_code != 200:
            print("Telegram error:", r.text)

    except Exception as e:

        print("Telegram exception:", e)


# ============================================================
# API FOOTBALL
# ============================================================

def api(endpoint, params=None):

    try:

        r = session.get(
            f"{API_URL}/{endpoint}",
            params=params,
            timeout=30
        )

        if r.status_code != 200:

            print(
                "API HTTP ERROR",
                r.status_code,
                r.text[:300]
            )

            return []

        data = r.json()

        if data.get("errors"):

            print(
                "API ERROR:",
                data["errors"]
            )

            return []

        return data.get("response", [])

    except Exception as e:

        print("API exception:", e)

        return []


# ============================================================
# SQLITE
# ============================================================

def db():

    return sqlite3.connect(
        DB_FILE,
        check_same_thread=False
    )


def init_db():

    conn = db()

    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS predictions (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            fixture_id INTEGER,

            date TEXT,

            league TEXT,

            home TEXT,

            away TEXT,

            market TEXT,

            selection TEXT,

            model_probability REAL,

            market_probability REAL,

            edge REAL,

            odds REAL,

            confidence REAL,

            edge_score REAL,

            status TEXT DEFAULT 'PENDING',

            result TEXT,

            profit REAL DEFAULT 0

        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bankroll (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            date TEXT,

            bankroll REAL,

            stake REAL,

            profit REAL

        )
    """)

    conn.commit()

    conn.close()


# ============================================================
# UTILITAIRES
# ============================================================

def safe_div(a, b):

    return a / b if b else 0


def clamp(value, minimum, maximum):

    return max(minimum, min(value, maximum))


def pct(value):

    return f"{value * 100:.1f}%"


def poisson_probability(lmbda, goals):

    try:

        return (
            math.exp(-lmbda)
            * lmbda ** goals
            / math.factorial(goals)
        )

    except Exception:

        return 0


# ============================================================
# FORM
# ============================================================

def get_form(team_id):

    fixtures = api(
        "fixtures",
        {
            "team": team_id,
            "last": FORM_MATCHES,
            "timezone": "Africa/Douala"
        }
    )

    W = D = L = 0

    GF = GA = 0

    home_W = home_D = home_L = 0

    away_W = away_D = away_L = 0

    over15 = 0
    over25 = 0
    btts = 0

    valid = 0

    for m in fixtures:

        if m["fixture"]["status"]["short"] != "FT":
            continue

        hg = m["goals"]["home"]
        ag = m["goals"]["away"]

        if hg is None or ag is None:
            continue

        home_id = m["teams"]["home"]["id"]

        valid += 1

        if home_id == team_id:

            scored = hg
            conceded = ag

            if hg > ag:
                W += 1
                home_W += 1

            elif hg == ag:
                D += 1
                home_D += 1

            else:
                L += 1
                home_L += 1

        else:

            scored = ag
            conceded = hg

            if ag > hg:
                W += 1
                away_W += 1

            elif ag == hg:
                D += 1
                away_D += 1

            else:
                L += 1
                away_L += 1

        GF += scored
        GA += conceded

        if hg + ag >= 2:
            over15 += 1

        if hg + ag >= 3:
            over25 += 1

        if hg >= 1 and ag >= 1:
            btts += 1

    return {

        "W": W,
        "D": D,
        "L": L,

        "GF": GF,
        "GA": GA,

        "AVG_GF": safe_div(GF, valid),
        "AVG_GA": safe_div(GA, valid),

        "OVER15": safe_div(over15, valid),
        "OVER25": safe_div(over25, valid),
        "BTTS": safe_div(btts, valid),

        "HOME_W": home_W,
        "HOME_D": home_D,
        "HOME_L": home_L,

        "AWAY_W": away_W,
        "AWAY_D": away_D,
        "AWAY_L": away_L,

        "VALID": valid,

        "FORM":
            f"{W}V-{D}N-{L}D"
    }


# ============================================================
# H2H
# ============================================================

def get_h2h(home_id, away_id):

    fixtures = api(
        "fixtures/headtohead",
        {
            "h2h":
                f"{home_id}-{away_id}",

            "last":
                H2H_MATCHES,

            "timezone":
                "Africa/Douala"
        }
    )

    W1 = W2 = D = 0

    GF1 = GF2 = 0

    valid = 0

    for m in fixtures:

        if m["fixture"]["status"]["short"] != "FT":
            continue

        hg = m["goals"]["home"]
        ag = m["goals"]["away"]

        if hg is None or ag is None:
            continue

        valid += 1

        if m["teams"]["home"]["id"] == home_id:

            GF1 += hg
            GF2 += ag

            if hg > ag:
                W1 += 1

            elif hg < ag:
                W2 += 1

            else:
                D += 1

        else:

            GF1 += ag
            GF2 += hg

            if ag > hg:
                W1 += 1

            elif ag < hg:
                W2 += 1

            else:
                D += 1

    return {

        "W1": W1,
        "W2": W2,
        "D": D,

        "GF1": GF1,
        "GF2": GF2,

        "VALID": valid
    }


# ============================================================
# POISSON
# ============================================================

def poisson_match(home_lambda, away_lambda):

    home = 0
    draw = 0
    away = 0

    over15 = 0
    over25 = 0

    btts = 0

    score_matrix = []

    for hg in range(0, 8):

        for ag in range(0, 8):

            p1 = poisson_probability(
                home_lambda,
                hg
            )

            p2 = poisson_probability(
                away_lambda,
                ag
            )

            p = p1 * p2

            score_matrix.append(
                (hg, ag, p)
            )

            if hg > ag:
                home += p

            elif hg == ag:
                draw += p

            else:
                away += p

            if hg + ag >= 2:
                over15 += p

            if hg + ag >= 3:
                over25 += p

            if hg >= 1 and ag >= 1:
                btts += p

    score_matrix.sort(
        key=lambda x: x[2],
        reverse=True
    )

    return {

        "HOME": home,
        "DRAW": draw,
        "AWAY": away,

        "OVER15": over15,
        "OVER25": over25,

        "BTTS": btts,

        "SCORES":
            score_matrix[:5]
    }


# ============================================================
# CALCUL LAMBDA
# ============================================================

def calculate_lambdas(home, away):

    # Attaque / défense
    home_attack = home["AVG_GF"]
    away_attack = away["AVG_GF"]

    home_defence = home["AVG_GA"]
    away_defence = away["AVG_GA"]

    # Modèle de base
    home_lambda = (
        home_attack * 0.55
        +
        away_defence * 0.45
    )

    away_lambda = (
        away_attack * 0.55
        +
        home_defence * 0.45
    )

    # Petit bonus domicile
    home_lambda *= 1.05

    home_lambda = clamp(
        home_lambda,
        0.20,
        4.00
    )

    away_lambda = clamp(
        away_lambda,
        0.20,
        4.00
    )

    return home_lambda, away_lambda


# ============================================================
# ODDS
# ============================================================

def get_odds(fixture_id):

    data = api(
        "odds",
        {
            "fixture": fixture_id
        }
    )

    if not data:
        return {}

    result = {}

    try:

        bookmakers = data[0]["bookmakers"]

        for bookmaker in bookmakers:

            bets = bookmaker["bets"]

            for bet in bets:

                name = bet["name"]

                for value in bet["values"]:

                    label = value["value"]

                    odd = value.get("odd")

                    try:
                        odd = float(odd)
                    except:
                        continue

                    if name == "Match Winner":

                        if label == "Home":
                            result["1"] = odd

                        elif label == "Draw":
                            result["N"] = odd

                        elif label == "Away":
                            result["2"] = odd

                    elif name == "Goals Over/Under":

                        if label in [
                            "Over 1.5",
                            "Over 2.5"
                        ]:

                            result[
                                label.replace(" ", "_")
                            ] = odd

                    elif name == "Both Teams Score":

                        if label == "Yes":
                            result["BTTS_YES"] = odd

    except Exception as e:

        print("Odds parsing:", e)

    return result


# ============================================================
# PROBABILITE DU MARCHE
# ============================================================

def implied_probability(odd):

    if not odd or odd <= 1:
        return 0

    return 1 / odd


# ============================================================
# EDGE
# ============================================================

def calculate_edge(model_probability, odd):

    market_probability = implied_probability(odd)

    edge = (
        model_probability
        -
        market_probability
    )

    return market_probability, edge


# ============================================================
# EDGE SCORE
# ============================================================

def calculate_edge_score(

    edge,
    probability,
    data_quality,
    agreement,
    volatility=0

):

    score = 0

    # Edge
    if edge >= 0.15:
        score += 40

    elif edge >= 0.10:
        score += 32

    elif edge >= 0.08:
        score += 25

    elif edge >= 0.05:
        score += 18

    elif edge >= 0.03:
        score += 8

    # Probabilité
    if probability >= 0.70:
        score += 20

    elif probability >= 0.60:
        score += 15

    elif probability >= 0.55:
        score += 10

    # Qualité données
    score += data_quality * 20

    # Accord modèles
    score += agreement * 15

    # Volatilité
    score -= volatility * 10

    return clamp(
        score,
        0,
        100
    )


# ============================================================
# QUALITE DES DONNEES
# ============================================================

def data_quality(home, away, h2h):

    score = 0

    if home["VALID"] >= 8:
        score += 0.35

    elif home["VALID"] >= 5:
        score += 0.20

    if away["VALID"] >= 8:
        score += 0.35

    elif away["VALID"] >= 5:
        score += 0.20

    if h2h["VALID"] >= 5:
        score += 0.20

    if home["AVG_GF"] > 0 and away["AVG_GF"] > 0:
        score += 0.10

    return clamp(
        score,
        0,
        1
    )


# ============================================================
# SELECTION DES MARCHES
# ============================================================

def build_markets(poisson, odds):

    markets = []

    definitions = [

        (
            "1X2",
            "1",
            "Victoire domicile",
            poisson["HOME"]
        ),

        (
            "1X2",
            "N",
            "Match nul",
            poisson["DRAW"]
        ),

        (
            "1X2",
            "2",
            "Victoire extérieur",
            poisson["AWAY"]
        ),

        (
            "TOTAL",
            "Over 1.5",
            "Over 1.5",
            poisson["OVER15"]
        ),

        (
            "TOTAL",
            "Over 2.5",
            "Over 2.5",
            poisson["OVER25"]
        ),

        (
            "BTTS",
            "BTTS Yes",
            "BTTS Oui",
            poisson["BTTS"]
        )
    ]

    odds_keys = {

        "1": "1",
        "N": "N",
        "2": "2",

        "Over 1.5":
            "Over_1.5",

        "Over 2.5":
            "Over_2.5",

        "BTTS Yes":
            "BTTS_YES"
    }

    for market, selection, name, probability in definitions:

        key = odds_keys.get(selection)

        odd = odds.get(key)

        if not odd:
            continue

        market_probability, edge = calculate_edge(
            probability,
            odd
        )

        markets.append({

            "market": market,

            "selection": selection,

            "name": name,

            "probability":
                probability,

            "market_probability":
                market_probability,

            "edge":
                edge,

            "odds":
                odd
        })

    return markets


# ============================================================
# ANALYSE COMPLETE
# ============================================================

def analyze_match(match):

    fixture_id = match["fixture"]["id"]

    home = match["teams"]["home"]

    away = match["teams"]["away"]

    print(
        f"Analyse {home['name']} vs {away['name']}"
    )

    form_home = get_form(
        home["id"]
    )

    time.sleep(0.5)

    form_away = get_form(
        away["id"]
    )

    time.sleep(0.5)

    h2h = get_h2h(
        home["id"],
        away["id"]
    )

    time.sleep(0.5)

    odds = get_odds(
        fixture_id
    )

    if not odds:

        return {
            "status": "NO_ODDS"
        }

    # --------------------------------------------------------
    # POISSON
    # --------------------------------------------------------

    home_lambda, away_lambda = calculate_lambdas(
        form_home,
        form_away
    )

    poisson = poisson_match(
        home_lambda,
        away_lambda
    )

    # --------------------------------------------------------
    # QUALITE
    # --------------------------------------------------------

    quality = data_quality(
        form_home,
        form_away,
        h2h
    )

    # --------------------------------------------------------
    # ACCORD MODELES
    # --------------------------------------------------------

    model_votes = []

    if form_home["W"] > form_away["W"]:
        model_votes.append("1")

    elif form_away["W"] > form_home["W"]:
        model_votes.append("2")

    else:
        model_votes.append("N")

    poisson_result = max(
        [
            ("1", poisson["HOME"]),
            ("N", poisson["DRAW"]),
            ("2", poisson["AWAY"])
        ],
        key=lambda x: x[1]
    )[0]

    model_votes.append(
        poisson_result
    )

    agreement = (
        1
        if model_votes[0] == model_votes[1]
        else 0.3
    )

    # --------------------------------------------------------
    # MARCHES
    # --------------------------------------------------------

    markets = build_markets(
        poisson,
        odds
    )

    if not markets:

        return {
            "status": "NO_MARKET"
        }

    # --------------------------------------------------------
    # SCORE EDGE
    # --------------------------------------------------------

    for m in markets:

        m["edge_score"] = calculate_edge_score(

            m["edge"],

            m["probability"],

            quality,

            agreement

        )

    markets.sort(
        key=lambda x: (
            x["edge_score"],
            x["edge"]
        ),
        reverse=True
    )

    best = markets[0]

    # --------------------------------------------------------
    # DECISION
    # --------------------------------------------------------

    if (
        best["edge"] >= STRONG_EDGE
        and
        best["probability"] >= MIN_MODEL_PROB
        and
        best["edge_score"] >= 60
    ):

        decision = "BET"

    elif (
        best["edge"] >= MIN_EDGE
        and
        best["probability"] >= MIN_MODEL_PROB
    ):

        decision = "SURVEILLANCE"

    else:

        decision = "NO BET"

    # --------------------------------------------------------
    # SCORE PROBABLE
    # --------------------------------------------------------

    probable_score = poisson["SCORES"][0]

    return {

        "status": "OK",

        "fixture_id":
            fixture_id,

        "league":
            match["league"]["name"],

        "home":
            home["name"],

        "away":
            away["name"],

        "time":
            datetime.fromtimestamp(
                match["fixture"]["timestamp"],
                tz=TZ
            ).strftime("%H:%M"),

        "form_home":
            form_home,

        "form_away":
            form_away,

        "h2h":
            h2h,

        "odds":
            odds,

        "poisson":
            poisson,

        "lambda_home":
            home_lambda,

        "lambda_away":
            away_lambda,

        "quality":
            quality,

        "agreement":
            agreement,

        "markets":
            markets,

        "best":
            best,

        "decision":
            decision,

        "score":
            probable_score
    }


# ============================================================
# SAUVEGARDE PREDICTION
# ============================================================

def save_prediction(result):

    if result["status"] != "OK":
        return

    best = result["best"]

    conn = db()

    cur = conn.cursor()

    cur.execute("""
        SELECT id
        FROM predictions
        WHERE fixture_id = ?
        AND market = ?
        AND selection = ?
    """, (
        result["fixture_id"],
        best["market"],
        best["selection"]
    ))

    existing = cur.fetchone()

    if not existing:

        cur.execute("""
            INSERT INTO predictions (

                fixture_id,
                date,
                league,
                home,
                away,
                market,
                selection,
                model_probability,
                market_probability,
                edge,
                odds,
                confidence,
                edge_score

            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (

            result["fixture_id"],

            datetime.now(TZ).isoformat(),

            result["league"],

            result["home"],

            result["away"],

            best["market"],

            best["selection"],

            best["probability"],

            best["market_probability"],

            best["edge"],

            best["odds"],

            best["probability"],

            best["edge_score"]

        ))

        conn.commit()

    conn.close()


# ============================================================
# MESSAGE MATCH
# ============================================================

def format_result(r):

    best = r["best"]

    p = r["poisson"]

    fh = r["form_home"]
    fa = r["form_away"]

    score = r["score"]

    if r["decision"] == "BET":
        icon = "🟢"

    elif r["decision"] == "SURVEILLANCE":
        icon = "🟡"

    else:
        icon = "🔴"

    text = (

        f"{icon} *ARGENT FOURMI V5*\n\n"

        f"⚽ *{r['home']} vs {r['away']}*\n"
        f"🏆 {r['league']}\n"
        f"⏰ {r['time']}\n\n"

        f"━━━━━━━━━━━━━━━━━━\n"

        f"📊 *FORME*\n"
        f"{r['home']} : {fh['FORM']}\n"
        f"{r['away']} : {fa['FORM']}\n\n"

        f"🧮 *POISSON*\n"
        f"1 : {pct(p['HOME'])}\n"
        f"N : {pct(p['DRAW'])}\n"
        f"2 : {pct(p['AWAY'])}\n"
        f"Over 1.5 : {pct(p['OVER15'])}\n"
        f"Over 2.5 : {pct(p['OVER25'])}\n"
        f"BTTS : {pct(p['BTTS'])}\n\n"

        f"🎯 *SCORE MODÈLE*\n"
        f"{score[0]} - {score[1]}\n\n"

        f"━━━━━━━━━━━━━━━━━━\n"

        f"💰 *MEILLEUR EDGE*\n"
        f"👉 {best['name']}\n"
        f"📈 Cote : *{best['odds']:.2f}*\n"
        f"🤖 Modèle : *{pct(best['probability'])}*\n"
        f"📉 Marché : *{pct(best['market_probability'])}*\n"
        f"🔥 EDGE : *{best['edge']*100:+.1f} points*\n"
        f"⭐ EDGE SCORE : *{best['edge_score']:.0f}/100*\n\n"

        f"🧠 Qualité données : "
        f"{r['quality']*100:.0f}%\n"

        f"🤝 Accord modèles : "
        f"{r['agreement']*100:.0f}%\n\n"

        f"━━━━━━━━━━━━━━━━━━\n"

        f"🚦 *DÉCISION : {r['decision']}*\n\n"

    )

    if r["decision"] == "BET":

        text += (
            "🟢 *SPOT À AVANTAGE THÉORIQUE*\n"
            "Le modèle estime une probabilité "
            "supérieure à celle implicite de la cote.\n"
        )

    elif r["decision"] == "SURVEILLANCE":

        text += (
            "🟡 *SURVEILLANCE*\n"
            "Un signal existe mais il n'est "
            "pas suffisamment fort pour déclencher "
            "une sélection V5.\n"
        )

    else:

        text += (
            "🔴 *NO BET*\n"
            "Le modèle ne détecte pas "
            "d'avantage suffisamment intéressant.\n"
        )

    return text


# ============================================================
# MATCHS DU JOUR
# ============================================================

def get_upcoming():

    now = datetime.now(TZ)

    tomorrow = now + timedelta(days=1)

    fixtures = api(
        "fixtures",
        {
            "from":
                now.strftime("%Y-%m-%d"),

            "to":
                tomorrow.strftime("%Y-%m-%d"),

            "timezone":
                "Africa/Douala"
        }
    )

    upcoming = []

    for m in fixtures:

        status = m["fixture"]["status"]["short"]

        if status not in [
            "NS",
            "TBD"
        ]:
            continue

        timestamp = m["fixture"]["timestamp"]

        if timestamp <= time.time():
            continue

        upcoming.append(m)

    upcoming.sort(
        key=lambda x:
            x["fixture"]["timestamp"]
    )

    return upcoming[:MAX_MATCHES]


# ============================================================
# ANALYSE AUTOMATIQUE
# ============================================================

def run_analysis():

    now = datetime.now(TZ)

    print(
        "\n================================"
    )

    print(
        "ARGENT FOURMI V5",
        now.strftime(
            "%d/%m/%Y %H:%M"
        )
    )

    print(
        "================================"
    )

    matches = get_upcoming()

    telegram(
        f"🐜 *ARGENT FOURMI V5*\n\n"
        f"🕒 {now.strftime('%d/%m/%Y %H:%M')}\n"
        f"🔎 Recherche d'EDGE...\n"
        f"⚽ {len(matches)} matchs candidats"
    )

    bets = 0
    surveillance = 0

    for match in matches:

        try:

            result = analyze_match(match)

            if result["status"] != "OK":

                print(
                    "Match ignoré:",
                    result["status"]
                )

                continue

            save_prediction(
                result
            )

            if result["decision"] == "BET":

                bets += 1

                telegram(
                    format_result(
                        result
                    )
                )

            elif result["decision"] == "SURVEILLANCE":

                surveillance += 1

                # On peut également notifier
                telegram(
                    format_result(
                        result
                    )
                )

            time.sleep(1)

        except Exception as e:

            print(
                "Analyse match ERROR:",
                e
            )

    telegram(
        "━━━━━━━━━━━━━━━━━━\n"
        f"🐜 *FIN DU SCAN V5*\n\n"
        f"🟢 Spots EDGE : {bets}\n"
        f"🟡 Surveillance : {surveillance}\n\n"
        "Le système privilégie "
        "*NO BET* lorsqu'aucun avantage "
        "suffisant n'est détecté."
    )


# ============================================================
# RESULTAT REEL
# ============================================================

def evaluate_predictions():

    conn = db()

    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            fixture_id,
            selection,
            odds
        FROM predictions
        WHERE status = 'PENDING'
    """)

    rows = cur.fetchall()

    for row in rows:

        pid = row[0]
        fixture_id = row[1]
        selection = row[2]
        odd = row[3]

        fixtures = api(
            "fixtures",
            {
                "id":
                    fixture_id
            }
        )

        if not fixtures:
            continue

        m = fixtures[0]

        status = m["fixture"]["status"]["short"]

        if status not in [
            "FT",
            "AET",
            "PEN"
        ]:

            continue

        hg = m["goals"]["home"]
        ag = m["goals"]["away"]

        if hg is None or ag is None:
            continue

        won = False

        if selection == "1":

            won = hg > ag

        elif selection == "2":

            won = ag > hg

        elif selection == "N":

            won = hg == ag

        elif selection == "Over 1.5":

            won = hg + ag >= 2

        elif selection == "Over 2.5":

            won = hg + ag >= 3

        elif selection == "BTTS Yes":

            won = (
                hg >= 1
                and
                ag >= 1
            )

        if won:

            profit = odd - 1

            result = "WIN"

        else:

            profit = -1

            result = "LOSS"

        cur.execute("""
            UPDATE predictions

            SET
                status = 'SETTLED',
                result = ?,
                profit = ?

            WHERE id = ?
        """, (
            result,
            profit,
            pid
        ))

    conn.commit()

    conn.close()


# ============================================================
# STATISTIQUES HISTORIQUES
# ============================================================

def get_statistics():

    conn = db()

    cur = conn.cursor()

    cur.execute("""
        SELECT
            COUNT(*),
            SUM(
                CASE
                    WHEN result='WIN'
                    THEN 1
                    ELSE 0
                END
            ),
            SUM(profit)
        FROM predictions
        WHERE status='SETTLED'
    """)

    total, wins, profit = cur.fetchone()

    total = total or 0
    wins = wins or 0
    profit = profit or 0

    winrate = safe_div(
        wins,
        total
    )

    roi = safe_div(
        profit,
        total
    )

    cur.execute("""
        SELECT
            market,
            COUNT(*),
            SUM(
                CASE
                    WHEN result='WIN'
                    THEN 1
                    ELSE 0
                END
            ),
            SUM(profit)

        FROM predictions

        WHERE status='SETTLED'

        GROUP BY market
    """)

    markets = cur.fetchall()

    conn.close()

    return {
        "total": total,
        "wins": wins,
        "profit": profit,
        "winrate": winrate,
        "roi": roi,
        "markets": markets
    }


# ============================================================
# RAPPORT PERFORMANCE
# ============================================================

def send_statistics():

    stats = get_statistics()

    if stats["total"] == 0:

        telegram(
            "📊 *ARGENT FOURMI V5*\n\n"
            "Pas encore assez de "
            "pronostics clôturés."
        )

        return

    text = (

        "📊 *ARGENT FOURMI V5 — PERFORMANCE*\n\n"

        f"🎯 Pronostics : {stats['total']}\n"
        f"✅ Victoires : {stats['wins']}\n"
        f"📈 Winrate : "
        f"{stats['winrate']*100:.1f}%\n"
        f"💰 Profit théorique : "
        f"{stats['profit']:+.2f} unité\n"
        f"📊 ROI : "
        f"{stats['roi']*100:+.2f}%\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "*PAR MARCHÉ*\n"
    )

    for market in stats["markets"]:

        name = market[0]
        total = market[1]
        wins = market[2]
        profit = market[3] or 0

        wr = safe_div(
            wins,
            total
        )

        text += (
            f"\n{ name }\n"
            f"• N : {total}\n"
            f"• Winrate : {wr*100:.1f}%\n"
            f"• Profit : {profit:+.2f}\n"
        )

    telegram(text)


# ============================================================
# SURVEILLANCE LIVE
# ============================================================

def get_live():

    return api(
        "fixtures",
        {
            "live": "all"
        }
    )


def live_probability(home_goals, away_goals, minute):

    # Modèle simplifié LIVE.
    #
    # Il ne remplace pas un véritable modèle
    # événementiel alimenté par tirs/corners/cartons.
    #
    # On ajuste la production de buts attendue
    # en fonction du temps restant.

    remaining = max(
        0,
        90 - minute
    )

    time_factor = remaining / 90

    total_goals = (
        home_goals
        +
        away_goals
    )

    # Probabilité indicative d'Over 1.5
    if total_goals >= 2:

        over15 = 0.99

    else:

        expected_remaining = (
            2.2 * time_factor
        )

        over15 = (
            1
            -
            math.exp(
                -expected_remaining
            )
        )

    return clamp(
        over15,
        0,
        0.99
    )


def live_monitor():

    notified = set()

    while True:

        try:

            matches = get_live()

            for m in matches:

                fixture_id = m["fixture"]["id"]

                status = m["fixture"]["status"]["short"]

                if status not in [
                    "1H",
                    "HT",
                    "2H",
                    "ET"
                ]:

                    continue

                minute = (
                    m["fixture"]["status"]
                    .get("elapsed")
                    or 0
                )

                hg = (
                    m["goals"]["home"]
                    or 0
                )

                ag = (
                    m["goals"]["away"]
                    or 0
                )

                probability = live_probability(
                    hg,
                    ag,
                    minute
                )

                odds = get_odds(
                    fixture_id
                )

                odd = odds.get(
                    "Over_1.5"
                )

                if not odd:
                    continue

                market_probability = (
                    implied_probability(
                        odd
                    )
                )

                edge = (
                    probability
                    -
                    market_probability
                )

                # Alerte uniquement sur gros edge
                if edge >= 0.10:

                    alert_key = (
                        fixture_id,
                        minute // 5
                    )

                    if alert_key in notified:
                        continue

                    notified.add(
                        alert_key
                    )

                    home = m["teams"]["home"]["name"]
                    away = m["teams"]["away"]["name"]

                    telegram(

                        "🔴 *ALERTE LIVE V5*\n\n"

                        f"⚽ {home} "
                        f"{hg}-{ag} "
                        f"{away}\n"

                        f"⏱ {minute}'\n\n"

                        f"🎯 Marché : "
                        f"*Over 1.5*\n"

                        f"🤖 Modèle LIVE : "
                        f"*{probability*100:.1f}%*\n"

                        f"📉 Marché : "
                        f"*{market_probability*100:.1f}%*\n"

                        f"🔥 EDGE LIVE : "
                        f"*{edge*100:+.1f} points*\n\n"

                        "⚠️ Signal mathématique à "
                        "vérifier, pas une garantie."
                    )

            time.sleep(
                LIVE_EVERY
            )

        except Exception as e:

            print(
                "LIVE ERROR:",
                e
            )

            time.sleep(
                LIVE_EVERY
            )


# ============================================================
# BOUCLE PRINCIPALE
# ============================================================

def main():

    print(
        """
╔════════════════════════════════════╗
║        ARGENT FOURMI V5            ║
║        MOTEUR EDGE FOOTBALL        ║
╠════════════════════════════════════╣
║ Analyse : toutes les 2 heures      ║
║ Live    : toutes les 3 minutes     ║
║ Modèle  : Poisson + Forme + Marché ║
║ Décision: BET / SURVEILLANCE / NO  ║
╚════════════════════════════════════╝
"""
    )

    if not API_KEY:

        print(
            "❌ API_FOOTBALL_KEY manquante"
        )

        return

    if not TG_TOKEN:

        print(
            "❌ TELEGRAM_TOKEN manquante"
        )

        return

    if not TG_CHAT:

        print(
            "❌ TELEGRAM_CHAT_ID manquante"
        )

        return

    init_db()

    # Thread LIVE
    live_thread = threading.Thread(
        target=live_monitor,
        daemon=True
    )

    live_thread.start()

    # Analyse initiale
    while True:

        try:

            evaluate_predictions()

            run_analysis()

            send_statistics()

        except Exception as e:

            print(
                "MAIN ERROR:",
                e
            )

            telegram(
                "⚠️ *ARGENT FOURMI V5*\n\n"
                "Erreur technique détectée."
            )

        print(
            "\nProchaine analyse dans 2 heures."
        )

        time.sleep(
            ANALYSIS_EVERY
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
