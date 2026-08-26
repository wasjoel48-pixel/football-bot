import os
import requests
from datetime import datetime, timedelta
from collections import Counter

API_KEY = os.getenv("API_FOOTBALL_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HEADERS = {"x-apisports-key": API_KEY}

def get_finished_matches(date_str):
    url = f"https://v3.football.api-sports.io/fixtures?date={date_str}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    data = r.json().get("response", [])
    finished = [m for m in data if m["fixture"]["status"]["short"] == "FT"]
    return finished

def analyze(matches):
    if not matches:
        return None
    total = len(matches)
    home_win = sum(1 for m in matches if m["goals"]["home"] > m["goals"]["away"])
    away_win = sum(1 for m in matches if m["goals"]["away"] > m["goals"]["home"])
    draw = total - home_win - away_win
    over15 = sum(1 for m in matches if (m["goals"]["home"] or 0)+(m["goals"]["away"] or 0) > 1.5)
    over25 = sum(1 for m in matches if (m["goals"]["home"] or 0)+(m["goals"]["away"] or 0) > 2.5)
    btts = sum(1 for m in matches if m["goals"]["home"]>0 and m["goals"]["away"]>0)

    return {
        "total": total,
        "home": home_win/total*100,
        "away": away_win/total*100,
        "draw": draw/total*100,
        "over15": over15/total*100,
        "over25": over25/total*100,
        "btts": btts/total*100,
    }

def format_table(a, b, label_a, label_b):
    lines = [
        f"📊 *AGENT SCIENTIFIQUE SPORTS* 📊",
        f"Analyse {label_a} vs {label_b} | {datetime.now().strftime('%d/%m %H:%M')}",
        "",
        f"`{'Loi':<10} {label_a:<8} {label_b:<8} Tendance`",
        f"`{'-'*40}`",
    ]
    laws = [("Domicile","home"),("Extérieur","away"),("Nul","draw"),("Over1.5","over15"),("Over2.5","over25"),("BTTS","btts")]
    best_law = ""
    best_gain = -100
    for name, key in laws:
        va = a[key] if a else 0
        vb = b[key] if b else 0
        diff = vb - va
        emoji = "🔥" if diff>10 else "📈" if diff>0 else "📉"
        if diff > best_gain:
            best_gain = diff
            best_law = name
        lines.append(f"`{name:<10} {va:5.1f}% {vb:5.1f}% {emoji} {diff:+.1f}%`")

    lines += ["", f"🏆 *Loi la plus en hausse: {best_law} ({best_gain:+.1f}%) aujourd'hui*"]

    if b and b['total']>0:
        if b['home']>65: lines.append(f"⚠️ TENDANCE: {b['home']:.0f}% victoires DOMICILE aujourd'hui!")
        if b['over25']>70: lines.append(f"⚠️ TENDANCE: Journée à BUTS {b['over25']:.0f}% Over2.5!")
        if b['btts']>65: lines.append(f"⚠️ TENDANCE: BTTS énorme {b['btts']:.0f}%!")

    lines.append(f"\n_Matchs analysés: {a['total'] if a else 0} hier / {b['total'] if b else 0} auj._")
    return "\n".join(lines)

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload, timeout=15)

if __name__ == "__main__":
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)

    print(f"Analyse {yesterday} et {today}")
    matches_y = get_finished_matches(str(yesterday))
    matches_t = get_finished_matches(str(today))

    if not matches_y and not matches_t:
        send_telegram(f"🤖 Agent en ligne - Pas encore de matchs finis aujourd'hui ({today}). {len(matches_y)} hier.")
    else:
        stats_y = analyze(matches_y)
        stats_t = analyze(matches_t)
        msg = format_table(stats_y, stats_t, "HIER", "AUJ")
        print(msg)
        send_telegram(msg)
