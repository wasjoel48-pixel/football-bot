import os, requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

API_KEY = os.getenv("API_FOOTBALL_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CAMEROON = ZoneInfo("Africa/Douala")
HEADERS = {"x-apisports-key": API_KEY}

def fetch_fixtures(date_str):
    url = f"https://v3.football.api-sports.io/fixtures?date={date_str}&timezone=Africa/Douala"
    return requests.get(url, headers=HEADERS, timeout=30).json().get("response", [])

def fetch_odds(date_str):
    # On récupère les cotes pour savoir qui est favori
    url = f"https://v3.football.api-sports.io/odds?date={date_str}&timezone=Africa/Douala"
    r = requests.get(url, headers=HEADERS, timeout=30).json().get("response", [])
    odds_map = {}
    for o in r:
        fid = o["fixture"]["id"]
        # On prend la cote 1X2 moyenne
        try:
            values = o["bookmakers"][0]["bets"][0]["values"] # 1X2
            # values = [{"value":"Home","odd":"1.50"},...]
            home_odd = float([v for v in values if v["value"]=="Home"][0]["odd"])
            away_odd = float([v for v in values if v["value"]=="Away"][0]["odd"])
            odds_map[fid] = {"home": home_odd, "away": away_odd}
        except: pass
    return odds_map

def analyze_favorite_trap(fixtures, odds_map):
    """Détecte les favoris qui se font surprendre"""
    pieges = 0
    total_fav = 0
    signes = {"away_fav_lose": 0, "small_odd_lose": 0, "btts_upset": 0}

    for m in fixtures:
        if m["fixture"]["status"]["short"]!= "FT": continue
        fid = m["fixture"]["id"]
        if fid not in odds_map: continue

        home_goals = m["goals"]["home"]
        away_goals = m["goals"]["away"]
        home_odd = odds_map[fid]["home"]
        away_odd = odds_map[fid]["away"]

        # Qui est favori? cote < 1.90
        fav = None
        if home_odd < 1.9 and home_odd < away_odd: fav = "home"
        if away_odd < 1.9 and away_odd < home_odd: fav = "away"
        if not fav: continue

        total_fav += 1
        # Favori battu?
        upset = (fav=="home" and home_goals < away_goals) or (fav=="away" and away_goals < home_goals)
        if upset:
            pieges += 1
            if fav=="away": signes["away_fav_lose"] += 1
            if min(home_odd, away_odd) < 1.60: signes["small_odd_lose"] += 1
            if home_goals>0 and away_goals>0: signes["btts_upset"] += 1

    if total_fav == 0: return None
    taux = round(pieges/total_fav*100, 1)
    return {"taux": taux, "pieges": pieges, "total": total_fav, "signes": signes}

# --- EXECUTION TEMPS REEL ---
now = datetime.now(CAMEROON)
today_str = now.date().isoformat()
yesterday_str = (now.date() - timedelta(days=1)).isoformat()

fix_y = fetch_fixtures(yesterday_str)
odds_y = fetch_odds(yesterday_str)

trap_stats = analyze_favorite_trap(fix_y, odds_y)

# Analyse classique (comme avant)
def quick_stats(fix):
    ft=[m for m in fix if m["fixture"]["status"]["short"]=="FT"]
    if not ft: return None
    t=len(ft)
    return {"t": t}

# Message
msg = f"📍 *V4 ALERTEUR FAVORI - {now.strftime('%H:%M')} BAF*\n\n"
msg += f"*HIER {yesterday_str}* analysé\n"

if trap_stats:
    msg += f"🎯 *LOI ALERTEUR MATHEMATIQUE*\n"
    msg += f"Favoris piégés: {trap_stats['pieges']}/{trap_stats['total']} = *{trap_stats['taux']}%*\n"

    if trap_stats["taux"] >= 35:
        msg += f"🚨 *ALERTE ROUGE - JOURNÉE À PIÈGES*\n"
        msg += f"Signes observés:\n"
        msg += f"- Favoris extérieur qui tombent: {trap_stats['signes']['away_fav_lose']}\n"
        msg += f"- Petites cotes <1.60 qui tombent: {trap_stats['signes']['small_odd_lose']}\n"
        msg += f"- Pièges avec BTTS: {trap_stats['signes']['btts_upset']}\n\n"
        msg += f"💡 *CONSEIL MATH*: Ne joue PAS les favoris <1.80 aujourd'hui. Joue Double Chance Outsiders ou BTTS.\n"
    elif trap_stats["taux"] >= 20:
        msg += f"⚠️ Tendance piège modérée. Prudence sur les favoris à l'extérieur.\n"
    else:
        msg += f"✅ Journée normale, favoris respectés. Tu peux jouer favoris Domicile.\n"
else:
    msg += f"Pas assez de cotes hier pour calculer les pièges.\n"

msg += f"\n⏳ {len([m for m in fetch_fixtures(today_str) if m['fixture']['status']['short']=='NS'])} matchs à venir aujourd'hui."

requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
              data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})

print("V4 envoyé")
