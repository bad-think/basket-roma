"""
rss_pool.py — Pool RSS unificato per fetch score post-partita.

NON è un fetcher per-team: legge una volta tutti i feed configurati e poi
viene interrogato per match specifici. Singleton pattern in main.py.

Strategia di matching: per ogni feed, estrae menzioni "TeamA-TeamB NN-NN"
e poi le associa al match cercato confrontando con gli alias delle squadre.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterator

from core.models import Match, RssFeed
from ._http import http_get_text
from ._text import normalize, extract_scores, strip_html


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
    Pool unificato di feed RSS. Carica una volta tutti i feed abilitati,
    poi permette query per match specifici via find_score().
    """

    def __init__(self, feeds: list[RssFeed]):
        self.feeds = feeds
        self._mentions: list[RssMention] = []
        self._refreshed = False

    def refresh(self) -> int:
        """Scarica tutti i feed abilitati e estrae le menzioni con score."""
        self._mentions = []
        for feed in self.feeds:
            if not feed.enabled:
                continue
            try:
                mentions = list(self._parse_feed(feed.url))
                self._mentions.extend(mentions)
                if mentions:
                    print(f"  📰 RSS {feed.url}: {len(mentions)} menzioni con score")
                else:
                    print(f"  · RSS {feed.url}: nessuno score nelle ultime entry")
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
        Per matchare richiede che ENTRAMBE le squadre appaiano nella menzione.
        """
        if not self._refreshed:
            print("  ⚠️  RssPoolFetcher: chiama refresh() prima di find_score()")
            return None

        for men in self._mentions:
            full_text = f"{men.article_title} {men.article_text}"
            home_hit = _text_contains_team(full_text, home_aliases)
            away_hit = _text_contains_team(full_text, away_aliases)
            if home_hit and away_hit:
                return (men.score_home, men.score_away)
        return None

    # ------------------------------------------------------------------
    # PARSING
    # ------------------------------------------------------------------
    def _parse_feed(self, url: str) -> Iterator[RssMention]:
        body = http_get_text(url)
        if not body:
            return
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            print(f"  ⚠️  Feed non parseabile (XML invalido): {url}")
            return

        for item in root.iter("item"):
            # Title può essere in CDATA — ElementTree lo gestisce ma può
            # ritornare None se ci sono sub-elementi. Estrai tutto il testo.
            title = _element_text(item.find("title"))
            description = _element_text(item.find("description"))
            description = strip_html(description)

            # Cerca score sia nel titolo che nella description
            full = f"{title} {description}"
            scores = extract_scores(full)
            for sh, sa in scores:
                yield RssMention(
                    feed_url=url,
                    article_title=title,
                    article_text=description,
                    score_home=sh,
                    score_away=sa,
                )


def _element_text(el) -> str:
    """Estrae text da elemento XML, gestendo CDATA e sub-elementi."""
    if el is None:
        return ""
    # ElementTree concatena .text e tutti i .tail di figli ricorsivamente
    # via itertext(), che è più robusto di .text per CDATA WordPress.
    try:
        return "".join(el.itertext()).strip()
    except Exception:
        return (el.text or "").strip()


def _text_contains_team(text: str, aliases: list[str]) -> bool:
    """
    Match permissivo: True se il testo contiene riferimento alla squadra.

    Strategia:
    1. Match esatto di un alias intero (caso pulito) → match
    2. Fallback: tutte le parole "distintive" (>=4 char, non stopword) di
       un alias devono comparire nel testo → match parziale

    Stopword italiane comuni rimosse dal matching distintivo.
    """
    text_n = normalize(text)
    if not text_n:
        return False

    STOPWORDS = {"basket", "club", "team", "pallacanestro", "sport"}

    for a in aliases:
        a_n = normalize(a)
        if not a_n:
            continue

        # 1. Match esatto alias intera
        if len(a_n) >= 4 and a_n in text_n:
            return True

        # 2. Fallback: parole distintive
        tokens = [
            t for t in a_n.split()
            if len(t) >= 4 and t not in STOPWORDS
        ]
        if len(tokens) >= 2 and all(t in text_n for t in tokens):
            return True

    return False
