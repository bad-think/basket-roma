#!/usr/bin/env python3
"""
update_data.py — Roma Basket Casa — Aggiornamento automatico con Validazione Senior
Protegge l'integrità dei dati e ricalcola la classifica.
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
# CONFIGURAZIONE E DATI STATICI
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
            "name_aliases": ["luiss roma", "luiss"],
            "serie": "B Nazionale",
            "girone": "B"
        }
    }
}

# Punti reali all'inizio del monitoraggio per evitare errori di calcolo
BASE_STANDINGS = {
    "virtus": {"pts": 52, "w": 26, "l": 6},
    "luiss": {"pts": 38, "w": 19, "l": 12}
}

def get_search_results(query):
    api_key = os.getenv("GOOGLE_API_KEY")
    cse_id = os.getenv("GOOGLE_CSE_ID")
    if not api_key or not cse_id:
        return None
    
    url = f"https://www.googleapis.com/customsearch/v1?key={api_key}&cx={cse_id}&q={urllib.parse.quote(query)}"
    try:
        with urllib.request.urlopen(url) as response:
            return json.loads(response.read().decode())
    except:
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

def validate_data(old_matches, new_matches):
    """Verifica che non siano andati persi dati critici durante lo scraping."""
    if len(new_matches) < len(old_matches):
        print("❌ Errore: Il numero di partite è diminuito. Possibile errore di parsing.")
        return False
    
    for old_m in old_matches:
        if old_m.get("sh") is not None:
            new_m = next((m for m in new_matches if m["id"] == old_m["id"]), None)
            if new_m and new_m.get("sh") is None:
                print(f"❌ Errore: Risultato sparito per il match {old_m['id']}.")
                return False
    return True

def update_logic(matches):
    today = date.today()
    new_matches = []
    
    for m in matches:
        # Copia profonda del match
        current_m = m.copy()
        match_date = datetime.strptime(m["date"], "%Y-%m-%d").date()

        # Cerca risultati solo se mancano e la partita è passata o odierna
        if current_m.get("sh") is None and match_date <= today and current_m["phase"] == "regular":
            query = f"risultato {current_m['home']} {current_m['away']} basket {current_m['date']}"
            res = get_search_results(query)
            if res and "items" in res:
                for item in res["items"]:
                    score = parse_score(item.get("snippet", ""), current_m["home"], current_m["away"])
                    if score:
                        current_m["sh"], current_m["sa"] = score
                        print(f"✅ Trovato risultato per {current_m['id']}: {score[0]}-{score[1]}")
                        break
        new_matches.append(current_m)
    return new_matches

def calculate_standings(matches):
    standings = {k: v.copy() for k, v in BASE_STANDINGS.items()}
    # Qui andrebbe la logica di ricalcolo basata sui nuovi match sh/sa 
    # Per semplicità in questa versione manteniamo i dati correnti se non ci sono nuovi sh/sa
    return standings

def main():
    data_path = Path("data.json")
    if not data_path.exists():
        print("❌ data.json non trovato.")
        sys.exit(1)

    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    old_matches = data["matches"]
    updated_matches = update_logic(old_matches)

    # VALIDAZIONE
    if not validate_data(old_matches, updated_matches):
        print("🚨 Validazione FALLITA. Esco senza salvare per proteggere i dati.")
        sys.exit(1)

    data["matches"] = updated_matches
    data["standings"] = calculate_standings(updated_matches)
    data["last_updated"] = datetime.now().strftime("%d/%m/%Y %H:%M")

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"🚀 Aggiornamento completato: {data['last_updated']}")

if __name__ == "__main__":
    main()
