import os, requests
from datetime import datetime
import pytz
from math import exp, factorial
from collections import defaultdict

API_KEY = os.getenv("API_FOOTBALL_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Heure Bafoussam
TZ = pytz.timezone("Africa/Douala")
NOW = datetime.now(TZ)

HEADERS = {"x-apisports-key": API_KEY}

def poisson(k, lam):
    return (lam**k * exp(-lam)) / factorial(k)

def prob_over(lam, seuil):
    # seuil 1.5 = P(k>=2), seuil 2.5 = P(k>=3)
    prob_under = sum(poisson(k, lam) for k in range(int(seuil)+1))
    return (1 - prob_under) * 100

def get_fixtures():
    # Matchs du jour
    date_str = NOW.strftime("%Y-%m-%d")
    url = f"https://v3.football.api-sports.io/fixtures?date={date_str}"
    r = requests.get(url, headers=HEADERS).json()
    return r.get("response", [])

def get_last5_goals(team_id):
    url = f"https://v3.football.api-sports.io/fixtures?team={team_id}&last=5"
    r = requests.get(url, headers=HEADERS).json()
    total_goals = []
    for m in r.get("response", []):
        g_home = m['goals']['home'] or 0
        g_away = m['goals']['away'] or 0
        total_goals.append(g_home + g_away)
    if not total_goals:
        return 1.5 # valeur par défaut si pas d'histo
    return sum(total_goals) / len(total_goals)

def main():
    fixtures = get_fixtures()
    analyses = []

    for f in fixtures[:20]: # on limite à 20 pour économiser l'API
        fixture_time = datetime.fromisoformat(f['fixture']['date'].replace("Z","+00:00")).astimezone(TZ)
        if fixture_time < NOW: # déjà joué
            continue
        
        home_id = f['teams']['home']['id']
        away_id = f['teams']['away']['id']
        home_name = f['teams']['home']['name']
        away_name = f['teams']['away']['name']

        avg_home = get_last5_goals(home_id)
        avg_away = get_last5_goals(away_id)
        
        # Lambda du match = moyenne des deux moyennes
        lam = (avg_home + avg_away) / 2

        over15 = prob_over(lam, 1.5)
        over25 = prob_over(lam, 2.5)

        analyses.append({
            "match": f"{home_name} vs {away_name}",
            "heure": fixture_time.strftime("%H:%M"),
            "moy_home": round(avg_home,2),
            "moy_away": round(avg_away,2),
            "lambda": round(lam,2),
            "over15": round(over15,1),
            "over25": round(over25,1),
            "score_max": max(over15, over25)
        })

    # TRI - Top 3 par probabilité la plus haute
    top3 = sorted(analyses, key=lambda x: x['score_max'], reverse=True)[:3]

    # Message Telegram PRO
    msg = f"📍 Bafoussam {NOW.strftime('%H:%M')} - Update 2H\n"
    msg += f"🔬 Loi de Poisson (5 derniers matchs - buts totaux)\n\n"

    if not top3:
        msg += "Pas de matchs à venir."
    else:
        for i, m in enumerate(top3, 1):
            msg += f"{i}️⃣ {m['heure']} - {m['match']}\n"
            msg += f"   Moy buts: {m['moy_home']} (Dom) | {m['moy_away']} (Ext) -> λ={m['lambda']}\n"
            msg += f"   📊 Over 1.5: {m['over15']}% | Over 2.5: {m['over25']}%\n"
            best = "OVER 1.5" if m['over15'] > m['over25'] else "OVER 2.5"
            msg += f"   ✅ RECO: {best}\n\n"

    # Envoi
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

if __name__ == "__main__":
    main()
name: Bot 2H
on:
  schedule:
    - cron: '0 */2 * * *' # toutes les 2 heures
  workflow_dispatch: # bouton manuel

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - run: pip install requests pytz
      - run: python bot.py
        env:
          API_FOOTBALL_KEY: ${{ secrets.API_FOOTBALL_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
