import os, requests, time
from datetime import datetime
from zoneinfo import ZoneInfo

API_KEY = os.getenv("API_FOOTBALL_KEY")
TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID")
CAMEROON = ZoneInfo("Africa/Douala")
HEADERS = {"x-apisports-key": API_KEY}

def api(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    return r.json().get("response", [])

def get_form(team_id):
    url = f"https://v3.football.api-sports.io/fixtures?team={team_id}&last=10&timezone=Africa/Douala"
    fixtures = api(url)
    w=d=l=0
    goals_for=0
    for m in fixtures:
        if m["fixture"]["status"]["short"]!="FT": continue
        is_home = m["teams"]["home"]["id"]==team_id
        hg, ag = m["goals"]["home"], m["goals"]["away"]
        goals_for += hg if is_home else ag
        if (is_home and hg>ag) or (not is_home and ag>hg): w+=1
        elif hg==ag: d+=1
        else: l+=1
    return {"W":w,"D":d,"L":l, "form_str": f"{w}V-{d}N-{l}D", "avg_goals": round(goals_for/max(1,len(fixtures)),1)}

def get_h2h(id1, id2):
    url = f"https://v3.football.api-sports.io/fixtures/headtohead?h2h={id1}-{id2}&last=10&timezone=Africa/Douala"
    fixtures = api(url)
    w1=w2=d=0
    for m in fixtures:
        if m["fixture"]["status"]["short"]!="FT": continue
        if m["goals"]["home"]>m["goals"]["away"]:
            if m["teams"]["home"]["id"]==id1: w1+=1
            else: w2+=1
        elif m["goals"]["home"]<m["goals"]["away"]:
            if m["teams"]["away"]["id"]==id1: w1+=1
            else: w2+=1
        else: d+=1
    return {"w1":w1,"w2":w2,"d":d, "total":len(fixtures)}

# --- COEUR PRO ---
now = datetime.now(CAMEROON)
today_str = now.date().isoformat()
fixtures_today = api(f"https://v3.football.api-sports.io/fixtures?date={today_str}&timezone=Africa/Douala")
upcoming = [m for m in fixtures_today if m["fixture"]["status"]["short"]=="NS"]
upcoming = sorted(upcoming, key=lambda x: x["fixture"]["timestamp"])[:6] # On analyse les 6 prochains pour ne pas cramer l'API

msg = f"🎙️ *AGENT PRO FOOTBALL - {now.strftime('%H:%M')} Bafoussam*\n"
msg += f"Bonsoir Joël, voici mon briefing tactique du jour.\n\n"
msg += f"J'ai isolé {len(upcoming)} matchs à fort enjeu. Analyse Forme + H2H :\n\n"

alerts = 0
for m in upcoming:
    home = m["teams"]["home"]
    away = m["teams"]["away"]
    hid, aid = home["id"], away["id"]
    
    time.sleep(0.6) # pour respecter l'API
    form_home = get_form(hid)
    time.sleep(0.6)
    form_away = get_form(aid)
    time.sleep(0.6)
    h2h = get_h2h(hid, aid)

    heure = datetime.fromtimestamp(m["fixture"]["timestamp"], tz=CAMEROON).strftime('%H:%M')
    
    # --- LOI MATHEMATIQUE ALERTEUR (sans cote) ---
    # Un favori est une équipe avec >=6 victoires sur 10 derniers
    fav = None
    if form_home["W"] >= 6 and form_home["W"] > form_away["W"]+2: fav = "home"
    if form_away["W"] >= 6 and form_away["W"] > form_home["W"]+2: fav = "away"

    is_trap = False
    raison = ""
    if fav=="home" and h2h["w1"] < h2h["w2"]:
        is_trap = True
        raison = f"Malgré sa forme ({form_home['form_str']}), {home['name']} est mené {h2h['w2']} à {h2h['w1']} sur les 10 derniers H2H."
    if fav=="away" and form_away["W"]>=6 and form_home["W"]>=3:
        is_trap = True
        raison = f"{away['name']} est favori ({form_away['form_str']}) mais {home['name']} est solide à domicile ({form_home['form_str']}). Piège classique extérieur."

    msg += f"⏰ *{heure} - {home['name']} vs {away['name']}*\n"
    msg += f"   Forme: {home['name']} {form_home['form_str']} | {away['name']} {form_away['form_str']}\n"
    msg += f"   H2H (10): {home['name']} {h2h['w1']} - {h2h['d']}N - {h2h['w2']} {away['name']}\n"

    if is_trap:
        alerts+=1
        msg += f"   🚨 *ALERTE LOI TRAPPE:* {raison}\n"
        msg += f"   👉 *Loi conseillée: Double Chance {home['name'] if fav=='away' else away['name']} ou BTTS OUI*\n\n"
    else:
        msg += f"   ✅ Tendance logique respectée. Loi: Victoire {home['name'] if form_home['W']>=form_away['W'] else away['name']} ou Over 1.5\n\n"

msg += f"---\n📊 *Synthèse:* {alerts} piège(s) détecté(s) sur {len(upcoming)} matchs. Reste prudent sur les gros favoris à l'extérieur."

# Envoi
requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data={"chat_id": TG_CHAT, "text": msg, "parse_mode": "Markdown"})
print("Message PRO envoyé")
