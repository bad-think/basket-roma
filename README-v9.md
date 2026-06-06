[README-v9.md](https://github.com/user-attachments/files/27855096/README-v9.md)
# Basket Roma v9.0 — Rewrite (Hybrid mode)

**Status**: Fase 2.1 (Hybrid) — pronta per test reale
**Branch**: `v9-rewrite`
**Data ultimo update**: 16/05/2026

---

## Strategia Hybrid (decisione 16/05/2026)

Il test reale della Fase 2 ha rivelato che **riscrivere il parser LNP team page** richiederebbe 3-5 sessioni di solo tuning su HTML reale. v8.9 ha 2700 righe di parser raffinati negli anni: re-implementarli "da zero" non porta valore.

**Soluzione adottata**: v9 NON sostituisce v8.9 come fetcher LNP. v8.9 continua a girare su main e popola `data.json` (calendario regular + score base). v9 porta valore aggiunto **diverso**:

- **Series closure detection** con override manuale (config.series_closed)
- **RSS pool** multi-feed con matching permissivo per score
- **Bracket playoff parser** per generazione automatica SF/F/Playout
- **Architettura plugin** pronta per Coppa, A2, europee senza refactor

## Cosa fa effettivamente v9 in Hybrid

1. Legge `data.json` (popolato da v8.9)
2. Genera nuove gare playoff dal bracket LNP (quando LNP pubblica nuovo turno)
3. Filtra gare di serie chiuse via `config.series_closed`
4. Cerca score mancanti nei feed RSS configurati (pool multi-fonte)
5. Salva `data-v9.json` arricchito

## Cosa NON fa v9 (delegato a v8.9)

- Parsing calendario regular season LNP
- PDF round map calendario ufficiale
- Classifica girone
- Discovery lega cascade

Questi continuano in v8.9 update_data.py su main.

## Struttura aggiornata

```
basket-roma/  (branch v9-rewrite)
├── config/seasons/2025-26.json   ← 8 RSS feed dichiarati, 2 attivi
├── scripts/
│   ├── main.py                   ← orchestrator Hybrid
│   ├── core/                     ← invariato dalla Fase 1
│   └── fetchers/
│       ├── _http.py              ← invariato
│       ├── _text.py              ← invariato
│       ├── lnp.py                ← REWRITE: solo bracket + score widget
│       ├── rss_pool.py           ← matching permissivo, gestione CDATA
│       └── pianetabasket.py      ← invariato (skeleton europee)
└── .github/workflows/
    └── update-data-v9-test.yml   ← workflow manuale invariato
```

## Test in Fase 2.1 (sample reali)

Verificato offline su sample XML simulato (basato su titoli sportando reali):

```
Title: "Playoff Serie B Nazionale, i risultati di gara 1 di venerdì 8 maggio"
Description: "Virtus GVM Roma 1960-Paffoni Fulgor Basket Omegna 94-71. ..."

→ Score estratti: [(94,71), (92,84), (72,89)]
→ Match Virtus alias 'Virtus GVM Roma 1960' in titolo: ✅
→ Match Omegna alias 'Paffoni Fulgor Basket Omegna' in titolo: ✅
→ Match Luiss + Orzinuovi nello stesso testo: ✅
```

## Test reale necessario su GitHub

Stesso workflow di prima: `Test v9 (manual)` su branch `v9-rewrite`.

Esito atteso ora rispetto al precedente:
```
ANTE Fase 2.1 (problemi reali):
  📋 [virtus] Schedule: 0 match recuperati          ← parser team page rotto
  📰 RSS sportando feed/: 0 menzioni                ← feed sbagliato
  ⚠️  Feed non parseabile: basketinside             ← XML invalido
  📰 RSS pianetabasket sez.38: 1 menzioni (0 score) ← matching ristretto

POST Fase 2.1 (atteso):
  · [virtus] Schedule: nessuna nuova partita       ← INFORMATIVO, atteso
  📰 RSS sportando serie-b feed: N menzioni        ← feed specifico
  📰 RSS pianetabasket sez.38: M menzioni
  · basketinside: enabled=false                     ← disabilitato
  ✅ RSS pool: K score aggiornati                   ← se ce ne sono
```

## Cambiamenti specifici dalla Fase 2

### config/seasons/2025-26.json
- ✅ Aggiunto `sportando.basketball/category/europa/italia/serie-b/feed/` (specifico)
- ✅ Disabilitato `sportando.basketball/feed/` generale (troppo rumore)
- ✅ Disabilitato `basketinside.com/feed/` (XML invalido, da investigare separatamente)
- ✅ Aggiunti feed PianetaBasket per A2/A/EuroCup/Champions (enabled: false, attivabili)

### scripts/fetchers/lnp.py
- ❌ Rimosso `_fetch_team_calendar` e `_iter_lnp_calendar_rows` (regex troppo fragile)
- ❌ Rimosso `_fetch_team_results` (delegato a v8.9)
- ✅ Mantenuto `_fetch_playoff_bracket` (utile, regex stabile)
- ✅ Mantenuto `_filter_closed_series`
- ✅ Riscritto `fetch_scores` per cercare score playoff via window-based matching su pagina LNP
- Da 471 → 320 righe (-32%)

### scripts/fetchers/rss_pool.py
- ✅ Gestione CDATA WordPress via `el.itertext()` (era `el.text`)
- ✅ Matching team più permissivo: alias intera OR parole distintive multiple
- ✅ Stopword italiane filtrate (`basket`, `club`, `team`, `pallacanestro`, `sport`)
- ✅ Log più informativo (distingue "0 score" vs "feed rotto")

### scripts/main.py
- ✅ Banner versione → "Fase 2.1 (Hybrid)"
- ✅ Schedule=0 non mostrato come allarme ma come info attesa

## Roadmap rimanente

| Fase | Obiettivo | Stato |
|------|-----------|-------|
| 1 | Foundation: models + state | ✅ |
| 2 | Fetchers (LNP, RSS, PianetaBasket) | ✅ |
| 2.1 | Hybrid pivot | ✅ Corrente |
| 3 | Frontend data-driven | ⏳ Prossima |
| 4 | Cutover (parziale o totale) | ⏳ |
| 5 | Hardening | ⏳ |

Il cutover Fase 4 sarà ridefinito:
- **NON** sostituirà v8.9 completamente
- v9 girerà in parallelo come "augmentation step" dopo v8.9
- Workflow: v8.9 produce data.json (regular + bracket parsing parziale)
  → v9 lo arricchisce con RSS pool + series_closed enforcement
  → frontend legge data.json (uno solo, schema retrocompatibile)
