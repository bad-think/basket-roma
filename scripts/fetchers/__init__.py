"""
scripts/fetchers — Plugin per il recupero dati da fonti esterne.

Ogni fetcher è una classe con interfaccia minima:
    class XxxFetcher:
        def __init__(self, competition: Competition, team: Team): ...
        def fetch_schedule(self) -> list[Match]: ...
        def fetch_scores(self, matches: list[Match]) -> list[Match]: ...

Il REGISTRY mappa stringa fetcher_type → classe, usato da main.py.

Stato Fase 1: registry vuoto. I fetcher concreti arrivano in Fase 2:
- lnp.py            — LNP (Serie B/A2/A + Coppa Italia LNP)
- rss_pool.py       — Pool RSS (sportando + basketinside + PianetaBasket)
- pianetabasket.py  — PianetaBasket article parser per europee
"""
from typing import Any

# Registry vuoto in Fase 1. Verrà popolato in Fase 2.
# Esempio target: REGISTRY = {"lnp": LNPFetcher, "rss_pool": RssPoolFetcher, ...}
REGISTRY: dict[str, Any] = {}


def get_fetcher(fetcher_type: str):
    """Ritorna la classe fetcher per il tipo, o None se non registrato."""
    return REGISTRY.get(fetcher_type)
