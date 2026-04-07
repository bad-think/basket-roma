#!/usr/bin/env python3
"""
update_data.py — Roma Basket Casa — Aggiornamento automatico v5
Usa Google Custom Search API per trovare gli URL reali di pianetabasket
senza dover stimare gli ID.
"""

import json
import os
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime, date, timedelta
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
            "name_aliases": [
                "virtus gvm roma", "virtus roma", "virtus gvm roma 1960",
                "pallacanestro virtus roma"
            ],
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

BASE_STANDINGS = {
    "virtus": {"pos": 1, "pts": 52, "w": 26, "l": 6},
    "luiss": {"pos": 6, "pts": 38, "w": 19, "l": 13}
}

# Mapping ID reali per evitare errori di stima (Pianetabasket)
KNOWN_URLS = {
    31: "356237",
    32: "357140",
    33: "357782",
    34: "358236", # Virtus vs Latina ID REALE
}

# Ricalcolo stime per le ultime giornate basato su G34
ROUND_BASE_IDS = {
    35: 358878, 
    36: 359520, 
    37: 360162, 
    38: 360804
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
        print(f"  ⚠️  {url}: {e}")
        return None

def google_search_result(query):
    api_key = os.environ.get("GOOGLE_API_KEY")
    cse_id  = os.environ.get("GOOGLE_CSE_ID")
    if not api_key or not cse_id:
        return None

    encoded_query = urllib.parse.quote(query)
    url = f"https://www.googleapis.com/customsearch/v1?key={api_key}&cx={cse_id}&q={encoded_query}"
    
    # Debug opzionale per i log di GitHub Actions
    # print(f"  🔍 Google Search: {query}") 

    try:
        res_json = json.loads(get_url(url))
        if "items" in res_json:
            for item in res_json["items"]:
                snippet = item.get("snippet", "")
                # Cerca pattern punteggio (es. 87-57 o 87 - 57)
                match = re.search(r'(\d{2,3})\s*-\s*(\d{2,3})', snippet)
                if match:
                    return int(match.group(1)), int(match.group(2))
    except Exception as e:
        print(f"  ⚠️  Google Search error: {e}")
    return None

def parse_score(html, team_name, opponent_name):
    if not html: return None
    
    # Cerca il blocco del punteggio nel testo
    clean_text = re.sub('<[^<]+?>', ' ', html).lower()
    
    # Pattern: NomeTeam 87 - 57 NomeAvversario
    pattern = rf'{team_name.lower()}.*?(\d{{2,3}})\s*-\s*(\d{{2,3}}).*?{opponent_name.lower()}'
    match = re.search(pattern, clean_text, re.DOTALL)
    if match:
        return int(match.group(1)), int(match.group(2))
    
    # Pattern inverso: NomeAvversario 57 - 87 NomeTeam
    pattern_rev = rf'{opponent_name.lower()}.*?(\d{{2,3}})\s*-\s*(\d{{2,3}}).*?{team_name.lower()}'
    match_rev = re.search(pattern_rev, clean_text, re.DOTALL)
    if match_rev:
        return int(match_rev.group(2)), int(match_rev.group(1))
        
    return None

def update_in_season(matches, config, standings):
    updated_count = 0
    today = date.today()

    for m in matches:
        # Aggiorna solo se la partita è passata e non ha ancora un punteggio
        match_date = datetime.strptime(m["date"], "%Y-%m-%d").date()
        if match_date <= today and m.get("sh") is None:
            
            round_num = m["round"]
            team_key  = m["team"]
            t_config  = config["teams"][team_key]
            
            print(f"  ✅ G{round_num}: cerco risultato per {m['home']} vs {m['away']}")

            score = None

            # 1. Prova con URL Conosciuto o Stimato su Pianetabasket
            pb_id = KNOWN_URLS.get(round_num) or ROUND_BASE_IDS.get(round_num)
            if pb_id:
                pb_url = f"https://www.pianetabasket.com/serie-b/live-{pb_id}"
                html = get_url(pb_url)
                score = parse_score(html, m["home"], m["away"])
                if score:
                    print(f"  ✅ pianetabasket → {m['home']} vs {m['away']}: {score[0]}-{score[1]}")

            # 2. Fallback: Google Search Snippet
            if not score:
                query = f"{m['home']} {m['away']} risultato basket {m['date']}"
                score = google_search_result(query)
                if score:
                    print(f"  ✅ google → {m['home']} vs {m['away']}: {score[0]}-{score[1]}")

            if score:
                m["sh"], m["sa"] = score[0], score[1]
                updated_count += 1
                
                # Aggiorna Standings (Semplificato: +2pt se vince casa, +0 se perde)
                if m["sh"] > m["sa"]:
                    standings[team_key]["pts"] += 2
                    standings[team_key]["w"] += 1
                else:
                    standings[team_key]["l"] += 1

    return updated_count, standings

# ================================================================
# MAIN
# ================================================================

def main():
    print(f"🏀 Roma Basket Updater v5.1 — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=======================================================")
    
    data_file = Path("data.json")
    if data_file.exists():
        with open(data_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        matches   = data.get("matches", [])
        standings = data.get("standings", dict(BASE_STANDINGS))
        config    = data.get("config", CONFIG)
        print(f"📂 Caricato — {len(matches)} partite")
    else:
        matches   = []
        standings = dict(BASE_STANDINGS)
        config    = CONFIG
        print("📂 Primo avvio — generazione file")

    today = date.today()
    
    # Esegui aggiornamento
    total_updated, updated_standings = update_in_season(matches, config, standings)
    
    # Salva i risultati
    output = {
        "last_updated": datetime.now().isoformat(),
        "season": config.get("season", "2025-26"),
        "config": config,
        "matches": matches,
        "standings": updated_standings
    }

    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n📝 Aggiornamenti effettuati: {total_updated}")
    print("💾 Salvato — data.json aggiornato.")
    print("✅ Completato!")

if __name__ == "__main__":
    main()
