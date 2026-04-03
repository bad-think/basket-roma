import os
import json
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime, date, timedelta
from pathlib import Path

# ================================================================
# CONFIGURAZIONE PERCORSI E SEGRETI
# ================================================================
# Definisce il percorso di data.json che si trova nella cartella superiore rispetto a questo script
DATA_FILE = Path(__file__).parent.parent / "data.json"

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID')

# ================================================================
# FUNZIONE RICERCA GOOGLE
# ================================================================

def google_search_fix(team_name, opponent, round_no):
    """Interroga Google per confermare date incerte (es. G35)"""
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        print("  ⚠️ Chiavi Google non trovate nei Secrets.")
        return None

    query = f"{team_name} vs {opponent} giornata {round_no} basket data orario 2026"
    encoded_query = urllib.parse.quote(query)
    url = f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CSE_ID}&q={encoded_query}"
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read().decode())
            if 'items' in res:
                # Analizziamo i primi 3 snippet per trovare la conferma del 11 aprile
                content = " ".join([item.get('snippet', '') for item in res['items'][:3]]).lower()
                
                if "11 apr" in content or "11 aprile" in content:
                    time_match = re.search(r"(\d{2}[:\.]\d{2})", content)
                    return {
                        "date": "2026-04-11",
                        "time": time_match.group(1).replace(".", ":") if time_match else "20:00"
                    }
    except Exception as e:
        print(f"  ⚠️ Errore durante la ricerca Google: {e}")
    return None

# ================================================================
# LOGICA DI AGGIORNAMENTO
# ================================================================

def main():
    print(f"\n🏀 Roma Basket Updater v6 (Google Search) — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 60)

    if not DATA_FILE.exists():
        print(f"❌ Errore: Il file {DATA_FILE} non esiste!")
        return

    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    updated_count = 0
    
    # Ciclo sulle partite per applicare i fix
    for m in data.get("matches", []):
        # FIX SPECIFICO PER LA G35 (Variazione LNP nota)
        if str(m.get("round")) == "35" and "Virtus" in m.get("home", ""):
            print(f"🔍 Controllo variazione G35: {m['home']} vs {m['away']}...")
            
            # Proviamo a usare Google Search
            google_res = google_search_fix("Virtus Roma", m["away"], 35)
            
            if google_res:
                if m["date"] != google_res["date"] or m["time"] != google_res["time"]:
                    m["date"] = google_res["date"]
                    m["time"] = google_res["time"]
                    print(f"  ✅ G35 AGGIORNATA VIA GOOGLE: {m['date']} alle {m['time']}")
                    updated_count += 1
            else:
                # Fallback manuale di emergenza se Google non risponde ma sappiamo che la data è cambiata
                if m["date"] == "2026-04-12":
                    m["date"] = "2026-04-11"
                    m["time"] = "20:00"
                    print("  ✅ G35 AGGIORNATA (Fallback manuale): 11 apr ore 20:00")
                    updated_count += 1

    # Aggiorna il timestamp dell'ultimo controllo
    data["last_updated"] = datetime.now().isoformat()

    # Salva il file
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 Salvataggio completato. Partite modificate: {updated_count}")
    print("✅ Processo terminato correttamente.")

if __name__ == "__main__":
    main()
