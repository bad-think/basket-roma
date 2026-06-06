#!/usr/bin/env python3
"""
main.py — Orchestrator Basket Roma v9.0.

Fase 2: invoca i fetcher per ogni (team, competition).
- Per ogni team in config:
    Per ogni active_competition:
        - Istanzia il fetcher giusto via REGISTRY
        - fetch_schedule() → lista Match
        - state.merge_matches() → preserva esistenti, aggiunge nuovi
        - fetch_scores() → aggiorna sh/sa dai canali del fetcher
- Singleton: RssPoolFetcher cross-team per score residui mancanti

USO:
    python scripts/main.py                  # esegue tutto, scrive data-v9.json
    python scripts/main.py --dry-run        # solo report, no scritture, no rete
    python scripts/main.py --no-fetch       # legge state, no chiamate esterne
    python scripts/main.py --write-legacy   # aggiorna anche data.json (cutover)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# PYTHONPATH setup
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from core import State, Season  # noqa: E402
from fetchers import REGISTRY, RssPoolFetcher  # noqa: E402


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
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--data", type=Path, default=DEFAULT_DATA)
    p.add_argument("--out-v9", type=Path, default=OUT_V9)
    p.add_argument("--dry-run", action="store_true",
                   help="Solo report, no scritture, no rete")
    p.add_argument("--no-fetch", action="store_true",
                   help="Legge state ma non chiama fetcher (utile per test offline)")
    p.add_argument("--write-legacy", action="store_true",
                   help="Aggiorna anche data.json in formato legacy v8.9")
    return p.parse_args()


# ============================================================================
# ORCHESTRATOR
# ============================================================================
def run_fetchers(state: State) -> None:
    """
    Esegue tutti i fetcher per ogni (team, competition) attiva.
    Aggiorna state.matches in-place.
    """
    season = state.season

    # 1. Fase per-competition: schedule + score primario
    for team in season.teams:
        for comp in team.active_competitions:
            FetcherCls = REGISTRY.get(comp.fetcher)
            if FetcherCls is None:
                print(f"  ⚠️  Fetcher '{comp.fetcher}' non registrato "
                      f"(team={team.key}, comp={comp.id})")
                continue

            print(f"\n🔍 [{team.key}] {comp.category} via {comp.fetcher}")
            try:
                fetcher = FetcherCls(competition=comp, team=team, season=season)
            except Exception as e:
                print(f"  ❌ Init fetcher: {type(e).__name__}: {e}")
                continue

            # Schedule
            try:
                new_matches = fetcher.fetch_schedule()
                if new_matches:
                    print(f"  📋 Schedule: {len(new_matches)} match recuperati")
                    changed = state.merge_matches(new_matches)
                    print(f"  ✏️  Merge: {changed} match modificati/aggiunti")
                else:
                    print(f"  · Schedule: nessuna nuova partita "
                          f"(regular gestita da v8.9, playoff: in attesa LNP)")
            except Exception as e:
                print(f"  ⚠️  fetch_schedule fallito: {type(e).__name__}: {e}")

            # Score primario via fetcher specifico
            try:
                state.matches = fetcher.fetch_scores(state.matches)
            except Exception as e:
                print(f"  ⚠️  fetch_scores fallito: {type(e).__name__}: {e}")

    # 2. Fase cross-team: RSS pool per score ancora mancanti
    enabled_rss = season.enabled_rss()
    if enabled_rss:
        print(f"\n🌐 RSS Pool: {len(enabled_rss)} feed attivi")
        pool = RssPoolFetcher(enabled_rss)
        try:
            pool.refresh()
            updated_via_rss = _apply_rss_pool(state, pool)
            if updated_via_rss:
                print(f"  ✅ RSS pool: {updated_via_rss} score aggiornati")
            else:
                print(f"  · RSS pool: nessuno score nuovo trovato")
        except Exception as e:
            print(f"  ⚠️  RSS pool fallito: {type(e).__name__}: {e}")


def _apply_rss_pool(state: State, pool: RssPoolFetcher) -> int:
    """
    Per ogni match senza score, prova a recuperarlo dal pool RSS.
    Ritorna numero di match aggiornati.
    """
    updated = 0
    # Indicizza aliases per team_key per matching veloce
    aliases_by_team: dict[str, list[str]] = {}
    for t in state.season.teams:
        aliases_by_team[t.key] = [t.display_name] + t.aliases

    for m in state.matches:
        if m.sh is not None and m.sa is not None:
            continue
        # Solo partite passate (oggi o precedenti)
        try:
            m_date = datetime.strptime(m.date, "%Y-%m-%d").date()
        except ValueError:
            continue
        if m_date > datetime.now().date():
            continue

        home_aliases = aliases_by_team.get(m.team_key, [m.home])
        # Per l'opponent usiamo solo il nome dal match (non in config)
        away_aliases = [m.away]
        score = pool.find_score(m, home_aliases, away_aliases)
        if score:
            m.sh, m.sa = score
            if "rss" not in m.sources:
                m.sources.append("rss")
            updated += 1
    return updated


# ============================================================================
# MAIN
# ============================================================================
def main() -> int:
    args = parse_args()
    print(f"\n🏀 Basket Roma v9.0 — Fase 2.1 (Hybrid) — "
          f"{datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 72)

    # Load
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

    s: Season = state.season
    print(f"\n✅ Stagione: {s.season} | Squadre: {len(s.teams)} | "
          f"RSS attivi: {len(s.enabled_rss())}/{len(s.rss_feeds)} | "
          f"Series chiuse: {len(s.series_closed)}")
    print(f"   {state.stats_summary()}")

    # Fetch
    if args.dry_run or args.no_fetch:
        print(f"\n🔎 Modalità {'dry-run' if args.dry_run else 'no-fetch'}: salto fetcher")
    else:
        run_fetchers(state)

    print(f"\n📊 Stato finale: {state.stats_summary()}")

    if args.dry_run:
        return 0

    # Save
    state.last_updated = datetime.now().isoformat()
    print(f"\n💾 Salvataggio:")
    state.save_v9(args.out_v9)
    print(f"   ✓ {args.out_v9} (schema v9.0)")
    if args.write_legacy:
        state.save_legacy(args.data)
        print(f"   ✓ {args.data} (schema legacy v8.9)")
    else:
        print(f"   ⊘ {args.data} non toccato (usa --write-legacy per cutover)")

    print("\n✅ Completato.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
