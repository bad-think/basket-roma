#!/usr/bin/env python3
"""
update_data.py — Roma Basket Casa — Aggiornamento automatico v6.8
Ricalcola la classifica partendo dai punti base corretti per evitare discrepanze.
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
            "name_aliases": ["virtus gvm roma", "virtus roma", "virtus gvm roma 1960", "pallacanestro virtus roma"],
            "serie": "B Nazionale",
            "girone": "B",
            "venue_name": "PalaTiziano – Palazzetto dello Sport",
            "venue_address": "Piazza Apollodoro 10, 00196 Roma",
            "venue_maps": "https://maps.google.com/?q=Palazzetto+dello+Sport+Piazza+Apollodoro+10+Roma"
        },
        "luiss": {
            "name": "Luiss Roma",
            "name_aliases": ["luiss roma", "luiss", "luiss basketball"],
            "serie": "B Nazionale",
            "girone": "B",
            "venue_name": "PalaTiziano – Palazzetto dello Sport",
            "venue_address": "Piazza Apollodoro 10, 00196 Roma",
            "venue_maps": "https://maps.google.com/?q=Palazzetto+dello+Sport+Piazza+Apollodoro+10+Roma"
        }
    }
}

# BASE_STANDINGS TARATA SUI MATCH NEL JSON:
# Virtus: 46 base + (3 vittorie nel JSON: v31, v33, v34) = 52 punti totali.
# Luiss: 36 base + (1 vittoria v31 nel JSON) = 38 punti totali.
BASE_STANDINGS = {
    "virtus": {"pos": 1, "pts": 46, "w": 23, "l": 6},
    "luiss": {"pos": 6, "pts": 36, "w": 18, "l": 11}
}

KNOWN_URLS = {
    31: "356237", 32: "357140", 33: "357782", 34: "358236"
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
        
        # Cerca punteggio o orario nello snippet
        if "items" in res:
            for item in res["items"]:
                snippet = item.get("snippet", "")
                
                # Cerca punteggio (es. 87-57)
                score_match = re.search(r'(\d{2,3})\s*-\s*(\d{2,3})', snippet)
                
                # Cerca orario (es. 21:00)
                time_match = re.search(r'(\d{2}:\d{2})', snippet)
                
                return {
                    "score": (int(score_match.group(1)), int(score_match.group(2))) if score_match else None,
                    "time": time_match.group(1) if time_match else None
                }
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
            return (int(match.group(1)), int(match.group(2))) if i == 0 else (int(match.group(2)), int(match.group(1)))
    return None

def update_logic(matches):
    today = date.today()
    new_standings = {k: v.copy() for k, v in BASE_STANDINGS.items()}
    
    for m in matches:
        match_date = datetime.strptime(m["date"], "%Y-%m-%d").date()
        team_key = m["team"]

        # Se manca il punteggio o l'orario è sospetto, cerca aggiornamenti
        if m.get("sh") is None or (m.get("time") == "15:00" and match_date >= today):
            print(f"🔍 Controllo {m['id']} - {m['home']} vs {m['away']}...")
            
            search_res = google_search_result(f"{m['home']} {m['away']} basket {m['date']}")
            
            if search_res:
                # Aggiorna orario se trovato
                if search_res.get("time") and m["time"] != search_res["time"]:
                    print(f"  ⏰ Nuovo orario trovato: {search_res['time']}")
                    m["time"] = search_res["time"]
                
                # Aggiorna punteggio se la
