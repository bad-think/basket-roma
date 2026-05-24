"""
models.py — Definizione dei tipi di dato strutturati per Basket Roma v9.0.

Tutto il sistema gira su questi modelli. Ogni fetcher produce Match;
lo State li raccoglie e li serializza/deserializza da/verso data.json.

Convenzioni:
- I tipi `str | None` indicano campo opzionale.
- I tipi Literal vincolano i valori accettati (es. Phase).
- Tutti i dataclass hanno from_dict/to_dict per (de)serializzazione JSON.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal, Any

# Tipi enumerati come Literal stringa (no enum, più semplice da serializzare)
Phase = Literal["regular", "playoff", "playout", "cup", "europe"]
CompetitionType = Literal["championship", "cup", "european"]
FetcherType = Literal["lnp", "rss_pool", "pianetabasket", "manual"]


# ============================================================================
# DOMINIO: Venue (impianto di gioco)
# ============================================================================
@dataclass
class Venue:
    """Impianto sportivo dove si gioca una partita in casa."""
    name: str
    address: str = ""
    maps_url: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Venue":
        return cls(
            name=d.get("name", ""),
            address=d.get("address", ""),
            maps_url=d.get("maps_url", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================================
# DOMINIO: Competition (campionato, coppa, europa per una squadra)
# ============================================================================
@dataclass
class Competition:
    """
    Una competizione attiva per una squadra in una stagione.
    Es: Serie B Nazionale girone B per Virtus, Coppa Italia LNP, EuroCup.
    """
    id: str                           # univoco: "b_naz_2526"
    type: CompetitionType             # championship | cup | european
    category: str                     # "B Nazionale" | "A2" | "Coppa Italia LNP"
    fetcher: FetcherType              # quale fetcher usare
    girone: str = ""                  # solo per championship
    source_slug: str = ""             # slug LNP o equivalente
    rss_section: int | None = None    # solo per pianetabasket fetcher
    phases: list[Phase] = field(default_factory=lambda: ["regular"])

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Competition":
        return cls(
            id=d["id"],
            type=d.get("type", "championship"),
            category=d.get("category", ""),
            fetcher=d.get("fetcher", "lnp"),
            girone=d.get("girone", ""),
            source_slug=d.get("source_slug", ""),
            rss_section=d.get("rss_section"),
            phases=d.get("phases", ["regular"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================================
# DOMINIO: Team (squadra tracciata)
# ============================================================================
@dataclass
class Team:
    """Squadra tracciata dal sistema, con tutte le sue competizioni attive."""
    key: str                          # identificatore breve: "virtus"
    display_name: str                 # nome visualizzato
    short_name: str = ""              # nome breve per UI
    aliases: list[str] = field(default_factory=list)  # nomi alternativi per matching
    color_primary: str = "#000000"
    color_secondary: str = "#FFFFFF"
    venue: Venue | None = None
    active_competitions: list[Competition] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Team":
        return cls(
            key=d["key"],
            display_name=d.get("display_name", d["key"]),
            short_name=d.get("short_name", ""),
            aliases=d.get("aliases", []),
            color_primary=d.get("color_primary", "#000000"),
            color_secondary=d.get("color_secondary", "#FFFFFF"),
            venue=Venue.from_dict(d["venue"]) if d.get("venue") else None,
            active_competitions=[
                Competition.from_dict(c) for c in d.get("active_competitions", [])
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "short_name": self.short_name,
            "aliases": self.aliases,
            "color_primary": self.color_primary,
            "color_secondary": self.color_secondary,
            "venue": self.venue.to_dict() if self.venue else None,
            "active_competitions": [c.to_dict() for c in self.active_competitions],
        }


# ============================================================================
# DOMINIO: Match (la singola partita)
# ============================================================================
@dataclass
class Match:
    """
    Una singola partita. Il modello universale per regular, playoff, playout,
    coppa, europa. La fase distingue il contesto.

    Convenzione storica v8.9: data.json contiene solo gare IN CASA delle
    squadre tracciate (visto da team_key). v9.0 mantiene questa convenzione.
    """
    id: str                           # stable id: "v_po_r37"
    team_key: str                     # "virtus" | "luiss"
    competition_id: str               # "b_naz_2526"
    phase: Phase                      # regular | playoff | playout | cup | europe
    date: str                         # ISO "YYYY-MM-DD"
    home: str                         # nome completo squadra casa
    away: str                         # nome completo squadra ospite
    time: str = "20:00"               # HH:MM
    round: int | None = None          # giornata regular o numero progressivo
    game_num: int | None = None       # 1..5 per playoff/playout best-of-5
    series_id: str | None = None      # raggruppa G1..G5 (es: "qf_tab2_vs_omegna")
    sh: int | None = None             # score home
    sa: int | None = None             # score away
    tentative: bool = False           # G4/G5 che potrebbero non disputarsi
    sources: list[str] = field(default_factory=list)  # provenance: ["bracket", "rss"]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Match":
        """Costruisce da dict, gestendo schema legacy v8.9.x."""
        # Legacy v8.9 usa "team" invece di "team_key" e non ha competition_id
        team_key = d.get("team_key") or d.get("team", "")
        competition_id = d.get("competition_id") or _infer_competition_id(d)

        return cls(
            id=d["id"],
            team_key=team_key,
            competition_id=competition_id,
            phase=d.get("phase", "regular"),
            date=d.get("date", ""),
            home=d.get("home", ""),
            away=d.get("away", ""),
            time=d.get("time", "20:00"),
            round=d.get("round"),
            game_num=d.get("game_num"),
            series_id=d.get("series_id"),
            sh=d.get("sh"),
            sa=d.get("sa"),
            tentative=d.get("tentative", False),
            sources=d.get("sources", []),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializza in dict, omettendo campi None/default per leggibilità."""
        out: dict[str, Any] = {
            "id": self.id,
            "team_key": self.team_key,
            "competition_id": self.competition_id,
            "phase": self.phase,
            "date": self.date,
            "time": self.time,
            "home": self.home,
            "away": self.away,
            "sh": self.sh,
            "sa": self.sa,
        }
        if self.round is not None:
            out["round"] = self.round
        if self.game_num is not None:
            out["game_num"] = self.game_num
        if self.series_id is not None:
            out["series_id"] = self.series_id
        if self.tentative:
            out["tentative"] = True
        if self.sources:
            out["sources"] = self.sources
        return out

    def to_legacy_dict(self) -> dict[str, Any]:
        """
        Serializza nello schema legacy v8.9 per retrocompatibilità frontend.
        Differenze: 'team' invece di 'team_key', no 'competition_id'.
        """
        out: dict[str, Any] = {
            "id": self.id,
            "team": self.team_key,
            "phase": self.phase,
            "date": self.date,
            "time": self.time,
            "home": self.home,
            "away": self.away,
            "sh": self.sh,
            "sa": self.sa,
        }
        if self.round is not None:
            out["round"] = self.round
        if self.game_num is not None:
            out["game_num"] = self.game_num
        if self.tentative:
            out["tentative"] = True
        return out


