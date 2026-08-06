[CONTINUITA.md](https://github.com/user-attachments/files/30793720/CONTINUITA.md)
[CONTINUITA.md](https://github.com/user-attachments/files/28839545/CONTINUITA.md)
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

## 3. Stato corrente (05/08/2026)

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
9. **Cleanup branch `v9-rewrite` + workflow `update-data-v9-test.yml`** (08/06)
10. **Probing sequenziale external_id Fase 2.3c** (11/06) — `lnp.py`: fallback `_probe_external_ids` quando la discovery via pagina avversario fallisce (round inter-girone, cache Drupal). Sonda id tabellino oltre il max noto; `PROBE_MAX_MISSES=12` perché LNP alloca gli id per blocchi di round con gap (verificato: SF tab.2 terminano a 79, Finale parte da 90). Il probe scrive anche `time` dal tabellino (il deducer mette placeholder 20:00)
11. **Guardia pubDate RSS pool** (11/06) — `rss_pool.py`: una menzione si applica solo se pubblicata il giorno gara o il successivo. Fix contaminazione: con 2 gare pendenti vs stesso avversario (G1/G2 Finale), lo stesso score veniva applicato a entrambe. Menzioni senza pubDate scartate
12. **Frontend: parziali + link tabellino + orari tentative** (11/06, deployato e verificato live) — `index.html`: card risultato mostra parziali quarti e bottone TABELLINO ↗ (URL costruito da `external_id` + `season`, helper `tabellinoUrl`/`periodsLine`, `SEASON_SHORT` derivato da `data.season`); hero/countdown segnalano "(DA CONFERMARE)" sulle gare tentative

### Stagione 2025-26 — CHIUSA
- **Virtus GVM Roma 1960**: QF vinta 3-0 vs Paffoni, SF vinta 3-2 vs Rucker San Vendemiano, Finale **PERSA 2-3 vs Montecatini Terme**, Gara Unica spareggio A2 **PERSA 67-71 vs Elachem Vigevano** (Forlì, 21/06/2026) → resta in Serie B Girone B 2026-27
- **LUISS Roma**: confermata in Serie B Girone B 2026-27
- Montecatini Terme Valdinievole (ex-La T Tecnica Gema Montecatini): slug LNP da aggiornare se servono query retrospettive

### Stagione 2026-27 — DATI NOTI (da CU FIP N.94 + Calendario LBA)

| Squadra | Categoria | Stato playoff |
|---------|-----------|---------------|
| Virtus GVM Roma 1960 | B Naz gir B | 1° (29V-7P, 58pt) — **FINALE 1-1** vs La T Tecnica Gema Montecatini (G1 64-69 L, G2 66-61 W) |
| Luiss Roma | B Naz gir B | 7° (21V-15P, 42pt) — eliminata QF (0-3 vs Logiman Orzinuovi) |

Pattern Finale (Virtus higher seed 1B vs Montecatini seed 2A): C-C-F-F-C
- G1 8/6 casa **64-69 L** · G2 10/6 casa **66-61 W** · G3 sab 13/6 trasferta 20:45 PalaTerme · G4 lun 15/6 trasferta (ev.) · G5 gio 18/6 casa (ev., tentative)
- external_id Finale: blocco `ita3_b_ply_90..94` (G1=90, G2=91; tabellone 1 simmetrico su `ita3_a_ply`)
- Perdente Finale → spareggio terza promozione, gara unica dom 21/6 a Forlì

### Known-cost (accettati, spariscono con Fase 4)
- **v9 è stateless tra run**: riparte da `data.json`, non rilegge `data-v9.json`. Conseguenze: re-discovery degli stessi external_id a ogni run + probing (~10-25 fetch LNP/run finché una serie è aperta). Tollerabile con 8 run/giorno
- **Score playoff = solo v9**: v8.9 non ha vie score per i playoff (calendario LNP = solo regular; widget = solo gare future). By design
- **RSS = ridondanza best-effort**: gli score stanno spesso solo nel body degli articoli, non nei titoli/description dei feed. Fonte canonica = tabellino LNP via external_id

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
    └── freshness-check.yml            # alert email se cron >24h fermo (36h lug-ago)
```

> Nota 08/06: `update-data-v9-test.yml` rimosso (workflow manuale di test v9, obsoleto post-cutover).

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
3b. **Parziali + tabellino (11/06)**: `periodsLine(m.periods)` rende "(17-21, 19-18, ...)"; `tabellinoUrl(m.external_id)` costruisce `LNP/wp/match/{ext_id}/{phase_id}/x{SEASON_SHORT}/tabellino` (phase_id = ext_id senza suffisso numerico). `SEASON_SHORT` settato in doRefresh da `data.season` ("2025-26" → "2526"). CSS: `.gc-score-meta`, `.gc-periods`, `.gc-boxlink`. Nota: l'URL tabellino dà 403 a curl/datacenter (WAF LNP) ma funziona dal browser.
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

> Stagione 2025-26 CHIUSA. La Virtus ha perso la Finale playoff 2025-26 vs Montecatini → NON promossa in A2.

```json
"series_closed": [
  {"team_key":"luiss",  "round_name":"QF",          "result":"0-3", "team_advances":false},
  {"team_key":"virtus", "round_name":"QF",          "result":"3-0", "team_advances":true},
  {"team_key":"virtus", "round_name":"SF",          "result":"3-2", "team_advances":true},
  {"team_key":"virtus", "round_name":"Finale",      "result":"2-3", "team_advances":false, "next_phase":"spareggio_a2"},
  {"team_key":"virtus", "round_name":"Gara Unica A2","result":"0-1","score":"67-71","date":"2026-06-21","team_advances":false}
]
```
(già aggiornato in `config/seasons/2025-26.json` con score partita per partita — `pre-v9-backup` **ELIMINATO** 05/08/2026)

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

## 10. Roadmap (aggiornata 27/06/2026)

> Principio guida: **foundation prima delle feature**, **detector che propone (gate umano), mai auto-apply su scraping**, **discovery solo con ≥2 fonti reali**.

| Fase | Quando | Cosa |
|------|--------|------|
| **4** | lug–ago 2026 | **Cutover completo (priorità #1):** dismetti `update_data.py`, cron usa solo `main.py`, rimuovi step legacy + cleanup. Frontend invariato (continua a leggere `data-v9.json`). Collassa il doppio parser → meno fragilità a ogni run |
| **5** | ago 2026 | Hardening (edge cases, test) **+ Bracket DETECTOR:** parser del bracket ufficiale LNP/LBA → scrive entry `series_closed` *proposta* in log Actions o `proposals.json`. Utente la incolla in `2025-26.json` (gate umano). Trigger B diventa *assistito*, non eliminato. Non time-critical: prossimi playoff = primavera 2027 |
| **6** | set 2026 | **Fetcher LBA + EuroCup:** scrivi `scripts/fetchers/lba.py` (legabasket.it) e `scripts/fetchers/eurocup.py`. Crea `config/seasons/2026-27.json` con **4 squadre** (Virtus, LUISS, Basketball Roma SPQR, Maxima Roma — categoria Virtus 26-27 fissata da esito Finale). Test canary su Olimpia Milano. **+ Discovery probe:** ogni fetcher espone `discover(team)` → auto-binding categoria. Slug LNP/LBA delle due nuove squadre da verificare su sito federale (non ancora pubblicati al 27/06). |
| **Go-live Serie A Roma** | ott 2026 | Inizio Serie A LBA 2026-27. Frontend autoconfigura ≥4 tab (Virtus, LUISS, Basketball Roma SPQR, Maxima Roma) + classifiche per categoria. EuroCup: entrambe le squadre romane impegnate (Basketball Roma SPQR + Maxima Roma). |
| 7 | gen 2027 *(condizionato)* | `lba_cup.py` — Coppa Italia LBA Final Eight, se BC Roma top-8 |
| 8 | est 2027 | **NBA Europe fetcher** — competizione confermata, 2 slot italiani (Milano + Roma). Probabili partecipanti: Basketball Roma SPQR e/o Maxima Roma. Implementazione condizionata all'effettiva assegnazione slot. |

### Principi fissati

- 🚨 **Fase 4 deve precedere Fase 6** — altrimenti Basketball Roma SPQR e Maxima Roma esisterebbero solo in `data-v9.json` e v8.9 non saprebbe gestirle. Con 4 squadre e 4+ competizioni il cutover non è più opzionale: **deadline fissa estate 2026**.
- **Un fetcher per ogni sito-fonte nuovo** = confine corretto, non fallimento. Costo "una volta", non "ogni anno". `lba.py` scritto una volta → BC Roma auto-gestita per sempre.
- **Mai auto-apply su scraping.** Il detector propone, l'utente conferma. Safety net (cleanup idempotente, filtro date-sospette) restano permanenti.
- **Detector ≠ autonomia totale.** Obiettivo reale: non dover *ricordare* la procedura, non "zero codice". L'autonomia cieca su fonti instabili è un cattivo scambio per un sistema non presidiato.
- **Categoria Virtus 26-27:** decisa dall'esito Finale, fissata manualmente alla creazione di `2026-27.json` (Fase 6). Se promossa A2 → `source_slug: "serie-a2"` + heading deducer `"Finale"` singolare (A2 usa singolare, non plurale).

---

## 11. Squadre future (post-2025-26)

> **Aggiornamento 27/06/2026 — Roma torna alla Serie A con DUE squadre**
> [VERIFIED — FIP Consiglio federale straordinario, 26/06/2026]

### Basketball Roma SPQR (ex-Vanoli Cremona)
- **[VERIFIED 29/05/2026]** Trasferimento titolo sportivo Vanoli Cremona → Basketball Roma SPQR approvato FIP
- Soci: Donnie Nelson, Luka Doncic, Bianchini, Kaukenas
- Gioca **Serie A LBA SisalClub 2026-27** + **EuroCup 2026-27**
- Nome nel calendario LBA: **"BC Roma SPQR"** (slug legabasket.it: da rilevare)
- Prima gara LBA: Dom **27/09/2026** TRASF vs Nutribullet Treviso Basket (G1)
- Prima gara CASA LBA: Dom **04/10/2026** vs Bertram Derthona Tortona (G2)
- Palazzetto: da confermare ufficialmente (PalaEUR candidato)

### Maxima Roma (ex-Germani Brescia)
- **[VERIFIED 26/06/2026]** Trasferimento titolo sportivo Germani Brescia → Maxima Roma approvato FIP
- Acquisita dall'imprenditore americano Paul Matiasic (stesso gruppo: Pallacanestro Trieste)
- Gioca **Serie A LBA SisalClub 2026-27** + **EuroCup 2026-27**
- Nome nel calendario LBA: **"Maxima Roma"** (slug legabasket.it: da rilevare)
- Prima gara LBA: Dom **27/09/2026** CASA vs Napoli Basketball (G1) — PalaEUR
- Palazzetto: **PalaEUR** (accordo con EUR S.p.A. confermato, capienza >11.000)
- Piano industriale: impatto economico stimato 24M€/anno su Roma

### NBA Europe 2027-28
- [VERIFIED] Progetto NBA per competizione continentale europea confermato
- 2 slot italiani garantiti: Milano + Roma
- Probabile coinvolgimento di entrambe le squadre romane di Serie A

### Virtus GVM Roma 1960 — 2026-27
- **[VERIFIED]** Confermata in **Serie B Girone B** — Finale persa 2-3 vs Montecatini Terme, poi spareggio A2 perso 67-71 vs Elachem Vigevano (Gara Unica, Forlì, 21/06/2026)
- `source_slug`: invariato (`"virtus-gvm-roma-1960"` — da verificare su LNP a stagione aperta)
- Prima gara: Sab **26/09/2026 20:00** vs Felice Scandone Avellino (CASA, gara 2351, PalaTiziano)
- Calendario: 17 giornate andata (set–dic 2026) + 17 ritorno (gen–apr 2027)
- Girone B 2026-27 include Montecatini (ora "MONTECATINI TERME VALDINIEVOLE" — slug LNP cambiato)

### LUISS Roma — 2026-27
- **[VERIFIED CU FIP N.94 30/07/2026]** Confermata in **Serie B Girone B**
- `source_slug`: invariato (`"luiss-roma"` — da verificare su LNP a stagione aperta)
- Prima gara: Sab **26/09/2026 18:00** TRASF vs Loreto Pesaro (gara 2346)
- Prima gara CASA: Sab **03/10/2026 18:30** vs Latina Basket (gara 2361, PalaTiziano)
- Calendario: stessa struttura di Virtus (girone B, 34 giornate)

### Implicazioni architetturali immediate
- `config/seasons/2026-27.json`: **4 squadre** + fonte EuroCup per SPQR e Maxima
- `scripts/fetchers/lba.py`: nuovo fetcher (legabasket.it) — Fase 6
- `scripts/fetchers/eurocup.py`: nuovo fetcher — Fase 6 (o 6b se serve priorità separata)
- PianetaBasket section EuroCup (35 o 48) già mappata in codice: usabile come RSS pool
- `PLAYOFF_PHASE_IDS` LBA: da rilevare su LNP/legabasket.it a stagione aperta
- Slug delle nuove società: da cercare su legabasket.it e/o legapallacanestro.com non appena pubblicati (atteso luglio-agosto 2026)

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
- `v9-rewrite`: **CANCELLATO 08/06/2026** (già in `main` via squash merge)
- `pre-v9-backup`: **ELIMINATO** 05/08/2026 (stagione 2025-26 chiusa)
- Via UI: `https://github.com/bad-think/basket-roma/branches` → icona trash

### Cancellare un workflow obsoleto
1. Apri la cartella `https://github.com/bad-think/basket-roma/tree/main/.github/workflows`
2. Click sul file `.yml` → icona cestino (Delete this file) → Commit
3. Commit message: `chore(ci): rimuovi workflow obsoleto <nome>.yml`
4. Sparisce dalla sidebar Actions; le run storiche restano (innocue), il file è recuperabile da git history

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
> Roadmap §10 Fase 5: questa procedura diventerà *assistita* dal bracket detector (proposta auto-generata, conferma manuale).

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

**08 giugno** — sessione roadmap + cleanup:
- Riprogrammata §10: Fase 4 (cutover) promossa a priorità #1; bracket parser riposizionato come *detector con gate umano* in Fase 5; discovery probe spostato in Fase 6 (richiede ≥2 fonti reali). Fissato confine "un fetcher per ogni sito-fonte nuovo"
- Cancellato branch obsoleto `v9-rewrite` (già in main)
- Cancellato workflow obsoleto `update-data-v9-test.yml`
- `pre-v9-backup` confermato da tenere fino a fine Finale (poi eliminato 05/08/2026)

**11 giugno** — sessione "score Finale" (debugging multi-step):
- Sintomo: G1 (8/6) senza score dopo 6+ run. Diagnosi: nessuna via di cattura funzionante — v8.9 non copre playoff (by design), discovery 2.3b fallita (pagina Montecatini = cache Drupal pre-partita, round inter-girone), RSS strutturalmente cieco (score nei body, non nei feed)
- Fix 1 — **Fase 2.3c probing sequenziale** (`lnp.py`): sonda id tabellino oltre il max noto. Prima iterazione fallita in silenzio: `MAX_MISSES=5` < gap inter-round LNP (SF finiscono a 79, Finale parte a 90 — id G2=`ita3_b_ply_91` VERIFIED dal link boxscore nel comunicato LNP). Ricalibrato a 12 → success: `🎯 2 external_id trovati (start=80)`
- Bug emerso in corsa — **contaminazione RSS**: con G1+G2 entrambe pendenti vs Montecatini, l'unica menzione (recap G2 66-61) veniva applicata a entrambe → G1 mostrava 66-61 W invece di 64-69 L. Fix: guardia pubDate in `rss_pool.py` (menzione valida solo se pubblicata il giorno gara o il successivo; senza pubDate si scarta)
- Fix 2 — **probe scrive `time`** dal tabellino: le gare agganciate dal probe hanno già sh/sa/periods e restano fuori dal targets dell'enrichment, quindi il placeholder 20:00 del deducer non veniva mai corretto (gare reali 20:30)
- Fix 3 — **frontend parziali + TABELLINO ↗ + caveat tentative** (vedi §7.3b). Deployato e verificato live
- Falso allarme chiuso: "anomalia cron" segnalata il 08-10/06 non esisteva — i run fuori schedule erano `workflow_dispatch` manuali. §3 era già corretto
- Lezione di metodo confermata (rinforza la nota 🚨 in §15): il primo probing è morto in silenzio per calibrazione su assunzione; la soluzione è arrivata trovando il dato reale (link boxscore nel comunicato LNP via web_fetch di /news)

**27 giugno** — notizia strutturale (nessun lavoro di codice):
- FIP approva trasferimento Germani Brescia → **Maxima Roma** (Paul Matiasic). Aggiunge seconda squadra romana in Serie A per 2026-27, accanto a Basketball Roma SPQR (ex-Vanoli)
- Da 2026-27: 4 squadre nel progetto (Virtus, LUISS, Basketball Roma SPQR, Maxima Roma), 4+ competizioni (B Naz, B Naz, Serie A + EuroCup, Serie A + EuroCup)
- Fase 4 (cutover) assume deadline obbligatoria estate 2026. Fasi 6-7 (multi-categoria, EuroCup) diventano requisiti concreti con go-live ottobre 2026
- Nessun codice da toccare: slug nuove società non ancora pubblicati da LNP/LBA (atteso luglio-agosto)
- §10 roadmap e §11 squadre future aggiornati in questo commit

---

**5 agosto 2026** — Calendari 2026-27 ufficiali:
- CU FIP N.94 (30/07/2026): calendario definitivo Serie B Girone B 2026-27. **Virtus Roma 1960 e LUISS Roma entrambe nel Girone B** → Virtus NON promossa: Finale persa 2-3 vs Montecatini Terme + Gara Unica spareggio A2 persa 67-71 vs Elachem Vigevano (Forlì, 21/06/2026)
- Calendario LBA SisalClub (30/07/2026): BC Roma SPQR e Maxima Roma confermati, nomi definitivi verificati. G1 LBA: 27/09/2026
- Slug LNP Serie B 2026-27 da verificare a stagione aperta (sito LNP aggiorna i profili team a settembre)
- `pre-v9-backup`: **ELIMINATO** 05/08/2026
- Montecatini rinominata "Montecatini Terme Valdinievole" — impatta solo query retroattive

---

**5 agosto 2026 (aggiornamento log playoff)** — log completo stagione 2025-26 acquisito:
- QF vs Paffoni Fulgor: W 3-0 (94-71, 98-79, 75-64 @)
- SF vs Rucker San Vendemiano: W 3-2 (75-59, 87-74, 66-73 @, 63-77 @, 86-62)
- Finale vs Montecatini Terme: L 2-3 (64-69, 66-61, 72-78 @, 73-54 @, 63-66)
- Gara Unica spareggio A2 vs Elachem Vigevano: L 67-71 (Forlì, 21/06/2026)
- Top scorer playoffs: Y. Rodriguez (32pt max vs Rucker G2), M. Visintin (protagonista Finale)
- Nota: G3-G5 Finale e Gara Unica non tracciati dal pipeline (partite trasferta/neutrali); data-v9.json ha solo G1 e G2 Finale
- Nota sessione: ho introdotto un errore (concluso "Finale VINTA" invece di "PERSA") che ho poi corretto con il log completo

---

## 15. Note critiche da NON dimenticare

> **Virtus 2025-26: Finale PERSA 2-3 + spareggio A2 PERSO.** Percorso: QF W 3-0 Paffoni, SF W 3-2 Rucker, Finale L 2-3 Montecatini Terme (G1 64-69 L, G2 66-61 W, G3 72-78 L, G4 73-54 W, G5 63-66 L), Gara Unica L 67-71 vs Elachem Vigevano (Forlì, 21/06/2026). `series_closed` aggiornato con score completi. `pre-v9-backup` **eliminato** 05/08/2026.

> **Montecatini cambia nome**: "La T Tecnica Gema Montecatini" → "MONTECATINI TERME VALDINIEVOLE". Il slug LNP per il girone 2026-27 sarà diverso. Non impatta i dati 2025-26 già consolidati.

🚨 **Mai riabilitare `--write-legacy`** finché lo schema legacy v9 non è validato 1:1 contro v8.9. Round numeri progressivi rompono il frontend.

🚨 **Il cleanup step deve restare** anche se sembra inutile. È no-op normale, salva-vita in caso di regressione.

🚨 **Quando aggiungi nuova categoria** (A2, Serie A, ecc.) verifica heading LNP/LBA per il deducer:
- B Naz LNP → `"Finali"` (plurale)
- A2 LNP → `"Finale"` (singolare) [VERIFIED via web]
- Serie A LBA → da verificare quando scriverai `lba.py`

🚨 **Il frontend legge SOLO data-v9.json**, non più data.json. Se aggiungi una nuova squadra al config, deve apparire in data-v9.json per essere visibile.

🚨 **Multi-classifica auto-deriva** da `teams[].active_competitions[0].category`. Se BC Roma config 26-27 avrà `category: "Serie A"`, frontend mostra automaticamente bottone "CLASSIFICA SERIE A" che linka legabasket.it.

✅ **Branch `pre-v9-backup`** eliminato 05/08/2026 — stagione 2025-26 chiusa, sistema stabile.

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

**Ultimo aggiornamento:** 08 giugno 2026 (roadmap §10 riprogrammata + cleanup branch `v9-rewrite` e workflow `update-data-v9-test.yml`)
