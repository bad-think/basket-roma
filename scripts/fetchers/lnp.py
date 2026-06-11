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
   sostituisce i placeholder "Vincente N vs vincente M". Deduciamo le gare
   da series_closed (con next_opponent valorizzato), riusando le date dalla
   heading round.
3. Tabellino parser (Fase 2.3a) — quando una Match ha `external_id` LNP
   (es. "ita3_b_ply_75"), fetcha il tabellino e arricchisce score + parziali.
   Discovery automatica del match_id è Fase 2.3b (TBD).
4. Score widget refresh — letture occasionali della pagina squadra LNP per
   score di gare playoff (fallback).
5. Filter series_closed — impedisce re-inserzione di gare obsolete.
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

# Phase_id prefix per match_id LNP (es. "ita3_b_ply_75" → phase_id "ita3_b_ply").
# Usato per costruire URL tabellino e per pattern di discovery via pagina avversario.
PLAYOFF_PHASE_IDS = {
    "B Nazionale": "ita3_b_ply",
    "A2": "ita2_a2_ply",
}

# Source slug per costruire URL pagina squadra LNP (es. /serie-b/{team_slug}).
# Fase 2.3c — probing sequenziale tabellini (fallback discovery)
# Nota calibrazione: LNP alloca gli id per blocchi di round con gap.
# Verificato 2025-26 B Naz tab.2: QF/SF terminano a 79, Finale parte
# da 90 (gap di 10 id inutilizzati). MAX_MISSES deve superare il gap.
PROBE_MAX_IDS = 30            # quante id oltre il massimo noto sondare
PROBE_MAX_MISSES = 12         # buchi consecutivi prima di fermarsi

CATEGORY_TO_SOURCE_SLUG = {
    "B Nazionale": "serie-b",
    "A2": "serie-a2",
}

# Ordine round playoff per deduzione next-round.
# QF → SF → F. Per Coppa Italia LNP (Final Four) si parte da SF.
PLAYOFF_ROUND_ORDER = ["QF", "SF", "F"]

# Mapping round_name → testo heading nella pagina LNP playoff.
ROUND_NAME_TO_HEADING = {
    "QF": "Quarti di Finale",
    "SF": "Semifinali",
    # B Nazionale LNP usa "Finali" (plurale) nel tabellone playoff.
    # A2 usa "Finale" (singolare): da gestire se/quando Virtus sale in A2 (Fase 6).
    "F": "Finali",
}

# Offset numero round per gare playoff generate (per ordering nel frontend).
ROUND_NUM_OFFSET = {
    "QF": 39,
    "SF": 44,
    "F": 49,
}


