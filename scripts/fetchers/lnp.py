"""
lnp.py — Fetcher per Lega Nazionale Pallacanestro (Hybrid mode).

STRATEGIA v9.0 HYBRID:
v9 NON re-implementa il parser calendario regular season LNP. Quella logica
è in v8.9 update_data.py (~2000 righe raffinate negli anni) e gira già su
main: produce data.json affidabile per regular season + score.

v9 si limita a:
1. Bracket QF parser — generazione automatica gare Quarti di Finale dal
   testo strutturato pubblicato da LNP (regex pattern stabile).
2. Next-round deducer (Fase 2.2) — per i round successivi (SF, F) LNP NON
   sostituisce i placeholder "Vincente N vs vincente M". Quindi deduciamo
   le gare dalla series_closed (con next_opponent valorizzato), riusando
   le date dalla heading round nella pagina playoff.
3. Score widget refresh — letture occasionali della pagina squadra LNP per
   score di gare playoff (delay <12h vs RSS).
4. Filter series_closed — impedisce re-inserzione di gare obsolete.

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

# Ordine round playoff per deduzione next-round.
# QF → SF → F. Per Coppa Italia LNP (Final Four) si parte da SF.
PLAYOFF_ROUND_ORDER = ["QF", "SF", "F"]

# Mapping round_name → testo heading nella pagina LNP playoff.
# Usato per estrarre le date del round target.
ROUND_NAME_TO_HEADING = {
    "QF": "Quarti di Finale",
    "SF": "Semifinali",
    "F": "Finale",
}

# Offset numero round per gare playoff generate (per ordering nel frontend).
# Convenzione v8.9: regular 1..38, playoff 37+ (sovrapposizione tollerata).
ROUND_NUM_OFFSET = {
    "QF": 39,
    "SF": 44,
    "F": 49,
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

        Due sorgenti:
        - QF (Quarti di Finale): testo bracket strutturato (regex serie_pat)
        - SF/F: deduzione da series_closed con team_advances=True e
          next_opponent valorizzato (LNP non popola placeholder oltre i QF)

        Regular season NON gestita qui: competenza di v8.9 update_data.py
        che gira su main. Le partite regular esistono già in data.json
        (caricate da state.load).
        """
        if "playoff" not in self.comp.phases:
            return []
        qf_games = self._fetch_playoff_bracket()
        advance_games = self._fetch_next_rounds_from_advances()
        return self._filter_closed_series(qf_games + advance_games)

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
    # BRACKET PARSER QF (cuore del fetcher Hybrid, invariato da v9.0)
    # ==================================================================
    def _fetch_playoff_bracket(self) -> list[Match]:
        """Parser del testo bracket QF per estrarre gare home della squadra."""
        text = self._fetch_playoff_page_text()
        if not text:
            print(f"  · [{self.team.key}] nessuna gara playoff parsabile "
                  f"(LNP non ha ancora pubblicato turno corrente)")
            return []

        team_aliases = [self.team.display_name] + self.team.aliases
        games = list(self._parse_bracket_for_team(text, team_aliases))
        if games:
            print(f"  📡 [{self.team.key}] {len(games)} gare casa playoff QF "
                  f"da bracket text")
        return games

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

            # Trova heading round PIÙ VICINA prima del matchup (rfind-style)
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
    # NEXT-ROUND DEDUCER (Fase 2.2 — Opzione A)
    # ==================================================================
    def _fetch_next_rounds_from_advances(self) -> list[Match]:
        """
        Deduce gare home dei round successivi (SF, F) da series_closed.

        Per ogni SeriesClosed della nostra squadra con team_advances=True
        e next_opponent valorizzato, genera Match per il round successivo
        usando:
        - date dalla heading round della pagina playoff LNP
        - pattern home CCFFC/FFCCF in base a (our_seed vs next_opponent_seed)
        - seed nostro dedotto dal bracket QF (preservato nei round successivi)

        Skippa se:
        - next_opponent vuoto (impossibile dedurre senza dato esterno)
        - round successivo già chiuso in series_closed
        - non si trova testo bracket o date insufficienti
        """
        advancing = [
            sc for sc in self.season.series_closed
            if sc.team_key == self.team.key
            and sc.competition_id == self.comp.id
            and sc.phase == "playoff"
            and sc.team_advances
            and sc.next_opponent
        ]
        if not advancing:
            return []

        text = self._fetch_playoff_page_text()
        if not text:
            return []

        games: list[Match] = []
        for sc in advancing:
            next_round = self._next_round_name(sc.round_name)
            if not next_round:
                continue
            # Skip se il next round è già chiuso (es. SF già conclusa, F prossima)
            if self._is_round_closed(next_round):
                continue

            round_games = self._generate_round_games(
                text=text,
                next_round=next_round,
                opponent=sc.next_opponent,
                opp_seed=sc.next_opponent_seed,
            )
            games.extend(round_games)

        if games:
            tentative_n = sum(1 for g in games if g.tentative)
            print(f"  🧩 [{self.team.key}] {len(games)} gare casa dedotte da "
                  f"advancement ({tentative_n} tentative)")
        return games

    def _next_round_name(self, current: str) -> str | None:
        """Ritorna il round successivo a `current` nella playoff order."""
        if current in PLAYOFF_ROUND_ORDER:
            idx = PLAYOFF_ROUND_ORDER.index(current)
            if idx + 1 < len(PLAYOFF_ROUND_ORDER):
                return PLAYOFF_ROUND_ORDER[idx + 1]
        return None

    def _is_round_closed(self, round_name: str) -> bool:
        """True se esiste già una SeriesClosed per (team, comp, round_name)."""
        for sc in self.season.series_closed:
            if (sc.team_key == self.team.key
                    and sc.competition_id == self.comp.id
                    and sc.round_name == round_name):
                return True
        return False

    def _generate_round_games(
        self,
        text: str,
        next_round: str,
        opponent: str,
        opp_seed: int | None,
    ) -> list[Match]:
        """Genera Match home per `next_round` contro `opponent`."""
        heading = ROUND_NAME_TO_HEADING.get(next_round)
        if not heading:
            return []

        dates = self._extract_round_dates(text, heading)
        if len(dates) < 3:
            return []

        team_aliases = [self.team.display_name] + self.team.aliases
        our_seed = self._get_seed_from_bracket(text, team_aliases)
        if our_seed is None:
            print(f"  ⚠️  [{self.team.key}] seed non determinabile da bracket, "
                  f"skip {next_round}")
            return []

        # Senza opp_seed assumiamo opp_seed alto → noi higher seed (CCFFC).
        # Conservativo: se il dato manca, prediligiamo home prima del lower seed.
        effective_opp_seed = opp_seed if opp_seed is not None else 99
        higher_seed = our_seed < effective_opp_seed

        if higher_seed:
            home_games = [(1, dates[0], False), (2, dates[1], False)]
            if len(dates) >= 5:
                home_games.append((5, dates[4], True))
        else:
            home_games = [(3, dates[2], False)]
            if len(dates) >= 4:
                home_games.append((4, dates[3], True))

        series_id = f"{next_round.lower()}_{normalize(opponent)[:20]}"
        round_offset = ROUND_NUM_OFFSET.get(next_round, 50)

        games: list[Match] = []
        for gnum, d_str, tentative in home_games:
            games.append(Match(
                id=f"{self.team.key[0]}_po_{next_round.lower()}_g{gnum}",
                team_key=self.team.key,
                competition_id=self.comp.id,
                phase="playoff",
                date=d_str,
                time="20:00",
                home=self.team.display_name,
                away=opponent,
                round=round_offset + (gnum - 1),
                game_num=gnum,
                series_id=series_id,
                tentative=tentative,
                sources=["lnp_advance"],
            ))
        return games

    def _extract_round_dates(self, text: str, round_heading: str) -> list[str]:
        """
        Estrae le date di un round specifico dal testo della pagina playoff.
        Cerca: "{heading} - {date_list_text}".

        Es: heading="Semifinali" trova
            "Semifinali - Giovedì 21, sabato 23, martedì 26, giovedì 28, domenica 31 maggio"
        e ritorna ['2026-05-21', '2026-05-23', '2026-05-26', '2026-05-28', '2026-05-31'].
        """
        pattern = re.compile(
            rf"{re.escape(round_heading)}\s*[-–]\s*([^\n]*)",
            re.IGNORECASE,
        )
        m = pattern.search(text)
        if not m:
            return []
        return _extract_dates(m.group(1), self.season.season)

    def _get_seed_from_bracket(
        self, text: str, team_aliases: list[str],
    ) -> int | None:
        """
        Trova lo seed della squadra nel testo bracket QF.
        Cerca pattern "Serie N - {team} (S^ girone X) - ..." e ritorna lo
        seed della squadra che matcha gli aliases.
        """
        serie_pat = re.compile(
            r"Serie\s+\d+\s*[-–]\s*"
            r"(.+?)\s*\(\s*(\d+)\s*\^\s*[^)]+\)\s*[-–]\s*"
            r"(.+?)\s*\(\s*(\d+)\s*\^\s*[^)]+\)",
            re.IGNORECASE | re.DOTALL,
        )
        for m in serie_pat.finditer(text):
            team_a = m.group(1).strip()
            seed_a = int(m.group(2))
            team_b = m.group(3).strip()
            seed_b = int(m.group(4))
            if team_name_matches(team_a, team_aliases):
                return seed_a
            if team_name_matches(team_b, team_aliases):
                return seed_b
        return None

    # ==================================================================
    # FETCH PAGINA PLAYOFF (cached via http_get_text)
    # ==================================================================
    def _fetch_playoff_page_text(self) -> str:
        """
        Fetch testo della pagina playoff contenente la nostra squadra.
        Itera sui PLAYOFF_PAGE_CODES (Tabellone 1, 2) e ritorna il primo
        che contiene un alias del team. http_get_text è cachato 5min, quindi
        chiamate multiple nello stesso run sono economiche.
        """
        serie_num = CATEGORY_TO_SERIE_NUM.get(self.comp.category)
        if serie_num is None:
            return ""
        anno = self._infer_year()
        codes = PLAYOFF_PAGE_CODES.get(self.comp.category, [])
        if not codes:
            return ""

        team_aliases = [self.team.display_name] + self.team.aliases
        aliases_norm = [normalize(a) for a in team_aliases if a]

        for code in codes:
            url = f"{LNP_BASE}/serie/{serie_num}/playoff-playout/{anno}/{code}"
            html = http_get_text(url)
            if not html:
                continue
            text = strip_html(html)
            text_n = normalize(text)
            if any(a in text_n for a in aliases_norm if a):
                return text
        return ""

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
