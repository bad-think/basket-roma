#!/usr/bin/env python3
"""
main.py — Orchestrator Basket Roma v9.0.

Fase 1 (corrente): smoke test del sistema.
- Carica config stagionale da config/seasons/{season}.json
- Carica state corrente da data.json (compatibilità v8.9 inclusa)
- Salva in data-v9.json (schema nativo) e/o aggiorna data.json (schema legacy)
- Nessun fetcher attivo: serve a verificare il round-trip I/O senza rompere
  nulla di v8.9.

Fase 2: si aggiungeranno i fetcher in scripts/fetchers/ e questo file li
orchestrerà secondo team.active_competitions[].fetcher.

USO:
    # smoke test Fase 1 — legge data.json, produce data-v9.json
    python scripts/main.py

    # mostra solo statistiche senza scrivere
    python scripts/main.py --dry-run

    # sovrascrive anche data.json in formato legacy (per cutover finale)
    python scripts/main.py --write-legacy
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Aggiunge la cartella scripts al PYTHONPATH per import relativi
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from core import State, Season  # noqa: E402


# ============================================================================
# PATH DI DEFAULT
# ============================================================================
ROOT = _HERE.parent
DEFAULT_CONFIG = ROOT / "config" / "seasons" / "2025-26.json"
DEFAULT_DATA = ROOT / "data.json"
OUT_V9 = ROOT / "data-v9.json"


# ============================================================================
# CLI
# ============================================================================
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Basket Roma v9.0 orchestrator")
    p.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG,
        help="Path al config stagionale (default: config/seasons/2025-26.json)",
    )
    p.add_argument(
        "--data", type=Path, default=DEFAULT_DATA,
        help="Path al data.json corrente (default: data.json)",
    )
    p.add_argument(
        "--out-v9", type=Path, default=OUT_V9,
        help="Path output schema v9.0 nativo (default: data-v9.json)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Non salva nulla, solo report",
    )
    p.add_argument(
        "--write-legacy", action="store_true",
        help="Sovrascrive anche data.json in formato legacy v8.9 (cutover)",
    )
    return p.parse_args()


# ============================================================================
# MAIN
# ============================================================================
def main() -> int:
    args = parse_args()
    print(f"\n🏀 Basket Roma v9.0 — Fase 1 (foundation) — "
          f"{datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 72)

    # 1. Load
    print(f"📂 Config: {args.config}")
    print(f"📂 Data:   {args.data}")

    try:
        state = State.load(args.config, args.data)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return 2
    except Exception as e:
        print(f"❌ Errore di caricamento: {type(e).__name__}: {e}")
        return 2

    # 2. Report
    s: Season = state.season
    print(f"\n✅ Stagione caricata: {s.season} → {s.next_season}")
    print(f"   Squadre: {len(s.teams)}")
    for t in s.teams:
        comps = ", ".join(f"{c.category}" for c in t.active_competitions)
        print(f"     • {t.key} ({t.display_name}) → {comps or 'nessuna competizione'}")

    print(f"   RSS feeds attivi: {len(s.enabled_rss())}/{len(s.rss_feeds)}")
    print(f"   Series chiuse:    {len(s.series_closed)}")
    for sc in s.series_closed:
        adv = "✓ avanza" if sc.team_advances else "✗ eliminata"
        print(f"     • {sc.team_key} vs {sc.opponent} ({sc.round_name}): "
              f"{sc.result} → {adv}")

    print(f"\n✅ State caricato")
    print(f"   {state.stats_summary()}")
    print(f"   last_updated: {state.last_updated or '—'}")
    print(f"   standings: {len(state.standings)} squadre")

    # 3. Save (se non dry-run)
    if args.dry_run:
        print("\n🔎 --dry-run: nessuna scrittura")
        return 0

    # Aggiorna timestamp prima di salvare
    state.last_updated = datetime.now().isoformat()

    print(f"\n💾 Salvataggio:")
    state.save_v9(args.out_v9)
    print(f"   ✓ {args.out_v9} (schema v9.0 nativo)")

    if args.write_legacy:
        state.save_legacy(args.data)
        print(f"   ✓ {args.data} (schema legacy v8.9)")
    else:
        print(f"   ⊘ {args.data} non toccato (usa --write-legacy per cutover)")

    print("\n✅ Completato.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
