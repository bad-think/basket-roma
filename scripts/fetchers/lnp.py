"""
lnp.py — Fetcher per Lega Nazionale Pallacanestro.

Copre:
- Serie B Nazionale
- Serie A2
- Serie A (LNP gestisce solo B/A2; per A serve LBA, ma struttura URL è simile)
- Coppa Italia LNP (futuro: stesso parser bracket)

Fonti usate:
1. Pagina squadra LNP: calendario + score regular season
   URL: legapallacanestro.com/squadra/{slug}
2. PDF calendario ufficiale: round numbering autoritativo
   URL: static.legapallacanestro.com/sites/default/files/editor/calendario_*.pdf
3. Pagina tabellone playoff: matchup + date G1-G5
   URL: legapallacanestro.com/serie/{N}/playoff-playout/{anno}/{codice}

Strategie eliminate da v8.9 (codice morto):
- Domino API playoff codes (mai funzionato)
- LNP match pages brute force (404 sistematici)
- LNP calendario centrale per playoff (troppo lento)
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Iterator

from core.models import Competition, Match, Season, SeriesClosed, Team
from ._http import http_get_text
from ._text import normalize, team_name_matches, strip_html


LNP_BASE = "https://www.legapallacanestro.com"

# Mappa categoria → codice serie URL LNP (i numeri sono nei URL playoff)
CATEGORY_TO_SERIE_NUM = {
    "B Nazionale": 4,
    "A2": 3,
    "A": 2,
}

# Codici pagina playoff per categoria/tabellone
PLAYOFF_PAGE_CODES = {
    "B Nazionale": ["ita3_b_poff", "ita3_b_poff_t1", "ita3_b_poff_t2"],
    "A2": ["ita2_a2_poff"],
}


class LNPFetcher:
    """
    Fetcher per una singola competizione LNP di una squadra.

    Args:
        competition: la Competition da gestire (es. B Nazionale girone B)
        team: la Team owner (per matching nomi e alias)
        season: l'intera Season (per accesso a series_closed)
    """

    def __init__(
        self,
        competition: Competition,
        team: Team,
        season: Season,
    ):
        self.comp = competition
        self.team = team
        self.season = season

    # ==================================================================
    # API PUBBLICA
    # ==================================================================
    def fetch_schedule(self) -> list[Match]:
        """
        Recupera tutte le partite IN CASA della squadra per questa competizione.
        Combina: calendario regular + playoff bracket (se applicabile).
        """
        out: list[Match] = []

        # 1. Calendario regular season da pagina squadra LNP
        team_slug = self._guess_team_slug()
        regular = self._fetch_team_calendar(team_slug)
        out.extend(regular)

        # 2. Playoff bracket (solo se la competition include "playoff" tra le fasi)
        if "playoff" in self.comp.phases:
            playoff = self._fetch_playoff_bracket()
            # Filtra serie chiuse via override manuale
            playoff = self._filter_closed_series(playoff)
            out.extend(playoff)

        return out

    def fetch_scores(self, matches: list[Match]) -> list[Match]:
        """
        Aggiorna sh/sa per le partite di questa competizione che ne sono prive.
        Fonte: pagina squadra LNP (widget risultati).
        """
        team_slug = self._guess_team_slug()
        results = self._fetch_team_results(team_slug)

        # Indicizza per data: dict[date_str] = (sh, sa)
        by_date: dict[str, tuple[int, int]] = {}
        for m_data, sh, sa in results:
            by_date[m_data] = (sh, sa)

        updated = 0
        for m in matches:
            if m.team_key != self.team.key:
                continue
            if m.competition_id != self.comp.id:
                continue
            if m.sh is not None and m.sa is not None:
                continue
            if m.date in by_date:
                m.sh, m.sa = by_date[m.date]
                if "lnp_team_page" not in m.sources:
                    m.sources.append("lnp_team_page")
                updated += 1
        if updated:
            print(f"  📊 [{self.team.key}] {updated} score aggiornati da LNP team page")
        return matches

    # ==================================================================
    # DISCOVERY: team slug + league slug
    # ==================================================================
    def _guess_team_slug(self) -> str:
        """
        Costruisce lo slug LNP del team dalla configurazione.
        Es: "Virtus GVM Roma 1960" → "virtus-gvm-roma-1960"
        """
        # In v8.9 si usava un discovery a cascade; qui usiamo direct mapping
        # da alias più lunga (più specifica) → slug
        candidate = max(
            self.team.aliases or [self.team.display_name],
            key=len,
        )
        s = normalize(candidate)
        return s.replace(" ", "-")

    def _team_page_url(self, team_slug: str) -> str:
        return f"{LNP_BASE}/squadra/{team_slug}"

    # ==================================================================
    # FETCH: pagina squadra LNP
    # ==================================================================
    def _fetch_team_calendar(self, team_slug: str) -> list[Match]:
        """Estrae partite future + recenti dalla pagina squadra."""
        url = self._team_page_url(team_slug)
        html = http_get_text(url)
        if not html:
            return []

        out: list[Match] = []
        # La pagina LNP ha tabella partite con righe "casa - data - ospite - risultato"
        # Pattern (semplificato, v8.9 ha versione più robusta):
        # Cerchiamo blocchi di partite in casa della squadra (home == self.team.display_name)
        team_aliases = [self.team.display_name] + self.team.aliases

        # Estrae blocchi <tr> della tabella calendario
        for date_str, home, away, score in _iter_lnp_calendar_rows(html):
            if not team_name_matches(home, team_aliases):
                continue  # ci interessano solo partite IN CASA
            sh, sa = score if score else (None, None)
            mid = f"{self.team.key[0]}{date_str.replace('-', '')[-4:]}"
            out.append(Match(
                id=mid,
                team_key=self.team.key,
                competition_id=self.comp.id,
                phase="regular",
                date=date_str,
                home=home,
                away=away,
                sh=sh,
                sa=sa,
                sources=["lnp_team_page"],
            ))
        return out

    def _fetch_team_results(self, team_slug: str) -> list[tuple[str, int, int]]:
        """
        Variante focalizzata sui risultati (solo partite GIOCATE con score).
        Ritorna lista di tuple (data ISO, sh, sa).
        """
        url = self._team_page_url(team_slug)
        html = http_get_text(url)
        if not html:
            return []

        out = []
        team_aliases = [self.team.display_name] + self.team.aliases
        for date_str, home, away, score in _iter_lnp_calendar_rows(html):
            if not score:
                continue
            if not team_name_matches(home, team_aliases):
                continue
            out.append((date_str, score[0], score[1]))
        return out

    # ==================================================================
    # FETCH: tabellone playoff
    # ==================================================================
    def _fetch_playoff_bracket(self) -> list[Match]:
        """
        Genera partite playoff dal tabellone LNP (testo della pagina dedicata).
        Pattern atteso:
            "Serie N - TeamA (X^girone) - TeamB (Y^girone)"
            "Quarti di Finale - Venerdì 8, domenica 10, mercoledì 13..."
        """
        serie_num = CATEGORY_TO_SERIE_NUM.get(self.comp.category)
        if serie_num is None:
            return []
        anno = self.season.season.split("-")[-1]  # "2025-26" → "26"
        if len(anno) == 2:
            anno = f"20{anno}"  # "26" → "2026"
        codes = PLAYOFF_PAGE_CODES.get(self.comp.category, [])
        if not codes:
            return []

        team_aliases = [self.team.display_name] + self.team.aliases
        all_games: list[Match] = []

        for code in codes:
            url = f"{LNP_BASE}/serie/{serie_num}/playoff-playout/{anno}/{code}"
            html = http_get_text(url)
            if not html:
                continue
            text = strip_html(html)
            games = list(self._parse_bracket_for_team(text, team_aliases))
            if games:
                print(f"  📡 [{self.team.key}] {len(games)} gare casa playoff dal codice {code}")
                all_games.extend(games)
                break  # un solo tabellone è quello giusto

        return all_games

    def _parse_bracket_for_team(
        self,
        text: str,
        team_aliases: list[str],
    ) -> Iterator[Match]:
        """Estrae matchup + date dal testo della pagina playoff."""
        # Pattern matchup: "Serie N - TeamA (X^girone Y) - TeamB (Z^girone W)"
        serie_pat = re.compile(
            r"Serie\s+(\d+)\s*[-–]\s*"
            r"(.+?)\s*\(\s*(\d+)\s*\^\s*[^)]+\)\s*[-–]\s*"
            r"(.+?)\s*\(\s*(\d+)\s*\^\s*[^)]+\)",
            re.IGNORECASE | re.DOTALL,
        )

        # Trova il round corrente (cerca heading più vicino al matchup)
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

            # Verifica se il nostro team è in questo matchup
            is_us_a = team_name_matches(team_a, team_aliases)
            is_us_b = team_name_matches(team_b, team_aliases)
            if not (is_us_a or is_us_b):
                continue

            opponent = team_b if is_us_a else team_a
            our_seed = seed_a if is_us_a else seed_b
            opp_seed = seed_b if is_us_a else seed_a
            higher_seed = our_seed < opp_seed  # seed più basso = più forte

            # Trova heading round PRIMA del matchup (usa rfind)
            before = text[: m.start()]
            round_match = None
            for rm in round_pat.finditer(before):
                round_match = rm  # tieni l'ultimo (il più vicino)
            if not round_match:
                continue

            round_name = round_match.group(1)
            dates_text = round_match.group(2)

            # Estrai date dal testo
            dates = _extract_dates(dates_text, self.season.season)
            if len(dates) < 3:
                continue  # LNP non ha ancora pubblicato date complete

            # Genera le 3 gare in casa per higher seed (CCFFC pattern),
            # o 2 per lower seed (FFCCF: G3, G4 casa)
            if higher_seed:
                home_games = [(1, dates[0], False), (2, dates[1], False)]
                if len(dates) >= 5:
                    home_games.append((5, dates[4], True))  # tentative
            else:
                home_games = [(3, dates[2], False)]
                if len(dates) >= 4:
                    home_games.append((4, dates[3], True))  # tentative

            series_id = f"{round_name.lower().replace(' ', '_')}_{serie_no}_{normalize(opponent)[:20]}"

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
                    round=int(d_str.replace("-", ""))%100 + 36,  # ~round 37+ per playoff
                    game_num=gnum,
                    series_id=series_id,
                    tentative=tentative,
                    sources=["lnp_bracket"],
                )

    # ==================================================================
    # FILTER: series_closed
    # ==================================================================
    def _filter_closed_series(self, matches: list[Match]) -> list[Match]:
        """Rimuove gare di serie già chiuse (override config.series_closed)."""
        kept: list[Match] = []
        skipped = 0
        for m in matches:
            if self._is_series_closed(m):
                skipped += 1
                continue
            kept.append(m)
        if skipped:
            print(f"  🚫 [{self.team.key}] {skipped} gara/e playoff saltate "
                  f"(serie chiusa via series_closed)")
        return kept

    def _is_series_closed(self, m: Match) -> bool:
        """True se la partita appartiene a una serie marcata come chiusa."""
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


# ============================================================================
# HELPER PRIVATI
# ============================================================================
_MONTH_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
    "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "novembre": 11, "dicembre": 12,
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
    "lug": 7, "ago": 8, "set": 9, "ott": 10, "nov": 11, "dic": 12,
}


def _extract_dates(text: str, season: str) -> list[str]:
    """
    Estrae date in formato ISO da testo italiano tipo "8, 10, 13, 15, 18 maggio".
    Usa l'anno della stagione (es. "2025-26" → 2026 per maggio).
    """
    # Pattern: numero(/, e) ... mese
    # "Venerdì 8, domenica 10, mercoledì 13 maggio"
    parts = re.split(r"\bmaggio|\bgiugno|\baprile|\bmarzo|\bfebbraio|\bgennaio"
                     r"|\bdicembre|\bnovembre|\bottobre|\bsettembre|\bagosto|\bluglio\b",
                     text, flags=re.IGNORECASE)
    if len(parts) < 2:
        return []

    out: list[str] = []
    # Cerca tutti i match "<day> <month>"
    pat = re.compile(
        r"(\d{1,2})\s*[°,e\s]*[a-z\s,]*?\s+"
        r"(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|"
        r"agosto|settembre|ottobre|novembre|dicembre)",
        re.IGNORECASE,
    )

    # Strategia più solida: trova prima il mese, poi i giorni prima del mese
    month_match = re.search(
        r"\b(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|"
        r"agosto|settembre|ottobre|novembre|dicembre)\b",
        text, re.IGNORECASE,
    )
    if not month_match:
        return []
    month_name = month_match.group(1).lower()
    month_num = _MONTH_IT.get(month_name)
    if not month_num:
        return []

    # Estrai giorni prima del mese
    before = text[: month_match.start()]
    days = re.findall(r"\b(\d{1,2})\b", before)
    if not days:
        return []

    # Determina anno: se mese è gen-giu → anno fine stagione (2026), altrimenti inizio
    year_start, year_end = _years_from_season(season)
    year = year_end if month_num <= 7 else year_start

    for d_str in days:
        try:
            d_num = int(d_str)
            if not (1 <= d_num <= 31):
                continue
            d_obj = date(year, month_num, d_num)
            out.append(d_obj.isoformat())
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


def _iter_lnp_calendar_rows(html: str) -> Iterator[tuple[str, str, str, tuple[int, int] | None]]:
    """
    Itera sulle righe del calendario LNP estraendo (data_iso, home, away, score|None).

    Implementazione semplificata. La pagina LNP ha struttura tabella con celle:
    [data, ora, casa, ospite, risultato].
    """
    # Pattern: estrae righe di tabella con data + due nomi squadra + opzionale score
    # Cerca pattern tipo "DD/MM/YYYY ... TeamA ... TeamB ... NN-NN"
    row_pat = re.compile(
        r"(\d{1,2}/\d{1,2}/\d{4})"   # data DD/MM/YYYY
        r"\s+\d{1,2}:\d{2}"           # orario
        r"\s+([A-Z][^|]{3,60}?)"      # home team (parte da maiuscola)
        r"\s+(?:vs|-)?\s*"
        r"([A-Z][^|]{3,60}?)"         # away team
        r"(?:\s+(\d{2,3})\s*-\s*(\d{2,3}))?",  # score opzionale
        re.MULTILINE,
    )

    text = strip_html(html)
    for m in row_pat.finditer(text):
        try:
            d, mo, y = m.group(1).split("/")
            date_iso = f"{y}-{int(mo):02d}-{int(d):02d}"
            home = m.group(2).strip()
            away = m.group(3).strip()
            sh_s, sa_s = m.group(4), m.group(5)
            score = (int(sh_s), int(sa_s)) if sh_s and sa_s else None
            yield date_iso, home, away, score
        except Exception:
            continue
