# CONTINUITA.md — Basket Roma PWA

> **Documento operativo single-source-of-truth.** Letto per riprendere il lavoro in nuova sessione senza ricostruire contesto.

---

## 1. Identità progetto

| | |
|---|---|
| **Live** | https://bad-think.github.io/basket-roma/ |
| **Repo** | https://github.com/bad-think/basket-roma (pubblico) |
| **Owner** | [@bad-think](https://github.com/bad-think) — solo developer |
| **Scopo** | PWA tracking squadre romane basket: calendario, risultati, classifica, countdown, notifiche |
| **Stile** | Brutalist arancione/giallo/nero, mobile-first, offline-first via service worker |
| **Hosting** | GitHub Pages da branch `main` |
| **CI/CD** | GitHub Actions free unlimited (repo pubblico) — costo €0 |

---

## 2. CONVENZIONI UTENTE — CRUCIALI

Da rispettare SEMPRE:

- **Browser-only.** No terminale locale, no editor IDE, no comandi shell. Tutte modifiche via web editor GitHub.
- **No programmazione autonoma.** Forniscigli sempre file COMPLETI da sostituire interamente. MAI istruzioni "modifica la riga X" o "aggiungi questo blocco". Solo: "apri questo URL, Ctrl+A, Delete, incolla il file, Commit".
- **Lingua italiana** sempre nelle risposte e commit messages.
- **Commit messages strutturati.** Dopo ogni file modificato fornisci sempre: file version (se versioned) + change summary. Esempi: `fix(lnp): heading "Finali" plurale + lookbehind regex`, `feat(frontend): switch source a data-v9.json + multi-classifica`.
- **Sostituzione file intera**, mai patch parziali. L'utente non sa risolvere conflict né merge selettivi.
- **AST validation** sui Python e syntax check sui JS prima di consegnare.
- **userPreferences attive** (sempre):
  - Anti-hallucination: classificare claim come [VERIFIED]/[INFERRED]/[UNCERTAIN] quando non banale
  - Dire `"non ho dati"` invece di inventare
  - Reasoning silenzioso prima di output denso
  - No "Certamente!", "Ottima domanda!", padding
  - Output denso, no ripetizioni, no postambolo
  - Critical thinking: contraddire premesse sbagliate
  - Intellectual honesty: se sbaglio, lo dico esplicitamente
  - Ottimizza uso token

---

## 3. Stato corrente (07/06/2026)

### Cosa gira in produzione

```
Cron 8/giorno (16,17,18,19,20,21 UTC + 2,3 UTC) → update-data.yml
├── Step 1: python scripts/update_data.py     [v8.9 legacy, ~1m]
├── Step 2: cleanup partite v9 spurie         [idempotente, 0s]
├── Step 3: python scripts/main.py            [v9 enrichment, ~15s]
└── Step 4: git commit + push se modifiche

Frontend: index.html
└── fetch('data-v9.json') → adapter v9→legacy → render
```

### Fasi completate ✅

1. Foundation v9 (multi-team architecture)
2. Hybrid mode (v9 arricchisce v8.9)
3. Next-round deducer Fase 2.2
4. Tabellino parser LNP Fase 2.3a
5. Discovery `external_id` via avversario Fase 2.3b
6. **Cutover backend v9 in produzione** (06/06)
7. **Frontend Fase 3 nativo v9** (07/06)
8. **Fix bug deducer date Finale** (07/06)

### Stagione 2025-26 stato squadre

| Squadra | Categoria | Stato playoff |
|---------|-----------|---------------|
| Virtus GVM Roma 1960 | B Naz gir B | 1° (29V-7P, 58pt) — **in FINALE** vs La T Tecnica Gema Montecatini (G1 8/6 ore 20:30) |
| Luiss Roma | B Naz gir B | 7° (21V-15P, 42pt) — eliminata QF (0-3 vs Logiman Orzinuovi) |

Pattern Finale (Virtus higher seed 1B vs Montecatini seed 2A): C-C-F-F-C
- G1 8/6 casa, G2 10/6 casa, G3 13/6 trasferta, G4 15/6 trasferta, G5 18/6 casa (se necessaria, tentative)

---

## 4. Architettura file

```
basket-roma/
├── index.html                         # PWA frontend single-file, ~2100 righe
├── sw.js                              # service worker offline
├── manifest.json                      # PWA manifest
├── data.json                          # output v8.9 (schema legacy)
├── data-v9.json                       # output v9 (schema 9.0) — FONTE PRIMARIA FRONTEND
├── README.md                          # con link live
├── CONTINUITA.md                      # questo file
│
├── scripts/
│   ├── update_data.py                 # v8.9 monolitico ~1m, scraping LNP + PDF + classifica
│   ├── main.py                        # v9 orchestrator
│   ├── core/
│   │   ├── __init__.py
│   │   ├── models.py                  # Match, Team, Season, SeriesClosed dataclasses
│   │   └── state.py                   # state load/save + merge logic
│   └── fetchers/
│       ├── __init__.py                # REGISTRY = {"lnp": LNPFetcher, ...}
│       ├── _text.py                   # normalize, http utilities
│       ├── lnp.py                     # **fetcher LNP + deducer Fase 2.2**
│       ├── pianetabasket.py           # parser articoli PianetaBasket
│       └── rss_pool.py                # multi-RSS aggregator
│
├── config/
│   └── seasons/
│       └── 2025-26.json               # squadre, RSS feeds, series_closed
│
└── .github/workflows/
    ├── update-data.yml                # cron principale (3 step + commit)
    ├── update-data-v9-test.yml        # workflow manuale di test v9
    └── freshness-check.yml            # alert email se cron >24h fermo (36h lug-ago)
```

---

## 5. Schema dati

### `data.json` (legacy v8.9)
```json
{
  "last_updated": "ISO",
  "season": "2025-26",
  "config": {
    "teams": { "virtus": {...}, "luiss": {...} },    // OBJECT
    "classifica_url": "...",                          // singolo URL
    "series_closed": [{ "team": "virtus", ... }]
  },
  "matches": [
    {"id": "v02", "team": "virtus", "phase": "regular", "round": 2,
     "date": "2025-09-26", "time": "20:30", "home": "...", "away": "...",
     "sh": 76, "sa": 69}
  ],
  "standings": { "virtus": {"pos":1, "pts":58, "w":29, "l":7} }
}
```

### `data-v9.json` (schema 9.0)
```json
{
  "$schema_version": "9.0",
  "last_updated": "ISO",
  "season": "2025-26",
  "config": {
    "teams": [                                        // LISTA
      {"key": "virtus", "display_name": "Virtus GVM Roma",
       "aliases": [...], "venue": {...},
       "active_competitions": [
         {"id": "b_naz_2526", "category": "B Nazionale",
          "fetcher": "lnp", "source_slug": "serie-b", "girone": "B"}
       ]}
    ],
    "series_closed": [{"team_key": "virtus", ...}]
  },
  "matches": [
    {"id": "v_po_r37_4", "team_key": "virtus", "competition_id": "b_naz_2526",
     "phase": "playoff", "date": "2026-05-31", "time": "20:00",
     "home": "Virtus...", "away": "Rucker...",
     "sh": 86, "sa": 62,
     "external_id": "ita3_b_ply_75",                  // link LNP tabellino
     "periods": [[21,14],[19,12],[17,20],[18,13]],    // parziali quarti
     "sources": ["lnp_advance", "lnp_tabellino"],     // provenance
     "game_num": 5, "tentative": false}
  ],
  "standings": {...}
}
```

### Mapping campi v9 → legacy (in adapter frontend)
- `team_key` → `team`
- `config.teams` lista → object
- `config.classifica_url` deriva da `teams[].active_competitions[0].category` tramite `CLASSIFICA_URLS_BY_CATEGORY`
- `series_closed[].team_key` → `team`

---

## 6. Workflow `update-data.yml` struttura

```yaml
# Concurrency: una run alla volta (no push concorrenti)
# Env: FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true (no Node 20 warnings)
# Python 3.11

Steps:
1. Checkout
2. Setup Python 3.11
3. python scripts/update_data.py        # v8.9, scrive data.json
4. CLEANUP: rimuove partite con id "v_po_f_g*" da data.json
   - Idempotente, no-op se non trova
   - Safety net permanente per residui bug deducer
5. python scripts/main.py --out-v9 data-v9.json
   - continue-on-error: true (v9 fallisce → workflow continua)
   - NO --write-legacy (causava round errati 50/53 nel data.json)
6. git commit + push se data.json o data-v9.json modificati
```

**Garanzie operative:**
- Se v9 crasha: cleanup l'ha già fatto il suo, data.json resta v8.9-puro
- Se v9 ha bug logico (es. partite con date strane): cleanup le rimuove al prossimo run
- freshness-check.yml alerta email se update-data fermo >24h (36h luglio-agosto off-season)

---

## 7. Frontend (`index.html`)

### Fonte dati
`fetch('data-v9.json')` → `adaptV9ToLegacy(rawData)` → render esistente.

### Logica adapter (nel JS, sezione `adaptV9ToLegacy`)
1. **Mappa matches**: `team_key`→`team`, preserva `external_id`/`periods`/`sources`
2. **Dedup intelligente per data**: key = `(phase, team, opponent_normalized, date)`. Preferenza:
   - score popolato > non popolato
   - game_num popolato > null
   - più sources > meno
   - Risolve: `v_po_r37_5` (G1 Finale da v8.9) e `v_po_f_g1` (G1 Finale da deducer v9) hanno stessa data dopo fix → mergiati a 1 sola entry
3. **Filtro date sospette (safety net)**: playoff/playout senza score con data < ultima disputata dello stesso team → nascosti. Protegge da residui bug deducer.
4. **Multi-classifica**: per ogni team in `config.teams[]`, deriva URL da:
   ```javascript
   CLASSIFICA_URLS_BY_CATEGORY = {
     "B Nazionale": "https://www.legapallacanestro.com/serie/4/classifica",
     "A2":          "https://www.legapallacanestro.com/serie/3/classifica",
     "Serie A":     "https://www.legabasket.it/standings"
   }
   ```
   Rendering: se tutti i team stessa lega → 1 bottone "CLASSIFICA UFFICIALE". Se categorie diverse → 1 bottone per ogni lega distinta.

### Features v9 ancora NON esposte nel frontend (futuro)
- Parziali quarti cliccabili (campo `periods`)
- Link diretto al tabellino LNP (campo `external_id`)
- Badge sources visibili
- Tab playoff/playout

---

## 8. Bug noti & safeguards permanenti

### BUG DEDUCER FASE 2.2 — FIXATO 07/06
**Sintomo originale:** date Finale dedotte erano a maggio invece di giugno (off-by-one-month).

**Causa:** regex `_extract_round_dates` in `lnp.py` cercava heading `"Finale"` (singolare) e matchava il sub-string DENTRO `"Quarti di Finale"` → estraeva date QF (maggio) invece di Finale (giugno). Inoltre il testo LNP B Nazionale usa `"Finali"` (plurale!), e tutto su una sola riga.

**Fix applicato:**
1. `ROUND_NAME_TO_HEADING["F"] = "Finali"` (era `"Finale"`)
2. Regex: `(?:^|\W){re.escape(round_heading)}\s*[-–]\s*([^\n]*)` con `re.IGNORECASE`
   - `(?:^|\W)` lookbehind: evita match dentro `Semifinali` (precede `i`, char `\w`)
   - Heading `"Finali"` non collide con `"Quarti di Finale"` (singolare ≠ plurale)

**ATTENZIONE per Fase 6 (Virtus eventualmente in A2):**
A2 LNP usa `"Finale"` singolare (verificato sulla pagina A2 playoff). Quando Virtus sale in A2, servirà:
- Heading dinamico per categoria (es. dict per league_key)
- OPPURE regex `Finali?` che matcha entrambe (ma serve gestire lookbehind per evitare "di Finale")

### BUG DUPLICATI G1 FINALE — workaround attivo
**Sintomo:** v8.9 (`v_po_r37_5`) e v9 deducer (`v_po_f_g1`) creano entrambi G1 Finale con stessa data (post-fix). Id diversi → state.merge non li fonde.

**Workaround:** dedup nel frontend per `(phase, team, opponent, date)`. Risolto display-side. Backend continua a tenerli entrambi in `data-v9.json` (innocuo).

### Filtro `lnp_advance`-only RIMOSSO dal frontend (07/06)
Dopo fix deducer, le partite con `sources=["lnp_advance"]` hanno date corrette. Quindi il filtro temporaneo è stato tolto. Resta il filtro `date < ultima_disputata` come safety net.

### `--write-legacy` DISABILITATO nel cron
Quando attivo, v9 scriveva data.json in schema legacy ma con `round` numerici progressivi (50, 53...) invece dei 37/38 v8.9 convention → frontend mostrava label sbagliate "G50, G53". Tolto. Il frontend legge data-v9.json direttamente.

### Cleanup step IDEMPOTENTE PERMANENTE
Rimuove partite con id `v_po_f_g*` da data.json. È no-op normalmente; se in futuro qualche regressione le rimette in data.json, le toglie automaticamente. NON rimuovere lo step anche se sembra inutile.

---

## 9. Config `config/seasons/2025-26.json` — series_closed correnti

```json
{
  "series_closed": [
    {"team_key": "luiss", "opponent": "Logiman Orzinuovi", "phase": "playoff",
     "round_name": "QF", "result": "0-3", "team_advances": false,
     "note": "Eliminata QF 2025-26"},
    {"team_key": "virtus", "opponent": "Paffoni Fulgor Basket Omegna", "phase": "playoff",
     "round_name": "QF", "result": "3-0", "team_advances": true,
     "next_opponent": "Rucker San Vendemiano", "next_opponent_seed": 4,
     "note": "Vincente QF, passa a SF"},
    {"team_key": "virtus", "opponent": "Rucker San Vendemiano", "phase": "playoff",
     "round_name": "SF", "result": "3-2", "team_advances": true,
     "next_opponent": "La T Tecnica Gema Montecatini", "next_opponent_seed": 2,
     "note": "Vincente SF, passa a Finale (Trigger B applicato 31/5)"}
  ]
}
```

**Pattern series_closed:** quando una serie playoff si chiude, l'utente aggiorna manualmente questo file aggiungendo l'entry corrispondente. Il deducer v9 leggerà `next_opponent` + `next_opponent_seed` per generare le partite del round successivo.

---

## 10. Roadmap aggiornata

| Fase | Quando | Cosa |
|------|--------|------|
| 1-3 | ✅ giugno 2026 | Foundation v9 + Hybrid + frontend nativo |
| **4** | luglio-agosto 2026 | **Cutover completo:** dismetti `update_data.py`, cron usa solo `main.py`. Frontend resta invariato (continua a leggere data-v9.json) |
| 5 | agosto 2026 | Hardening (edge cases, test) |
| **6** | settembre 2026 | **Fetcher LBA + BC Roma:** scrivi `scripts/fetchers/lba.py` per legabasket.it. Crea `config/seasons/2026-27.json` con 3 squadre. Test su canary (es. Olimpia Milano) prima del go-live |
| **Go-live BC Roma** | ottobre 2026 | Inizio Serie A LBA 2026-27. Frontend autoconfigura 3 tab + 3 classifiche (se categorie diverse) |
| 7 | gennaio 2027 condizionato | Coppa Italia LBA Final Eight (se BC Roma top-8) — `lba_cup.py` fetcher |
| 8 | estate 2027 | NBA Europe fetcher (se BC Roma selezionata slot Roma garantito) |

**Vincolo critico:** Fase 4 (dismissione v8.9) deve precedere Fase 6, altrimenti BC Roma esisterebbe solo in data-v9.json e v8.9 non saprebbe gestirla.

---

## 11. Squadre future (post-2025-26)

### BC Roma (ex-Vanoli Cremona)
- **[VERIFIED da Il Post + FIP + RealGM]** codice FIP a BC Roma Srl dal 29/05/2026
- Soci: Donnie Nelson, Luka Doncic, Bianchini, Kaukenas
- Gioca **Serie A LBA 2026-27** (esordio ottobre 2026)
- Vanoli 2025-26 finita 11° (11V-17S), fuori playoff → BC Roma NON eredita qualifiche europee
- Palazzetto TBD (PalaEUR vs altro)
- Nome ufficiale commerciale TBD (atteso annuncio luglio 2026)
- **NBA Europe 2027-28** con 16 squadre, 2 slot italiani garantiti (Milano + Roma)

### Virtus 2026-27
- Se vince Finale playoff 2025-26 → **promossa in A2**, categoria cambia, fetcher resta LNP con `source_slug: "serie-a2"`
- Se perde Finale → resta in B Naz
- Architettura v9 supporta cambio categoria nel config senza modifiche codice

### Luiss 2026-27
- Sicuramente in **B Nazionale** (no rischio retrocessione, no promozione)

---

## 12. Procedure operative ricorrenti

### Sostituire un file su main
1. URL `https://github.com/bad-think/basket-roma/edit/main/<path>`
2. Ctrl+A → Delete → incolla → Commit
3. Commit message: forma `tipo(scope): descrizione`

### Forzare un run del cron
1. URL `https://github.com/bad-think/basket-roma/actions/workflows/update-data.yml`
2. "Run workflow" → branch main → Run
3. Wait ~1m 30s
4. Verifica log + frontend con Ctrl+F5

### Verificare data-v9.json freshness
URL diretto: `https://github.com/bad-think/basket-roma/blob/main/data-v9.json` → controlla `last_updated`

### Cleanup branch backup
- `pre-v9-backup`: cancellabile dopo 14/06/2026 se sistema stabile
- `v9-rewrite`: obsoleto, cancellabile in qualsiasi momento
- Via UI: `https://github.com/bad-think/basket-roma/branches` → icona trash

---

## 13. Convenzioni codice + dettagli tecnici

### Schema id matches (legacy v8.9)
- Regular: `v01..v36`, `l01..l36` (team_letter + number 01-36 = round)
- Playoff QF: `v_po_r37`, `v_po_r38` (G1, G2 sulla giornata corrispondente), `l_po_r37` (Luiss)
- Playoff SF Virtus (post-cleanup): `v_po_r37_2..5` (suffisso _N = game)
- Finale dedotta v9: `v_po_f_g1`, `v_po_f_g2`, `v_po_f_g5` (RIMOSSE da data.json via cleanup step se schema sbagliato; lasciate intatte in data-v9.json)

### ROUND_NUM_OFFSET in lnp.py (post-fix)
```python
ROUND_NUM_OFFSET = {
    "QF": 39,    # G1 QF dedotta → round 39 (per ordering)
    "SF": 44,    # G1 SF dedotta → round 44
    "F":  49,    # G1 Finale dedotta → round 49
}
```
Convenzione interna v9, NON usata dal frontend (legge `game_num` come label).

### Pattern Trigger B (chiusura serie)
Quando una serie playoff finisce, utente aggiorna `2025-26.json` aggiungendo nuova entry in `series_closed` con `team_advances` + `next_opponent` + `next_opponent_seed`. Al prossimo cron, deducer genera schedule round successivo.

### Frontend: campo `tentative`
Match con `tentative: true` (es. G5 Finale, può non disputarsi) → frontend mostra badge "DA CONFERMARE" giallo. Logica già attiva.

### Stack tecnico
- **Frontend:** HTML5 + CSS3 + Vanilla JS (no framework), service worker
- **Backend:** Python 3.11, stdlib + minimal deps (no pypdf installato, usa fallback stdlib per parsing PDF calendario LNP)
- **PDF calendario LNP:** parsato con fallback stdlib custom (`update_data.py` ha stdlib parser ~342 entries per girone)

---

## 14. Storia sintetica sessioni recenti

**24-31 maggio 2026** — sviluppo v9 backend incrementale:
- Fase 2.1 hybrid mode
- Fase 2.2 next-round deducer
- Fase 2.3a tabellino parser (Test 8 success)
- Fase 2.3b discovery via avversario (Test 10/11 success)

**31 maggio** — Trigger B applicato (chiusura SF Virtus 3-2 vs Rucker)

**06 giugno** — sessione cutover (4-5 ore):
- Squash merge `v9-rewrite` → `main`
- Modifica `update-data.yml` con step v9 enrichment (additivo)
- Run successo: data-v9.json creato per la prima volta su main
- Tentativo `--write-legacy` → fallito (creava round errati 50/53 nel data.json)
- Rollback `--write-legacy`
- Aggiunto cleanup step idempotente per rimuovere partite spurie

**07 giugno** — sessione frontend + bug deducer:
- Riscrittura `index.html` (adapter v9→legacy, multi-classifica, dedup intelligente)
- Tentativo 1 fix deducer: ancoraggio `^...$` con MULTILINE → FALLITO (testo LNP è su singola riga, e usa "Finali" plurale)
- Tentativo 2 fix deducer: heading `"Finali"` + lookbehind `(?:^|\W)` → SUCCESS (testato sul testo reale via web search)
- Frontend mostra G1, G2, G5 Finale con badge "DA CONFERMARE" su G5

---

## 15. Note critiche da NON dimenticare

🚨 **Mai riabilitare `--write-legacy`** finché lo schema legacy v9 non è validato 1:1 contro v8.9. Round numeri progressivi rompono il frontend.

🚨 **Il cleanup step deve restare** anche se sembra inutile. È no-op normale, salva-vita in caso di regressione.

🚨 **Quando aggiungi nuova categoria** (A2, Serie A, ecc.) verifica heading LNP/LBA per il deducer:
- B Naz LNP → `"Finali"` (plurale)
- A2 LNP → `"Finale"` (singolare) [VERIFIED via web]
- Serie A LBA → da verificare quando scriverai `lba.py`

🚨 **Il frontend legge SOLO data-v9.json**, non più data.json. Se aggiungi una nuova squadra al config, deve apparire in data-v9.json per essere visibile.

🚨 **Multi-classifica auto-deriva** da `teams[].active_competitions[0].category`. Se BC Roma config 26-27 avrà `category: "Serie A"`, frontend mostra automaticamente bottone "CLASSIFICA SERIE A" che linka legabasket.it.

🚨 **Branch `pre-v9-backup`** è safety net fino al 14/06/2026. NON cancellare prima.

🚨 **freshness-check.yml** monitora il workflow `update-data.yml`. Se cambi nome del workflow principale, aggiorna anche freshness-check.

🚨 **Per fixare bug nel parser LNP**, SEMPRE verificare prima il testo reale della pagina (via web search o web_fetch su `https://www.legapallacanestro.com/serie/4/playoff-playout/2026/ita3_b_poff`). Mai fixare regex su assunzioni.

---

## 16. Quick reference URLs

| Cosa | URL |
|------|-----|
| Live frontend | https://bad-think.github.io/basket-roma/ |
| Repo | https://github.com/bad-think/basket-roma |
| data-v9.json (raw) | https://raw.githubusercontent.com/bad-think/basket-roma/main/data-v9.json |
| Actions | https://github.com/bad-think/basket-roma/actions |
| LNP B Naz Tab 1 (Luiss) | https://www.legapallacanestro.com/serie/4/playoff-playout/2026/ita3_a_poff |
| LNP B Naz Tab 2 (Virtus) | https://www.legapallacanestro.com/serie/4/playoff-playout/2026/ita3_b_poff |
| LNP B Naz classifica | https://www.legapallacanestro.com/serie/4/classifica |
| LBA Serie A standings | https://www.legabasket.it/standings |

---

**Ultimo aggiornamento:** 07 giugno 2026 (post-Fase 3 frontend + fix deducer definitivo)
