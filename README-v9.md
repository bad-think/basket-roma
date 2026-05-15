[README-v9.md](https://github.com/user-attachments/files/27800408/README-v9.md)
# Basket Roma v9.0 — Rewrite

**Status**: Fase 1/5 (foundation) — completata
**Branch**: `v9-rewrite`
**Data inizio**: 15/05/2026

---

## Cosa contiene la Fase 1

Fondamenta dell'architettura nuova. **Nessun fetcher attivo**: ancora non scarica dati. Verifica solo che il sistema sappia leggere/scrivere `data.json` con la nuova struttura tipata.

```
basket-roma/
├── config/
│   └── seasons/
│       └── 2025-26.json          ← configurazione statica della stagione
├── scripts/
│   ├── main.py                   ← orchestrator (entry point)
│   ├── core/
│   │   ├── __init__.py           ← esporta i modelli
│   │   ├── models.py             ← dataclass tipati (Match, Team, ...)
│   │   └── state.py              ← load/save/merge data.json
│   └── fetchers/
│       └── __init__.py           ← registry placeholder per Fase 2
└── data.json                     ← invariato, gestito anche da v8.9
```

## Come testare in locale (opzionale)

Se vuoi testare prima di committare, scarica il branch e lancia:

```bash
git clone -b v9-rewrite https://github.com/bad-think/basket-roma.git
cd basket-roma
python3 scripts/main.py --dry-run     # solo report
python3 scripts/main.py               # genera data-v9.json
```

Output atteso (con data.json post-cleanup QF):
```
🏀 Basket Roma v9.0 — Fase 1 (foundation)
✅ Stagione caricata: 2025-26 → 2026-27
   Squadre: 2
   RSS feeds attivi: 3/5
   Series chiuse:    2
✅ State caricato
   matches=39 | by_team[luiss=19, virtus=20] | by_phase[playoff=3, regular=36]
💾 Salvataggio:
   ✓ data-v9.json (schema v9.0 nativo)
```

## Cosa NON fa ancora (per design)

- ❌ Nessuna chiamata a LNP / RSS / sito esterno
- ❌ Nessun aggiornamento score automatico
- ❌ Nessun update di `data.json` legacy (a meno di `--write-legacy`)
- ❌ Nessun workflow GitHub Actions modificato

**Il sito pubblico continua a girare con v8.9.2 invariato.**

## Schema dati v9.0

### Match (la singola partita)
```python
@dataclass
class Match:
    id: str                # "v_po_r37"
    team_key: str          # "virtus" (era "team" in v8.9)
    competition_id: str    # "b_naz_2526" (nuovo, identifica la competizione)
    phase: Phase           # regular | playoff | playout | cup | europe
    date: str              # "YYYY-MM-DD"
    home: str
    away: str
    time: str = "20:00"
    sh: int | None = None
    sa: int | None = None
    round: int | None = None
    game_num: int | None = None
    series_id: str | None = None   # raggruppa G1-G5 della stessa serie
    tentative: bool = False
    sources: list[str] = []         # provenance: ["bracket", "rss", "manual"]
```

### Competition (per ogni squadra può essere multipla)
```python
@dataclass
class Competition:
    id: str                # "b_naz_2526"
    type: str              # "championship" | "cup" | "european"
    category: str          # "B Nazionale"
    fetcher: str           # quale fetcher usare per questa competizione
    girone: str = ""
    source_slug: str = ""  # es. "serie-b" per LNP
    rss_section: int | None = None   # per pianetabasket fetcher
    phases: list[Phase]
```

### Config stagionale (config/seasons/2025-26.json)
File JSON statico con:
- `season`, `next_season`
- `teams[]` — squadre tracciate con `active_competitions[]`
- `rss_feeds[]` — pool RSS riusabile (sportando, basketinside, pianetabasket sezioni)
- `series_closed[]` — override manuale per serie chiuse

## Roadmap rimanente

| Fase | Obiettivo | Stato |
|------|-----------|-------|
| 1 | Foundation: models + state + main scheletro | ✅ Completata |
| 2 | Fetchers: LNPFetcher, RssPoolFetcher, PianetaBasketArticleFetcher | ⏳ Prossima |
| 3 | Frontend data-driven (autoconfigurante da config.teams) | ⏳ |
| 4 | Cutover: swap GitHub Actions a main + delete codice v8.9 | ⏳ |
| 5 | Hardening: AST pre-commit hook, unit test, alert no-capture | ⏳ |

## Quando finiremo

- Fase 2: 2-3 sessioni → ~10 giorni
- Fase 3: 2-3 sessioni → ~10 giorni
- Fase 4: 1 sessione → 1 giorno
- Fase 5: 1-2 sessioni → ~5 giorni

**Totale stimato**: 3-4 settimane. Le SF Virtus iniziano 21/5 e durano max 10 giorni: ci avviciniamo alla fine SF con Fase 2 completata.

## Compatibilità con v8.9

- `config/seasons/2025-26.json` è un **nuovo file**: non interferisce con v8.9.
- `scripts/main.py` v9 produce `data-v9.json` separato: il `data.json` esistente non viene toccato.
- Il workflow `.github/workflows/update-data.yml` di v8.9 **non è modificato**: continua a girare 8 volte/giorno con `scripts/update_data.py` di v8.9.
- Quando v9.0 sarà pronto: cambieremo il workflow per chiamare `scripts/main.py` invece di `scripts/update_data.py`.
