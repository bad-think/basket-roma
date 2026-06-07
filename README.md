# 🏀 Roma Basket Sport

> **Live → [bad-think.github.io/basket-roma](https://bad-think.github.io/basket-roma/)**

PWA (Progressive Web App) per seguire le squadre romane di pallacanestro: calendario, risultati, classifica, countdown alle partite e notifiche.

Stile brutalist arancione/giallo/nero. Pensato mobile-first. Funziona offline grazie a service worker.

---

## Squadre tracciate

| Squadra | Categoria | Stagione | Stato |
|---------|-----------|----------|-------|
| Virtus GVM Roma 1960 | B Nazionale (gir. B) | 2025-26 | ✅ attiva |
| Luiss Roma | B Nazionale (gir. B) | 2025-26 | ✅ attiva |
| BC Roma | Serie A LBA | 2026-27 | 🔜 da ottobre 2026 |

---

## Architettura

Il backend è organizzato in **due strati che cooperano**, entrambi schedulati 8 volte al giorno via GitHub Actions:

```
┌─────────────────────────────────────────────┐
│  cron (8/giorno) — .github/workflows        │
│  └── update-data.yml                        │
│       ├── 1. scripts/update_data.py  (v8.9) │
│       │       └→ data.json (schema legacy)  │
│       └── 2. scripts/main.py         (v9)   │
│               └→ data-v9.json (schema v9)   │
└─────────────────────────────────────────────┘
                      │
                      ▼
              index.html (PWA)
              └→ legge data-v9.json
                 (adapter v9 → legacy compat)
```

**v8.9** (`update_data.py`): monolitico, scraping LNP + PDF calendario + classifica girone. Produce `data.json` (schema legacy).

**v9** (`scripts/main.py` + `scripts/core/` + `scripts/fetchers/`): modulare, multi-team/multi-categoria. Arricchisce v8.9 con:
- tabellini LNP (score + parziali per quarto)
- deduzione automatica schedule playoff (SF e Finale)
- discovery degli `external_id` LNP via pagina squadra avversario
- multi-source (RSS pool: Sportando, PianetaBasket, ecc.)

**Frontend** legge `data-v9.json` come fonte primaria con adapter di compatibilità verso lo schema legacy. Dedup intelligente per gestire duplicati tra le due fonti.

---

## Struttura repository

```
basket-roma/
├── index.html              # PWA frontend (single file)
├── sw.js                   # service worker offline
├── manifest.json           # PWA manifest
├── data.json               # output v8.9 (schema legacy)
├── data-v9.json            # output v9 (schema 9.0, fonte primaria frontend)
│
├── scripts/
│   ├── update_data.py      # v8.9 monolitico (legacy fetcher)
│   ├── main.py             # v9 orchestrator
│   ├── core/
│   │   ├── models.py       # Match, Team, Season, SeriesClosed
│   │   └── state.py        # state loader + merge logic
│   └── fetchers/
│       ├── lnp.py          # fetcher LNP + deducer Fase 2.2
│       ├── pianetabasket.py
│       ├── rss_pool.py
│       └── _text.py        # utility text parsing
│
├── config/
│   └── seasons/
│       └── 2025-26.json    # config stagione (squadre, RSS, series_closed)
│
└── .github/workflows/
    ├── update-data.yml             # cron principale (8/giorno)
    ├── freshness-check.yml         # alert se cron fermo >24h
    └── update-data-v9-test.yml     # workflow manuale di test v9
```

---

## Automazione

**Schedule cron** (orari italiani, gestiti UTC):
- Serali: 18, 19, 20, 21, 22, 23
- Notturna: 04:00

**Garanzie operative:**
- `concurrency: update-data` → una sola run alla volta, no push paralleli
- `continue-on-error: true` su step v9 → se v9 fallisce, v8.9 continua a girare e il frontend resta servito
- Step cleanup idempotente → rimuove eventuali partite spurie da bug deducer
- Workflow `freshness-check` alerta via email se update-data non gira con successo da >24h

**Costo:** €0 (repo pubblico → GitHub Actions free e illimitati)

---

## Caratteristiche frontend

- Multi-team da config (oggi 2, domani 3 con BC Roma — autoconfigurazione)
- Multi-classifica per categoria (B Nazionale, A2, Serie A) — un bottone per ogni lega distinta
- Countdown alla prossima partita
- Risultati live con badge e notifiche browser
- Calcolo "casa giocate / restanti" per ogni squadra
- Banner ticker con ultimi risultati
- Detection automatica: serie chiusa / eliminata / in attesa di playoff
- Offline-first via service worker

---

## Stato del progetto

**Stagione 2025-26:**
- ✅ Fase 1 — Foundation v9 (multi-team architecture)
- ✅ Fase 2.1 — Hybrid mode (v9 arricchisce v8.9)
- ✅ Fase 2.2 — Next-round deducer (genera schedule SF/F automaticamente)
- ✅ Fase 2.3a — Tabellino parser LNP (score + parziali)
- ✅ Fase 2.3b — Discovery `external_id` via pagina avversario
- ✅ Cutover backend v9 in produzione su `main`
- ✅ Fase 3 — Frontend nativo v9 (multi-classifica + dedup intelligente)

**Roadmap:**
- 🔜 Fase 4 — Cutover completo v8.9→v9, dismissione `update_data.py` (estate 2026)
- 🔜 Fase 6 — Fetcher LBA (`scripts/fetchers/lba.py`) per Serie A → integrazione BC Roma (settembre 2026)
- 🔜 Fase 7 — Coppa Italia LBA Final Eight (gennaio 2027, se BC Roma top-8)
- 🔜 Fase 8 — Fetcher NBA Europe (estate 2027, se BC Roma selezionata)

---

## Stack tecnico

- **Frontend:** HTML5 + CSS3 + Vanilla JavaScript (no framework), Service Worker
- **Backend:** Python 3.11 (stdlib + minimal deps)
- **Hosting:** GitHub Pages (deploy automatico da branch `main`)
- **CI/CD:** GitHub Actions (free tier illimitato per repo pubblici)
- **Storage dati:** file JSON committati nel repo
- **Sorgenti dati:** LNP, PDF calendario, RSS Pool (Sportando, PianetaBasket)

---

## Sviluppo

Il progetto è mantenuto da una sola persona ([@bad-think](https://github.com/bad-think)) in modalità browser-only (nessun terminale locale, tutte le modifiche via web editor di GitHub).

**Documento operativo:** `CONTINUITA.md` mantiene lo stato di tutte le decisioni architetturali, bug noti e prossimi step. È la fonte di verità per riprendere il lavoro tra una sessione e l'altra.

---

## Licenza

Codice e contenuti del repository sono di proprietà dell'autore. I dati delle partite sono di proprietà della Lega Nazionale Pallacanestro (LNP) e delle rispettive società sportive.

PWA non ufficiale: nessuna affiliazione con Virtus GVM Roma 1960, Luiss Roma o LNP.