class LNPFetcher:
    """Fetcher LNP focalizzato su playoff/bracket (modalità Hybrid)."""

    def __init__(self, competition: Competition, team: Team, season: Season):
        self.comp = competition
        self.team = team
        self.season = season

    # ==================================================================
    # API PUBBLICA
    # ==================================================================
    def fetch_schedule(self) -> list[Match]:
        """Schedule playoff: QF bracket + SF/F dedotti da advancement."""
        if "playoff" not in self.comp.phases:
            return []
        qf_games = self._fetch_playoff_bracket()
        advance_games = self._fetch_next_rounds_from_advances()
        return self._filter_closed_series(qf_games + advance_games)

    def fetch_scores(self, matches: list[Match]) -> list[Match]:
        """
        Aggiorna sh/sa per gare playoff senza score.

        Ordine di tentativo (dal più accurato al meno):
        1. Discovery automatica external_id (Fase 2.3b) — via pagina avversario
        2. Tabellino LNP diretto (Fase 2.3a) — per Match con external_id
        3. Widget pagina squadra LNP — fallback regex su testo
        """
        # 1. Discovery external_id via pagina squadra avversario (Fase 2.3b)
        self._discover_external_ids(matches)

        # 1b. Fallback: probing sequenziale id tabellino (Fase 2.3c)
        #     Copre i casi in cui la pagina avversario non espone il round
        #     corrente (es. Finale inter-girone, cache Drupal stantia).
        self._probe_external_ids(matches)

        # 2. Tabellino diretto (priorità: più accurato + parziali)
        self._fetch_scores_from_tabellini(matches)

        # 2. Widget pagina squadra (fallback per Match senza external_id)
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
    # BRACKET PARSER QF
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
    # NEXT-ROUND DEDUCER (Fase 2.2)
    # ==================================================================
    def _fetch_next_rounds_from_advances(self) -> list[Match]:
        """Deduce gare home dei round successivi (SF, F) da series_closed."""
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
        if current in PLAYOFF_ROUND_ORDER:
            idx = PLAYOFF_ROUND_ORDER.index(current)
            if idx + 1 < len(PLAYOFF_ROUND_ORDER):
                return PLAYOFF_ROUND_ORDER[idx + 1]
        return None

    def _is_round_closed(self, round_name: str) -> bool:
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
        # Il testo LNP playoff è una linea continua con headers separati da spazi:
        #   "Quarti di Finale - ... maggio Semifinali - ... maggio Finali - ... giugno"
        # Servono DUE protezioni nel regex:
        #
        # 1. Lookbehind (?:^|\W): match heading SOLO se preceduto da inizio stringa
        #    o da un non-word char. Evita match dentro "Semifinali" (heading="Finali"
        #    matcherebbe il suffisso). Per "Quarti di Finale" non c'è collisione con
        #    "Finali" perché differente: "Finale" singolare vs "Finali" plurale.
        #
        # 2. ROUND_NAME_TO_HEADING usa "Finali" (B Naz LNP convention). Cercare
        #    "Finale" singolare farebbe matchare DENTRO "Quarti di Finale" → date QF
        #    invece di Finale (bug "off by one month" osservato in produzione).
        pattern = re.compile(
            rf"(?:^|\W){re.escape(round_heading)}\s*[-–]\s*([^\n]*)",
            re.IGNORECASE,
        )
        m = pattern.search(text)
        if not m:
            return []
        return _extract_dates(m.group(1), self.season.season)

    def _get_seed_from_bracket(
        self, text: str, team_aliases: list[str],
    ) -> int | None:
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
    # TABELLINO PARSER (Fase 2.3a)
    # ==================================================================
    def _fetch_scores_from_tabellini(self, matches: list[Match]) -> int:
        """
        Per ogni Match con external_id e senza score completo, fetcha il
        tabellino LNP e arricchisce sh/sa + parziali.

        Returns: numero di Match aggiornati.
        """
        targets = [
            m for m in matches
            if m.team_key == self.team.key
            and m.competition_id == self.comp.id
            and m.phase in ("playoff", "playout")
            and m.external_id
            and (m.sh is None or m.sa is None or not m.periods)
        ]
        if not targets:
            return 0

        season_short = self._season_short()
        team_aliases = [self.team.display_name] + self.team.aliases
        updated = 0

        for m in targets:
            url = _build_tabellino_url(m.external_id, season_short)
            if not url:
                continue
            html = http_get_text(url)
            if not html:
                continue
            parsed = parse_tabellino(html)
            if not parsed:
                print(f"  ⚠️  [{self.team.key}] parse fallito per "
                      f"{m.external_id}")
                continue

            # Verifica che NOI siamo home (convention v8.9: data.json contiene
            # solo gare casa delle squadre tracciate)
            if not team_name_matches(parsed["home"], team_aliases):
                print(f"  ⚠️  [{self.team.key}] external_id {m.external_id} non "
                      f"corrisponde a gara in casa (home={parsed['home']!r})")
                continue

            changed = False
            if m.sh is None or m.sh != parsed["sh"]:
                m.sh = parsed["sh"]
                changed = True
            if m.sa is None or m.sa != parsed["sa"]:
                m.sa = parsed["sa"]
                changed = True
            if parsed["periods"] and not m.periods:
                m.periods = parsed["periods"]
                changed = True
            # Affina time se presente nel tabellino e diverso
            if parsed.get("time") and parsed["time"] != m.time:
                m.time = parsed["time"]
                changed = True
            if changed:
                if "lnp_tabellino" not in m.sources:
                    m.sources.append("lnp_tabellino")
                updated += 1

        if updated:
            print(f"  📊 [{self.team.key}] {updated} match arricchiti da LNP "
                  f"tabellino")
        return updated


    # ==================================================================
    # DISCOVERY EXTERNAL_ID (Fase 2.3b) — via pagina squadra avversario
    # ==================================================================
    def _discover_external_ids(self, matches: list[Match]) -> int:
        """
        Discovery automatica external_id per Match playoff senza ID.

        Strategia: fetch pagina squadra dell'avversario, estrai link tabellini
        dalla tabella calendario, match per (date_iso, phase). Funziona perché
        la pagina avversario (es. Rucker) elenca le sue partite playoff con
        link diretti al tabellino LNP.

        Limitazione: tabellone visibile nella pagina avversario dipende dal
        suo "tab default" (di solito il round corrente / il primo turno
        playoff). Per SF/F della NOSTRA squadra (dove l'avversario potrebbe
        non mostrarle ancora) usare `match_id_overrides` nel config.

        Returns: numero di Match aggiornati.
        """
        candidates = [
            m for m in matches
            if m.team_key == self.team.key
            and m.competition_id == self.comp.id
            and m.phase in ("playoff", "playout")
            and not m.external_id
        ]
        if not candidates:
            return 0

        phase_id = PLAYOFF_PHASE_IDS.get(self.comp.category)
        source_slug = CATEGORY_TO_SOURCE_SLUG.get(self.comp.category)
        if not phase_id or not source_slug:
            return 0

        # Raggruppa Match per avversario normalizzato
        by_opp: dict[str, list[Match]] = {}
        for m in candidates:
            by_opp.setdefault(normalize(m.away), []).append(m)

        updated = 0
        for opp_norm, opp_matches in by_opp.items():
            opp_slug = self._opponent_to_slug(opp_norm)
            if not opp_slug:
                continue
            url = f"{LNP_BASE}/{source_slug}/{opp_slug}"
            html = http_get_text(url)
            if not html:
                continue
            date_to_id = _extract_match_ids_from_team_page(html, phase_id)
            if not date_to_id:
                continue
            for m in opp_matches:
                if m.date in date_to_id:
                    m.external_id = date_to_id[m.date]
                    updated += 1

        if updated:
            print(f"  🔍 [{self.team.key}] {updated} external_id scoperti da "
                  f"pagine avversario")
        return updated

    # ==================================================================
    # PROBING SEQUENZIALE (Fase 2.3c) — fallback indipendente da pagine
    # ==================================================================
    def _probe_external_ids(self, matches: list[Match]) -> int:
        """
        Fallback discovery: sonda gli id tabellino LNP in sequenza.

        Gli id tabellino sono progressivi per phase_id: i nuovi turni
        (es. Finale) hanno id > max noto. A differenza della discovery
        via pagina avversario, non dipende dal tab default ne' dalla
        cache Drupal delle pagine squadra: il tabellino match esiste
        sempre, anche pre-partita (score vuoto).

        Si attiva SOLO se esiste almeno una gara gia' giocata (date <=
        oggi) senza external_id e senza score. Mappa pero' anche le
        gare future trovate nella finestra (id assegnato subito, score
        arrivera' dall'enrichment standard nei run successivi).

        Returns: numero di Match a cui e' stato assegnato external_id.
        """
        pending = [
            m for m in matches
            if m.team_key == self.team.key
            and m.competition_id == self.comp.id
            and m.phase in ("playoff", "playout")
            and not m.external_id
        ]
        today_iso = date.today().strftime("%Y-%m-%d")
        # Trigger: basta una gara giocata senza external_id. NON richiede
        # score mancante: uno score potrebbe esserci ma essere errato
        # (es. contaminazione RSS) e il tabellino e' la fonte canonica.
        trigger = [
            m for m in pending
            if m.date and m.date <= today_iso
        ]
        if not trigger:
            return 0

        phase_id = PLAYOFF_PHASE_IDS.get(self.comp.category)
        if not phase_id:
            return 0

        known_ids = []
        prefix = phase_id + "_"
        for mm in matches:
            ext = mm.external_id or ""
            if ext.startswith(prefix):
                tail = ext.rsplit("_", 1)[-1]
                if tail.isdigit():
                    known_ids.append(int(tail))
        start = (max(known_ids) + 1) if known_ids else 1

        season_short = self._season_short()
        team_aliases = [self.team.display_name] + self.team.aliases
        date_pat = re.compile(r"Data:\s*(\d{1,2})/(\d{1,2})/(\d{4})")

        updated = 0
        misses = 0
        for n in range(start, start + PROBE_MAX_IDS):
            if not pending:
                break
            ext_id = f"{phase_id}_{n}"
            url = _build_tabellino_url(ext_id, season_short)
            if not url:
                break
            html = http_get_text(url)
            if not html:
                misses += 1
                if misses >= PROBE_MAX_MISSES:
                    break
                continue

            h_name, a_name = _parse_match_teams(html)
            if not h_name or not a_name:
                # Pagina template senza match → conta come buco
                misses += 1
                if misses >= PROBE_MAX_MISSES:
                    break
                continue
            misses = 0

            # Data (senza richiedere lo score: pre-partita ammesso)
            dm = date_pat.search(strip_html(html))
            if not dm:
                continue
            try:
                p_date = (f"{int(dm.group(3)):04d}-"
                          f"{int(dm.group(2)):02d}-"
                          f"{int(dm.group(1)):02d}")
            except ValueError:
                continue

            # Siamo noi in casa? (convention: tracciamo gare casa)
            if not team_name_matches(h_name, team_aliases):
                continue

            a_norm = normalize(a_name)
            for m in list(pending):
                m_away_n = normalize(m.away)
                if m.date != p_date:
                    continue
                if not (a_norm and m_away_n
                        and (a_norm in m_away_n or m_away_n in a_norm)):
                    continue
                m.external_id = ext_id
                # Se il tabellino ha gia' lo score, riempi subito
                parsed = parse_tabellino(html)
                if parsed:
                    m.sh = parsed["sh"]
                    m.sa = parsed["sa"]
                    if parsed.get("periods"):
                        m.periods = parsed["periods"]
                    if "lnp_tabellino" not in m.sources:
                        m.sources.append("lnp_tabellino")
                pending.remove(m)
                updated += 1
                break

        if updated:
            print(f"  🎯 [{self.team.key}] {updated} external_id trovati "
                  f"via probing sequenziale (start={start})")
        return updated

    def _opponent_to_slug(self, opp_norm: str) -> str:
        """
        Converte nome avversario normalizzato in slug URL LNP.
        Es: "rucker san vendemiano" → "rucker-san-vendemiano"

        Slug LNP di solito = team_name lowercase con "-" al posto degli spazi.
        Caratteri speciali/accenti già rimossi da normalize().
        """
        if not opp_norm:
            return ""
        return opp_norm.replace(" ", "-")

    # ==================================================================
    # FETCH PAGINA PLAYOFF (cached via http_get_text)
    # ==================================================================
    def _fetch_playoff_page_text(self) -> str:
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
    # SCORE WIDGET (fallback)
    # ==================================================================
    def _find_score_in_team_page(
        self, text: str, match: Match,
    ) -> tuple[int, int] | None:
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

    def _season_short(self) -> str:
        """'2025-26' → '2526'"""
        parts = self.season.season.split("-")
        start_short = parts[0][-2:] if len(parts[0]) >= 2 else parts[0]
        end_short = parts[1] if len(parts) > 1 else parts[0][-2:]
        return f"{start_short}{end_short}"


