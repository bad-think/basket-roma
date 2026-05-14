[CONTINUITA.md](https://github.com/user-attachments/files/27750360/CONTINUITA.md)
# BASKET ROMA: DOCUMENTO DI CONTINUITÀ

**Versione doc:** v8.9.2
**Versione script:** v8.9.1
**Versione frontend:** v8.9.2
**Data:** 14 maggio 2026
**Repo:** github.com/bad-think/basket-roma

---

## STATO STAGIONE 2025-26

**Regular season:** completa.
- Virtus: 1° girone B, 29V-7P, 58pt
- LUISS: 6° girone B, 21V-15P, 42pt

**Quarti playoff: CONCLUSI**
- **Virtus vs Omegna: 3-0** (G1 94-71, G2 98-79, G3 75-64 in trasferta) → **Semifinale**
- **LUISS vs Orzinuovi: 0-3** (G3 in casa 72-89) → **Eliminata, stagione finita**

**Prossimo:** semifinali playoff Virtus. Bracket SF + calendario gare casa verranno generati automaticamente dal prossimo run quando LNP pubblica il tabellone aggiornato.

---

## CLEANUP ESEGUITO (14/05/2026)

`data.json` aggiornato:
- ✅ G3 LUISS-Orzinuovi (13/5): score 72-89 inserito
- 🗑️ G4 LUISS (15/5 tentative): rimossa, serie chiusa 0-3
- 🗑️ G5 Virtus (18/5 tentative): rimossa, serie chiusa 3-0
- 📊 Totale: 41 → 39 partite
- ➕ Nuovo blocco `config.series_closed` con 2 serie chiuse (LUISS-Orzinuovi, Virtus-Omegna)

---

## PATCH v8.9.1 — Series closure detection

**Problema risolto:** lo script v8.9 al run successivo rigenerava G4/G5 tentative dal bracket parser, annullando il cleanup manuale, perché la pagina LNP playoff resta statica con tutte le gare programmate finché LNP non aggiorna il tabellone.

**Soluzione:** funzione `_is_series_concluded()` (linea ~1538) con due strategie:

1. **Override manuale via `config.series_closed`** in data.json — massima precisione.
   ```json
   "series_closed": [
     {"team": "luiss", "opponent": "Logiman Orzinuovi", "phase": "playoff", "result": "0-3"}
   ]
   ```

2. **Euristica temporale** — auto-rilevazione future serie:
   - Higher seed: 2+ vittorie casa registrate + ≥2 gg dall'ultima → 3-0 likely
   - Generico: ≥3 gare nella serie + ≥3 gg dall'ultima + tentative senza score

**Punto di iniezione:** filtro su `playoff_extra` subito dopo `fetch_playoff_matches()` in `update_in_season()` (linea ~2163). Le partite di serie chiuse vengono escluse PRIMA del merge in `lnp_matches`.

**Log atteso:** `🚫 [team] N gara/e playoff saltate (serie chiusa)`

**Workflow per future serie chiuse:**
1. Confermare esito serie da fonte affidabile (sito LNP o testate)
2. Rimuovere G4/G5 tentative manualmente da `data.json` se ancora presenti
3. Aggiungere entry in `config.series_closed` con `team_advances: true/false`
4. Push → cron successivi non re-inseriranno, frontend mostra stato corretto

---

## PATCH v8.9.2 — Frontend awaiting state

**Problema risolto:** dopo cleanup G4/G5, il frontend mostrava "FINAL BUZZER · STAGIONE ARCHIVIATA" anche se Virtus passa alle semifinali. Causa: logica `seasonEnd = lastMatch` (max data in matches), con cleanup l'ultima data era G3 LUISS (13/5) → frontend pensava stagione finita.

**Soluzione lato frontend (`index.html`):**

1. Nuove variabili globali `seriesClosed` e `teamsConfig` con persistenza localStorage (`brc_sc`, `brc_tc`).

2. Caricamento da `data.config.series_closed` e `data.config.teams` in `fetch()`.

3. **Nuovo SCENARIO C-bis "NEXT ROUND"** in `renderSeasonBanners()`:
   - Calcola `awaitingTeams` = squadre con `team_advances:true` in `series_closed` ma senza partite future in `matches`
   - Si attiva quando `now > seasonEnd` E `hasAwaiting`
   - Banner: *"VIRTUS — AL TURNO SUCCESSIVO · IN ATTESA TABELLONE LNP"*
   - Debug URL: `?banner=awaiting`

4. **SCENARIO D modificato**: condizione aggiunta `!hasAwaiting`. Il final buzzer scatta solo se NESSUNA squadra avanza.

**Soluzione lato backend (`data.json`):**
Schema `series_closed` arricchito con campo `team_advances` (boolean) e `round_name`:
```json
{
  "team": "virtus",
  "opponent": "Paffoni Fulgor Basket Omegna",
  "phase": "playoff",
  "round_name": "QF",
  "result": "3-0",
  "team_advances": true,
  "note": "Vincente QF, passa a SF"
}
```

**Comportamento atteso (oggi 14/05/2026 post-quarti):**
- LUISS: `team_advances:false` → considerata eliminata
- Virtus: `team_advances:true`, no partite future → in `awaitingTeams`
- Banner mostrato: ★ NEXT ROUND ★ — VIRTUS GVM AL TURNO SUCCESSIVO
- Banner NON mostrato: FINAL BUZZER

**Quando LNP pubblicherà SF Virtus:**
- Run script aggiunge partite SF in `matches`
- `hasFuture` diventa true per Virtus → esce da `awaitingTeams`
- Banner "NEXT ROUND" scompare automaticamente, calendario gare appare

---

## ARCHITETTURA v8.9 (corrente, da deprecare)

**Cosa funziona davvero:**
- PDF calendario LNP (regular season)
- Bracket parser testo HTML (playoff schedule)
- RSS sportando/basketinside (score playoff, delay ~12h)
- Team page widget LNP (score regular)

**Codice morto da rimuovere (cascade non funzionanti):**
- `_fetch_playoff_match_page_scores` — URL pattern 404
- `_fetch_playoff_scores_domino` — Domino non risponde per playoff
- `_fetch_scores_from_lnp_calendar` — troppo lento per playoff
- Fallback team page playoff — cache Drupal ferma

**Limiti strutturali:**
- File monolitico `scripts/update_data.py` (2564 righe)
- `_parse_last_result` scomparsa 3x durante `str_replace`
- 8 run/giorno (sovradimensionato)
- Squadre + categoria hardcoded
- Niente supporto playout, coppe, europee
- Niente multi-stagione automatica

---

## REWRITE v9.0 — PIANO

**Obiettivi:**
- Supporto multi-categoria: B Nazionale, A2, Serie A, Coppa Italia LNP, EuroCup/Champions
- Supporto playoff + playout (simmetrici)
- Multi-stagione: cambio config = cambio categoria/squadra senza modifiche codice
- Squadre configurabili (oggi 2, espandibile a N)
- Frontend autoconfigurante da `data.json`
- Modulare (file ~200 righe max)

**Struttura proposta:**
```
basket-roma/
├── config/
│   ├── seasons/2025-26.json     # team + competizioni + venue
│   └── sources.json             # endpoint LNP/LBA/FIBA
├── scripts/
│   ├── main.py                  # orchestrator (~150 righe)
│   ├── core/
│   │   ├── models.py            # Match, Team, Competition
│   │   ├── state.py             # I/O data.json + merge
│   │   └── cleanup.py
│   ├── fetchers/
│   │   ├── lnp.py               # B, A2
│   │   ├── lba.py               # Serie A (lazy load)
│   │   ├── fiba.py              # europee (lazy load)
│   │   └── rss_news.py
│   ├── parsers/
│   │   ├── bracket.py
│   │   ├── pdf_calendar.py
│   │   └── match_score.py
│   └── tests/
├── public/
│   ├── index.html               # zero hardcode squadre
│   ├── app.js                   # render driven by config
│   └── style.css
└── data.json
```

**Match model unificato:**
```python
{
  "id": "stable_hash",
  "season": "2025-26",
  "team_key": "virtus",
  "competition_id": "b_naz_2526",
  "phase": "regular|playoff|playout|cup|europe",
  "round": int | null,
  "game_num": int | null,
  "series_id": "qf_tab2" | null,
  "date": "ISO",
  "time": "HH:MM",
  "home": "...",
  "away": "...",
  "sh": int | null,
  "sa": int | null,
  "tentative": false,
  "sources": ["bracket", "rss", "manual"]
}
```

**Cron ridotto:** 3 run/giorno (09:00, 14:00, 23:00) invece di 8.

**Fasi implementazione:**
1. Foundation: config schema + models + state (parità funzionale v8.9)
2. Fetchers modulari LNP
3. Frontend data-driven
4. Estensioni LBA/FIBA on-demand
5. Hardening: AST pre-commit, unit test parser, alert se score non catturato dopo 24h

---

## WORKFLOW OPERATIVO ATTUALE

**Dopo partita playoff:**
1. Verifica log run per `📰 [team] away: NN-NN (RSS)`
2. Se assente dopo 24h → manual update data.json
3. Cleanup automatico rimuove tentative obsolete (G4/G5 se serie chiusa)

**Cron attuale:** 8 run/giorno (mantenere fino a rewrite, poi 3/giorno).

**Commit dopo modifiche:** sempre versione + descrizione tecnica.

---

## NOTE PER CLAUDE FUTURO

- Memory instruction attiva: versione + commit message dopo ogni modifica
- Verifiche pre-consegna script: `python3 -c "import ast; ast.parse(open('update_data.py').read())"` + `grep -c "def _parse_last_result"`
- Inizio rewrite v9.0: utente conferma quando.
- Transcript sessione cleanup: `/mnt/transcripts/2026-05-14-basket-roma-cleanup-v8-9-1.txt`
