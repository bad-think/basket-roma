#!/usr/bin/env python3
import json
import os
import re
from datetime import datetime, date
from pathlib import Path

# Punti base corretti al 09/04/2026
BASE_STANDINGS = {
    "virtus": {"pts": 54, "w": 27, "l": 7, "pos": 1},
    "luiss": {"pts": 40, "w": 20, "l": 14, "pos": 6}
}

def main():
    # Percorso dinamico per funzionare su GitHub Actions
    base_dir = Path(__file__).parent.parent
    data_path = base_dir / "data.json"
    
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # In questa versione ci limitiamo ad aggiornare il timestamp
    # Lo script è pronto per lo scraping se aggiungi le API Google
    data["last_updated"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    
    # Assicurati che la classifica sia presente
    if "standings" not in data:
        data["standings"] = BASE_STANDINGS

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Dati aggiornati con successo alle {data['last_updated']}")

if __name__ == "__main__":
    main()
