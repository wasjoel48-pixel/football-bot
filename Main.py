import os, requests, re
from datetime import datetime, timedelta
import pytz
from math import exp, factorial
from collections import defaultdict

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("API_FOOTBALL_KEY")
TZ = pytz.timezone("Africa/Douala")
HEADERS = {"x-apisports-key": API_KEY}

def poisson_prob(lam, seuil):
    def pois(k): return (lam**k * exp(-lam)) / factorial(k)
    prob_under = sum(pois(k) for k in range(int(seuil)+1))
    return round((1 - prob_under)*100, 1)

def get_team_id(name):
    url = f"https://v3.football.api-sports.io/teams?search={name}"
    r = requests.get(url, headers=HEADERS).json()
    if r['response']: return r['response'][0]['team']['id'], r['response'][0]['team']['name']
    return None, None

def analyse_equipe(team_id):
    url = f"https://v3.football.api-sports.io/fixtures?team={team_id}&last=10"
    data = requests.get(url, headers=HEADERS).json().get('response', [])
    buts_pour = []
    buts_contre = []
    btts = 0
    over15 = 0
    over25 = 0
    vic = nul = defe = 0

    for m in data:
        gh = m['goals']['home']; ga = m['goals']['away']
        if gh is None or ga is None: continue
        is_home = m['teams']['home']['id'] == team_id
        bp = gh if is_home else ga
        bc = ga if is_home else gh
        buts_pour.append(bp); buts_contre.append(bc)
        if gh>0 and ga>0: btts+=1
        if gh+ga > 1: over15+=1
        if gh+ga > 2: over25+=1
        # resultat
        if (is_home and gh>ga) or (not is_home and ga>gh): vic+=1
        elif gh==ga: nul+=1
        else: defe+=1

    if not buts_pour: return None
    return {
        "moy_pour": sum(buts_pour)/len(buts_pour),
        "moy_contre": sum(buts_contre)/len(buts_contre),
        "moy_total": sum([a+b for a,b in zip(buts_pour,buts_contre)])/len(buts_pour),
        "btts_rate": round(btts/len(data)*100,1),
        "over15_rate": round(over15/len(data)*100,1),
        "over25_rate": round(over25/len(data)*100,1),
        "forme": f"{vic}V-{nul}N-{defe}D sur 10",
        "clean_sheet": round(buts_contre.count(0)/len(data)*100,1)
    }

def get_h2h(id1, id2):
    url = f"https://v3.football.api-sports.io/fixtures/headtohead?h2h={id1}-{id2}&last=5"
    data = requests.get(url, headers=HEADERS).json().get('response', [])
    buts = []
    for m in data:
        gh = m['goals']['home'] or 0; ga = m['goals']['away'] or 0
        buts.append(gh+ga)
    if not buts: return "Pas de H2H", 0
    return f"{len(data)} matchs, Moy {sum(buts)/len(buts):.2f} buts/match", sum(buts)/len(buts)

def analyse_match(nom_match, heure):
    # nom_match = "Arsenal vs Chelsea"
    if "vs" not in nom_match: return "Format: Equipe A vs Equipe B"
    a,b = [x.strip() for x in nom_match.split("vs")[:2]]
    id_a, vrai_a = get_team_id(a)
    id_b, vrai_b = get_team_id(b)
    if not id_a or not id_b: return f"❌ Equipe non trouvée: {a} ou {b}"

    stat_a = analyse_equipe(id_a)
    stat_b = analyse_equipe(id_b)
    h2h_text, h2h_moy = get_h2h(id_a, id_b)

    lam = (stat_a['moy_total'] + stat_b['moy_total'] + h2h_moy) / 3 if h2h_moy else (stat_a['moy_total']+stat_b['moy_total'])/2

    over15_p = poisson_prob(lam, 1.5)
    over25_p = poisson_prob(lam, 2.5)
    btts_p = (stat_a['btts_rate'] + stat_b['btts_rate'])/2

    # CONCLUSION INTELLIGENTE DU BOT
    if over15_p >= 80 and stat_a['over15_rate']>=80 and stat_b['over15_rate']>=80:
        reco = "✅ CONCLUSION BOT: OVER 1.5 ULTRA SAFE"
    elif over25_p >= 70 and btts_p >= 55:
        reco = "✅ CONCLUSION BOT: OVER 2.5 + BTTS OUI (match ouvert)"
    elif stat_a['clean_sheet']>=50 or stat_b['clean_sheet']>=50:
        reco = "✅ CONCLUSION BOT: BTTS NON probable (une défense solide)"
    elif btts_p >= 65:
        reco = "✅ CONCLUSION BOT: BTTS OUI"
    else:
        reco = "✅ CONCLUSION BOT: UNDER 3.5 Safe"

    msg = f"🔍 **{vrai_a} vs {vrai_b} - {heure}**\n"
    msg += f"📍 Heure Bafoussam: {heure}\n\n"
    msg += f"--- {vrai_a} (10 derniers) ---\n"
    msg += f"Forme: {stat_a['forme']} | Moy buts marqués: {stat_a['moy_pour']:.2f} | Encaissés: {stat_a['moy_contre']:.2f}\n"
    msg += f"BTTS: {stat_a['btts_rate']}% | Over 1.5: {stat_a['over15_rate']}% | Over 2.5: {stat_a['over25_rate']}%\n\n"
    msg += f"--- {vrai_b} (10 derniers) ---\n"
    msg += f"Forme: {stat_b['forme']} | Moy buts marqués: {stat_b['moy_pour']:.2f} | Encaissés: {stat_b['moy_contre']:.2f}\n"
    msg += f"BTTS: {stat_b['btts_rate']}% | Over 1.5: {stat_b['over15_rate']}% | Over 2.5: {stat_b['over25_rate']}%\n\n"
    msg += f"--- H2H ---\n{h2h_text}\n\n"
    msg += f"--- CALCUL POISSON (λ={lam:.2f}) ---\n"
    msg += f"Over 1.5 Poisson: {over15_p}% | Over 2.5 Poisson: {over25_p}% | BTTS Estimé: {btts_p}%\n\n"
    msg += f"{reco}\n"
    return msg

# BOUCLE TELEGRAM
def main():
    print("Bot chercheur démarré...")
    offset = 0
    while True:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset}&timeout=30"
        r = requests.get(url).json()
        for upd in r.get('result', []):
            offset = upd['update_id']+1
            if 'message' not in upd: continue
            chat_id = upd['message']['chat']['id']
            text = upd['message'].get('text','')

            # Exemple: tu envoies 2 lignes
            # Arsenal vs Chelsea 20:00
            # Real vs Barca 21:00
            lignes = text.split('\n')
            reponse_finale = f"🕐 Analyse lancée à {datetime.now(TZ).strftime('%H:%M')} Bafoussam\n\n"
            for ligne in lignes:
                if 'vs' not in ligne.lower(): continue
                # extrait heure
                m = re.search(r'(\d{1,2}:\d{2})', ligne)
                heure = m.group(1) if m else "??:??"
                nom = re.sub(r'\d{1,2}:\d{2}', '', ligne).strip()
                reponse_finale += analyse_match(nom, heure) + "\n\n---\n\n"
