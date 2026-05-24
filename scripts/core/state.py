"""
state.py — Gestione dello stato applicativo.

State è il contenitore di tutti i dati dinamici:
- Lista delle partite (Match)
- Classifica (Standing) per squadra
- Timestamp ultimo aggiornamento

Responsabilità:
1. Caricare config (Season) da config/seasons/{season}.json
2. Caricare state da data.json (con backward compat v8.9)
3. Applicare match_id_overrides da config (Fase 2.3a→b transition)
4. Mergeare nuovi match preservando dati esistenti (sh/sa non null)
5. Salvare in formato v8.9 (legacy) e/o v9.0 (nativo)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Match, Season, Standing


@dataclass
class State:
    """Stato dinamico del sistema: partite + classifiche + metadata."""
    season: Season                                # config statica della stagione
    matches: list[Match] = field(default_factory=list)
    standings: dict[str, Standing] = field(default_factory=dict)  # team_key → Standing
    last_updated: str = ""                        # ISO datetime

    # ------------------------------------------------------------------
    # LOAD
    # ------------------------------------------------------------------
    @classmethod
    def load(cls, season_config_path: Path | str, data_path: Path | str) -> "State":
        """
        Carica state combinando config stagionale + data.json esistente.

        Args:
            season_config_path: percorso a config/seasons/{season}.json
            data_path: percorso a data.json (o data-v9.json)
        """
        # 1. Carica config stagionale (obbligatorio)
        season_config_path = Path(season_config_path)
        if not season_config_path.exists():
            raise FileNotFoundError(f"Config stagione non trovata: {season_config_path}")

        with open(season_config_path, encoding="utf-8") as f:
            season_data = json.load(f)
        season = Season.from_dict(season_data)

        # 2. Carica data.json (opzionale: se non esiste, parte vuoto)
        data_path = Path(data_path)
        matches: list[Match] = []
        standings: dict[str, Standing] = {}
        last_updated = ""

        if data_path.exists():
            with open(data_path, encoding="utf-8") as f:
                data = json.load(f)

            # Match: gestisce sia schema v9.0 nativo che legacy v8.9
            for m_dict in data.get("matches", []):
                try:
                    matches.append(Match.from_dict(m_dict))
                except (KeyError, TypeError) as e:
                    print(f"⚠️  Match skippata (parsing): {m_dict.get('id', '?')} — {e}")

            # Standings
            for team_key, s_dict in (data.get("standings") or {}).items():
                if isinstance(s_dict, dict):
                    standings[team_key] = Standing.from_dict(s_dict)

            last_updated = data.get("last_updated", "")

            # Se data.json ha series_closed (v8.9.2 layout), arricchisce season
            # — utile durante la transizione finché data.json contiene anche config
            legacy_series_closed = (data.get("config") or {}).get("series_closed", [])
            if legacy_series_closed and not season.series_closed:
                from .models import SeriesClosed
                season.series_closed = [
                    SeriesClosed.from_dict(s) for s in legacy_series_closed
                ]

        # 3. Applica match_id_overrides (Fase 2.3a→b transition)
        # Popola external_id su Match esistenti quando il config specifica un mapping.
        # Usato per: (a) validazione Fase 2.3a senza discovery, (b) edge case
        # dove Fase 2.3b discovery fallisce.
        applied = _apply_match_id_overrides(matches, season.match_id_overrides)
        if applied:
            print(f"  🔗 Applicati {applied} match_id_overrides da config")

        return cls(
            season=season,
            matches=matches,
            standings=standings,
            last_updated=last_updated,
        )

    # ------------------------------------------------------------------
    # SAVE
    # ------------------------------------------------------------------
    def save_v9(self, path: Path | str) -> None:
        """Salva nello schema v9.0 nativo (per data-v9.json di test)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "$schema_version": "9.0",
            "last_updated": self.last_updated or datetime.now().isoformat(),
            "season": self.season.season,
            "config": self.season.to_dict(),
            "matches": [m.to_dict() for m in self._sorted_matches()],
            "standings": {k: v.to_dict() for k, v in self.standings.items()},
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def save_legacy(self, path: Path | str) -> None:
        """
        Salva nello schema legacy v8.9 per retrocompatibilità con frontend attuale.
        Usato durante la transizione finché il frontend non viene rifatto in Fase 3.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Ricostruisce la sezione config legacy (teams come dict, non lista)
        legacy_teams: dict[str, dict[str, Any]] = {}
        for t in self.season.teams:
            legacy_teams[t.key] = {
                "name": t.display_name,
                "name_aliases": t.aliases,
                # Per legacy: prima competition come "serie" + "girone"
                "serie": t.active_competitions[0].category if t.active_competitions else "",
                "girone": t.active_competitions[0].girone if t.active_competitions else "",
                "venue_name": t.venue.name if t.venue else "",
                "venue_address": t.venue.address if t.venue else "",
                "venue_maps": t.venue.maps_url if t.venue else "",
            }

        legacy_series_closed = [
            {
                "team": s.team_key,
                "opponent": s.opponent,
                "phase": s.phase,
                "round_name": s.round_name,
                "result": s.result,
                "team_advances": s.team_advances,
                "note": s.note,
            }
            for s in self.season.series_closed
        ]

        payload = {
            "last_updated": self.last_updated or datetime.now().isoformat(),
            "season": self.season.season,
            "config": {
                "season": self.season.season,
                "next_season": self.season.next_season,
                "teams": legacy_teams,
                "classifica_url": self.season.league_classifica_url,
                "series_closed": legacy_series_closed,
            },
            "matches": [m.to_legacy_dict() for m in self._sorted_matches()],
            "standings": {k: v.to_dict() for k, v in self.standings.items()},
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # MERGE
    # ------------------------------------------------------------------
    def merge_matches(self, new_matches: list[Match]) -> int:
        """
        Mergea nuove partite preservando dati esistenti.

        Regole:
        - Match con stesso (team_key, date, away_normalized) → aggiorna campi
          MA preserva sh/sa esistenti se i nuovi sono None (no overwrite con vuoto).
        - Match senza corrispondenza → aggiunge alla lista.

        Returns:
            Numero di match modificati o aggiunti.
        """
        changed = 0
        for nm in new_matches:
            idx = self._find_match_index(nm)
            if idx is None:
                self.matches.append(nm)
                changed += 1
                continue
            # Aggiornamento: preserva score esistenti se nuovi sono None
            existing = self.matches[idx]
            if self._update_match(existing, nm):
                changed += 1
        # Riapplica match_id_overrides anche ai nuovi Match aggiunti
        _apply_match_id_overrides(self.matches, self.season.match_id_overrides)
        return changed

    def _find_match_index(self, m: Match) -> int | None:
        """Trova indice di match esistente per (team_key, date, away normalizzato)."""
        away_n = _normalize(m.away)
        for i, em in enumerate(self.matches):
            if em.team_key != m.team_key:
                continue
            if em.date != m.date:
                continue
            if _normalize(em.away) == away_n:
                return i
        return None

    @staticmethod
    def _update_match(existing: Match, new: Match) -> bool:
        """Aggiorna existing con campi non-None di new. Ritorna True se cambiato."""
        changed = False
        # Score: aggiorna solo se nuovo non è None e diverso
        if new.sh is not None and new.sh != existing.sh:
            existing.sh = new.sh
            changed = True
        if new.sa is not None and new.sa != existing.sa:
            existing.sa = new.sa
            changed = True
        # Time: aggiorna se diverso (LNP affina orario)
        if new.time and new.time != existing.time:
            existing.time = new.time
            changed = True
        # Tentative: può sbloccarsi
        if existing.tentative and not new.tentative:
            existing.tentative = False
            changed = True
        # Sources: union
        for src in new.sources:
            if src not in existing.sources:
                existing.sources.append(src)
                changed = True
        # Series_id, game_num: imposta se non presenti
        if new.series_id and not existing.series_id:
            existing.series_id = new.series_id
            changed = True
        if new.game_num is not None and existing.game_num is None:
            existing.game_num = new.game_num
            changed = True
        # external_id: imposta se nuovo specificato e esistente vuoto
        if new.external_id and not existing.external_id:
            existing.external_id = new.external_id
            changed = True
        # Periods: imposta se esistente vuoto
        if new.periods and not existing.periods:
            existing.periods = new.periods
            changed = True
        return changed

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------
    def _sorted_matches(self) -> list[Match]:
        """Match ordinati per data, poi team_key (deterministico)."""
        return sorted(self.matches, key=lambda m: (m.date, m.team_key, m.id))

    def matches_for_team(self, team_key: str) -> list[Match]:
        return [m for m in self.matches if m.team_key == team_key]

    def matches_for_competition(self, competition_id: str) -> list[Match]:
        return [m for m in self.matches if m.competition_id == competition_id]

    def stats_summary(self) -> str:
        """Ritorna riepilogo testuale per logging."""
        by_team: dict[str, int] = {}
        by_phase: dict[str, int] = {}
        for m in self.matches:
            by_team[m.team_key] = by_team.get(m.team_key, 0) + 1
            by_phase[m.phase] = by_phase.get(m.phase, 0) + 1
        team_part = ", ".join(f"{k}={v}" for k, v in sorted(by_team.items()))
        phase_part = ", ".join(f"{k}={v}" for k, v in sorted(by_phase.items()))
        return f"matches={len(self.matches)} | by_team[{team_part}] | by_phase[{phase_part}]"


# ============================================================================
# UTIL
# ============================================================================
def _normalize(s: str) -> str:
    """Normalizza nome squadra per matching (lower + no whitespace extra)."""
    if not s:
        return ""
    return " ".join(s.lower().strip().split())


def _apply_match_id_overrides(
    matches: list[Match],
    overrides: list[dict[str, str]],
) -> int:
    """
    Applica override manuali di external_id su Match esistenti.

    Ogni override è un dict con keys: team_key, date, away, external_id.
    Match matchata se (team_key, date, normalize(away)) corrispondono.
    Non sovrascrive external_id già popolato.

    Returns: numero di Match aggiornate.
    """
    if not overrides:
        return 0
    applied = 0
    for ov in overrides:
        ov_team = ov.get("team_key", "")
        ov_date = ov.get("date", "")
        ov_away_n = _normalize(ov.get("away", ""))
        ov_id = ov.get("external_id", "")
        if not (ov_team and ov_date and ov_away_n and ov_id):
            continue
        for m in matches:
            if m.team_key != ov_team:
                continue
            if m.date != ov_date:
                continue
            if _normalize(m.away) != ov_away_n:
                continue
            if not m.external_id:
                m.external_id = ov_id
                applied += 1
            break  # un override → al massimo una Match
    return applied
