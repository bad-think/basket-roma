import os
import json
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime, date
from pathlib import Path

DATA_FILE = Path(__file__).parent.parent / "data.json"
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID')

def google_search_fix(team_name, opponent, round_no):
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID: return None
    query = f"{team_name} vs {opponent} giornata {round_no} basket data orario 2026"
    url = f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CSE_ID}&q={urllib.parse.quote(query)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read().decode())
            if 'items' in res:
                content = " ".join([item.get('snippet', '') for item in res['items'][:3]]).lower()
                if "11 apr" in content or "11 aprile" in content:
                    return {"date": "2026-04-11", "time": "20:00"}
    except: return None
    return None

def main():
    print(f"🏀 Roma Basket Updater v7 (Big Match & Tickets Edition)")
    if not DATA_FILE.exists(): return

    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Elenco squadre per Big Match (Alta classifica/Derby/Storiche)
    TOP_TEAMS = ["livorno", "roseto", "piombino", "herons", "faenza", "jesesi", "fabriano", "chiusi"]

    for m in data.get("matches", []):
        # 1. Fix G35 via Google
        if str(m.get("round")) == "35" and "Virtus" in m.get("home", ""):
            g_res = google_search_fix("Virtus Roma", m["away"], 35)
            if g_res:
                m["date"], m["time"] = g_res["date"], g_res["time"]
            elif m["date"] == "2026-04-12":
                m["date"], m["time"] = "2026-04-11", "20:00"

        # 2. Assegnazione Big Match
        away_lower = m.get("away", "").lower()
        m["big_match"] = any(top in away_lower for top in TOP_TEAMS)

        # 3. Link Biglietti Automatici
        if "Virtus" in m.get("home", ""):
            m["ticket_url"] = "https://www.ticketone.it/artist/virtus-roma-1960/"
        elif "Luiss" in m.get("home", ""):
            m["ticket_url"] = "https://www.vivaticket.com/it/tour/luiss-basket-roma/3534"
        else:
            m["ticket_url"] = ""

    data["last_updated"] = datetime.now().isoformat()
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("✅ Update completato con Big Match e Ticket URLs.")

if __name__ == "__main__":
    main()