# ============================================================================
# TABELLINO PARSER — Funzione modulo (testabile in isolamento)
# ============================================================================
def parse_tabellino(html: str) -> dict | None:
    """
    Parse pagina tabellino LNP → dict con keys: date, time, home, away, sh, sa, periods.

    Estrae da:
    - meta og:title o <title> per nomi squadra (più affidabile)
    - testo "Data: DD/MM/YYYY HH:MM" per data e ora
    - riga summary "Home - Away NN-MM (NN-NN, NN-NN, ...)" per score + parziali

    Returns None se il parsing fallisce su campi essenziali (nomi/score).
    """
    if not html:
        return None

    # 1. Nomi squadra: meta og:title preferito, fallback <title>
    home_name, away_name = _parse_match_teams(html)
    if not home_name or not away_name:
        return None

    # Strip HTML per pattern testuali (whitespace compatto)
    text = strip_html(html)

    # 2. Data + ora (formato italiano DD/MM/YYYY HH:MM)
    date_match = re.search(
        r"Data:\s*(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}:\d{2})",
        text,
    )
    if not date_match:
        return None
    d, mo, y, time_s = date_match.groups()
    try:
        iso_date = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    except ValueError:
        return None

    # 3. Score + parziali dalla riga summary (più affidabile)
    # Pattern: "NN-NN (NN-NN, NN-NN, NN-NN, NN-NN)"
    # Score con hyphen (es. "75-59"), parziali con hyphen separati da virgola.
    summary_pat = re.compile(
        r"(\d{2,3})\s*[-–]\s*(\d{2,3})\s*"
        r"\(\s*(\d+\s*[-–]\s*\d+(?:\s*,\s*\d+\s*[-–]\s*\d+){1,})\s*\)"
    )
    sm = summary_pat.search(text)
    periods: list[tuple[int, int]] = []
    if sm:
        sh = int(sm.group(1))
        sa = int(sm.group(2))
        # Estrai parziali
        for part_match in re.finditer(r"(\d+)\s*[-–]\s*(\d+)", sm.group(3)):
            try:
                periods.append((int(part_match.group(1)), int(part_match.group(2))))
            except ValueError:
                continue
    else:
        # Fallback: score em-dash "NN — NN" (presente sopra la tabella parziali)
        em_pat = re.compile(r"(\d{2,3})\s*—\s*(\d{2,3})")
        em_match = em_pat.search(text)
        if not em_match:
            return None
        sh = int(em_match.group(1))
        sa = int(em_match.group(2))

    if not (30 <= sh <= 200 and 30 <= sa <= 200):
        return None

    # 4. Validazione score vs parziali (sanity check)
    if periods:
        period_sum_h = sum(p[0] for p in periods)
        period_sum_a = sum(p[1] for p in periods)
        # LNP a volte mostra parziali "Ospite | Casa" invertiti: tolleriamo entrambe
        if period_sum_h == sh and period_sum_a == sa:
            pass  # parziali h,a corretti
        elif period_sum_a == sh and period_sum_h == sa:
            # Parziali invertiti: scambia
            periods = [(p[1], p[0]) for p in periods]
        # Se non torna in nessuno dei due modi, lascia comunque (forse partita con OT)

    return {
        "date": iso_date,
        "time": time_s,
        "home": home_name,
        "away": away_name,
        "sh": sh,
        "sa": sa,
        "periods": periods,
    }


