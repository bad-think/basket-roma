"""
lnp.py — Fetcher per Lega Nazionale Pallacanestro (Hybrid mode).

STRATEGIA v9.0 HYBRID:
v9 NON re-implementa il parser calendario regular season LNP. Quella logica
è in v8.9 update_data.py (~2000 righe raffinate negli anni) e gira già su
main: produce data.json affidabile per regular season + score.

v9 si limita a:
1. Bracket playoff parser — generazione automatica gare SF/F/Playout quando
   LNP pubblica il testo strutturato del tabellone (regex pattern stabile).
2. Score widget refresh — letture occasionali della pagina squadra LNP per
   score di gare playoff (delay <12h vs RSS).
3. Filter series_closed — impedisce re-inserzione di gare obsolete.

Quando in futuro servirà fetcher per Coppa Italia LNP, riusiamo questa
stessa classe (stesso dominio, formato bracket simile).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Iterator

from core.models import Competition, Match, Season, Team
from ._http import http_get_text
from ._text import normalize, team_name_matches, strip_html


LNP_BASE = "https://www.legapallacanestro.com"

CATEGORY_TO_SERIE_NUM = {
    "B Nazionale": 4,
    "A2": 3,
}

PLAYOFF_PAGE_CODES = {
    "B Nazionale": ["ita3_a_poff", "ita3_b_poff"],
    "A2": ["ita2_a2_poff"],
}


class LNPFetcher:
    """
    Fetcher LNP focalizzato su playoff/bracket (modalità Hybrid).
    """

    def __init__(self, competition: Competition, team: Team, season: Season):
        self.comp = competition
        self.team = team
        self.season = season

    # ==================================================================
    # API PUBBLICA
    # ==================================================================
    def fetch_schedule(self) -> list[Match]:
        """
        Ritorna nuove partite IN CASA dalla pagina playoff LNP.

        Regular season NON gestita qui: competenza di v8.9 update_data.py
        che gira su main. Le partite regular esistono già in data.json
        (caricate da state.load).
        """
        if "playoff" not in self.comp.phases:
            return []
        playoff = self._fetch_playoff_bracket()
        return self._filter_closed_series(playoff)

    def fetch_scores(self, matches: list[Match]) -> list[Match]:
        """
        Aggiorna sh/sa per gare playoff della squadra senza score.
        Strategia Hybrid: solo per gare playoff (regular gestite da v8.9).
        """
        targets = [
            m for m in matches
            if m.team_key == self.team.key
            and m.competition_id == self.comp.id
            and m.phase in ("playoff", "playout")
            and (m.sh is None or m.sa is None)
        ]
        if not targets:
            return matches

        team_slug = self._guess_team_slug()
        html = http_get_text(f"{LNP_BASE}/squadra/{team_slug}")
        if not html:
            return matches

        text = strip_html(html)
        updated = 0
        for m in targets:
            sh_sa = self._find_score_in_team_page(text, m)
            if sh_sa:
                m.sh, m.sa = sh_sa
                if "lnp_widget" not in m.sources:
                    m.sources.append("lnp_widget")
                updated += 1
        if updated:
            print(f"  📊 [{self.team.key}] {updated} score playoff da LNP widget")
        return matches

    # ==================================================================
    # BRACKET PARSER (cuore del fetcher Hybrid)
    # ==================================================================
    def _fetch_playoff_bracket(self) -> list[Match]:
        serie_num = CATEGORY_TO_SERIE_NUM.get(self.comp.category)
        if serie_num is None:
            return []
        anno = self._infer_year()
        codes = PLAYOFF_PAGE_CODES.get(self.comp.category, [])
        if not codes:
            return []

        team_aliases = [self.team.display_name] + self.team.aliases
        for code in codes:
            url = f"{LNP_BASE}/serie/{serie_num}/playoff-playout/{anno}/{code}"
            html = http_get_text(url)
            if not html:
                continue
            text = strip_html(html)
            games = list(self._parse_bracket_for_team(text, team_aliases))
            if games:
                print(f"  📡 [{self.team.key}] {len(games)} gare casa playoff "
                      f"dal codice {code}")
                return games

        print(f"  · [{self.team.key}] nessuna gara playoff parsabile "
              f"(LNP non ha ancora pubblicato turno corrente)")
        return []

    def _parse_bracket_for_team(
        self,
        text: str,
        team_aliases: list[str],
    ) -> Iterator[Match]:
        serie_pat = re.compile(
            r"Serie\s+(\d+)\s*[-–]\s*"
            r"(.+?)\s*\(\s*(\d+)\s*\^\s*[^)]+\)\s*[-–]\s*"
            r"(.+?)\s*\(\s*(\d+)\s*\^\s*[^)]+\)",
            re.IGNORECASE | re.DOTALL,
        )
        round_pat = re.compile(
            r"(Quarti di Finale|Semifinali|Finale|Play-In|Playout)\s*"
            r"[-–]\s*([^\n]*)",
            re.IGNORECASE,
        )

        for m in serie_pat.finditer(text):
            serie_no = m.group(1)
            team_a = m.group(2).strip()
            seed_a = int(m.group(3))
            team_b = m.group(4).strip()
            seed_b = int(m.group(5))

            is_us_a = team_name_matches(team_a, team_aliases)
            is_us_b = team_name_matches(team_b, team_aliases)
            if not (is_us_a or is_us_b):
                continue

            opponent = team_b if is_us_a else team_a
            our_seed = seed_a if is_us_a else seed_b
            opp_seed = seed_b if is_us_a else seed_a
            higher_seed = our_seed < opp_seed

            # Trova heading round PIÙ VICINA prima del matchup
            before = text[: m.start()]
            last_round_match = None
            for rm in round_pat.finditer(before):
                last_round_match = rm
            if not last_round_match:
                continue

            round_name = last_round_match.group(1)
            dates_text = last_round_match.group(2)
            dates = _extract_dates(dates_text, self.season.season)
            if len(dates) < 3:
                continue

            # Pattern CCFFC higher seed, FFCCF lower seed
            if higher_seed:
                home_games = [(1, dates[0], False), (2, dates[1], False)]
                if len(dates) >= 5:
                    home_games.append((5, dates[4], True))
            else:
                home_games = [(3, dates[2], False)]
                if len(dates) >= 4:
                    home_games.append((4, dates[3], True))

            series_id = (
                f"{round_name.lower().replace(' ', '_')}_"
                f"{serie_no}_{normalize(opponent)[:20]}"
            )

            for gnum, d_str, tentative in home_games:
                yield Match(
                    id=f"{self.team.key[0]}_po_s{serie_no}_g{gnum}",
                    team_key=self.team.key,
                    competition_id=self.comp.id,
                    phase="playoff",
                    date=d_str,
                    time="20:00",
                    home=team_a if is_us_a else team_b,
                    away=opponent,
                    round=39 + (gnum - 1),
                    game_num=gnum,
                    series_id=series_id,
                    tentative=tentative,
                    sources=["lnp_bracket"],
                )

    # ==================================================================
    # FILTER series_closed
    # ==================================================================
    def _filter_closed_series(self, matches: list[Match]) -> list[Match]:
        kept: list[Match] = []
        skipped = 0
        for m in matches:
            if self._is_series_closed(m):
                skipped += 1
                continue
            kept.append(m)
        if skipped:
            print(f"  🚫 [{self.team.key}] {skipped} gara/e playoff saltate "
                  f"(serie chiusa)")
        return kept

    def _is_series_closed(self, m: Match) -> bool:
        opp_n = normalize(m.away)
        for sc in self.season.series_closed:
            if sc.team_key != self.team.key:
                continue
            if sc.competition_id != self.comp.id:
                continue
            if sc.phase != m.phase:
                continue
            sc_opp_n = normalize(sc.opponent)
            if opp_n in sc_opp_n or sc_opp_n in opp_n:
                return True
        return False

    # ==================================================================
    # SCORE WIDGET (semplice ma efficace)
    # ==================================================================
    def _find_score_in_team_page(
        self, text: str, match: Match,
    ) -> tuple[int, int] | None:
        """
        Cerca nel testo della pagina LNP un pattern "NN-NN" vicino al
        nome dell'avversario (entro 120 caratteri).
        """
        opp_n = normalize(match.away)
        if not opp_n:
            return None
        opp_tokens = [t for t in opp_n.split() if len(t) >= 5]
        if not opp_tokens:
            return None

        score_pat = re.compile(r"(\d{2,3})\s*[-–]\s*(\d{2,3})")
        text_n = normalize(text)

        for m in score_pat.finditer(text_n):
            try:
                sh = int(m.group(1))
                sa = int(m.group(2))
                if not (30 <= sh <= 200 and 30 <= sa <= 200):
                    continue
            except ValueError:
                continue
            window_start = max(0, m.start() - 120)
            window_end = min(len(text_n), m.end() + 120)
            window = text_n[window_start:window_end]
            if any(t in window for t in opp_tokens):
                return (sh, sa)
        return None

    # ==================================================================
    # HELPERS
    # ==================================================================
    def _guess_team_slug(self) -> str:
        candidate = max(
            self.team.aliases or [self.team.display_name],
            key=len,
        )
        return normalize(candidate).replace(" ", "-")

    def _infer_year(self) -> str:
        parts = self.season.season.split("-")
        end_str = parts[1] if len(parts) > 1 else parts[0]
        if len(end_str) == 2:
            return f"20{end_str}"
        return end_str


# ============================================================================
# DATE HELPER
# ============================================================================
_MONTH_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
    "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "novembre": 11, "dicembre": 12,
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
    "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12,
}


def _extract_dates(text: str, season: str) -> list[str]:
    """Estrae date ISO da testo italiano tipo "8, 10, 13, 15, 18 maggio"."""
    month_match = re.search(
        r"\b(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|"
        r"agosto|settembre|ottobre|novembre|dicembre)\b",
        text, re.IGNORECASE,
    )
    if not month_match:
        return []
    month_num = _MONTH_IT.get(month_match.group(1).lower())
    if not month_num:
        return []

    before = text[: month_match.start()]
    days = re.findall(r"\b(\d{1,2})\b", before)
    if not days:
        return []

    year_start, year_end = _years_from_season(season)
    year = year_end if month_num <= 7 else year_start

    out: list[str] = []
    for d_str in days:
        try:
            d_num = int(d_str)
            if not (1 <= d_num <= 31):
                continue
            out.append(date(year, month_num, d_num).isoformat())
        except (ValueError, TypeError):
            continue
    return out


def _years_from_season(season: str) -> tuple[int, int]:
    """'2025-26' → (2025, 2026)"""
    try:
        parts = season.split("-")
        start = int(parts[0])
        end_str = parts[1] if len(parts) > 1 else parts[0]
        if len(end_str) == 2:
            end = (start // 100) * 100 + int(end_str)
            if end <= start:
                end += 100
        else:
            end = int(end_str)
        return start, end
    except Exception:
        return 2025, 2026
