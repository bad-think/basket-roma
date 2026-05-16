[CONTINUITA.md](https://github.com/user-attachments/files/27855194/CONTINUITA.md)
# BASKET ROMA: DOCUMENTO DI CONTINUITÀ

**Versione doc:** v8.9.2 + v9.0 Fase 2.1 in parallelo
**Versione script main:** v8.9.1 (in produzione su main)
**Versione frontend main:** v8.9.2 (in produzione su main)
**Versione v9 rewrite:** Fase 2.1 Hybrid (branch `v9-rewrite`, test-only)
**Data ultimo aggiornamento:** 16 maggio 2026
**Repo:** github.com/bad-think/basket-roma

---

## 1. STATO STAGIONE 2025-26

**Regular season:** completa.
- Virtus: 1° girone B, 29V-7P, 58pt
- LUISS: 6° girone B, 21V-15P, 42pt

**Quarti playoff: CONCLUSI**
- Virtus vs Omegna 3-0 → **Semifinale**
- LUISS vs Orzinuovi 0-3 → **Eliminata**

**Semifinali (in attesa):**
- Virtus vs Rucker San Vendemiano (Tabellone 2, Serie 5)
- Date formula LNP: 21, 23, 26, 28, 31 maggio 2026
- LNP non ha ancora pubblicato testo strutturato SF (atteso 18-20/5)
- Bracket visuale già mostra accoppiamento ma testo è ancora "Vincente 1 vs vincente 4"

---

## 2. ARCHITETTURA DOPPIA TRACCIA

### 2.1. Main (produzione) — v8.9.x

```
scripts/update_data.py       v8.9.1, 2727 righe (monolitico)
index.html                   v8.9.2 (frontend con banner NEXT ROUND)
data.json                    39 partite, config.series_closed popolato
.github/workflows/
  ├── update-data.yml         8 cron/giorno
  ├── freshness-check.yml     daily check 24h
  └── update-data-v9-test.yml workflow_dispatch only (test v9-rewrite)
```

**Funziona, copre:** regular + playoff + bracket + series_closed + frontend.

### 2.2. Branch `v9-rewrite` (sviluppo) — v9.0 Fase 2.1 Hybrid

```
config/seasons/2025-26.json   config statica (squadre, comp, RSS, series_closed)
scripts/
  ├── main.py                  orchestrator
  ├── core/
  │   ├── __init__.py          esporta i modelli
  │   ├── models.py            dataclass: Match, Team, Competition, Season, ...
  │   └── state.py             load/save/merge data.json
  └── fetchers/
      ├── __init__.py          REGISTRY = {"lnp": LNPFetcher, "pianetabasket": ...}
      ├── _http.py             helper HTTP con cache 5min
      ├── _text.py             normalize, fuzzy match, extract_scores
      ├── lnp.py               bracket playoff + score widget (no team page calendar)
      ├── rss_pool.py          pool multi-feed RSS
      └── pianetabasket.py     skeleton parser articoli europee
README-v9.md                   documentazione architettura
```

**Strategia Hybrid:**
- v9 NON sostituisce v8.9 nel parsing regular season
- v8.9 popola `data.json` (regular + score base)
- v9 può arricchire con: bracket SF/F automatici, score via RSS pool, series_closed enforcement
- v9 in test isolato finché non si decide cutover (parziale o totale)

---

## 3. CONOSCENZE TECNICHE CRITICHE

### 3.1. PianetaBasket — sezioni RSS per competizione

```
sez 38 = Serie B Nazionale       ← attiva
sez 43 = Serie A2                ← disponibile, enabled:false
sez  2 = Lega A                  ← disponibile, enabled:false
sez 35 = EuroCup/FIBA Europe Cup ← disponibile, enabled:false
sez 48 = Champions League        ← disponibile, enabled:false
sez 34 = EuroLeague              ← disponibile, enabled:false
```

URL pattern: `https://www.pianetabasket.com/rss/?section={N}`

**Cambio competizione = cambio numero in config + enabled:true. Zero codice.**

### 3.2. LNP — codici playoff per categoria

```python
CATEGORY_TO_SERIE_NUM = {"B Nazionale": 4, "A2": 3}

PLAYOFF_PAGE_CODES = {
    "B Nazionale": ["ita3_a_poff", "ita3_b_poff"],  # Tabellone 1 / 2
    "A2": ["ita2_a2_poff"],
}
```

URL: `legapallacanestro.com/serie/{N}/playoff-playout/{anno}/{codice}`

### 3.3. LNP — pattern testo bracket parser

LNP pubblica sulla pagina playoff testo strutturato così:
```
QUARTI DI FINALE - Venerdì 8, domenica 10, mercoledì 13, venerdì 15, domenica 18 maggio
Serie 1 - Virtus GVM Roma 1960 (1^ girone B) - Paffoni Fulgor Basket Omegna (8^ girone A, ...)
Serie 4 - Rucker San Vendemiano (4^ girone A) - Allianz Pazienza San Severo (5^ girone B)
...
SEMIFINALI - Giovedì 21, sabato 23, martedì 26, giovedì 28, domenica 31 maggio
Serie 5 - Vincente 1 vs vincente 4          ← finché QF non sono tutti chiusi
Serie 6 - Vincente 2 vs vincente 3
```

Regex matchup in `lnp.py`:
```python
serie_pat = re.compile(
    r"Serie\s+(\d+)\s*[-–]\s*"
    r"(.+?)\s*\(\s*(\d+)\s*\^\s*[^)]+\)\s*[-–]\s*"
    r"(.+?)\s*\(\s*(\d+)\s*\^\s*[^)]+\)",
)
round_pat = re.compile(
    r"(Quarti di Finale|Semifinali|Finale|Play-In|Playout)\s*[-–]\s*([^\n]*)",
)
```

**Round detection critico:** usare `rfind`-style (heading più vicina al matchup), non `in before[-500:]` — bug risolto in v8.9.

### 3.4. Playoff best-of-5 — pattern home games

```
Higher seed (es. 1° contro 8°): CCFFC → home G1, G2, G5
Lower seed  (es. 4° contro 5°): FFCCF → home G3, G4
```

G4 e G5 sono **tentative** (possono non disputarsi se serie chiusa prima).
`data.json` contiene SOLO gare in casa delle squadre tracciate.

### 3.5. RSS — gestione CDATA WordPress

Sportando e PianetaBasket usano `<![CDATA[...]]>` per `<title>` e `<description>`.
ElementTree `.text` può ritornare None in alcuni casi.
**Fix:** usare `"".join(el.itertext())` (in `rss_pool.py` `_element_text`).

### 3.6. Matching nome squadra — stopword italiane

`team_name_matches_anywhere` filtra parole troppo comuni:
```python
STOPWORDS = {"basket", "club", "team", "pallacanestro", "sport"}
```
Match richiede: alias intera OR almeno 2 parole distintive (>=4 char, non stopword).

---

## 4. DECISIONI STRATEGICHE PRESE

1. **No riscrittura full parser LNP regular** — costo 3-5 sessioni, beneficio nullo (v8.9 funziona)
2. **SofaScore SCARTATO** — ToS vieta API non documentate, rischio blocco IP. Le librerie pubbliche (LanusStats, ScraperFC) usano endpoint ma è scraping
3. **PianetaBasket RIABILITATO** come fonte — era scartato per HTML scraping, ma RSS è valido e copre tutte le categorie con sezioni dedicate
4. **basketinside.com DISABILITATO** — `/feed/` ritorna HTML invece di XML (WordPress feed disabilitato o plugin di redirect). Da investigare se serve in futuro
5. **sportando.basketball/feed/ generale DISABILITATO** — troppo rumore (mercato, interviste). Usare `/category/europa/italia/serie-b/feed/` specifico
6. **Architettura plugin** — aggiungere nuova competizione = config + opzionale fetcher class, NO refactor
7. **Cutover NON in big-bang** — quando v9 sarà pronto, girerà come step aggiuntivo dopo v8.9, non sostituzione

---

## 5. BUG NOTI E FIX STORICI v8.9

### 5.1. `_parse_last_result` scomparsa 3x durante editing
- **Causa:** file monolitico 2727 righe, `str_replace` operations al boundary perdevano funzioni
- **Fix:** verifica pre-consegna `grep -c "def _parse_last_result"` deve essere 1
- **Lezione per v9:** modularità in file <500 righe risolve strutturalmente

### 5.2. Opponent name fallback playoff sovrascriveva G1-G5
- **Causa:** matching per nome avversario, ma in playoff stesso opponent in G1-G5 → tutte le date sovrascritte
- **Fix:** `if m.get("phase","regular") == "regular":` prima del fallback nome

### 5.3. Cleanup troppo aggressivo rimuoveva G1/G2/G3 playoff
- **Causa:** rimuoveva TUTTE le partite playoff con `sh=None` e data passata
- **Fix:** rimuove solo `tentative==True AND date<today AND sh==None`

### 5.4. Bracket round detection sbagliato
- **Causa:** `in before[-500:]` trovava "SEMIFINAL" prima di "QUARTI" quando il testo SF appariva prima del bracket QF
- **Fix:** `rfind()` per trovare la heading più vicina al matchup

### 5.5. URL encoding caratteri accentati (OraSì Ravenna)
- **Sintomo:** `oras%C3%AC-ravenna: calendario non parsabile`
- **Stato:** issue preesistente in v8.9, non bloccante (Ravenna non avversario diretto)
- **Fix futuro v9:** encoding URL robusto via urllib.parse

---

## 6. TEST REALI ESEGUITI

### Test 1 (Fase 2, 14/05/2026)
- LNPFetcher.fetch_schedule: 0 match (parser team page regex fragile) ❌
- RSS sportando feed generale: 0 menzioni ❌
- RSS basketinside: XML non parseabile ❌
- RSS pianetabasket sez. 38: 1 menzione ma 0 score ❌

→ Decisione: pivot a Hybrid mode, abbandono riscrittura parser team page LNP

### Test 2 (Fase 2.1 Hybrid, 16/05/2026)
- Workflow 12s (-62% vs Test 1) ✅
- Log puliti, nessun warning spurio ✅
- 39 → 39 match preservati, series_closed rispettato ✅
- Sportando Serie B feed: fetchato OK ✅
- Sistema funziona come previsto, in attesa di nuovi eventi ✅

---

## 7. TRIGGER PER PROSSIMA SESSIONE

### Trigger A — Validazione SF Virtus (atteso 18-21/5)
Quando LNP pubblicherà il testo SF strutturato:
1. Frontend v8.9.2 dovrebbe già mostrare banner SF (cron v8.9 le aggiunge auto)
2. Lancia "Test v9 (manual)" su Actions → branch `v9-rewrite`
3. Verifica bracket parser v9 abbia generato G1/G2/G5 SF Virtus con date 21/23/31 maggio
4. Se ✅ → procediamo a Fase 3 (frontend data-driven) o Fase 4 (cutover parziale)
5. Se ❌ → tuning regex bracket parser su pagina LNP reale

### Trigger B — Fine playoff Virtus
Indipendentemente dall'esito:
1. Aggiungi entry in `config.series_closed`:
   ```json
   {
     "team_key": "virtus",
     "competition_id": "b_naz_2526",
     "phase": "playoff",
     "round_name": "SF",
     "opponent": "Rucker San Vendemiano",
     "result": "X-Y",
     "team_advances": true/false,
     "note": "..."
   }
   ```
2. Su entrambi i branch: main (per v8.9) E v9-rewrite (per v9)
3. Cleanup eventuali partite tentative obsolete

### Trigger C — Promozione Virtus in A2 (2026-27)
1. Copy `config/seasons/2025-26.json` → `2026-27.json`
2. Cambia `team.active_competitions[].source_slug` da `serie-b` a `serie-a2`
3. Cambia `category` a `"A2"`
4. Su feed RSS PianetaBasket: abilita sez 43 (A2)
5. Test su branch v9-rewrite prima di main

### Trigger D — Qualificazione Coppa Italia LNP
1. Aggiungi nuova entry in `team.active_competitions[]`:
   ```json
   {
     "id": "coppa_lnp_2526",
     "type": "cup",
     "category": "Coppa Italia LNP",
     "fetcher": "lnp",
     "phases": ["cup"]
   }
   ```
2. Riusa `LNPFetcher` esistente (bracket parser funziona per formato Final Four)
3. Test fine-tuning su pagina LNP Coppa reale

### Trigger E — Qualificazione europee (Champions/EuroCup)
1. Aggiungi competition in config con `fetcher: "pianetabasket"` e `rss_section: 48` (Champions) o `35` (EuroCup)
2. Abilita feed RSS PianetaBasket corrispondente
3. Lancia test → fine-tuning regex articoli (parser non testato sul vero)

---

## 8. WORKFLOW OPERATIVO

### 8.1. Dopo ogni modifica
- Fornisci versione file + commit message
- Verifica AST: `python3 -c "import ast; ast.parse(open('FILE').read())"`
- Per v8.9: `grep -c "def _parse_last_result" scripts/update_data.py` deve essere 1
- Per v9: `python3 scripts/main.py --no-fetch` smoke test offline

### 8.2. Test reale v9
- Su Actions → "Test v9 (manual)" → Run workflow → branch `v9-rewrite`
- Scarica artifact `v9-output-{id}` contenente `data-v9.json`
- Confronta con `data.json` di main

### 8.3. Sviluppo browser-only (utente)
- Tutte le modifiche via github.com web editor
- Branch v9-rewrite per sviluppo v9.0
- Main per fix urgenti v8.9.x

---

## 9. ROADMAP RIMANENTE v9.0

| Fase | Obiettivo | Stato |
|------|-----------|-------|
| 1 | Foundation: models + state | ✅ |
| 2 | Fetchers (LNP, RSS, PianetaBasket) | ✅ |
| 2.1 | Hybrid pivot — parser regular delegato a v8.9 | ✅ |
| 3 | Frontend data-driven (autoconfig da config.teams) | ⏳ |
| 4 | Cutover parziale (v9 affianca v8.9 in produzione) | ⏳ |
| 5 | Hardening (AST hook, unit test, alert) | ⏳ |

**Trigger Fase 3:** dopo validazione SF Virtus (Trigger A).

---

## 10. NOTE PER CLAUDE FUTURO

- **Memorie userMemories** dovrebbero contenere stato sintetico cross-session
- **CONTINUITA.md** è la single source of truth completa
- **Codice repo** è il riferimento per dettagli implementativi
- **Workflow Actions** è il modo per testare modifiche v9 senza rischio
- **In caso di dubbi:** leggere prima questo file, poi il README-v9.md, poi i file di codice

### Convenzioni
- Token optimization: risposte concise, dense, no fronzoli
- Verità sopra approvazione: critica costruttiva con evidenza
- Versione + commit message dopo ogni modifica
- AST validation obbligatoria prima della consegna codice
- Test offline (`--no-fetch`) per validare architettura senza rete
