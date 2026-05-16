"""
scripts/core — Modelli dati e gestione stato per Basket Roma v9.0.

Esporta le classi pubbliche utilizzabili da main.py e dai fetcher:
- Match, Team, Competition, Venue, SeriesClosed, Standing, Season, State
"""
from .models import (
    Match,
    Team,
    Competition,
    Venue,
    SeriesClosed,
    Standing,
    Season,
    RssFeed,
    Phase,
    CompetitionType,
)
from .state import State

__all__ = [
    "Match",
    "Team",
    "Competition",
    "Venue",
    "SeriesClosed",
    "Standing",
    "Season",
    "RssFeed",
    "Phase",
    "CompetitionType",
    "State",
]
