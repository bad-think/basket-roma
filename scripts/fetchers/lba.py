"""
lba.py — Fetcher per Lega Basket Serie A (legabasket.it).

STRATEGIA v9.0 Fase 6:
    legabasket.it è un'app Next.js con rendering SSR. I dati calendario/score
    arrivano tramite endpoint REST accessibili via pagina squadra calendario.

    Due approcci in cascata:
    1. __NEXT_DATA__ JSON embedded nel HTML della pagina calendario.
    2. /_next/data/{buildId}/... endpoint (next/router prefetch).
    3. Fallback: scraping HTML della tabella partite.

    fetch_schedule() → lista di Match (solo gare CASA del team).
    fetch_scores()   → aggiorna sh/sa sulle Match esistenti.

    Stadio della competizione: "A" (Serie A LBA).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterator

from core.models import Competition, Match, Season, Team
from ._http import http_get_text
from ._text import normalize, team_name_matches

LBA_BASE = "https://www.legabasket.it"

# Regex per estrarre il punteggio dalla stringa tipo "81-79" o "81 - 79"
SCORE_RE = re.compile(r"\b(\d{2,3})\s*[-–]\s*(\d{2,3})\b")

# Pattern data LBA: "27/09/2026" o "27 set 2026"
DATE_RE = re.compile(r"(\d{1,2})[/ ](\d{2}|\w{3})[/ ](\d{4})")

MONTH_IT = {
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
    "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12,
}


def _parse_date_lba(raw: str) -> str | None:
    """Converte data LBA ('27/09/2026' o '27 set 2026') in ISO YYYY-MM-DD."""
    m = DATE_RE.search(raw or "")
    if not m:
        return None
    d, month_raw, y = m.groups()
    try:
        if month_raw.isdigit():
            mm = int(month_raw)
        else:
            mm = MONTH_IT.get(month_raw[:3].lower())
        if not mm:
            return None
        return f"{int(y):04d}-{mm:02d}-{int(d):02d}"
    except (ValueError, TypeError):
        return None


def _extract_next_data(html: str) -> dict | None:
    """Estrae __NEXT_DATA__ JSON dal HTML della pagina."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return None


def _games_from_next_data(nd: dict, team_id: int) -> list[dict]:
    """
    Naviga il JSON Next.js per trovare la lista delle partite.
    La struttura varia con il buildId; questo tenta i percorsi più comuni.
    """
    candidates = []
    # Percorso tipico Next.js: props.pageProps.games o props.pageProps.calendar
    try:
        pp = nd["props"]["pageProps"]
        for key in ("games", "matches", "calendar", "schedule", "gare"):
            if isinstance(pp.get(key), list):
                candidates = pp[key]
                break
        if not candidates:
            # fallback: cerca in profondità qualsiasi lista con chiave "date"
            def _walk(obj, depth=0):
                if depth > 8:
                    return
                if isinstance(obj, list) and obj and isinstance(obj[0], dict):
                    if any(k in obj[0] for k in ("date", "data", "home", "casa")):
                        candidates.extend(obj)
                        return
                elif isinstance(obj, dict):
                    for v in obj.values():
                        _walk(v, depth + 1)
            _walk(pp)
    except (KeyError, TypeError, IndexError):
        pass
    return candidates


