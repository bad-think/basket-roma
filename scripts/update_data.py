#!/usr/bin/env python3
"""
update_data.py — Roma Basket Casa — Aggiornamento automatico v6.7
Ricalcola la classifica ad ogni esecuzione per evitare errori di punteggio.
"""

import json
import os
import re
import urllib.request
import urllib.parse
from datetime import datetime, date
from pathlib import Path

# ================================================================
# CONFIGURAZIONE
# ================================================================
CONFIG = {
    "season": "2025-26",
    "next_season": "2026-27",
    "teams": {
        "virtus": {
            "name": "Virtus GVM Roma",
            "name_aliases": ["virtus gvm roma", "virtus roma", "virtus gvm roma 1960"],
            "serie": "B Nazionale",
            "girone": "B",
            "venue_name": "PalaTiziano – Palazzetto dello Sport",
            "venue_address": "Piazza Apollodoro 10, 00196 Roma",
            "venue_maps": "https://maps.google.com/?q=Palazzetto+dello+Sport+Piazza+Apollodoro+10+Roma"
        },
        "luiss": {
            "name": "Luiss Roma",
            "name_aliases": ["luiss roma", "luiss"],
            "serie": "B Nazionale",
            "girone": "B",
            "venue_name": "PalaTiziano – Palazzetto dello Sport",
            "venue_address": "Piazza Apollodoro 10, 00196 Roma",
            "venue_maps": "https://maps.google.com/?q=Palazzetto+dello+Sport+Piazza+Apollodoro+10+Roma"
        }
    }
}

# Classifica PRIMA dei risultati presenti nel JSON (G31 per Virtus, G32 per Luiss)
# Questi valori + i risultati nel file porteranno a Virtus 52 e Luiss 38.
BASE_STANDINGS = {
    "virtus": {"pos": 1, "pts": 46, "w": 23, "l": 6},
    "luiss": {"pos": 6, "pts": 38, "w": 19, "l": 11}
}

KNOWN_URLS = {
    31: "356237",
    32: "357140",
    33: "357782",
    34: "358236"
}

ROUND_BASE_IDS = {
    35: 358878, 36: 359520, 37: 360162, 38: 360804
}

# ================================================================
# UTILITIES
# ================================================================

def get_url(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"  ⚠️ Errore URL {url}: {e}")
        return None

def google_search_result(query):
    api_key = os.environ.get("GOOGLE_API_KEY")
    cse_id = os.environ.get("GOOGLE_CSE_ID")
    if not api_key or not cse_id: return None

    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.googleapis.com/customsearch/v1?key={api_key}&cx={cse_id}&q={encoded_query}"
        html = get_url(url)
        if not html: return None
        res = json.loads(html)
        if "items" in res:
            for item in res["items"]:
                snippet = item.get("snippet", "")
                match = re.search(r'(\d{2,3})\s*-\s*(\d{2,3})', snippet)
                if match: return int(match.group(1)), int(match.group(2))
    except Exception: pass
    return None

def parse_score(html, home, away):
    if not html: return None
    clean_text = re.sub('<[^<]+?>', ' ', html).lower()
    patterns = [
        rf'{home.lower()}.*?(\d{{2,3}})\s*-\s*(\d{{2,3}}).*?{away.lower()}',
        rf'{away.lower()}.*?(\d{{2,3}})\s*-\s*(\d{{2,3}}).*?{home.lower()}'
    ]
    for i, p in enumerate(patterns):
        match = re.search(p, clean_text, re.DOTALL)
        if match:
            # Se match[0] è home, ritorna (h, a), altrimenti inverte
            return (int(match.group(1)), int(match.group(2))) if i == 0 else (int(match.group(2)), int(match.group(1)))
    return None

def update_logic(matches):
    today = date.today()
    # Ripartiamo SEMPRE dai punti base per evitare accumuli errati
    new_standings = {k: v.copy() for k, v in BASE_STANDINGS.items()}
    
    for m in matches:
        match_date = datetime.strptime(m["date"], "%Y-%m-%d").date()
        team_key = m["team"]

        # 1. Se manca il punteggio ed è passata, cercalo
        if m.get("sh") is None and match_date <= today:
            print(f"🔍 Ricerca risultato: {m['home']} vs {m['away']}...")
            score = None
            pb_id = KNOWN_URLS.get(m["round"]) or ROUND_BASE_IDS.get(m["round"])
            if pb_id:
                html = get_url(f"https://www.pianetabasket.com/serie-b/live-{pb_id}")
                score = parse_score(html, m["home"], m["away"])
            
            if not score: # Fallback Google
                score = google_search_result(f"{m['home']} {m['away']} risultato basket {m['date']}")
            
            if score:
                m["sh"], m["sa"] = score[0], score[1]
                print(f"✅ Trovato: {score[0]}-{score[1]}")

        # 2. Ricalcolo punti classifica se c'è un punteggio (vecchio o nuovo)
        if m.get("sh") is not None:
            if m["sh"] > m["sa"]:
                new_standings[team_key]["pts"] += 2
                new_standings[team_key]["w"] += 1
            else:
                new_standings[team_key]["l"] += 1
    
    return new_standings

# ================================================================
# MAIN
# ================================================================

def main():
    data_file = Path("data.json")
    if not data_file.exists():
        print("❌ Errore: data.json non trovato.")
        return

    with open(data_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"🏀 Roma Basket Updater v6.7 — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    
    # Aggiorna i dati e ricalcola
    data["standings"] = update_logic(data["matches"])
    data["last_updated"] = datetime.now().strftime("%d/%m/%Y %H:%M")

    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print("💾 data.json aggiornato con successo.")

if __name__ == "__main__":
    main()
