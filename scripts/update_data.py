#!/usr/bin/env python3
import json
import os
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime, date
from pathlib import Path

# Configurazione per ricalcolo classifica se necessario
BASE_STANDINGS = {
    "virtus": {"pts": 52, "w": 26, "l": 6, "pos": 1},
    "luiss": {"pts": 38, "w": 19, "l": 12, "pos": 6}
}

def get_search_results(query):
    api_key = os.getenv("GOOGLE_API_KEY")
    cse_id = os.getenv("GOOGLE_CSE_ID")
    if not api_key or not cse_id: return None
    url = f"https://www.googleapis.com/customsearch/v1?key={api_key}&cx={cse_id}&q={urllib.parse.quote(query)}"
    try:
        with urllib.request.urlopen(url) as response:
            return json.loads(response.read().decode())
    except: return None

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
            s1, s2 = int(match.group(1)), int(match.group(2))
            return (s1, s2) if i == 0 else (s2, s1)
    return None

def validate_data(old_matches, new_matches):
    """Protezione: non salva se il numero di partite diminuisce drasticamente."""
    if len(new_matches) < len(old_matches) - 1: return False
    return True

def main():
    # Cerca il file data.json nella root partendo dalla cartella scripts/
    data_path = Path(__file__).parent.parent / "data.json"
    
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    today = date.today()
    old_matches = data.get("matches", [])
    new_matches = []

    for m in old_matches:
        nm = m.copy()
        m_date = datetime.strptime(nm["date"], "%Y-%m-%d").date()
        
        # Aggiorna solo match passati o odierni senza punteggio
        if nm.get("sh") is None and m_date <= today:
            query = f"risultato {nm['home']} {nm['away']} basket {nm['date']}"
            res = get_search_results(query)
            if res and "items" in res:
                for item in res["items"]:
                    score = parse_score(item.get("snippet", ""), nm["home"], nm["away"])
                    if score:
                        nm["sh"], nm["sa"] = score
                        break
        new_matches.append(nm)

    if not validate_data(old_matches, new_matches):
        print("🚨 Errore validazione dati. Salvataggio annullato.")
        sys.exit(1)

    data["matches"] = new_matches
    data["last_updated"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    
    # Se non esiste la chiave standings, la crea per evitare errori nel frontend
    if "standings" not in data:
        data["standings"] = BASE_STANDINGS

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"✅ Database aggiornato: {data['last_updated']}")

if __name__ == "__main__":
    main()
