[CONTINUITA.md](https://github.com/user-attachments/files/27235149/CONTINUITA.md)
# Roma Basket Casa — Documento di Continuità

> Ultimo aggiornamento: 30 aprile 2026
> Versione script: v8.7 (1972 righe)
> Repo: `github.com/bad-think/basket-roma`
> Live: `bad-think.github.io/basket-roma/`

---

## 1. Cosa fa il progetto

PWA che traccia le **partite in casa** di Virtus GVM Roma 1960 e LUISS Roma in Serie B Nazionale (Girone B). Aggiornamento automatico ogni ora via GitHub Actions. Zero intervento manuale.

## 2. Architettura

```
GitHub Actions (cron orario)
    └── scripts/update_data.py (v8.6)
            ├── Fonte 1: Pagine squadra LNP (HTML) → date, orari, risultati
            ├── Fonte 2: PDF ufficiale LNP → round di campionato (autoritativo)
            ├── Fonte 3: Domino API (JSON) → risultati in tempo reale
            ├── Fonte 4: 19 pagine girone → classifica + fill punteggi cross-ref
            └── Output: data.json → GitHub Pages

GitHub Pages
    ├── index.html (frontend brutalist, single-file PWA)
    ├── sw.js (service worker v3, stale-while-revalidate)
    ├── data.json (dati partite + standings + config)
    ├── assets/virtus-roma.png, luiss-roma.png
    └── manifest.json, icon-192.png, icon-512.png
```

## 3. File del repo

| File | Funzione |
|---|---|
| `scripts/update_data.py` | Script Python, cuore del sistema. Gira su GitHub Actions |
| `data.json` | Dati runtime: partite, standings, config, classifica_url |
| `index.html` | Frontend PWA single-file (HTML+CSS+JS inline) |
| `sw.js` | Service worker v3. Cache: stale-while-revalidate per HTML, network-first per data.json |
| `assets/*.png` | Loghi squadre (sfondo trasparente) |
| `.github/workflows/update-data.yml` | Workflow update con cron 8 run/giorno (6 serali 18-23 IT + 1 notturna 04:00 IT, con duplicato per gestione DST) + commit automatico. Schedule basketball-aware: copre orari di gioco senza sprecare run inutili. **Concurrency guard** (`group: update-data`, `cancel-in-progress: false`) serializza run sovrapposte (cron + manuali) per prevenire push concorrenti |
| `.github/workflows/freshness-check.yml` | Workflow giornaliero (09:00 UTC): controlla via API GitHub l'ultima esecuzione *riuscita* di `update-data.yml`. Soglia 24h normale / 36h off-season (lug-ago). Fallisce → email automatica. **NB**: controlla l'esecuzione del workflow, NON il `last_updated` di `data.json` (il dato può non cambiare per giorni in fasi statiche, falsi positivi) |

## 4. update_data.py — Struttura funzionale

### 4.1 Configurazione (righe 1-130)
- `TRACKED_TEAMS`: slug, display_name, aliases per Virtus e LUISS
- `LEAGUE_PATHS`: cascade discovery `serie-b → serie-a2 → serie-a`
- `LEAGUE_SERIE_IDS`: mapping per URL classifica LNP
- `DOMINO_LEAGUE_CODES`: mapping per API Domino (risultati real-time)
- `LNP_PDF_BASE`: URL base PDF calendario
- `CONFIG_DEFAULT`: config iniziale data.json

### 4.2 Funzioni core

| Funzione | Scopo |
|---|---|
| `fetch(url)` | HTTP GET con UA browser, timeout 8s |
| `normalise(name)` | Lowercase, strip accenti, strip punteggiatura |
| `parse_lnp_calendar(html)` | Parsa tabella calendario da pagina squadra LNP |
| `calc_team_stats(matches, aliases)` | Calcola W/L/pts da lista partite |
| `filter_season(matches, season)` | Dedup + filtra partite per stagione (fix duplicati LNP) |
| `discover_team_league(slug)` | Cascade discovery lega (B→A2→A) |
| `discover_girone_slugs(league, opponents, self_slug)` | Trova 19 slug del girone dalla pagina indice |
| `compute_full_standings(league, slugs, season)` | Fetch 19 pagine, calcola classifica con H2H + quoziente canestri |
| `fetch_lnp_pdf_round_map(league, season, girone, known_teams)` | Scarica PDF calendario, parsa round per coppia squadre |
| `parse_lnp_pdf_calendar(text, known_teams)` | Parser robusto: regex finditer + vocabolario squadre |
| `extract_pdf_text(bytes)` | Chain: pdftotext → pypdf → parser stdlib (FlateDecode+Tj/TJ) |
| `extract_pdf_text_stdlib(bytes)` | Parser PDF pure-Python, zero dipendenze |
| `round_for_match(pdf_map, home, away)` | Lookup round: esatto → token-overlap fuzzy |
| `_teams_match(a, b)` | Match nomi squadra tollerante a cambi sponsor |
| `fetch_domino_scores(league, girone, season, rounds)` | Fetch risultati real-time da Domino API |
| `build_round_map(all_matches)` | Fallback: round da date (fase1: segmentazione, fase2: consolidamento) |
| `auto_insert_new_home_matches(...)` | Aggiunge partite nuove (recuperi, playoff) con dedup robusta. Dedup ±10gg disattivato in postseason (best-of-5 vs stesso avversario in pochi giorni) |
| `detect_phase(round, pos, date, regular_end_date)` | round≤38=regular, ≥39=playoff/playin (in base a pos). Doppio check: se data > regular_end_date → postseason a prescindere dal round. `regular_end_date` dedotto runtime dall'N-esima partita LNP |
| `update_home_matches(matches, key, aliases, lnp)` | Aggiorna punteggi/date partite esistenti |
| `bootstrap_new_season(config, current_season)` | Ricostruisce data.json da zero per nuova stagione |
| `update_in_season(matches, config, standings)` | Orchestratore principale: update + standings + round + fill |

### 4.3 Chain di risoluzione punteggi (per partite con sh=null)

1. **Domino API** ⚡ (secondi) → `lnpstat.domino.it`, JSON, `game_status: "finished"`
2. **Cross-ref girone** (già in cache) → 19 pagine squadra, cerca lato avversario
3. **Pagina squadra LNP** (24-48h ritardo) → fonte primaria ma lenta

### 4.4 Chain di risoluzione round

1. **PDF ufficiale LNP** (autoritativo) → match per coppia (home, away), gestisce recuperi/anticipi
2. **build_round_map** (fallback) → algoritmo date con consolidamento, può sbagliare ±5

### 4.5 Tiebreaker classifica

`pts desc → H2H wins desc → H2H canestri diff desc → overall canestri diff desc → W desc → nome asc`

## 5. data.json — Schema

```json
{
  "last_updated": "ISO datetime",
  "season": "2025-26",
  "config": {
    "season": "2025-26",
    "next_season": "2026-27",
    "classifica_url": "https://www.legapallacanestro.com/serie/4/classifica",
    "teams": {
      "virtus": { "name", "name_aliases[]", "serie", "girone", "venue_name", "venue_address", "venue_maps" },
      "luiss": { ... }
    }
  },
  "matches": [
    { "id": "v34", "team": "virtus", "phase": "regular|playoff|playin",
      "round": 34, "date": "2026-04-04", "time": "20:00",
      "home": "Virtus GVM Roma 1960", "away": "Benacquista Assicurazioni Latina",
      "sh": 69, "sa": 42 }
  ],
  "standings": {
    "virtus": { "pos": 1, "pts": 58, "w": 29, "l": 7 },
    "luiss": { "pos": 6, "pts": 42, "w": 21, "l": 14 }
  }
}
```

## 6. index.html — Frontend

- **Design**: brutalist/newspaper, Archivo Black + Barlow Condensed, dark theme, CRT scanlines
- **Framework**: zero — vanilla JS, CSS inline, single-file
- **Dati**: `MATCHES = []` (vuoto), tutto viene da data.json fetch con cache-bust
- **Merge**: replace completo (non merge), elimina duplicati da localStorage stale
- **Loghi avversari**: `teamInitials(name)` genera monogramma (es. Chiusi → "GC")
- **Service worker**: registrato con `updateViaCache: 'none'`
- **Banner**: automatici, nessun riferimento a interventi manuali

## 7. sw.js — Service Worker v3

| Risorsa | Strategia |
|---|---|
| `data.json` | Network-first (timeout 4s, fallback cache) |
| `index.html`, `/` | Stale-while-revalidate (serve cache, aggiorna background) |
| Font, CDN | Cache-first |
| Asset statici | Cache-first |
| API esterne | Sempre rete |

## 8. API esterne usate

| API | URL Pattern | Dato |
|---|---|---|
| Pagina squadra LNP | `legapallacanestro.com/serie-b/{slug}` | Calendario, date, orari, risultati (HTML) |
| PDF calendario LNP | `static.legapallacanestro.com/.../calendario_b_nazionale_gir._b_{season}.pdf` | Round ufficiali (statico) |
| Domino API | `lnpstat.domino.it/getstatisticsfiles?task=schedule&year=x{YYNN}&league={code}&round={N}` | Risultati real-time (JSON) |
| Pagina indice girone | `legapallacanestro.com/serie-b` | Lista slug squadre (HTML) |

### Codici Domino per lega

| Lega | Codice | Year format |
|---|---|---|
| Serie B Girone B | `ita3_b` | `x2526` (per 2025-26) |
| Serie B Girone A | `ita3_a` | idem |
| Serie A2 | `ita2` | idem |

## 9. Bug risolti (cronologia)

| Versione | Bug | Soluzione |
|---|---|---|
| v8.0 | pianetabasket instabile, 17 errori 404 | Eliminato, LNP-only |
| v8.1 | Falsi duplicati auto-insert | Dedup 2 livelli: data+avversario, poi avversario±10gg |
| v8.2 | Nessun bootstrap se matches vuoto | Bootstrap on-demand + backup file |
| v8.3 | Round = n-esima partita (non giornata campionato) | build_round_map con regola squadra-ripetuta |
| v8.4 | build_round_map produce 44 round (non 38) | Consolidamento globale (fusione round piccoli) |
| v8.5 | Consolidamento fallisce su dati reali | Pivot a PDF ufficiale LNP come fonte round |
| v8.5 | extract_pdf_text fallisce (no pdftotext/pypdf su Actions) | Parser stdlib pure-Python (FlateDecode+Tj/TJ) |
| v8.5 | parse_lnp_pdf_calendar fallisce su testo monoriga (stdlib) | finditer su pattern `\d+ \d\d/\d\d/\d\d\d\d` |
| v8.6 | round_for_match fallisce per nomi divergenti (Raggisolaris↔Tema Sinergie) | Token-overlap matching (_teams_match) |
| v8.6 | LUISS 72 partite (duplicati HTML) | filter_season con dedup per (data, home, away) |
| v8.6 | Classifica: Virtus 3ª-4ª invece di 1ª | Tiebreaker H2H + quoziente canestri |
| v8.6 | Punteggi null per ritardo pagine squadra LNP | Domino API real-time + cross-ref girone |
| v8.6 | Cache browser persistente | SW v3 stale-while-revalidate + updateViaCache:'none' |
| v8.6 | Partite duplicate nel frontend | Replace completo invece di merge |
| v8.6 | Banner con istruzioni manuali | Riscritti: tutto automatico, nessun data.json manuale |
| v8.7 | Dedup ±10gg blocca G1/G2 playoff (stesso avversario in 2gg) | `is_duplicate` accetta `is_postseason`; in postseason solo match forte (data+avversario esatti) |
| v8.7 | `detect_phase` può classificare playoff come regular se build_round_map dà round ≤38 | Doppio check: round + data; se data > fine regular → postseason |
| v8.7 | `REGULAR_END_DATE` hardcoded richiederebbe modifica manuale ogni stagione | Dedotto runtime dall'N-esima partita LNP della squadra (N da `N_REGULAR_GAMES_BY_LEAGUE`). Zero manutenzione |
| v8.7 | Nessuna protezione contro parse LNP corrotto (cambio HTML) | Sanity check per-team: skip se `lnp_matches < home esistenti`. Sanity globale: exit 1 se tutte le squadre saltate |
| v8.7 | Cron senza coverage di failure systemic (cron fermo, parser rotto, repo archiviato) | Workflow `freshness-check.yml` giornaliero: controlla via API GitHub l'ultima run riuscita di `update-data.yml` → email automatica se ferma |
| v8.7 | Push concorrenti possibili se cron + workflow_dispatch partono ravvicinati → "non-fast-forward" | Concurrency guard (`group: update-data`) serializza esecuzioni: nuova run aspetta che la precedente finisca |
| v8.7 (interim) | Prima versione di freshness-check controllava `last_updated` in data.json → falso positivo quando lo script gira ma non commetta (dati invariati) | Riscritto: ora controlla via `gh api` l'ultima run riuscita del workflow, non il timestamp del JSON |
| v8.7 | CONTINUITA.md descriveva "cron orario" ma lo schedule reale è 8 run/giorno serali+notturna | Documentazione corretta: schedule basketball-aware già efficiente |

## 10. Problemi noti / limiti

1. **Tiebreaker classifica approssimato**: segue pts → H2H → canestri ma non implementa la mini-classifica ricorsiva LNP per parità a 3+. Il link "Classifica ufficiale" compensa.
2. **Nomi squadra possono cambiare con sponsor**: `_teams_match` gestisce i casi noti ma potrebbe fallire su nomi completamente nuovi. Token overlap ≥1 parola ≥5 char copre la maggior parte.
3. **PDF calendario non esiste per playoff**: i round playoff non sono nel PDF statico. Lo script usa fallback `build_round_map` + check su `regular_end_date` dedotto runtime per riconoscere comunque le partite postseason.
4. **Domino API non documentata**: trovata via DevTools, potrebbe cambiare. Codici playoff (`ita3_b_poff`, `ita3_a_poff`) o play-in (`_pin`) ancora da verificare empiricamente con `curl` quando i calendari saranno pubblici. Fallback su girone + pagine squadra copre.

   **Comandi di test Domino playoff** (riferiti da §12.5):
   ```bash
   # Ipotesi A: suffisso _poff / _pin
   curl -s 'https://lnpstat.domino.it/getstatisticsfiles?task=schedule&year=x2526&league=ita3_b_poff&round=1' | head -c 500
   curl -s 'https://lnpstat.domino.it/getstatisticsfiles?task=schedule&year=x2526&league=ita3_b_pin&round=1' | head -c 500

   # Ipotesi B: stessa lega, round estesi
   curl -s 'https://lnpstat.domino.it/getstatisticsfiles?task=schedule&year=x2526&league=ita3_b&round=39' | head -c 500
   curl -s 'https://lnpstat.domino.it/getstatisticsfiles?task=schedule&year=x2526&league=ita3_b&round=37' | head -c 500
   ```
   Il primo che restituisce JSON non vuoto identifica la convenzione.
5. **GitHub Actions**: `pdftotext` e `pypdf` non disponibili sui runner. Il parser stdlib funziona ma è meno robusto su PDF esotici.
6. **`N_REGULAR_GAMES_BY_LEAGUE` hardcoded**: 36 per B/A2, 30 per A. Se LNP cambia il numero di squadre per girone va aggiornato. Probabilità: bassa.

## 11. Stagione 2025-26 — Stato playoff

- **Virtus GVM Roma 1960**: 1° posto regular (29V-7L, 58pt), Tabellone 2 quarti
- **LUISS Roma**: 6° posto regular (21V-14L, 42pt), Tabellone 1 quarti
- **Tabelloni playoff pubblicati LNP** il 26 aprile 2026
- **Avversario Virtus ai quarti**: vincente Play-In Tab. 2 — sarà Omegna (8A), Capo d'Orlando (9A) o Vicenza (12A), determinato entro il 7 maggio sera
- **Calendario quarti**: 8, 10, 13, 15, 18 maggio 2026 (orari e ordine casa/fuori pubblicati da LNP dopo il Play-In del 7 maggio)
- **PDF calendario playoff non esiste**: lo script userà `build_round_map` + sanity check su `regular_end_date` per detect_phase
- **Codici Domino playoff non confermati**: ipotesi `ita3_b_poff` (suffisso URL) o stesso `ita3_b` con round 39+. Da verificare empiricamente all'8 maggio


---

## 12. Troubleshooting playoff — diagnosi guidata

> Da consultare se l'8 maggio (o successive partite playoff) la prima partita di Virtus/LUISS non appare in `data.json` entro un'ora dalla pubblicazione su LNP.

### 12.1 Procedura diagnostica (in ordine)

**Step 1 — Verifica che LNP abbia pubblicato la partita**
- Apri `legapallacanestro.com/squadre/serie-b/virtus-gvm-roma-1960`
- Se la partita NON è elencata → non è un problema dello script, attendere
- Se è elencata → procedi

**Step 2 — Lancia run manuale del workflow**
- GitHub repo → Actions → "Aggiorna Dati Basket Roma" → "Run workflow"
- Attendi 30s, apri il log della run

**Step 3 — Cerca questi pattern nel log**

| Pattern nel log | Significato | Sezione fix |
|---|---|---|
| `📋 [virtus] N partite nel calendario LNP` con N=36 (regular) | LNP non espone playoff in pagina squadra → problema #A | §12.2 |
| `📋 [virtus] N partite nel calendario LNP` con N≥37 ma `📝 Aggiornamenti: 0` | Partita parsata ma scartata da dedup o detect_phase → problema #B | §12.3 |
| `🚨 [virtus] SAFETY SKIP` | Il sanity check ha bloccato l'inserimento → problema #C | §12.4 |
| `🎯 Domino round X: 0 partite` per round playoff | Codice Domino sbagliato per playoff → problema #D | §12.5 |
| Errore `urllib.error` o traceback Python | Eccezione runtime → problema #E | §12.6 |

### 12.2 Problema A — LNP non espone playoff in pagina squadra

**Sintomo**: lo script non vede la partita perché `parse_lnp_calendar` legge la pagina squadra ma LNP la mette solo nella pagina playoff dedicata.

**Verifica manuale**: apri `https://www.legapallacanestro.com/serie/4/playoff-playout/2026/ita3_b_poff`. Se la partita è lì ma non in pagina squadra → confermato.

**Cosa dire al prossimo Claude**:
> "Lo script non vede le partite playoff perché LNP le pubblica solo in `/serie/4/playoff-playout/...` e non nelle pagine squadra. Serve estendere `discover_team_league` o `parse_lnp_calendar` per fetchare anche la pagina playoff e fonderne il calendario."

### 12.3 Problema B — Partita parsata ma non inserita

**Sintomo**: `lnp_matches` contiene la partita ma `data.json` no.

**Cause possibili**:
1. `is_duplicate` la scarta (false positive del dedup)
2. `detect_phase` la classifica come `regular` invece di `playoff` → ID generato non riconosciuto
3. Filtro stagione (`filter_season`) la esclude se la data non matcha la stagione corrente

**Cosa dire al prossimo Claude**:
> "Una partita playoff Virtus del [DATA] vs [AVVERSARIO] è in `lnp_matches` (parse OK) ma non finisce in `data.json`. Verifica con uno script di debug: chiama `is_duplicate(date, away_normalised, is_postseason=True)` e `detect_phase(real_round, team_pos, match_date, regular_end_date)` per quella partita e dimmi i valori. Allego il log della run."

### 12.4 Problema C — Sanity check skip

**Sintomo**: log mostra `🚨 [team] SAFETY SKIP: lnp_matches=N < home esistenti=M`.

**Causa**: il sanity check protegge contro parse corrotto. Se LNP ha cambiato HTML e ora `parse_lnp_calendar` torna meno partite di quante ce ne sono già nel JSON, lo script salta per evitare data loss.

**Cosa dire al prossimo Claude**:
> "Il sanity check di `update_in_season` blocca l'aggiornamento di [team] perché `parse_lnp_calendar` torna meno partite del previsto. Probabile cambio HTML LNP. Verifica con `curl` la pagina squadra e adatta il parser. La logica safety in `update_in_season` è `if existing_home > 0 and len(lnp_matches) < existing_home: skip`."

### 12.5 Problema D — Domino non popola scores playoff

**Sintomo**: la partita appare in `data.json` ma con `sh: null, sa: null` (punteggi vuoti) anche dopo la fine del match.

**Causa**: il codice lega Domino per playoff è diverso. `DOMINO_LEAGUE_CODES` ha solo `("serie-b", "b"): "ita3_b"` per la regular.

**Cosa dire al prossimo Claude**:
> "I punteggi delle partite playoff non vengono popolati da Domino. Allego il log con le righe `🎯 Domino round X`. Devi: (1) testare manualmente con `curl 'https://lnpstat.domino.it/getstatisticsfiles?task=schedule&year=x2526&league=ita3_b_poff&round=1'` e altre varianti (`_pin`, round 39+ con `ita3_b`), (2) trovare il codice giusto, (3) aggiornare `DOMINO_LEAGUE_CODES` o modificare `fetch_domino_scores` per gestire playoff. Le ipotesi da testare sono in §10.4 di questa CONTINUITA."

### 12.6 Problema E — Eccezione runtime

**Sintomo**: traceback Python nel log, workflow fallisce con exit code ≠ 0.

**Cosa dire al prossimo Claude**:
> "Workflow `update-data.yml` fallisce con eccezione. Allego log completo. Diagnostica e proponi fix chirurgico."

### 12.7 Note generali per fix futuri

- L'utente non programma. Fornisci sempre file completi pronti da incollare, non patch parziali.
- Verifica sintassi Python con `python3 -c "import ast; ast.parse(...)"` prima di consegnare.
- Aggiorna sempre il banner versione in `update_data.py` quando applichi patch (`vX.Y` → `vX.Y+1`) per dare un segnale visibile nei log.
- Aggiorna questa CONTINUITA con la nuova entry in §9 (Bug risolti).

## 13. Istruzioni per nuova sessione Claude

### Contesto minimo da dare
```
Progetto: Roma Basket Casa (bad-think/basket-roma)
PWA che traccia partite in casa Virtus Roma + LUISS Roma, Serie B Nazionale.
Script Python v8.6 su GitHub Actions (cron orario), frontend brutalist single-file.
Fonti dati: LNP pagine squadra + PDF calendario + Domino API real-time.
```

### Se devi fare un fix
1. Carica `scripts/update_data.py` + `data.json` + log ultima run
2. Descrivi il problema (es. "punteggio non appare", "classifica sbagliata")
3. Claude ha il contesto dal documento di continuità nelle memorie

### Se devi modificare il frontend
1. Carica `index.html`
2. Specifica cosa cambiare
3. Vincoli: MATCHES=[] (dati solo da data.json), no framework, CSS inline

### Se inizia la nuova stagione
Lo script gestisce automaticamente, **zero modifiche manuali**:
- Cambio stagione → `bootstrap_new_season` ricostruisce data.json
- Cambio lega (promozione/retrocessione) → cascade discovery (B→A2→A)
- Cambio girone → auto-discovery da pagina indice
- PDF nuovo → URL pattern prevedibile (`calendario_b_nazionale_gir._b_{season}.pdf`)
- Fine regular season → `regular_end_date` dedotto runtime dall'N-esima partita LNP
- Squadre in leghe diverse (es. Virtus in A2, LUISS in B) → `classifica_cache` separa per lega, ogni squadra processata indipendentemente

L'unico caso che richiederebbe intervento manuale è se LNP cambia il numero di squadre per girone → aggiornare `N_REGULAR_GAMES_BY_LEAGUE` in cima al file.

### Preferenze dell'utente (Donato)
- Fix chirurgici, NO refactor totali
- Risposte precise senza disclaimer
- Programmatore principiante: spiegare cosa fare passo-passo
- Lingua italiana per l'interfaccia, inglese per il codice
- Mai usare Gemini sul progetto (ha rotto file 3 volte in passato)
- **Ottimizzare l'uso di token**: massimo risultato con minimo consumo. Niente preamboli, riepiloghi, ripetizioni o postamboli di cortesia. Output denso, diretto. Quando si modifica un file usare `str_replace` su singoli blocchi, mai riscrivere file interi se non strettamente necessario.
