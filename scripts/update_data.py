import os
import json
import re
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

# ================================================================
# CONFIGURAZIONE PERCORSI E SEGRETI
# ================================================================
DATA_FILE = Path(__file__).parent.parent / "data.json"

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID')

# ================================================================
# FUNZIONI DI SUPPORTO
# ================================================================

def google_search_fix(team_name, opponent, round_no):
    """Interroga Google per confermare date incerte (es. G35)"""
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        return None

    query = f"{team_name} vs {opponent} giornata {round_no} basket data orario 2026"
    try:
        url = f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CSE_ID}&q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.loads(r.read().decode())
            if 'items' in res:
                content = " ".join([item.get('snippet', '') for item in res['items'][:3]]).lower()
                if "11 apr" in content or "11 aprile" in content:
                    time_match = re.search(r"(\d{2}[:\.]\d{2})", content)
                    return {
                        "date": "2026-04-11",
                        "time": time_match.group(1).replace(".", ":") if time_match else "20:00"
                    }
    except Exception as e:
        print(f"  ⚠️ Errore ricerca Google: {e}")
    return None

# ================================================================
# LOGICA DI AGGIORNAMENTO
# ================================================================

def main():
    print(f"\n🏀 Roma Basket Updater v7 (Full Ticketing & Big Match)")
    print("=" * 60)

    if not DATA_FILE.exists():
        print(f"❌ Errore: Il file {DATA_FILE} non esiste!")
        return

    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    updated_count = 0
    
    # Squadre per attivare il badge Big Match
    TOP_TEAMS = ["livorno", "roseto", "piombino", "herons", "faenza", "jovesi", "fabriano", "chiusi", "fortitudo", "cantu", "pesaro"]

    for m in data.get("matches", []):
        old_date = m.get("date")
        
        # 1. FIX G35 (Variazione nota LNP)
        if str(m.get("round")) == "35" and "Virtus" in m.get("home", ""):
            g_res = google_search_fix("Virtus Roma", m["away"], 35)
            if g_res:
                m["date"], m["time"] = g_res["date"], g_res["time"]
            elif m["date"] == "2026-04-12":
                # Fallback manuale se Google non dà risultati certi
                m["date"], m["time"] = "2026-04-11", "20:00"
            
            if old_date != m["date"]:
                print(f"  📅 Data aggiornata per G35: {m['home']} vs {m['away']}")
                updated_count += 1

        # 2. ASSEGNAZIONE BIG MATCH
        # Controlliamo se l'avversaria è tra le top teams
        away_team = m.get("away", "").lower()
        m["big_match"] = any(top in away_team for top in TOP_TEAMS)

        # 3. LINK BIGLIETTI (Solo se la partita non è ancora stata giocata)
        if m.get("sh") is None: # Se non c'è punteggio, la partita è futura
            if "Virtus" in m.get("home", ""):
                m["ticket_url"] = "https://www.ticketone.it/artist/virtus-roma-1960/"
            elif "Luiss" in m.get("home", ""):
                m["ticket_url"] = "https://www.vivaticket.com/it/tour/luiss-basket-roma/3534"
            else:
                m["ticket_url"] = None
        else:
            # Se la partita è passata, rimuoviamo il link ai biglietti
            m["ticket_url"] = None

    # Aggiorna timestamp e salva
    data["last_updated"] = datetime.now().isoformat()
    
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"💾 File salvato con successo.")
    print(f"✅ Processo completato: Big Match attivati e Link Ticketing aggiornati.")

if __name__ == "__main__":
    main()
