[CONTINUITA.md](https://github.com/user-attachments/files/28196044/CONTINUITA.md)
# BASKET ROMA: DOCUMENTO DI CONTINUITÀ

**Versione doc:** v8.9.2 + v9.0 Fase 2.3a completa
**Versione script main:** v8.9.1 (in produzione su main)
**Versione frontend main:** v8.9.2 (in produzione su main)
**Versione v9 rewrite:** Fase 2.3a tabellino parser (pronto per deploy)
**Data ultimo aggiornamento:** 24 maggio 2026
**Repo:** github.com/bad-think/basket-roma

---

## 1. STATO STAGIONE 2025-26

**Regular season:** completa.
- Virtus: 1° girone B, 29V-7P, 58pt
- LUISS: 6° girone B, 21V-15P, 42pt

**Quarti playoff: CONCLUSI**
- Virtus vs Omegna 3-0 → **Semifinale**
- LUISS vs Orzinuovi 0-3 → **Eliminata**

**Semifinali in corso — Virtus vs Rucker San Vendemiano (Tabellone 2, Serie 5):**
- **G1 (21/05/2026 20:30): Virtus 75 — 59 Rucker** ✅ (21-14, 19-12, 17-20, 18-13)
- G2 (23/05/2026): disputata, score via RSS
- G3 (26/05/2026): trasferta a San Vendemiano
- G4 (28/05/2026): trasferta, tentative
- G5 (31/05/2026): home Virtus, tentative
- Pattern CCFFC (Virtus higher seed 1 vs 4)

---

## 2. ARCHITETTURA DOPPIA TRACCIA

### 2.1. Main (produzione) — v8.9.x

```
scripts/update_data.py       v8.9.1, 2727 righe
index.html                   v8.9.2
data.json                    41 partite (al 24/05)
.github/workflows/
  ├── update-data.yml         8 cron/giorno
  ├── freshness-check.yml
  └── update-data-v9-test.yml workflow_dispatch only
```

### 2.2. Branch `v9-rewrite` (sviluppo) — v9.0 Fase 2.3a ✅

```
config/seasons/2025-26.json   config + series_closed con next_opponent
scripts/
  ├── main.py
  ├── core/
  │   ├── models.py            Match con external_id + periods (NUOVO)
  │   │                         SeriesClosed con next_opponent
  │   └── state.py             load/save/merge
  └── fetchers/
      ├── lnp.py               QF + next-round deducer + TABELLINO PARSER (NUOVO)
      │                         (~736 righe — sopra target morbido 500)
      ├── rss_pool.py
      └── pianetabasket.py
```

**Stato v9-rewrite (24/05):** 42 partite vs main 41. v9 supera main in copertura.

---

## 3. CONOSCENZE TECNICHE CRITICHE

### 3.1. PianetaBasket — sezioni RSS

```
sez 38 = Serie B Nazionale       ← attiva
sez 43 = Serie A2                ← disponibile, enabled:false
sez  2 = Lega A
sez 35 = EuroCup
sez 48 = Champions League
sez 34 = EuroLeague
```

URL: `https://www.pianetabasket.com/rss/?section={N}`

### 3.2. LNP — codici playoff per categoria

```python
CATEGORY_TO_SERIE_NUM = {"B Nazionale": 4, "A2": 3}
PLAYOFF_PAGE_CODES = {
    "B Nazionale": ["ita3_a_poff", "ita3_b_poff"],
    "A2": ["ita2_a2_poff"],
}
```

### 3.3. LNP — bracket parser limiti

**Solo i QF hanno testo strutturato con nomi squadra.** SF/F hanno placeholder
`Vincente N vs vincente M` che LNP non aggiorna mai. Soluzione: §3.5.

### 3.4. LNP — pagina tabellino partita

URL: `legapallacanestro.com/wp/match/{external_id}/{phase_id}/x{season_short}/tabellino`
Esempio: `ita3_b_ply_75` (G1 SF Virtus).

**Phase_id** = external_id senza il suffisso "_N" (es. "ita3_b_ply").
**season_short** = "2526" per 2025-26.

Pattern external_id:
- Regular B Nazionale: `ita3_b_N`
- Playoff B Nazionale: `ita3_b_ply_N`
- Coppa Italia LNP: `ita3_cup_N`
- A2 playoff: `ita2_a2_ply_N`

Parser estrae: data, ora, nomi squadra (da `meta og:title` o `<title>`), score finale, parziali (con validazione: somma parziali = score).

### 3.5. NEXT-ROUND DEDUCER (Fase 2.2) ✅

Deduce gare home dei round successivi (SF, F) da `series_closed` con
`team_advances=True` e `next_opponent` valorizzato. Riusa date heading LNP +
pattern home CCFFC/FFCCF. Validato 24/05.

### 3.6. TABELLINO PARSER (Fase 2.3a) ✅

**Cosa fa:**
- Per ogni Match con `external_id` valorizzato e score/parziali mancanti
- Fetcha `LNP_BASE/wp/match/{external_id}/.../tabellino`
- Parsing robusto con doppia sorgente nomi squadra (og:title → fallback title)
- Validazione: sum(parziali) == score (autocorrezione invertimento home/away se necessario)
- Arricchimento Match: sh, sa, periods, time → aggiunge `lnp_tabellino` a sources

**Popolamento `external_id`:**
- Manuale via `Season.match_id_overrides` nel config (§3.11)
- Automatico via discovery (Fase 2.3b, ⏳)

**Cosa NON fa (rimandato a Fase 2.3b):**
- Discovery automatica: pagina squadra LNP NON mostra link playoff,
  pagina bracket NON ha link tabellini. Discovery richiede investigare
  `/serie/{N}/calendario`.

### 3.11. match_id_overrides (Fase 2.3a→b transition)

Campo opzionale in `Season` (config stagionale). Lista di mapping manuali:
```json
"match_id_overrides": [
  {
    "team_key": "virtus",
    "date": "2026-05-21",
    "away": "Rucker San Vendemiano",
    "external_id": "ita3_b_ply_75",
    "note": "..."
  }
]
```

Applicato da `state._apply_match_id_overrides` post-load:
- Match matchata su `(team_key, date, normalize(away))`
- Popola `external_id` solo se vuoto (no sovrascrittura)
- Log: `🔗 Applicati N match_id_overrides da config`

**Uso permanente:**
- Validation Fase 2.3a (popola manualmente per testare parser)
- Edge case Fase 2.3b (fallback dove discovery automatica fallisce)
- Override esplicito (es. correggere mismatching detected)

**Stato pratico Fase 2.3a:** override per G1 SF Virtus (ita3_b_ply_75) popolato
per validation end-to-end del parser tabellino.

### 3.7. Regex matchup bracket (QF / Play-In / Playout)

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

**Round detection critico:** `rfind`-style.

### 3.8. Playoff best-of-5 — pattern home games

```
Higher seed: CCFFC → home G1, G2, G5
Lower seed:  FFCCF → home G3, G4
```

G4/G5 sono `tentative=True`. `data.json` contiene SOLO gare home delle squadre tracciate.

### 3.9. RSS — gestione CDATA WordPress

Fix: `"".join(el.itertext())` invece di `.text` (in `rss_pool.py`).

### 3.10. State merge — chiave di identità Match

`state._find_match_index` matcha su `(team_key, date, normalize(away))`.
Conseguenza: due fonti che producono lo stesso Match (v8.9 widget + v9 deducer)
vengono mergeate, non duplicate. Sources accumulato come union.

---

## 4. DECISIONI STRATEGICHE PRESE

1. **No riscrittura full parser LNP regular** — v8.9 funziona
2. **SofaScore SCARTATO** — ToS vieta scraping
3. **PianetaBasket RIABILITATO** come RSS
4. **basketinside.com DISABILITATO** — feed HTML
5. **sportando.basketball feed generale DISABILITATO** — troppo rumore
6. **Architettura plugin** — nuova competizione = config + opzionale fetcher
7. **Cutover NON in big-bang**
8. **Bracket SF/F via deduzione logica + tabellini diretti** (23/05/2026)
   - Opzione A (Fase 2.2): ✅ deployed 24/05
   - Opzione B (Fase 2.3a): ✅ infrastruttura pronta 24/05
   - Opzione B discovery (Fase 2.3b): ⏳ prossimo
9. **🆕 Scope-cut Fase 2.3** (24/05/2026)
   - 2.3a = solo infrastruttura + parser (alta confidenza)
   - 2.3b = discovery automatica external_id (richiede investigazione)
   - Motivazione: lesson 23/05 — non assumere sorgenti non verificate

---

## 5. BUG NOTI E FIX STORICI

### 5.1. `_parse_last_result` scomparsa 3x v8.9
- **Lezione v9:** modularità file <500 righe (target morbido, ora `lnp.py` = 736)

### 5.2. Opponent name fallback playoff sovrascriveva G1-G5
- **Fix:** `if m.get("phase","regular") == "regular":` prima del fallback

### 5.3. Cleanup troppo aggressivo rimuoveva G1/G2/G3 playoff
- **Fix:** rimuove solo `tentative AND date<today AND sh==None`

### 5.4. Bracket round detection sbagliato
- **Fix:** `rfind()` per heading più vicina al matchup

### 5.5. URL encoding caratteri accentati (OraSì Ravenna)
- **Stato:** issue v8.9, non bloccante

### 5.6. Drift data.json main vs v9-rewrite (INVERTITO 24/05)
- Post-Fase 2.2: v9=42 > main=41
- **Risoluzione strutturale:** Fase 4 cutover

### 5.7. Bracket parser v9 incompleto per SF/F (RISOLTO 24/05)
- **Fix:** Fase 2.2 next-round deducer ✅

### 5.8. lnp.py supera target 500 righe (24/05)
- **Stato:** 736 righe, ancora gestibile, ben organizzato in sezioni
- **Soglia di refactor:** se supera 900 righe, splittare in:
  - `lnp/__init__.py` (LNPFetcher class)
  - `lnp/bracket.py` (QF parser + next-round deducer)
  - `lnp/tabellino.py` (parse_tabellino + url builder)

---

## 6. TEST REALI ESEGUITI

### Test 1 (Fase 2, 14/05/2026)
LNPFetcher fallita. Pivot a Hybrid mode.

### Test 2 (Fase 2.1 Hybrid, 16/05/2026)
Workflow 12s, 39 match preservati.

### Test 3 (Fase 2.1 Hybrid, 21/05/2026)
Workflow 10s, 39 match. LNP bracket SF: 0 gare parsabili.

### Test 4 (Diagnosi LNP SF, 23/05/2026)
Confermato: LNP non popola placeholder SF/F. Tabellini accessibili.

### Test 5 (Fase 2.2 deployed, 24/05/2026) ✅
3 gare SF dedotte, 2 mergeate, 1 nuova. RSS pool bonus: 2 score.
Workflow 15s. Validato `_find_match_index`.

### Test 6 (Fase 2.3a offline, 24/05/2026) ✅
Test parser `parse_tabellino` su 5 scenari HTML sintetici:
- ✅ HTML completo (og:title, data, score em-dash, summary, parziali)
- ✅ URL builder per B Nazionale + A2 playoff
- ✅ Fallback `<title>` quando manca og:title
- ✅ HTML invalido → ritorna None
- ✅ Overtime (5 quarti) con validazione parziali
- ✅ Auto-correzione invertimento home/away dei parziali via sum check

### Test 7 (Fase 2.3a deployed silent, 24/05/2026) ✅
Run su v9-rewrite con codice 2.3a: identico output a Fase 2.2 (no
external_id popolato). Conferma backward-compat e zero regressioni.

### Test 8 (Fase 2.3a validation end-to-end, 24/05/2026) — DA LANCIARE
Config con `match_id_overrides` per G1 SF Virtus → "ita3_b_ply_75".

**Output atteso al runtime:**
```
🔗 Applicati 1 match_id_overrides da config
...
🔍 [virtus] B Nazionale via lnp
  🧩 [virtus] 3 gare casa dedotte da advancement (1 tentative)
  📋 Schedule: 3 match recuperati
  ✏️  Merge: 3 match modificati/aggiunti
  📊 [virtus] 1 match arricchiti da LNP tabellino   ← NUOVO
...
```

**Output atteso in `data-v9.json`:** G1 SF Virtus con
- `sh: 75, sa: 59` (era null prima)
- `periods: [[21,14], [19,12], [17,20], [18,13]]`
- `external_id: "ita3_b_ply_75"`
- `sources` include `"lnp_tabellino"`

End-to-end offline simulato con successo (State.load + apply overrides).

---

## 7. TRIGGER PER PROSSIMA SESSIONE

### Trigger A — Fase 2.3b: discovery automatica external_id 🔥 PROSSIMO
**Obiettivo:** popolare `external_id` automaticamente per Match playoff.

**Investigazione necessaria (prima di scrivere codice):**
1. Fetch `/serie/4/calendario` → ha link a `ita3_b_ply_*`?
2. Se sì → parser tabella calendario, mapping (date, opponent_normalized) → external_id
3. Se no → alternativa:
   - Pagina squadra avversario (link a partite contro di noi)
   - Enumeration limitata con cache state (max 20 fetch/run)

**Implementazione probabile:**
- Nuovo metodo `LNPFetcher._discover_external_ids(matches)`
- Chiamato in `fetch_schedule` o all'inizio di `fetch_scores`
- Popola `external_id` su Match in state
- Attivazione automatica del parser tabellino Fase 2.3a

### Trigger B — Fine playoff Virtus (SF Rucker)
Quando serie chiude:
1. Aggiungi entry `series_closed` per round SF (manuale fino a 2.3b)
2. Se Virtus avanza → aggiungi `next_opponent` (vincente Serie 6) per Finale
3. Sistema genererà Match Finale automaticamente

### Trigger C — Fase 3 (frontend data-driven)
Pre-requisito tecnico soddisfatto. Cambio frontend per leggere `data-v9.json` schema v9.0.

### Trigger D — Promozione Virtus in A2 (2026-27)
1. Copy config `2025-26.json` → `2026-27.json`
2. `source_slug`: `serie-b` → `serie-a2`, `category`: `"A2"`
3. Abilita sez 43 RSS PianetaBasket

### Trigger E — Qualificazione Coppa Italia LNP
1. Nuova competition con `fetcher: "lnp"`, `phases: ["cup"]`
2. **Importante:** Final Four parte da SF. Rivedere `PLAYOFF_ROUND_ORDER`
   per cup type (es. `CUP_ROUND_ORDER = ["SF", "F"]`)
3. Pattern external_id: `ita3_cup_N`

### Trigger F — Qualificazione europee (Champions/EuroCup)
1. Competition con `fetcher: "pianetabasket"`, `rss_section: 48/35`

---

## 8. WORKFLOW OPERATIVO

### 8.1. Dopo ogni modifica
- Versione file + commit message
- AST validation: `python3 -c "import ast; ast.parse(open('FILE').read())"`
- v8.9: `grep -c "def _parse_last_result" scripts/update_data.py` = 1
- v9: `python3 scripts/main.py --no-fetch` smoke test offline

### 8.2. Test reale v9
- Pre-step: sync `data.json` da main se necessario
- Actions → "Test v9 (manual)" → branch `v9-rewrite`
- Scarica artifact `v9-output-{id}` con `data-v9.json`

### 8.3. Sviluppo browser-only
- Modifiche via github.com web editor
- Branch v9-rewrite per sviluppo v9.0

---

## 9. ROADMAP RIMANENTE v9.0

| Fase | Obiettivo | Stato |
|------|-----------|-------|
| 1 | Foundation: models + state | ✅ |
| 2 | Fetchers (LNP QF, RSS, PianetaBasket) | ✅ |
| 2.1 | Hybrid pivot — regular delegato a v8.9 | ✅ |
| 2.2 | Next-round deducer SF/F (Opzione A) | ✅ 24/05/2026 |
| 2.3a | Tabellino parser infrastruttura | ✅ 24/05/2026 |
| **2.3b** | **Discovery external_id automatica** | 🔥 PROSSIMO |
| 3 | Frontend data-driven | ⏳ |
| 4 | Cutover parziale | ⏳ |
| 5 | Hardening (AST hook, unit test, alert) | ⏳ |

---

## 10. NOTE PER CLAUDE FUTURO

- **CONTINUITA.md** è single source of truth
- **Codice repo** è riferimento implementativo
- **Workflow Actions** per testare v9 senza rischio
- Lettura ordine: CONTINUITA → README-v9 → codice

### Convenzioni
- Token optimization: risposte concise, dense
- Verità sopra approvazione
- Versione + commit message dopo ogni modifica
- AST validation obbligatoria
- Test offline `--no-fetch` prima del workflow reale
- Test offline sintetici per parser puri (vedi Test 6)

### Lessons learned 23-24/05/2026
- **Non assumere come pubblicato qualcosa che non si è verificato direttamente.** Esempio: ipotesi "LNP pubblicherà testo bracket SF" persa 5+ giorni.
- **Fetch manuale URL reali appena possibile** quando un trigger dipende da output esterno.
- **Falsificabilità:** ogni assunzione architetturale deve avere un test concreto.
- **State merge ben progettato evita refactor:** chiave `(team_key, date, normalize(away))` ha permesso v9 di affiancare v8.9 senza duplicati.
- **Scope-cut quando l'incertezza è alta:** scoperto 24/05 che pagina squadra LNP NON ha link playoff. Invece di tirare a indovinare la discovery, splittato Fase 2.3 in 2.3a (alta confidenza) e 2.3b (richiede investigazione).