def _infer_competition_id(d: dict[str, Any]) -> str:
    """Per match legacy v8.9 senza competition_id, deduce da phase/round."""
    # In v8.9 c'era una sola competizione attiva: B Nazionale 2025-26
    return "b_naz_2526"


# ============================================================================
# DOMINIO: SeriesClosed (override manuale serie chiuse)
# ============================================================================
@dataclass
class SeriesClosed:
    """
    Marca esplicita che una serie playoff/playout è chiusa.
    Usata da fetcher e cleanup per impedire re-inserzione di gare obsolete.

    Campi `next_opponent` e `next_opponent_seed` sono usati dal fetcher
    LNPFetcher per dedurre automaticamente le gare del turno successivo
    quando team_advances=True. Popolati manualmente in Fase 2.2 (Opzione A);
    saranno auto-popolati dal tabellino LNP in Fase 2.3 (Opzione B).
    """
    team_key: str
    competition_id: str
    phase: Phase
    opponent: str
    result: str                       # "3-0" | "3-1" | "0-3" ...
    team_advances: bool               # True = vince e passa al turno successivo
    round_name: str = ""              # "QF" | "SF" | "F" | "P-OUT-R1" ...
    note: str = ""
    next_opponent: str = ""           # nome completo avversario nel round successivo
    next_opponent_seed: int | None = None  # seed dell'avversario nel round successivo

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SeriesClosed":
        # Compat con v8.9.2 che usa "team" invece di "team_key"
        team_key = d.get("team_key") or d.get("team", "")
        return cls(
            team_key=team_key,
            competition_id=d.get("competition_id", "b_naz_2526"),
            phase=d.get("phase", "playoff"),
            opponent=d.get("opponent", ""),
            result=d.get("result", ""),
            team_advances=d.get("team_advances", False),
            round_name=d.get("round_name", ""),
            note=d.get("note", ""),
            next_opponent=d.get("next_opponent", ""),
            next_opponent_seed=d.get("next_opponent_seed"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================================
# DOMINIO: Standing (posizione di squadra in classifica)
# ============================================================================
@dataclass
class Standing:
    """Posizione di classifica di una squadra in una competizione."""
    pos: int
    pts: int
    w: int                            # vittorie
    l: int                            # sconfitte

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Standing":
        return cls(
            pos=d.get("pos", 0),
            pts=d.get("pts", 0),
            w=d.get("w", 0),
            l=d.get("l", 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================================
# DOMINIO: RssFeed (configurazione di un feed RSS)
# ============================================================================
@dataclass
class RssFeed:
    """Sorgente RSS da interrogare per score post-partita."""
    url: str
    categories: list[str] = field(default_factory=lambda: ["all"])
    enabled: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RssFeed":
        return cls(
            url=d["url"],
            categories=d.get("categories", ["all"]),
            enabled=d.get("enabled", True),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================================
# DOMINIO: Season (configurazione completa di una stagione)
# ============================================================================
@dataclass
class Season:
    """
    Configurazione statica della stagione: squadre, competizioni, fonti, override.
    Caricata da config/seasons/{season}.json all'avvio.
    """
    season: str                       # "2025-26"
    next_season: str                  # "2026-27"
    teams: list[Team] = field(default_factory=list)
    rss_feeds: list[RssFeed] = field(default_factory=list)
    series_closed: list[SeriesClosed] = field(default_factory=list)
    league_classifica_url: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Season":
        return cls(
            season=d["season"],
            next_season=d.get("next_season", ""),
            teams=[Team.from_dict(t) for t in d.get("teams", [])],
            rss_feeds=[RssFeed.from_dict(r) for r in d.get("rss_feeds", [])],
            series_closed=[SeriesClosed.from_dict(s) for s in d.get("series_closed", [])],
            league_classifica_url=d.get("league_classifica_url", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "next_season": self.next_season,
            "league_classifica_url": self.league_classifica_url,
            "teams": [t.to_dict() for t in self.teams],
            "rss_feeds": [r.to_dict() for r in self.rss_feeds],
            "series_closed": [s.to_dict() for s in self.series_closed],
        }

    def get_team(self, key: str) -> Team | None:
        """Helper: ritorna Team per key, o None se non trovato."""
        for t in self.teams:
            if t.key == key:
                return t
        return None

    def enabled_rss(self) -> list[RssFeed]:
        """Helper: solo i feed RSS con enabled=True."""
        return [r for r in self.rss_feeds if r.enabled]
