import os
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# --- CONFIG ---
API_KEY = os.getenv("API_FOOTBALL_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CAMEROON = ZoneInfo("Africa/Douala")
HEADERS = {"x-apisports-key": API_KEY}
BASE_URL = "https://v3.football.api-sports.io/fixtures"

def fetch(date_str):
    """Récupère tous les matchs d'une date en heure de Bafoussam"""
    url = f"{BASE_URL}?date={date_str}&timezone=Africa/Douala"
    r = requests.get(url, headers=HEADERS, timeout=30)
    return r.json().get("response", [])

def analyze(fixtures):
    ft = [m for m in fixtures if m["fixture"]["status"]["short"] == "FT"]
    if not ft: return None
    total = len(ft)
    def pct(n): return round(n/total*100, 1)
    hw = sum(1 for m in ft if m["goals"]["home"] > m["goals"]["away"])
    aw = sum(1 for m in ft if m["goals"]["away"] > m["goals"]["home"])
    dr = total - hw - aw
    o15 = sum(1 for m in ft if (m["goals"]["home"] or 0)+(m["goals"]["away"] or 0) > 1.5)
    o25 = sum(1 for m in ft if (m["goals"]["home"] or 0)+(m["goals"]["away"] or 0) > 2.5)
    btts = sum(1 for m in ft if m["goals"]["home"]>0 and m["goals"]["away"]>0)
    return {"total": total, "home": pct(hw), "away": pct(aw), "draw": pct(dr), "over15": pct(o15), "over25": pct(o25), "btts": pct(btts)}

# --- TEMPS RÉEL BAFOSSAM ---
now = datetime.now(CAMEROON)
today_str = now.date().isoformat()
yesterday_str = (now.date() - timedelta(days=1)).isoformat()

print(f"Analyse lancée à Bafoussam: {now.strftime('%H:%M %d/%m/%Y')}")

fixtures_yesterday = fetch(yesterday_str)
fixtures_today = fetch(today_str)

stats_y = analyze(fixtures_yesterday)
stats_today_ft = analyze(fixtures_today)

# Chronologie du temps réel aujourd'hui
live = [m for m in fixtures_today if m["fixture"]["status"]["short"] in ["1H","2H","HT","ET","P","LIVE"]]
upcoming = [m for m in fixtures_today if m["fixture"]["status"]["short"] == "NS"]

# Filtrer les matchs à venir APRÈS ton heure actuelle
upcoming_future = []
for m in upcoming:
    # l'heure du match est déjà en Africa/Douala grâce à l'API
    kickoff_ts = m["fixture"]["timestamp"]
    kickoff = datetime.fromtimestamp(kickoff_ts, tz=CAMEROON)
    if kickoff > now:
        upcoming_future.append(m)

# Meilleure loi d'hier
if stats_y:
    best_loi = max([("Domicile", stats_y["home"]), ("Over 1.5", stats_y["over15"]), ("Over 2.5", stats_y["over25"]), ("BTTS", stats_y["btts"])], key=lambda x: x[1])
else:
    best_loi = ("Over 1.5", 0)

# --- MESSAGE TELEGRAM ---
message = f"📍 *AGENT SCIENTIFIQUE V3 - BAFOSSAM*\n"
message += f"🕐 {now.strftime('%H:%M')} - {now.strftime('%d %B %Y')}\n\n"

if stats_y:
    message += f"*HIER ({yesterday_str})* - {stats_y['total']} matchs finis\n"
    message += f"`Domicile: {stats_y['home']}% | Ext: {stats_y['away']}% | Nul: {stats_y['draw']}%`\n"
    message += f"`Over1.5: {stats_y['over15']}% | Over2.5: {stats_y['over25']}% | BTTS: {stats_y['btts']}%`\n\n"
else:
    message += f"Aucun match fini hier.\n\n"

message += f"*AUJOURD'HUI ({today_str})*\n"
if stats_today_ft:
    message += f"✅ Finis: {stats_today_ft['total']} matchs\n"
message += f"🔴 Live maintenant: {len(live)} matchs\n"
message += f"⏳ À venir après {now.strftime('%H:%M')}: {len(upcoming_future)} matchs\n\n"

message += f"🏆 *LOI DU JOUR (basée sur hier): {best_loi[0]} à {best_loi[1]}%*\n"
message += f"👉 À appliquer sur les {len(upcoming_future)} prochains matchs.\n"

if len(upcoming_future) > 0:
    message += f"\n*PROCHAINS MATCHS:*\n"
    for m in upcoming_future[:5]: # 5 premiers
        heure = datetime.fromtimestamp(m["fixture"]["timestamp"], tz=CAMEROON).strftime('%H:%M')
        message += f"{heure} - {m['teams']['home']['name']} vs {m['teams']['away']['name']}\n"

# Envoi
url_tg = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
requests.post(url_tg, data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"})
print("Message envoyé")
