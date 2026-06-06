"""
scripts/fetchers — Plugin per il recupero dati da fonti esterne.

Ogni fetcher per-competition ha interfaccia:
    class XxxFetcher:
        def __init__(self, competition: Competition, team: Team, season: Season): ...
        def fetch_schedule(self) -> list[Match]: ...
        def fetch_scores(self, matches: list[Match]) -> list[Match]: ...

Il REGISTRY mappa stringa fetcher_type → classe.
Usato da main.py per istanziare il fetcher giusto per ogni competition.

Stato Fase 2: registry popolato con 2 fetcher per-competition + 1 singleton.
"""
from typing import Any

from .lnp import LNPFetcher
from .pianetabasket import PianetaBasketArticleFetcher
from .rss_pool import RssPoolFetcher

# Registry per fetcher per-competition (uno per ogni team+competition).
# 'rss_pool' NON sta qui: è singleton cross-team istanziato da main.py.
REGISTRY: dict[str, Any] = {
    "lnp": LNPFetcher,
    "pianetabasket": PianetaBasketArticleFetcher,
}


def get_fetcher(fetcher_type: str):
    """Ritorna la classe fetcher per il tipo, o None se non registrato."""
    return REGISTRY.get(fetcher_type)


__all__ = [
    "REGISTRY",
    "get_fetcher",
    "LNPFetcher",
    "PianetaBasketArticleFetcher",
    "RssPoolFetcher",
]
