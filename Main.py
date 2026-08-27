#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bot GitHub - Version adaptée
- Analyse les matchs déjà joués aujourd'hui vs hier
- Liste les matchs à venir dans les 30 prochaines minutes
- Envoie tout sur Telegram via GitHub Actions
- Fuseau: Douala
- API: TheSportsDB (gratuite)
"""

import os, requests, logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ================= CONFIG GITHUB =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API_BASE_URL = "https://www.thesportsdb.com/api/v1/json/3"
TIMEZONE = ZoneInfo("Africa/Douala")
# =================================================

logging.basicConfig(level=logging.INFO)

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Token ou Chat ID manquant")
        print(text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    r = requests.post(url, data=payload, timeout=10)
    print(f"Telegram: {r.status_code}")

def get_events_for_date(date_str: str):
    url = f"{API_BASE_URL}/eventsday.php?d={date_str}&s=Soccer"
    try:
        r = requests.get(url, timeout=15)
        data = r.json()
        return data.get("events", []) or []
    except Exception as e:
        print(f"Erreur API {date_str}: {e}")
        return []

def filter_finished(events): return [ev for ev in events if ev.get("strStatus") == "Match Finished"]

def filter_upcoming(events, now, delta_minutes=30):
    upcoming = []
    for ev in events:
        if ev.get("strStatus") != "Not Started": continue
        ts = ev.get("strTimestamp")
        if not ts: continue
        try: match_time = datetime.fromtimestamp(int(ts), tz=TIMEZONE)
        except: continue
        if now <= match_time <= now + timedelta(minutes=delta_minutes):
            upcoming.append(ev)
    return upcoming

def compute_trends(events):
    if not events: return {"nb":0,"home":0,"draw":0,"away":0,"total":0,"avg":0,"hg":0,"ag":0}
    home_wins=draws=away_wins=total=hg_tot=ag_tot=0
    for ev in events:
        try: hg=int(ev.get("intHomeScore",0) or 0); ag=int(ev.get("intAwayScore",0) or 0)
        except: hg=ag=0
        hg_tot+=hg; ag_tot+=ag; total+=hg+ag
        if hg>ag: home_wins+=1
        elif hg<ag: away_wins+=1
        else: draws+=1
    return {"nb":len(events),"home":home_wins,"draw":draws,"away":away_wins,"total":total,"avg":round(total/len(events),2) if events else 0,"hg":hg_tot,"ag":ag_tot}

def main():
    now = datetime.now(TIMEZONE)
    today_str = now.strftime("%Y-%m-%d")
    yest_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    yest_events = get_events_for_date(yest_str)
    today_events = get_events_for_date(today_str)

    yest_fini = filter_finished(yest_events)
    today_fini = filter_finished(today_events)
    upcoming = filter_upcoming(today_events, now, 30)

    y = compute_trends(yest_fini)
    t = compute_trends(today_fini)

    # MESSAGE 1 : TENDANCES
    if t['nb'] > 0:
        msg1 = f"📊 *TENDANCES FOOT - {now.strftime('%d/%m %H:%M')} Douala*\n\n"
        msg1 += f"*Hier* ({y['nb']} matchs) : 🏠{y['home']} 🤝{y['draw']} ✈️{y['away']} | Buts {y['hg']}/{y['ag']}/{y['total']} | Moy {y['avg']}\n\n"
        msg1 += f"*Auj. déjà joués* ({t['nb']} matchs) : 🏠{t['home']} 🤝{t['draw']} ✈️{t['away']} | Buts {t['hg']}/{t['ag']}/{t['total']} | Moy {t['avg']}\n\n"
        msg1 += "🔎 *Comparaison*\n"
        msg1 += f"Dom: {'⬆️' if t['home']>y['home'] else '⬇️' if t['home']<y['home'] else '➡️'} {y['home']}→{t['home']}\n"
        msg1 += f"Nuls: {'⬆️' if t['draw']>y['draw'] else '⬇️' if t['draw']<y['draw'] else '➡️'} {y['draw']}→{t['draw']}\n"
        msg1 += f"Ext: {'⬆️' if t['away']>y['away'] else '⬇️' if t['away']<y['away'] else '➡️'} {y['away']}→{t['away']}\n"
        msg1 += f"Buts/match: {'⬆️' if t['avg']>y['avg'] else '⬇️' if t['avg']<y['avg'] else '➡️'} {y['avg']}→{t['avg']}"
        send_telegram(msg1)
    else:
        send_telegram(f"📊 Aucun match terminé aujourd'hui pour le moment - {now.strftime('%H:%M')} Douala")

    # MESSAGE 2 : MATCHS DANS 30 MIN
    if upcoming:
        msg2 = f"⏰ *MATCHS DANS 30 MIN* - {now.strftime('%H:%M')} Douala\n\n"
        for ev in upcoming:
            home=ev.get("strHomeTeam","?"); away=ev.get("strAwayTeam","?"); league=ev.get("strLeague","?")
            ts=int(ev.get("strTimestamp",0))
            h=datetime.fromtimestamp(ts, tz=TIMEZONE).strftime("%H:%M")
            msg2+=f"🏟 {home} vs {away}\n   Ligue: {league}\n   Heure: {h}\n\n"
        msg2+="💡 *Note bot*: Si les domiciles ont gagné hier, ils sont en confiance."
        send_telegram(msg2)
    else:
        send_telegram("⏰ Aucun match ne commence dans les 30 prochaines minutes.")

if __name__ == "__main__":
    main()