class LBAFetcher:
    """
    Fetcher per Lega Basket Serie A (legabasket.it).

    Usa legabasket_id e legabasket_slug dalla competition config.
    """

    def __init__(self, competition: Competition, team: Team, season: Season):
        self.comp = competition
        self.team = team
        self.season = season
        # ID numerico squadra su legabasket.it (es. 1761 per BC Roma SPQR)
        self.lba_id: int = getattr(competition, "legabasket_id", 0)
        # Slug squadra (es. "bc-roma-spqr")
        self.lba_slug: str = getattr(competition, "legabasket_id_slug",
                                     competition.source_slug)
        # Anno inizio stagione (es. 2026 per 2026-27)
        self.lba_year: int = int(season.season.split("-")[0])

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------

    def _url_calendario(self) -> str:
        return (
            f"{LBA_BASE}/protagonisti/squadre/{self.lba_year}"
            f"/{self.lba_id}/{self.lba_slug}/calendario"
        )

    def _url_dettaglio_gare(self) -> str:
        """Pagina 'dettaglio gare' — spesso più ricca di dati score."""
        return (
            f"{LBA_BASE}/protagonisti/squadre/{self.lba_year}"
            f"/{self.lba_id}/{self.lba_slug}/dettaglio-gare"
        )

    # ------------------------------------------------------------------
    # Fetch schedule (gare CASA)
    # ------------------------------------------------------------------

    def fetch_schedule(self) -> list[Match]:
        """
        Ritorna le gare casalinghe della squadra nella stagione corrente.
        Usa prima __NEXT_DATA__, poi scraping HTML come fallback.
        """
        url = self._url_calendario()
        html = http_get_text(url)
        if not html:
            print(f"  ⚠️  [{self.team.key}] LBA calendario: nessuna risposta da {url}")
            return []

        matches = []

        # Tentativo 1: __NEXT_DATA__ JSON
        nd = _extract_next_data(html)
        if nd:
            raw_games = _games_from_next_data(nd, self.lba_id)
            matches = list(self._parse_games_json(raw_games))
            if matches:
                print(f"  📋 [{self.team.key}] LBA: {len(matches)} gare casa "
                      f"(via __NEXT_DATA__)")
                return matches

        # Tentativo 2: scraping HTML della tabella calendario
        matches = list(self._parse_games_html(html))
        if matches:
            print(f"  📋 [{self.team.key}] LBA: {len(matches)} gare casa "
                  f"(via HTML scraping)")
        else:
            print(f"  ⚠️  [{self.team.key}] LBA: nessuna gara trovata. "
                  f"Aggiornare il parser se la struttura HTML è cambiata.")

        return matches

    def _parse_games_json(self, raw_games: list[dict]) -> Iterator[Match]:
        """
        Converte i dict grezzi da __NEXT_DATA__ in Match (solo gare CASA).
        Cerca i campi home/away in vari formati (it/en).
        """
        home_keys = ("home", "homeTeam", "casa", "homeName", "home_team")
        away_keys = ("away", "awayTeam", "trasferta", "awayName", "away_team")
        date_keys = ("date", "data", "gameDate", "game_date", "matchDate")
        time_keys = ("time", "ora", "gameTime", "game_time")
        home_score_keys = ("homeScore", "home_score", "score_home", "sh", "puntiCasa")
        away_score_keys = ("awayScore", "away_score", "score_away", "sa", "puntiOspite")

        team_aliases = [self.team.display_name] + self.team.aliases

        for g in raw_games:
            if not isinstance(g, dict):
                continue

            home_name = next((g[k] for k in home_keys if g.get(k)), "")
            away_name = next((g[k] for k in away_keys if g.get(k)), "")

            # Solo gare CASA del nostro team
            if not team_name_matches(str(home_name), team_aliases):
                continue

            raw_date = next((g[k] for k in date_keys if g.get(k)), "")
            game_date = _parse_date_lba(str(raw_date))
            if not game_date:
                continue

            raw_time = next((str(g[k]) for k in time_keys if g.get(k)), "")

            sh = g.get(next((k for k in home_score_keys if k in g), ""), None)
            sa = g.get(next((k for k in away_score_keys if k in g), ""), None)
            try:
                sh = int(sh) if sh is not None else None
                sa = int(sa) if sa is not None else None
            except (ValueError, TypeError):
                sh = sa = None

            yield Match(
                id=self._make_id(game_date, normalize(str(away_name))),
                team_key=self.team.key,
                competition_id=self.comp.id,
                phase="regular",
                date=game_date,
                time=raw_time or "20:00",
                home=str(home_name),
                away=str(away_name),
                sh=sh,
                sa=sa,
                sources=["lba"],
            )

    def _parse_games_html(self, html: str) -> Iterator[Match]:
        """
        Fallback HTML: cerca righe tabella con data + squadre + punteggio.
        Assume struttura: <td class="...">data</td><td>home</td><td>score</td><td>away</td>

        ⚠️  Questo parser è fragile e andrà adattato alla struttura reale.
        Da perfezionare dopo il primo run su Actions (vedi TODO nel log).
        """
        team_aliases = [self.team.display_name] + self.team.aliases

        # Semplice euristica: cerca pattern "DD/MM/YYYY" vicino a nome squadra
        # e punteggio. La struttura precisa dipende dal layout legabasket.it.
        rows = re.findall(
            r"(\d{1,2}/\d{2}/\d{4})\s+"           # data
            r"([A-Za-zÀ-ú\s\.]+?)\s+"              # home
            r"(?:(\d{2,3})\s*[-–]\s*(\d{2,3}))?\s*"  # score (opzionale)
            r"([A-Za-zÀ-ú\s\.]+?)(?=\d{1,2}/\d{2}/\d{4}|$)",
            html,
        )
        for row in rows:
            raw_date, home_raw, sh_raw, sa_raw, away_raw = row
            if not team_name_matches(home_raw.strip(), team_aliases):
                continue
            game_date = _parse_date_lba(raw_date)
            if not game_date:
                continue
            try:
                sh = int(sh_raw) if sh_raw else None
                sa = int(sa_raw) if sa_raw else None
            except (ValueError, TypeError):
                sh = sa = None

            yield Match(
                id=self._make_id(game_date, normalize(away_raw.strip())),
                team_key=self.team.key,
                competition_id=self.comp.id,
                phase="regular",
                date=game_date,
                time="20:00",
                home=home_raw.strip(),
                away=away_raw.strip(),
                sh=sh,
                sa=sa,
                sources=["lba_html"],
            )

    # ------------------------------------------------------------------
    # Fetch scores (aggiorna sh/sa sui Match esistenti)
    # ------------------------------------------------------------------

    def fetch_scores(self, matches: list[Match]) -> list[Match]:
        """
        Aggiorna sh/sa per le partite già in lista (data <= oggi, score mancante).
        Ri-fetcha la stessa pagina calendario con filtro data.
        """
        today = datetime.today().strftime("%Y-%m-%d")
        pending = [
            m for m in matches
            if m.team_key == self.team.key
            and m.competition_id == self.comp.id
            and m.date and m.date <= today
            and (m.sh is None or m.sa is None)
        ]
        if not pending:
            return matches

        updated = self.fetch_schedule()
        score_map = {m.date: (m.sh, m.sa) for m in updated if m.sh is not None}

        count = 0
        for m in matches:
            if m.date in score_map and (m.sh is None or m.sa is None):
                m.sh, m.sa = score_map[m.date]
                if "lba" not in m.sources:
                    m.sources.append("lba")
                count += 1

        if count:
            print(f"  📊 [{self.team.key}] {count} score LBA aggiornati")
        return matches

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_id(self, date: str, away_norm: str) -> str:
        """Genera ID stabile per una gara (es. 'bcroma_lba_2026-10-04')."""
        away_short = re.sub(r"\s+", "_", away_norm)[:12]
        return f"{self.team.key}_lba_{date}_{away_short}"
