# ============================================
# BOT CHERCHEUR - 1 CODE COMPLET - GITHUB
# Tu changes juste MATCH1 et MATCH2 ici
# ============================================
MATCH1 = "dynamo barbanaul vs omsk 11h30"
MATCH2 = "Real Madrid vs Barcelona 21:00"

import os, requests, re
from datetime import datetime
from math import exp, factorial
import pytz

# --- TES CLES DANS GITHUB SECRETS ---
API_KEY = os.getenv("API_FOOTBALL_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HEADERS = {"x-apisports-key": API_KEY}
TZ = pytz.timezone("Africa/Douala")

def poisson(lam, seuil):
    def p(k): return (lam**k * exp(-lam)) / factorial(k)
    return round((1 - sum(p(k) for k in range(int(seuil)+1))) * 100, 1)

def get_id(name):
    r = requests.get(f"https://v3.football.api-sports.io/teams?search={name}", headers=HEADERS).json()
    return (r['response'][0]['team']['id'], r['response'][0]['team']['name']) if r['response'] else (None, None)

def stats(team_id):
    data = requests.get(f"https://v3.football.api-sports.io/fixtures?team={team_id}&last=10", headers=HEADERS).json().get('response', [])
    bp, bc, btts, o15, o25, v, n, d = [], [], 0, 0, 0, 0, 0, 0
    for m in data:
        gh, ga = m['goals']['home'], m['goals']['away']
        if gh is None: continue
        home = m['teams']['home']['id'] == team_id
        pour = gh if home else ga
        contre = ga if home else gh
        bp.append(pour); bc.append(contre)
        if gh>0 and ga>0: btts+=1
        if gh+ga>1: o15+=1
        if gh+ga>2: o25+=1
        if (home and gh>ga) or (not home and ga>gh): v+=1
        elif gh==ga: n+=1
        else: d+=1
    if not bp: return None
    return {
        "pour": sum(bp)/len(bp), "contre": sum(bc)/len(bc),
        "total": sum(a+b for a,b in zip(bp,bc))/len(bp),
        "btts": btts/len(data)*100, "o15": o15/len(data)*100, "o25": o25/len(data)*100,
        "forme": f"{v}V-{n}N-{d}D"
    }

def h2h(id1, id2):
    data = requests.get(f"https://v3.football.api-sports.io/fixtures/headtohead?h2h={id1}-{id2}&last=5", headers=HEADERS).json().get('response', [])
    buts = [(m['goals']['home'] or 0)+(m['goals']['away'] or 0) for m in data]
    return (f"{len(buts)} H2H - {sum(buts)/len(buts):.2f} buts/moy" if buts else "Pas de H2H", sum(buts)/len(buts) if buts else 0)

def analyser(texte_complet):
    heure = re.search(r'(\d{1,2}:\d{2})', texte_complet)
    heure = heure.group(1) if heure else "??:??"
    nom = re.sub(r'\d{1,2}:\d{2}', '', texte_complet).strip()
    a,b = [x.strip() for x in nom.split("vs")]
    id_a, vrai_a = get_id(a)
    id_b, vrai_b = get_id(b)
    if not id_a: return f"❌ Equipe non trouvée {a}"

    sa, sb = stats(id_a), stats(id_b)
    h2h_txt, h2h_moy = h2h(id_a, id_b)
    lam = (sa['total']+sb['total']+h2h_moy)/3 if h2h_moy else (sa['total']+sb['total'])/2

    o15_p = poisson(lam, 1.5)
    o25_p = poisson(lam, 2.5)
    btts_p = (sa['btts']+sb['btts'])/2

    # CONCLUSION QUE L'HOMME NE PEUT PAS FAIRE VITE
    if o15_p >= 85: concl = "🔒 OVER 1.5 = BANKER - Les 2 équipes marquent/encaissent beaucoup"
    elif o25_p >= 72 and btts_p >= 60: concl = "🔥 OVER 2.5 + BTTS OUI - Match très ouvert"
    elif btts_p >= 70: concl = "✅ BTTS OUI - Les 2 attaques supérieures aux défenses"
    elif sa['contre']<0.8 or sb['contre']<0.8: concl = "🛡️ BTTS NON + UNDER 3.5 - Une défense très solide"
    else: concl = "⚖️ UNDER 3.5 SAFE - Match serré"

    txt = f"🔍 {vrai_a} vs {vrai_b} - {heure} Bafoussam\n\n"
    txt += f"[{vrai_a}] Forme {sa['forme']} | Marque {sa['pour']:.2f}/match | Encaisse {sa['contre']:.2f} | BTTS {sa['btts']:.0f}% | Over2.5 {sa['o25']:.0f}%\n"
    txt += f"[{vrai_b}] Forme {sb['forme']} | Marque {sb['pour']:.2f}/match | Encaisse {sb['contre']:.2f} | BTTS {sb['btts']:.0f}% | Over2.5 {sb['o25']:.0f}%\n\n"
    txt += f"H2H: {h2h_txt}\n"
    txt += f"CALCUL POISSON: λ={lam:.2f} -> Over1.5 {o15_p}% | Over2.5 {o25_p}% | BTTS estimé {btts_p:.0f}%\n\n"
    txt += f"{concl}\n"
    return txt

# --- LANCEMENT ---
msg = f"🤖 BOT CHERCHEUR - {datetime.now(TZ).strftime('%d/%m %H:%M')} Bafoussam\n\n"
msg += analyser(MATCH1) + "\n" + "="*30 + "\n\n" + analyser(MATCH2)

requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": msg})
print(msg)