def _parse_match_teams(html: str) -> tuple[str | None, str | None]:
    """
    Estrai nomi (home, away) da meta og:title o <title> tag.
    Pattern atteso: "{Home} VS {Away}".
    """
    # Meta og:title (più affidabile, è esplicito nel head)
    meta_pat = re.compile(
        r"""<meta[^>]*(?:property|name)\s*=\s*["']og:title["'][^>]*"""
        r"""content\s*=\s*["']([^"']+?)\s+VS\s+([^"']+?)["']""",
        re.IGNORECASE,
    )
    m = meta_pat.search(html)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # Fallback: <title>X VS Y | Lega Nazionale Pallacanestro</title>
    title_pat = re.compile(
        r"<title>([^<]+?)\s+VS\s+([^<|]+?)(?:\s*\||\s*</title>)",
        re.IGNORECASE,
    )
    m = title_pat.search(html)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    return None, None


def _build_tabellino_url(external_id: str, season_short: str) -> str:
    """
    Costruisci URL tabellino da external_id come 'ita3_b_ply_75'.
    Formato: LNP_BASE/wp/match/{external_id}/{phase_id}/x{season_short}/tabellino
    dove phase_id è external_id senza il suffisso "_N".
    """
    if not external_id:
        return ""
    # Strip trailing "_N" per ottenere phase_id (es. "ita3_b_ply_75" → "ita3_b_ply")
    m = re.match(r"^(.+?)_\d+$", external_id)
    if not m:
        return ""
    phase_id = m.group(1)
    return f"{LNP_BASE}/wp/match/{external_id}/{phase_id}/x{season_short}/tabellino"


