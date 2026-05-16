"""
rss_pool.py — Pool RSS unificato per fetch score post-partita.

NON è un fetcher per-team: legge una volta tutti i feed configurati e poi
viene interrogato per match specifici. Pattern singleton in main.py.

Fonti tipiche:
- sportando.basketball/feed/         (tutte le serie)
- basketinside.com/feed/             (tutte le serie)
- pianetabasket.com/rss/?section=38  (Serie B)
- pianetabasket.com/rss/?section=43  (A2) — abilitato on-demand
- pianetabasket.com/rss/?section=2   (A)  — abilitato on-demand

Ogni feed è XML standard RSS 2.0. Cerchiamo nei <title> e <description>
pattern "TeamA-TeamB NN-NN" per estrarre risultati.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterator

from core.models import Match, RssFeed
from ._http import http_get_text
from ._text import normalize, team_name_matches, extract_scores, strip_html


@dataclass
class RssMention:
    """Una menzione di partita estratta da un feed RSS."""
    feed_url: str
    article_title: str
    article_text: str
    score_home: int
    score_away: int


class RssPoolFetcher:
    """
    Pool unificato di feed RSS. Carica una volta tutti i feed, poi permette
    query per match specifici.

    Uso tipico:
        pool = RssPoolFetcher(season.enabled_rss())
        pool.refresh()                          # download di tutti i feed
        for match in matches_without_score:
            score = pool.find_score(match, team_aliases)
            if score:
                match.sh, match.sa = score
                match.sources.append("rss")
    """

    def __init__(self, feeds: list[RssFeed]):
        self.feeds = feeds
        self._mentions: list[RssMention] = []
        self._refreshed = False

    def refresh(self) -> int:
        """
        Scarica tutti i feed e estrae le menzioni di partite.
        Ritorna il numero totale di menzioni estratte.
        """
        self._mentions = []
        for feed in self.feeds:
            if not feed.enabled:
                continue
            try:
                mentions = list(self._parse_feed(feed.url))
                self._mentions.extend(mentions)
                print(f"  📰 RSS {feed.url}: {len(mentions)} menzioni")
            except Exception as e:
                print(f"  ⚠️  RSS {feed.url} fallito: {type(e).__name__}: {e}")
        self._refreshed = True
        return len(self._mentions)

    def find_score(
        self,
        match: Match,
        home_aliases: list[str],
        away_aliases: list[str],
    ) -> tuple[int, int] | None:
        """
        Cerca lo score per un match specifico nelle menzioni cachate.

        Args:
            match: la partita da cercare
            home_aliases: alias del nome squadra in casa (per matching)
            away_aliases: alias del nome squadra ospite

        Returns:
            (sh, sa) se trovato, None altrimenti.
        """
        if not self._refreshed:
            print("  ⚠️  RssPoolFetcher: chiama refresh() prima di find_score()")
            return None

        for men in self._mentions:
            full_text = f"{men.article_title} {men.article_text}"
            home_hit = team_name_matches_anywhere(full_text, home_aliases)
            away_hit = team_name_matches_anywhere(full_text, away_aliases)
            if home_hit and away_hit:
                return (men.score_home, men.score_away)
        return None

    # ------------------------------------------------------------------
    # PARSING
    # ------------------------------------------------------------------
    def _parse_feed(self, url: str) -> Iterator[RssMention]:
        """Parse di un singolo feed RSS, yields RssMention con score."""
        body = http_get_text(url)
        if not body:
            return
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            print(f"  ⚠️  Feed non parseabile: {url}")
            return

        # RSS 2.0: feed → channel → item*
        for item in root.iter("item"):
            title_el = item.find("title")
            desc_el = item.find("description")
            title = (title_el.text or "") if title_el is not None else ""
            description = (desc_el.text or "") if desc_el is not None else ""
            # description spesso contiene HTML → strip
            description = strip_html(description)
            scores = extract_scores(f"{title} {description}")
            for sh, sa in scores:
                yield RssMention(
                    feed_url=url,
                    article_title=title,
                    article_text=description,
                    score_home=sh,
                    score_away=sa,
                )


def team_name_matches_anywhere(text: str, aliases: list[str]) -> bool:
    """
    True se almeno una delle aliases appare nel testo (search, non match esatto).
    """
    text_n = normalize(text)
    if not text_n:
        return False
    for a in aliases:
        a_n = normalize(a)
        # Match richiede almeno 4 caratteri per evitare false positive
        if a_n and len(a_n) >= 4 and a_n in text_n:
            return True
    return False
