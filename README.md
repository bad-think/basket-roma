[README.md](https://github.com/user-attachments/files/32595317/README.md)
# 🏀 Roma Basket Sport

**Live → [bad-think.github.io/basket-roma](https://bad-think.github.io/basket-roma)**

PWA per seguire le squadre romane di pallacanestro: calendario gare casalinghe, risultati, classifica, countdown e notifiche. Stile brutalist nero/giallo. Mobile-first, funziona offline.

---

## Squadre tracciate — stagione 2026-27

| Squadra | Categoria | Palazzetto |
|---|---|---|
| Virtus GVM Roma 1960 | Serie B Nazionale (gir. B) | PalaTiziano |
| LUISS Roma | Serie B Nazionale (gir. B) | PalaTiziano |
| BC Roma SPQR | Serie A LBA + EuroCup | PalaTiziano |
| Maxima Roma | Serie A LBA + EuroCup | PalaEUR |

---

## Architettura

```
cron (3-8/giorno) — .github/workflows/update-data.yml
│
├── 1. scripts/update_data.py  (v8.9 legacy)
│       Scraping LNP: calendario, classifica girone Serie B
│       → data.json  (schema legacy, Virtus + LUISS)
│
└── 2. scripts/main.py  (v9 orchestrator)
        Arricchisce v8.9 + gestisce team LBA:
        ├── fetchers/lnp.py      → tabellini, parziali, playoff dedotti
        ├── fetchers/lba.py      → calendario BC Roma e Maxima (legabasket.it)
        ├── fetchers/rss_pool.py → score da feed RSS (Sportando, PianetaBasket)
        └── core/ (models, state, season)
        → data-v9.json  (schema v9.0, fonte primaria frontend)
                │
                ▼
          index.html (PWA)
          Legge data-v9.json · 4 tab squadra · standings · countdown
```

**Principi operativi:**
- `continue-on-error: true` su v9 → v8.9 continua sempre
- `concurrency: update-data` → nessun push parallelo
- Step cleanup idempotente dopo ogni run
- Freshness-check alert se cron fermo >24h
- Costo: **€0** (repo pubblico, GitHub Actions free)

---

## Struttura repository

```
basket-roma/
├── index.html              # PWA frontend (single file, 4 team)
├── sw.js                   # service worker offline
├── manifest.json
├── data.json               # output v8.9 (Virtus + LUISS)
├── data-v9.json            # output v9  (4 squadre, schema 9.0)
│
├── scripts/
│   ├── update_data.py      # v8.9 legacy (LNP Serie B)
│   ├── main.py             # v9 orchestrator
│   ├── core/
│   │   ├── models.py       # Match, Team, Competition, Season, Standing
│   │   └── state.py        # state loader + merge + save_v9
│   └── fetchers/
│       ├── lnp.py          # LNP: schedule, tabellino, probing external_id
│       ├── lba.py          # LBA: legabasket.it (schedule statica + fetcher live)
│       ├── rss_pool.py     # RSS pool multi-source con guard pubDate
│       ├── _http.py
│       └── _text.py
│
├── config/
│   └── seasons/
│       ├── 2025-26.json    # stagione chiusa (series_closed completi)
│       └── 2026-27.json    # stagione corrente (4 team, home_games LBA)
│
└── .github/workflows/
    ├── update-data.yml         # cron principale
    ├── freshness-check.yml
    └── update-data-v9-test.yml # test manuale
```

---

## Stato del progetto

### ✅ Completato — stagione 2025-26

- Fase 1 — Architettura v9 multi-team
- Fase 2.1 — Hybrid mode (v9 arricchisce v8.9)
- Fase 2.2 — Deducer playoff (genera schedule SF/F automaticamente)
- Fase 2.3a/b/c — Tabellino LNP: parser score+parziali, discovery external_id via pagina avversario, probing sequenziale (`MAX_MISSES=12`) per id inter-girone
- Fase 2.3c-fix — Guardia pubDate in rss_pool (anti-contaminazione gare stesso avversario)
- Frontend v9: parziali per quarto, bottone TABELLINO ↗, caveat gare tentative

### ✅ Completato — stagione 2026-27

- Transizione automatica a 2026-27 (slugs LNP invariati)
- `config/seasons/2026-27.json`: 4 squadre, home_games LBA statici, RSS disabilitati se 404
- Slugs LBA verificati su legabasket.it (23/09/2026): BC Roma SPQR = `bc-roma-spqr` (ID 1761), Maxima Roma = `maxima-roma` (ID 1762)
- `fetchers/lba.py`: __NEXT_DATA__ + HTML scraping + fallback statico da config
- `core/models.py`: Competition espone `enabled`, `home_games`, `legabasket_id`
- Frontend: 4 tab squadra, score-bar per team, PLAYOFF nascosto fino a playoff esistenti
- Standings iniettati per tutti i team (inclusi LBA, inizialmente pos=0)

### 🔜 Roadmap

| Fase | Target | Descrizione |
|---|---|---|
| 4 | inverno 2026 | Cutover completo: dismissione `update_data.py`, v9 unico sistema |
| 6 | ott 2026 | Fetcher LBA live (legabasket.it __NEXT_DATA__ / API) per score in tempo reale |
| 6b | ott 2026 | Fetcher EuroCup (euroleaguebasketball.net) — BC Roma Gruppo D |
| 7 | feb 2027 | Coppa Italia LBA Final Eight (Torino, 17-21/02/2027) |
| 8 | 2027-28 | Fetcher NBA Europe (se slot confermato per Roma) |

---

## Note tecniche

**LBA fetcher (Fase 6):** legabasket.it è un'app Next.js con SSR. Il piano è estrarre `__NEXT_DATA__` o usare l'endpoint `/_next/data/{buildId}/...`. Fino al fetcher live, il calendario casalingo è pre-caricato in `config/seasons/2026-27.json → home_games`.

**EuroCup BC Roma 2026-27:** Gruppo D con Lietkabelis, BOSNA BH Telecom, PAOK, Manresa, Balkan, ratiopharm Ulm (AS Monaco esclusa per insolvenza). Prima gara casa: 06/10/2026 vs Lietkabelis (PalaTiziano).

**Modalità sviluppo:** browser-only — tutte le modifiche via GitHub web editor. Nessun terminale locale. Documento operativo: [`CONTINUITA.md`](CONTINUITA.md).

---

## Stack

- **Frontend:** HTML5 + CSS3 + Vanilla JS + Service Worker
- **Backend:** Python 3.11 (stdlib + requests)
- **Hosting:** GitHub Pages (branch `main`)
- **CI/CD:** GitHub Actions (free tier illimitato su repo pubblici)
- **Storage:** JSON committati nel repo
- **Dati:** LNP, legabasket.it, RSS (Sportando, PianetaBasket)

---

*PWA non ufficiale — nessuna affiliazione con le società o le leghe citate. Dati di proprietà delle rispettive organizzazioni.*
