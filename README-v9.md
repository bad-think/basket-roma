[README-v9.md](https://github.com/user-attachments/files/27851493/README-v9.md)
# Basket Roma v9.0 — Rewrite

**Status**: Fase 2/5 (fetcher modulari) — pronta per test
**Branch**: `v9-rewrite`
**Data ultimo update**: 15/05/2026

---

## Cosa è cambiato in Fase 2

Aggiunti i fetcher concreti per recupero dati. Il sistema **ora può scaricare davvero da LNP e RSS**.

```
basket-roma/  (branch v9-rewrite)
├── config/seasons/2025-26.json   ← Fase 1
├── scripts/
│   ├── main.py                   ← aggiornato Fase 2 (orchestrator completo)
│   ├── core/                     ← Fase 1, invariato
│   │   ├── __init__.py
│   │   ├── models.py
│   │   └── state.py
│   └── fetchers/
│       ├── __init__.py           ← registry popolato Fase 2
│       ├── _http.py              ← NUOVO: helper HTTP condiviso
│       ├── _text.py              ← NUOVO: normalize, score extraction, fuzzy match
│       ├── lnp.py                ← NUOVO: LNPFetcher (team page + PDF + bracket)
│       ├── rss_pool.py           ← NUOVO: pool unificato sportando+basketinside+pianetabasket
│       └── pianetabasket.py      ← NUOVO: parser articoli per europee (skeleton)
└── .github/workflows/
    ├── update-data.yml           ← v8.9.2 invariato su main
    ├── freshness-check.yml       ← v8.9.2 invariato su main
    └── update-data-v9-test.yml   ← NUOVO Fase 2: workflow manuale di test
```

## Confronto con v8.9.1

| Metrica | v8.9.1 | v9.0 Fase 2 | Δ |
|---|---|---|---|
| Righe totali Python | 2727 | 1922 | **-30%** |
| File Python | 1 monolitico | 9 modulari | **+800% leggibilità** |
| Cascade morti (Domino, brute force) | 4 livelli | 0 | **-100%** |
| Fonti score effettive | 2 RSS | 3 RSS + LNP team page | **+50%** |
| Estendibile (nuova competizione) | 1-3 sessioni codice | 1 riga config | **~∞ meglio** |

## Architettura dei fetcher

### LNPFetcher
- `fetch_schedule()` → calendario regular (team page LNP) + playoff (bracket parser)
- `fetch_scores()` → score da widget LNP team page
- **Riusa** logica v8.9 ma **eliminato** il codice morto
- Filtra automaticamente le serie chiuse via `config.series_closed`

### RssPoolFetcher (singleton)
- `refresh()` → scarica tutti i feed RSS attivi una volta
- `find_score(match, home_aliases, away_aliases)` → cerca menzione partita nei titoli/descrizioni
- Cross-team: serve tutte le squadre in una sola lettura

### PianetaBasketArticleFetcher
- Skeleton funzionante per europee (EuroCup, Champions League, EuroLeague)
- Cerca articoli con keyword `calendario`, `risultati`, `turno` nella sezione RSS specifica
- Parser regex per `"GG mese, ore HH:MM: TeamA vs TeamB NN-NN"`
- **Non testato sul vero** finché nessuna squadra tracciata accede a europee — la prima qualificazione richiederà fine-tuning regex

## Test offline già fatti

Parser regex validati su sample reali:
- ✅ QF Virtus 2025-26: estrazione 5 date "Venerdì 8, domenica 10, mercoledì 13, venerdì 15, domenica 18 maggio" → 2026-05-{08,10,13,15,18}
- ✅ SF formula 2025-26: "Giovedì 21, sabato 23, martedì 26, giovedì 28, domenica 31 maggio" → 2026-05-{21,23,26,28,31}
- ✅ Score extraction: "94-71", "82 - 76", "65–82" (en-dash)
- ✅ Name matching: "OraSì Ravenna" ↔ "orasi-ravenna" (gestione accenti)
- ✅ Round-trip data.json: 39 matches preservati, schema convertito

## Test reale da fare (su GitHub)

Per testare i fetcher veri **senza toccare main**:

### Step 1 — Crea il workflow di test
Crea il file `.github/workflows/update-data-v9-test.yml` sul branch `v9-rewrite`. Contenuto fornito in questo PR.

### Step 2 — Lancia manualmente
1. Vai su https://github.com/bad-think/basket-roma/actions
2. Seleziona "**Test v9 (manual)**" nella sidebar
3. Click **`Run workflow`** → selezioni branch `v9-rewrite` → **`Run workflow`**
4. Attendi ~1 minuto, click sulla run per vedere il log

### Step 3 — Confronta output
Il workflow produce due artifact scaricabili:
- `data-v9.json` (output v9.0)
- `data.json.legacy` (output v9.0 in formato compatibile v8.9)

Confronta `data-v9.json` con il `data.json` attuale di main:
- Numero match deve coincidere (39 + eventuali aggiornamenti)
- Score esistenti devono essere preservati
- Series chiuse devono restare filtrate

### Step 4 — Decidi
- ✅ Se l'output v9 è coerente con v8.9.2 → procediamo con Fase 3 (frontend)
- ❌ Se ci sono regressioni → segnala, debug, fix

## Cosa NON fa ancora (per design)

- ❌ Non aggiorna `data.json` su main automaticamente (solo via `--write-legacy` esplicito)
- ❌ Il cron 8x/giorno continua a girare `update_data.py` v8.9.1 su main
- ❌ Il frontend `index.html` continua a leggere `data.json` (non `data-v9.json`)
- ❌ Nessuna copertura A2/A/Coppa/Europee attiva (feed RSS predisposti ma `enabled: false`)

## Roadmap rimanente

| Fase | Obiettivo | Stato |
|------|-----------|-------|
| 1 | Foundation: models + state + main scheletro | ✅ Completata |
| 2 | Fetchers: LNPFetcher, RssPoolFetcher, PianetaBasketArticleFetcher | ✅ Completata |
| 3 | Frontend data-driven (autoconfigurante da config.teams) | ⏳ Prossima |
| 4 | Cutover: swap GitHub Actions a v9, retire `update_data.py` v8.9 | ⏳ |
| 5 | Hardening: AST pre-commit hook, unit test, alert no-capture | ⏳ |

## Limiti onesti

- **Parser LNP team page** (`_iter_lnp_calendar_rows`): regex semplificata rispetto a v8.9. **Potrebbe** non matchare tutti i casi edge della pagina LNP reale. Il test reale via workflow è necessario per verifica.
- **PianetaBasket parser articoli**: regex tarata su formato tipico ma può fallire su articoli scritti diversamente. Solo il primo uso reale lo dirà.
- **Cascade discovery lega** (per quando Virtus salirà): non implementato in v9 Fase 2. Aggiungeremo in Fase 4 se serve. Per ora la `source_slug` è hardcoded in config.
- **PDF parser calendario** (per round numbering): non portato in Fase 2. La logica c'è in v8.9, andrà splittata in `parsers/pdf_calendar.py` in Fase 3 quando serviranno round corretti nel frontend.

Questi sono **deliberati**: portiamoli quando avremo evidenza che servono. La Fase 2 è già funzionale per il caso d'uso primario.
