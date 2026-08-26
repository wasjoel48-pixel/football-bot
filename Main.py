import os, math, requests
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API_KEY = os.getenv("API_FOOTBALL_KEY")

HEADERS = {"x-apisports-key": API_KEY}
BASE_URL = "https://v3.football.api-sports.io"

def poisson(k, lam):
    if lam <= 0: lam = 0.1
    return (math.exp(-lam) * (lam**k)) / math.factorial(k)

def get_last_5_stats(team_id):
    try:
        url = f"{BASE_URL}/fixtures?team={team_id}&last=5"
        r = requests.get(url, headers=HEADERS, timeout=10).json()
        fixtures = r.get('response', [])
        if not fixtures: return 1.2, 1.2
        bp, bc = 0, 0
        for f in fixtures:
            is_home = f['teams']['home']['id'] == team_id
            gh = f['goals']['home'] or 0
            ga = f['goals']['away'] or 0
            if is_home: bp+=gh; bc+=ga
            else: bp+=ga; bc+=gh
        return bp/5, bc/5
    except: return 1.2, 1.2

def analyser():
    today = datetime.now().strftime('%Y-%m-%d')
    url = f"{BASE_URL}/fixtures?date={today}"
    data = requests.get(url, headers=HEADERS, timeout=10).json().get('response', [])[:8]
    msg = f"⚽ *ANALYSE CHRONO {today}*\n\n"
    trouve=0
    for m in data:
        hid = m['teams']['home']['id']; aid = m['teams']['away']['id']
        hname = m['teams']['home']['name']; aname = m['teams']['away']['name']
        hp, hc = get_last_5_stats(hid)
        ap, ac = get_last_5_stats(aid)
        xg_h = (hp + ac)/2; xg_a = (ap + hc)/2
        prob_h=0
        for i in range(6):
            for j in range(6):
                if i>j: prob_h += poisson(i,xg_h)*poisson(j,xg_a)
        if prob_h>0.55:
            trouve+=1
            msg+=f"🎯 *{hname} vs {aname}*\nForme: {round(hp,1)} vs {round(ap,1)} buts\nxG: {round(xg_h,2)}-{round(xg_a,2)} | P(Home): {round(prob_h*100,1)}%\n\n"
    if trouve>0:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id":CHAT_ID,"text":msg,"parse_mode":"Markdown"})
        print("Envoyé")
    else: print("Pas de value")

if __name__ == "__main__": analyser()
