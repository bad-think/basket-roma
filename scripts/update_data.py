#!/usr/bin/env python3
"""
update_data.py — Roma Basket Casa — Versione 6.6
- Interrogazione Proattiva Google Search mirata a calendari LNP
- Ricalcolo Totale Classifica (Auto-correzione punti)
- Gestione Alias Sponsor e Team
"""

import json
import os
import re
import urllib.request
import urllib.parse
from datetime import datetime, date, timedelta
from pathlib import Path

# ================================================================
# CONFIGURAZIONE
# ================================================================
CONFIG = {
    "season": "2025-26",
    "teams": {
        "virtus": {
            "name": "Virtus GVM Roma",
            "aliases": ["virtus gvm roma", "virtus roma", "virtus 1960", "virtus gvm"],
            "serie": "B Nazionale"
        },
        "luiss": {
            "name": "Luiss Roma",
            "aliases": ["luiss roma", "luiss basket", "ssd luiss"],
            "serie": "B Nazionale"
        }
    }
}

# Credenziali Google (da GitHub Secrets)
API_KEY = os.environ.get("GOOGLE_API_KEY")
CSE_ID = os.environ.get("GOOGLE_CSE_ID")

# Situazione punti consolidata (Punti pre-G33/G34)
BASE_STANDINGS = {
    "virtus": {"pos": 1, "pts": 52, "w": 26, "l": 6}, 
    "luiss": {"pos": 6, "pts": 38, "w": 19, "l": 13}
}

OPPONENT_ALIASES = {
    "raggisolaris faenza": ["tema sinergie faenza", "faenza", "black panthers"],
    "janus fabriano": ["ristopro fabriano", "fabriano"],
    "benacquista latina": ["latina basket", "latina"]
}

# ================================================================
# MOTORE DI RICERCA GOOGLE
# ================================================================

def google_search_time(home, away, match_date):
    """Ricerca potenziata per trovare l'orario esatto nei comunicati LNP"""
    if not API_KEY or not CSE_ID:
        print("⚠️ API Key o CSE_ID mancanti negli environment.")
        return None

    # Query ottimizzata per i comunicati ufficiali o tabelle LNP
    query = f"LNP basket calendario {home} {away} {match_date}"
    encoded_query = urllib.parse.quote(query)
    url = f"https://www.googleapis.com/customsearch/v1?key={API_KEY}&cx={CSE_ID}&q={encoded_query}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode())
            for item in res.get("items", []):
                snippet = item.get("snippet", "")
                title = item.get("title", "")
                text = (title + " " + snippet).lower()
                
                # Cerca orari plausibili (esclude 00:00 e orari mattutini strani)
                # Match formato HH:MM tra le 15:00 e le 22:55 che finiscono per 0 o 5
                times = re.findall(r'(?:1[5-9]|2[0-2]):[0-5][05]', text)
                if times:
                    return times[0]
    except Exception as e:
        print(f"⚠️ Errore API Google: {e}")
    return None

# ================================================================
# LOGICA DATI E CLASSIFICA
# ================================================================

def get_html(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode('utf-8', errors='ignore')
    except: return None

def parse_score(html, home, away):
    if not html: return None
    text = re.sub('<[^<]+?>', ' ', html).lower()
    h_list = [home.lower()] + OPPONENT_ALIASES.get(home.lower(), [])
    a_list = [away.lower()] + OPPONENT_ALIASES.get(away.lower(), [])

    for h in h_list:
        for a in a_list:
            p1 = rf'{re.escape(h)}.*?(\d{{2,3}})\s*-\s*(\d{{2,3}}).*?{re.escape(a)}'
            m1 = re.search(p1, text, re.DOTALL)
            if m1: return int(m1.group(1)), int(m1.group(2))
            
            p2 = rf'{re.escape(a)}.*?(\d{{2,3}})\s*-\s*(\d{{2,3}}).*?{re.escape(h)}'
            m2 = re.search(p2, text, re.DOTALL)
            if m2: return int(m2.group(2)), int(m2.group(1))
    return None

def recalculate_standings(matches):
    """Ricalcola i punti partendo dai risultati nel JSON"""
    std = {k: dict(v) for k, v in BASE_STANDINGS.items()}
    for m in matches:
        if m.get("sh") is not None and m.get("sa") is not None:
            tk = m["team"]
            if tk in std:
                aliases = CONFIG["teams"][tk]["aliases"]
                is_home = any(a in m["home"].lower() for a in aliases)
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
        print("❌ Errore: data.json non trovato.")
        return

    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    matches = data.get("matches", [])
    today = date.today()
    horizon = today + timedelta(days=14) # Finestra di 2 settimane
    updated = False

    print(f"🚀 Avvio Aggiornamento Proattivo — {today}")

    for m in matches:
        m_date = datetime.strptime(m["date"], "%Y-%m-%d").date()
        
        # 1. RECUPERO RISULTATI (Partite passate)
        if m_date <= today and m.get("sh") is None:
            # Fallback su ID generico o noto per cercare i punteggi
            url = f"https://www.pianetabasket.com/serie-b/live-358236"
            score = parse_score(get_html(url), m["home"], m["away"])
            if score:
                m["sh"], m["sa"] = score[0], score[1]
                print(f"✅ Risultato acquisito: {m['home']} {score[0]}-{score[1]} {m['away']}")
                updated = True

        # 2. AGGIORNAMENTO ORARI (Interrogazione diretta per partite imminenti)
        if today <= m_date <= horizon:
            print(f"🕒 Verifica orario Google per: {m['home']} vs {m['away']} ({m['date']})...")
            new_time = google_search_time(m["home"], m["away"], m["date"])
            
            if new_time and new_time != m.get("time"):
                old_time = m.get("time", "ND")
                m["time"] = new_time
                print(f"✨ ORARIO AGGIORNATO: {old_time} -> {new_time}")
                updated = True

    # 3. SALVATAGGIO E RICALCOLO
    data["standings"] = recalculate_standings(matches)
    data["last_updated"] = datetime.now().strftime("%d/%m/%Y %H:%M")

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"🏁 Fine. File salvato. Modifiche: {updated}")

if __name__ == "__main__":
    main()