def _extract_match_ids_from_team_page(html: str, phase_id: str) -> dict[str, str]:
    """
    Estrai mapping (date_iso → external_id) da una pagina squadra LNP.

    La tabella calendario contiene righe tipo:
        <td>21/05/2026 20:30</td> ... <a href="/wp/match/ita3_b_ply_75/...">75-59</a>

    Pattern: data DD/MM/YYYY (con o senza ora) seguita entro N caratteri
    da un link tabellino con `phase_id`. Lazy match per evitare cross-row.

    Args:
        html: HTML grezzo della pagina squadra LNP
        phase_id: prefisso phase_id (es. "ita3_b_ply")

    Returns:
        Dict {date_iso: external_id}. Es: {"2026-05-08": "ita3_b_ply_51"}.
    """
    if not html or not phase_id:
        return {}
    pattern = re.compile(
        r"(\d{2})/(\d{2})/(\d{4})(?:\s+\d{1,2}:\d{2})?"
        # Lazy match ma SENZA consumare altri "/wp/match/" (evita cross-row drift)
        r"(?:(?!/wp/match/).)*?"
        r"/wp/match/" + re.escape(phase_id) + r"_(\d+)/",
        re.DOTALL,
    )
    out: dict[str, str] = {}
    for m in pattern.finditer(html):
        try:
            day = int(m.group(1))
            month = int(m.group(2))
            year = int(m.group(3))
            match_n = m.group(4)
            iso_date = f"{year:04d}-{month:02d}-{day:02d}"
            external_id = f"{phase_id}_{match_n}"
            # Prima occorrenza vince (in caso di duplicati nella pagina)
            if iso_date not in out:
                out[iso_date] = external_id
        except (ValueError, IndexError):
            continue
    return out



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
