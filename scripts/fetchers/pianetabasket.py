"""
pianetabasket.py — Fetcher per articoli PianetaBasket (europee + coppe).

PianetaBasket pubblica articoli con calendario e risultati strutturati
testualmente per ogni turno di EuroCup, Champions League, EuroLeague,
Coppa Italia. Esempio formato atteso:

    "EuroCup 2025-2026 – Quarti di finale
    17 marzo, ore 18:00: Hapoel Jerusalem vs Turk Telekom
    18 marzo, ore 19:00: Buducnost vs Cluj-Napoca 82-100
    ..."

Strategia:
1. Carica il feed RSS della sezione (es. 35=EuroCup, 48=Champions)
2. Trova articoli con keyword tipo "calendario", "risultati", "turno"
3. Per ogni articolo, parsa il testo con regex per estrarre matchup + date

Stato Fase 2: scheletro funzionante. Pronto per essere attivato quando
una squadra tracciata si qualifica a EuroCup/Champions.

NOTA: non testato sul vero perché 2025-26 non ha squadre italiane tracciate
in europee. Il primo uso reale richiederà tarature regex sui formati attuali.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Iterator

from core.models import Competition, Match, Season, Team
from ._http import http_get_text
from ._text import normalize, team_name_matches, strip_html


PIANETABASKET_RSS = "https://www.pianetabasket.com/rss/?section={section}"

# Keyword che identificano articoli di calendario/risultati (vs news generiche)
SCHEDULE_KEYWORDS = [
    "calendario", "risultati", "turno", "giornata", "quarti",
    "semifinali", "finale", "ottavi", "ritorno", "andata",
]


class PianetaBasketArticleFetcher:
    """
    Fetcher per calendario/risultati europee via articoli PianetaBasket.

    Args:
        competition: Competition con campo `rss_section` configurato.
        team: la Team tracciata (per filtrare partite rilevanti).
        season: l'intera Season.
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
        if not competition.rss_section:
            raise ValueError(
                f"Competition '{competition.id}' richiede rss_section per "
                f"PianetaBasketArticleFetcher"
            )

    def fetch_schedule(self) -> list[Match]:
        """Estrae calendario partite della squadra dalla sezione PianetaBasket."""
        articles = list(self._fetch_schedule_articles())
        if not articles:
            return []

        team_aliases = [self.team.display_name] + self.team.aliases
        all_matches: list[Match] = []
        for article_title, article_body in articles:
            matches = list(self._parse_article(article_body, team_aliases))
            all_matches.extend(matches)

        # Deduplica per (date, opponent)
        seen: set[tuple[str, str]] = set()
        unique: list[Match] = []
        for m in all_matches:
            key = (m.date, normalize(m.away))
            if key in seen:
                continue
            seen.add(key)
            unique.append(m)
        return unique

    def fetch_scores(self, matches: list[Match]) -> list[Match]:
        """
        Gli articoli PianetaBasket includono spesso anche i risultati.
        Riusa lo stesso parser, e per ogni match esistente prova ad aggiornare
        sh/sa se trova score nello stesso articolo.
        """
        # Per ora delegato a RssPoolFetcher: PianetaBasket è già nel pool RSS.
        return matches

    # ------------------------------------------------------------------
    # PRIVATE
    # ------------------------------------------------------------------
    def _fetch_schedule_articles(self) -> Iterator[tuple[str, str]]:
        """Itera articoli della sezione filtrati per keyword schedule."""
        url = PIANETABASKET_RSS.format(section=self.comp.rss_section)
        xml = http_get_text(url)
        if not xml:
            return
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return

        for item in root.iter("item"):
            title_el = item.find("title")
            desc_el = item.find("description")
            title = (title_el.text or "") if title_el is not None else ""
            desc = (desc_el.text or "") if desc_el is not None else ""
            desc_clean = strip_html(desc)

            title_n = title.lower()
            if any(kw in title_n for kw in SCHEDULE_KEYWORDS):
                yield title, desc_clean

    def _parse_article(
        self,
        body: str,
        team_aliases: list[str],
    ) -> Iterator[Match]:
        """
        Estrae partite della squadra dal testo dell'articolo.

        Pattern atteso (varia, regex permissiva):
            "17 marzo, ore 18:00: Hapoel Jerusalem vs Turk Telekom 98-81"
            "18 marzo - Buducnost - Cluj-Napoca 82-100"
        """
        # Pattern: "GG mese, ore HH:MM(:|) TeamA (vs|-) TeamB (NN-NN)?"
        line_pat = re.compile(
            r"(\d{1,2})\s+"
            r"(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|"
            r"agosto|settembre|ottobre|novembre|dicembre)"
            r"[,\s]*(?:ore\s+)?(\d{1,2}[:.]?\d{2})?\s*[:\s-]+"
            r"([A-Z][a-zA-Z\s\.'\-àèìòù]{3,40}?)"
            r"\s+(?:vs|-)\s+"
            r"([A-Z][a-zA-Z\s\.'\-àèìòù]{3,40}?)"
            r"(?:\s+(\d{2,3})\s*[-–]\s*(\d{2,3}))?",
            re.IGNORECASE,
        )

        from .lnp import _MONTH_IT, _years_from_season
        year_start, year_end = _years_from_season(self.season.season)

        for m in line_pat.finditer(body):
            try:
                day = int(m.group(1))
                month_name = m.group(2).lower()
                month_num = _MONTH_IT.get(month_name)
                if not month_num:
                    continue
                time_str = m.group(3) or "20:00"
                if "." in time_str:
                    time_str = time_str.replace(".", ":")
                if ":" not in time_str and len(time_str) == 4:
                    time_str = time_str[:2] + ":" + time_str[2:]

                team_a = m.group(4).strip()
                team_b = m.group(5).strip()
                sh_s, sa_s = m.group(6), m.group(7)

                is_us_a = team_name_matches(team_a, team_aliases)
                is_us_b = team_name_matches(team_b, team_aliases)
                if not (is_us_a or is_us_b):
                    continue

                year = year_end if month_num <= 7 else year_start
                from datetime import date as _date
                d_iso = _date(year, month_num, day).isoformat()

                opponent = team_b if is_us_a else team_a
                home = team_a if is_us_a else team_b
                away = team_b if is_us_a else team_a

                sh = int(sh_s) if sh_s else None
                sa = int(sa_s) if sa_s else None

                yield Match(
                    id=f"{self.team.key[0]}_{self.comp.id}_{d_iso.replace('-', '')}",
                    team_key=self.team.key,
                    competition_id=self.comp.id,
                    phase="europe" if self.comp.type == "european" else "cup",
                    date=d_iso,
                    time=time_str,
                    home=home,
                    away=away,
                    sh=sh,
                    sa=sa,
                    sources=["pianetabasket_article"],
                )
            except Exception:
                continue
