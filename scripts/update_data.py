#!/usr/bin/env python3
"""
update_data.py — Roma Basket Casa — Versione Corretta v5.2
- Ricalcolo totale classifica da zero ad ogni avvio (Auto-correzione)
- Gestione alias per avversari (es. Faenza/Tema Sinergie)
"""

import json
import os
import re
import sys
import urllib.request
import urllib.parse
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
            "serie": "B Nazionale",
            "girone": "B"
        },
        "luiss": {
            "name": "Luiss Roma",
            "name_aliases": ["luiss roma", "luiss", "luiss basket"],
            "serie": "B Nazionale",
            "girone": "B"
        }
    }
}

# Punti di partenza (situazione a inizio girone di ritorno o data fissa)
# Se Virtus ha 52 punti prima di G34, inserisci qui i dati corretti
BASE_STANDINGS = {
    "virtus": {"pos": 1, "pts": 52, "w": 26, "l": 6}, 
    "luiss": {"pos": 6, "pts": 38, "w": 19, "l": 13}
}

# Mapping ID Pianetabasket
KNOWN_URLS = {
    34: "358236", # Virtus vs Latina
}

ROUND_BASE_IDS = {
    35: 358878, # Possibile ID per Luiss vs Faenza / Virtus vs Fabriano
    36: 359520
}

# Alias per avversari che cambiano nome (Sponsor)
OPPONENT_ALIASES = {
    "raggisolaris faenza": ["tema sinergie faenza", "faenza", "raggisolaris"],
    "janus fabriano": ["ristopro fabriano", "fabriano"],
    "benacquista latina": ["latina basket", "latina"]
}

# ================================================================
# FUNZIONI DI AGGIORNAMENTO
# ================================================================

def get_url(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode('utf-8', errors='ignore')
    except: return None

def parse_score(html, home_name, away_name):
    if not html: return None
    text = re.sub('<[^<]+?>', ' ', html).lower()
    
    # Crea liste di nomi possibili includendo alias
    home_list = [home_name.lower()] + OPPONENT_ALIASES.get(home_name.lower(), [])
    away_list = [away_name.lower()] + OPPONENT_ALIASES.get(away_name.lower(), [])

    for h in home_list:
        for a in away_list:
            pattern = rf'{re.escape(h)}.*?(\d{{2,3}})\s*-\s*(\d{{2,3}}).*?{re.escape(a)}'
            match = re.search(pattern, text, re.DOTALL)
            if match: return int(match.group(1)), int(match.group(2))
            
            pattern_rev = rf'{re.escape(a)}.*?(\d{{2,3}})\s*-\s*(\d{{2,3}}).*?{re.escape(h)}'
            match_rev = re.search(pattern_rev, text, re.DOTALL)
            if match_rev: return int(match_rev.group(2)), int(match_rev.group(1))
    return None

def recalculate_all_standings(matches):
    """Ricalcola la classifica da zero basandosi sui match nel JSON"""
    new_standings = {k: dict(v) for k, v in BASE_STANDINGS.items()}
    
    for m in matches:
        if m.get("sh") is not None and m.get("sa") is not None:
            tk = m["team"]
            if tk in new_standings:
                # Se la squadra del file (Virtus o Luiss) è in casa
                is_home = (m["home"].lower() in CONFIG["teams"][tk]["name_aliases"])
                
                win = False
                if is_home and m["sh"] > m["sa"]: win = True
                elif not is_home and m["sa"] > m["sh"]: win = True
                
                if win:
                    new_standings[tk]["pts"] += 2
                    new_standings[tk]["w"] += 1
                else:
                    new_standings[tk]["l"] += 1
    return new_standings

# ================================================================
# MAIN
# ================================================================

def main():
    data_file = Path("data.json")
    if not data_file.exists(): return
    
    with open(data_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    matches = data.get("matches", [])
    today = date.today()
    updated_any = False

    print(f"🔍 Controllo aggiornamenti per il {today}...")

    for m in matches:
        m_date = datetime.strptime(m["date"], "%Y-%m-%d").date()
        if m_date <= today and m.get("sh") is None:
            pb_id = KNOWN_URLS.get(m["round"]) or ROUND_BASE_IDS.get(m["round"])
            if pb_id:
                url = f"https://www.pianetabasket.com/serie-b/live-{pb_id}"
                html = get_url(url)
                score = parse_score(html, m["home"], m["away"])
                if score:
                    m["sh"], m["sa"] = score[0], score[1]
                    print(f"✅ G{m['round']}: {m['home']} {score[0]}-{score[1]} {m['away']}")
                    updated_any = True

    # RICALCOLO TOTALE SEMPRE (Risolve il problema della classifica bloccata)
    data["standings"] = recalculate_all_standings(matches)
    data["last_updated"] = datetime.now().isoformat()
    
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print("✅ Classifica ricalcolata e file data.json salvato.")

if __name__ == "__main__":
    main()
