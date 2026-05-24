[CONTINUITA.md](https://github.com/user-attachments/files/28190911/CONTINUITA.md)
# BASKET ROMA: DOCUMENTO DI CONTINUITÀ

**Versione doc:** v8.9.2 + v9.0 Fase 2.2 (in test)
**Versione script main:** v8.9.1 (in produzione su main)
**Versione frontend main:** v8.9.2 (in produzione su main)
**Versione v9 rewrite:** Fase 2.2 next-round deducer (branch `v9-rewrite`)
**Data ultimo aggiornamento:** 23 maggio 2026
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
- **G1 (21/05/2026 20:30): Virtus 75 — 59 Rucker** ✅ (parziali 21-14, 19-12, 17-20, 18-13)
- **Serie: 1-0 Virtus**
- Date formula LNP: 21, 23, 26, 28, 31 maggio 2026 (CCFFC: home Virtus G1, G2, G5)
- URL tabellino G1: `legapallacanestro.com/wp/match/ita3_b_ply_75/ita3_b_ply/x2526/tabellino`

---

## 2. ARCHITETTURA DOPPIA TRACCIA

### 2.1. Main (produzione) — v8.9.x

```
scripts/update_data.py       v8.9.1, 2727 righe (monolitico)
index.html                   v8.9.2 (frontend con banner NEXT ROUND)
data.json                    41 partite (al 23/05), config.series_closed popolato
.github/workflows/
  ├── update-data.yml         8 cron/giorno
  ├── freshness-check.yml     daily check 24h
  └── update-data-v9-test.yml workflow_dispatch only (test v9-rewrite)
```

### 2.2. Branch `v9-rewrite` (sviluppo) — v9.0 Fase 2.2

```
config/seasons/2025-26.json   config + series_closed con next_opponent
scripts/
  ├── main.py                  orchestrator
  ├── core/
  │   ├── models.py            SeriesClosed con next_opponent + next_opponent_seed
  │   └── state.py             load/save/merge data.json
  └── fetchers/
      ├── lnp.py               QF bracket + NEXT-ROUND DEDUCER (nuovo)
      ├── rss_pool.py
      └── pianetabasket.py
```

**⚠️ NOTA SYNC:** `data.json` su v9-rewrite va periodicamente allineato a main (cron v8.9 commits non auto-propagati). Al 23/05: main=41, v9=40 (delta -1).

---

## 3. CONOSCENZE TECNICHE CRITICHE

### 3.1. PianetaBasket — sezioni RSS

```
sez 38 = Serie B Nazionale       ← attiva
sez 43 = Serie A2                ← disponibile, enabled:false
sez  2 = Lega A                  ← disponibile, enabled:false
sez 35 = EuroCup/FIBA Europe Cup ← disponibile, enabled:false
sez 48 = Champions League        ← disponibile, enabled:false
sez 34 = EuroLeague              ← disponibile, enabled:false
```

URL pattern: `https://www.pianetabasket.com/rss/?section={N}`

### 3.2. LNP — codici playoff per categoria

```python
CATEGORY_TO_SERIE_NUM = {"B Nazionale": 4, "A2": 3}
PLAYOFF_PAGE_CODES = {
    "B Nazionale": ["ita3_a_poff", "ita3_b_poff"],
    "A2": ["ita2_a2_poff"],
}
```

URL: `legapallacanestro.com/serie/{N}/playoff-playout/{anno}/{codice}`

### 3.3. LNP — bracket parser limiti (CRITICO, scoperto 23/05/2026)

**Solo i QF hanno testo strutturato con nomi squadra:**
```
QUARTI DI FINALE - Venerdì 8, domenica 10, mercoledì 13, venerdì 15, lunedì 18 maggio
Serie 1 - Virtus GVM Roma 1960 (1^ girone B) - Paffoni Fulgor Basket Omegna (8^ girone A)
Serie 4 - Rucker San Vendemiano (4^ girone A) - Allianz Pazienza San Severo (5^ girone B)
```

**SF/F hanno SOLO placeholder che LNP non aggiorna mai:**
```
SEMIFINALI - Giovedì 21, sabato 23, martedì 26, giovedì 28, domenica 31 maggio
Serie 5 - Vincente 1 vs vincente 4          ← NON popolato con nomi reali
```

**Implicazione:** regex bracket QF matcha solo round QF. Per SF/F serve deduzione (vedi §3.5).

### 3.4. LNP — pagina tabellino partita

URL pattern: `legapallacanestro.com/wp/match/{match_id}/ita3_b_ply/x2526/tabellino`
Esempio: `ita3_b_ply_75` (G1 SF Virtus vs Rucker).

Contiene data/ora, squadre, score finale, parziali, tabellino giocatori.
**Sorgente futura Fase 2.3 (Opzione B):** parser per arricchire score playoff.

### 3.5. NEXT-ROUND DEDUCER (Fase 2.2, implementato 23/05/2026)

Strategia per round dopo i QF (LNP non popola placeholder):

1. Per ogni `SeriesClosed` con `team_advances=True` e `next_opponent` valorizzato
2. Calcola round successivo via `PLAYOFF_ROUND_ORDER = ["QF", "SF", "F"]`
3. Skip se round successivo già chiuso in series_closed
4. Fetch pagina playoff LNP (cached 5min via `_http`)
5. Estrai date dalla heading round target via `ROUND_NAME_TO_HEADING`
6. Deduci `our_seed` riusando regex bracket QF (`_get_seed_from_bracket`)
7. Applica pattern CCFFC (higher seed: home G1, G2, G5) o FFCCF (lower: G3, G4)
8. Genera Match con `sources=["lnp_advance"]`

**Campi richiesti in series_closed (nuovi):**
- `next_opponent`: str — nome completo avversario nel round successivo
- `next_opponent_seed`: int|None — seed avversario (per home pattern)

Popolamento manuale in Fase 2.2. Auto-popolato in Fase 2.3 (Opzione B).

### 3.6. Regex matchup bracket (per QF / Play-In / Playout)

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

**Round detection critico:** `rfind`-style (heading più vicina al matchup).

### 3.7. Playoff best-of-5 — pattern home games

```
Higher seed (es. 1° contro 8°): CCFFC → home G1, G2, G5
Lower seed  (es. 4° contro 5°): FFCCF → home G3, G4
```

G4/G5 sono `tentative=True`.
`data.json` contiene SOLO gare home delle squadre tracciate.

### 3.8. RSS — gestione CDATA WordPress

Fix: `"".join(el.itertext())` invece di `.text` (in `rss_pool.py`).

### 3.9. Matching nome squadra — stopword italiane

`team_name_matches`: alias entire OR substring match. Stopword filtrate.

---

## 4. DECISIONI STRATEGICHE PRESE

1. **No riscrittura full parser LNP regular** — v8.9 funziona
2. **SofaScore SCARTATO** — ToS vieta scraping
3. **PianetaBasket RIABILITATO** come RSS
4. **basketinside.com DISABILITATO** — feed restituisce HTML
5. **sportando.basketball feed generale DISABILITATO** — troppo rumore
6. **Architettura plugin** — nuova competizione = config + opzionale fetcher
7. **Cutover NON in big-bang**
8. **🆕 Bracket SF/F via deduzione logica + tabellini diretti** (23/05/2026)
   - Opzione A (implementata Fase 2.2): deduzione da series_closed + bracket QF
   - Opzione B (Fase 2.3): parser tabellini `/wp/match/{id}/.../tabellino`
   - Opzione C = A + B (target finale)

---

## 5. BUG NOTI E FIX STORICI

### 5.1. `_parse_last_result` scomparsa 3x durante editing v8.9
- **Fix:** verifica `grep -c "def _parse_last_result"` = 1
- **Lezione v9:** modularità file <500 righe (target morbido)

### 5.2. Opponent name fallback playoff sovrascriveva G1-G5
- **Fix:** `if m.get("phase","regular") == "regular":` prima del fallback

### 5.3. Cleanup troppo aggressivo rimuoveva G1/G2/G3 playoff
- **Fix:** rimuove solo `tentative==True AND date<today AND sh==None`

### 5.4. Bracket round detection sbagliato
- **Fix:** `rfind()` per heading più vicina al matchup

### 5.5. URL encoding caratteri accentati (OraSì Ravenna)
- **Stato:** issue v8.9, non bloccante

### 5.6. Drift data.json main vs v9-rewrite
- **Mitigazione:** sync manuale data.json prima di Test v9
- **Risoluzione strutturale:** Fase 4 cutover

### 5.7. Bracket parser v9 incompleto per SF/F (scoperto 23/05/2026)
- **Sintomo:** "nessuna gara playoff parsabile" persistente
- **Causa root:** LNP non aggiorna placeholder "Vincente N" oltre i QF (§3.3)
- **Fix:** Fase 2.2 next-round deducer (§3.5)

---

## 6. TEST REALI ESEGUITI

### Test 1 (Fase 2, 14/05/2026)
Architettura iniziale fallita su LNPFetcher.fetch_schedule. Pivot a Hybrid mode.

### Test 2 (Fase 2.1 Hybrid, 16/05/2026)
Workflow 12s, 39 match preservati. Sistema healthy.

### Test 3 (Fase 2.1 Hybrid, 21/05/2026)
Workflow 10s, 39 match. LNP bracket SF: 0 gare parsabili.

### Test 4 (Diagnosi LNP SF, 23/05/2026)
- Workflow v9: 10s, 40 match
- LNP bracket SF: 0 gare parsabili (confermato 3a volta)
- Fetch manuale: placeholder "Vincente N" non sostituiti
- Fetch tabellino G1 SF: dati completi (Virtus 75-59 Rucker)
- **Conclusione:** ipotesi originale falsificata, servono Opzione A+B

### Test 5 (atteso) — Fase 2.2 next-round deducer
Pre-condizioni:
- `models.py`, `lnp.py` aggiornati su v9-rewrite
- `config/seasons/2025-26.json` con `next_opponent: "Rucker San Vendemiano"` per Virtus QF
- `data.json` sincronizzato con main

Output atteso:
- `🧩 [virtus] N gare casa dedotte da advancement (M tentative)` nei log
- 3 nuove Match SF Virtus vs Rucker (G1 21/5, G2 23/5, G5 31/5 tentative)
- by_phase[playoff] aumenta di 3 unità

---

## 7. TRIGGER PER PROSSIMA SESSIONE

### Trigger A — DEPLOY Fase 2.2 next-round deducer ✅ CODICE PRONTO
Da fare:
1. Sostituire 3 file su branch `v9-rewrite`:
   - `scripts/core/models.py` (SeriesClosed + 2 campi)
   - `scripts/fetchers/lnp.py` (next-round deducer)
   - `config/seasons/2025-26.json` (next_opponent per Virtus QF)
2. Sync `data.json` da main (vedi §5.6)
3. Lancia "Test v9 (manual)" su Actions → branch `v9-rewrite`
4. Verifica output atteso (Test 5)

### Trigger B — Implementazione Opzione B (parser tabellino) — Fase 2.3
Dopo Trigger A validato:
- Parser pagine `/wp/match/{id}/.../tabellino` per score finali
- Auto-popolamento `next_opponent` da widget LNP

### Trigger C — Fine playoff Virtus
Quando serie SF chiude (3-X o X-3):
1. Aggiungi entry in `config.series_closed` per round SF
2. Se Virtus avanza: aggiungi `next_opponent` per dedurre Finale
3. Su entrambi i branch

### Trigger D — Promozione Virtus in A2 (2026-27)
1. Copy config `2025-26.json` → `2026-27.json`
2. `source_slug`: `serie-b` → `serie-a2`, `category`: `"A2"`
3. Abilita sez 43 RSS PianetaBasket

### Trigger E — Qualificazione Coppa Italia LNP
1. Nuova entry in `team.active_competitions[]` con `fetcher: "lnp"`, `phases: ["cup"]`
2. **Importante:** per Final Four `PLAYOFF_ROUND_ORDER` parte da SF. Necessario rivedere logica `_next_round_name` per competizioni tipo Final Four.

### Trigger F — Qualificazione europee (Champions/EuroCup)
1. Competition con `fetcher: "pianetabasket"`, `rss_section: 48/35`
2. Abilita feed RSS

---

## 8. WORKFLOW OPERATIVO

### 8.1. Dopo ogni modifica
- Versione file + commit message
- AST validation: `python3 -c "import ast; ast.parse(open('FILE').read())"`
- v8.9: `grep -c "def _parse_last_result" scripts/update_data.py` = 1
- v9: `python3 scripts/main.py --no-fetch` smoke test offline

### 8.2. Test reale v9
- Pre-step: sync `data.json` da main
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
| **2.2** | **Next-round deducer SF/F (Opzione A)** | 🔥 **PRONTO PER DEPLOY** |
| 2.3 | Parser tabellini `/wp/match/{id}/...` (Opzione B) | ⏳ |
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

### Lessons learned 23/05/2026
- **Non assumere come pubblicato qualcosa che non si è verificato direttamente.** L'ipotesi "LNP pubblicherà testo bracket SF" era basata su pattern QF, mai testata fino al 23/05. Persi 5+ giorni in attesa di evento che non avverrà mai.
- **Fetch manuale URL reali appena possibile.** Quando un trigger dipende da output esterno, verificalo via web fetch alla prima occasione.
- **Falsificabilità:** ogni assunzione architetturale deve avere un test concreto per essere validata, non un'attesa passiva.
