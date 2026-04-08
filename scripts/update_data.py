#!/usr/bin/env python3
"""
update_data.py — Roma Basket Casa — Versione 5.5
- Ricalcolo classifica automatico
- Aggiornamento orari partite future
- Gestione Alias Sponsor
"""

import json
import re
import urllib.request
from datetime import datetime, date
from pathlib import Path

# ================================================================
# CONFIGURAZIONE
# ================================================================
CONFIG = {
    "season": "2025-26",
    "teams": {
        "virtus": {
            "name": "Virtus GVM Roma",
            "name_aliases": ["virtus gvm roma", "virtus roma", "virtus gvm roma 1960"],
            "serie": "B Nazionale", "girone": "B"
        },
        "luiss": {
            "name": "Luiss Roma",
            "name_aliases": ["luiss roma", "luiss", "luiss basket"],
            "serie": "B Nazionale", "girone": "B"
        }
    }
}

# Punti e record reali all'inizio del monitoraggio (o situazione attuale nota)
BASE_STANDINGS = {
    "virtus": {"pos": 1, "pts": 52, "w": 26, "l": 6}, 
    "luiss": {"pos": 6, "pts": 38, "w": 19, "l": 13}
}

# Mapping ID Pianetabasket per le giornate
# Se una giornata non è qui, usa ROUND_BASE_IDS come stima
KNOWN_URLS = {
    33: "357594", # G33
    34: "358236", # G34 (15 Aprile)
}

ROUND_BASE_IDS = {
    34: 358236,
    35: 358878,
    36: 359520
}

# Alias per avversari (Nomi che compaiono sui siti vs nomi nel tuo JSON)
OPPONENT_ALIASES = {
    "raggisolaris faenza": ["tema sinergie faenza", "faenza", "raggisolaris"],
    "janus fabriano": ["ristopro fabriano", "fabriano", "janus"],
    "benacquista latina": ["latina basket", "latina"],
    "pallacanestro roseto": ["lume roseto", "roseto"]
}

# ================================================================
# FUNZIONI CORE
# ================================================================

def get_html(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"⚠️ Errore fetch {url}: {e}")
        return None

def parse_score(html, home, away):
    if not html: return None
    text = re.sub('<[^<]+?>', ' ', html).lower()
    
    # Genera combinazioni di nomi (Reali + Alias)
    h_names = [home.lower()] + OPPONENT_ALIASES.get(home.lower(), [])
    a_names = [away.lower()] + OPPONENT_ALIASES.get(away.lower(), [])

    for h in h_names:
        for a in a_names:
            # Match Casa-Trasferta
            p1 = rf'{re.escape(h)}.*?(\d{{2,3}})\s*-\s*(\d{{2,3}}).*?{re.escape(a)}'
            m1 = re.search(p1, text, re.DOTALL)
            if m1: return int(m1.group(1)), int(m1.group(2))
            
            # Match Trasferta-Casa (inverte i punteggi)
            p2 = rf'{re.escape(a)}.*?(\d{{2,3}})\s*-\s*(\d{{2,3}}).*?{re.escape(h)}'
            m2 = re.search(p2, text, re.DOTALL)
            if m2: return int(m2.group(2)), int(m2.group(1))
    return None

def parse_time(html, team_name):
    if not html: return None
    # Cerca un orario HH:MM vicino al nome della squadra
    pattern = rf'{re.escape(team_name.lower())}.*?(\d{{2}}:\d{{2}})'
    match = re.search(pattern, html.lower(), re.DOTALL)
    if match:
        return match.group(1)
    return None

def recalculate_standings(matches):
    """Ricostruisce la classifica basandosi sui match nel file"""
    std = {k: dict(v) for k, v in BASE_STANDINGS.items()}
    for m in matches:
        if m.get("sh") is not None and m.get("sa") is not None:
            tk = m["team"]
            if tk in std:
                # Verifica se la squadra monitorata ha vinto
                is_home = any(alias in m["home"].lower() for alias in CONFIG["teams"][tk]["name_aliases"])
                win = (is_home and m["sh"] > m["sa"]) or (not is_home and m["sa"] > m["sh"])
                
                if win:
                    std[tk]["pts"] += 2
                    std[tk]["w"] += 1
                else:
                    std[tk]["l"] += 1
    return std

# ================================================================
# MAIN
# ================================================================

def main():
    data_path = Path("data.json")
    if not data_path.exists():
        print("❌ File data.json non trovato.")
        return

    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    matches = data.get("matches", [])
    today = date.today()
    changes = False

    print(f"🏀 Avvio aggiornamento — {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    for m in matches:
        m_date = datetime.strptime(m["date"], "%Y-%m-%d").date()
        pb_id = KNOWN_URLS.get(m["round"]) or ROUND_BASE_IDS.get(m["round"])
        
        if not pb_id: continue
        url = f"https://www.pianetabasket.com/serie-b/live-{pb_id}"

        # 1. Recupero Punteggi (per partite passate o odierne senza risultato)
        if m_date <= today and m.get("sh") is None:
            html = get_html(url)
            score = parse_score(html, m["home"], m["away"])
            if score:
                m["sh"], m["sa"] = score[0], score[1]
                print(f"✅ Risultato G{m['round']}: {m['home']} {score[0]}-{score[1]} {m['away']}")
                changes = True

        # 2. Aggiornamento Orari (per partite future senza orario certo)
        if m_date >= today and (m.get("time") == "00:00" or not m.get("time")):
            html = get_html(url)
            new_time = parse_time(html, m["home"])
            if new_time and new_time != m.get("time"):
                m["time"] = new_time
                print(f"🕒 Orario G{m['round']} aggiornato: {new_time}")
                changes = True

    # 3. Ricalcolo Classifica (sempre, per sicurezza)
    data["standings"] = recalculate_standings(matches)
    data["last_updated"] = datetime.now().strftime("%d/%m/%Y %H:%M")

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"🏁 Elaborazione completata. Modifiche effettuate: {changes}")

if __name__ == "__main__":
    main()
