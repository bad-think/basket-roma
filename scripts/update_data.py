#!/usr/bin/env python3
"""
update_data.py — Roma Basket Casa — v8.7
Architettura LNP-only con auto-discovery, auto-insert, auto-bootstrap.

Fonte unica: legapallacanestro.com
- Calendario, date, orari, risultati: pagine squadra LNP (HTML)
- Classifica completa con pos: derivata da tutte le squadre del girone
- Round di campionato: PDF ufficiale LNP della stagione (fonte autoritativa)
  fallback: build_round_map_from_dates (algoritmo legacy basato su date)
- Cambio lega: cascade discovery serie-b → serie-a2 → serie-a
- Auto-insert partite postseason (playoff/play-in) con phase auto-rilevata
- Auto-bootstrap nuova stagione con backup file di sicurezza
- Bootstrap on-demand: se data.json ha matches vuoti, popola da LNP
- Deduplica robusta: match per nome avversario + tolleranza data ±10 giorni
- Correzione retroattiva round (auto-fix dei round sbagliati a ogni run)
- Zero hardcoded round URLs, zero pianetabasket, zero intervento manuale
"""

import json
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, date, timedelta
from pathlib import Path

# ================================================================
# CONFIGURAZIONE
# ================================================================

# Squadre seguite — basta lo SLUG LNP (parte finale dell'URL pagina squadra).
# Lo slug è stabile attraverso le stagioni, anche in caso di cambio lega.
# Per aggiungere/togliere squadre, modificare solo questo dict.
TRACKED_TEAMS = {
    "virtus": {
        "slug": "virtus-gvm-roma-1960",
        "display_name": "Virtus GVM Roma",
        "name_aliases": [
            "virtus gvm roma 1960", "virtus gvm roma", "virtus roma",
            "pallacanestro virtus roma",
        ],
    },
    "luiss": {
        "slug": "luiss-roma",
        "display_name": "Luiss Roma",
        "name_aliases": ["luiss roma", "luiss", "luiss basketball"],
    },
}

# PDF ufficiali LNP del calendario stagione — fonte autoritativa per round.
# Pattern URL standard: si convertono lega+girone+stagione in URL prevedibile.
# Se il PDF non è raggiungibile, lo script ricade sull'algoritmo basato su date.
#
# Stagione viene espressa nel filename come "YYYY-NN" (es. "2025-26").
# Il formato esatto del nome cambia leggermente tra leghe:
# - Serie B: calendario_b_nazionale_gir._{a|b}_{season}.pdf
# - A2:      calendario_a2_{season}.pdf  (nessun girone, da verificare)
LNP_PDF_BASE = "https://static.legapallacanestro.com/sites/default/files/editor"

def lnp_pdf_url(league_path, season, girone_letter=None):
    """Costruisce URL del PDF calendario LNP per una lega/girone/stagione."""
    season_norm = season.replace("/", "-")  # "2025/26" → "2025-26"
    if league_path == "serie-b" and girone_letter:
        return f"{LNP_PDF_BASE}/calendario_b_nazionale_gir._{girone_letter.lower()}_{season_norm}.pdf"
    if league_path == "serie-a2":
        return f"{LNP_PDF_BASE}/calendario_a2_{season_norm}.pdf"
    if league_path == "serie-a":
        return f"{LNP_PDF_BASE}/calendario_serie_a_{season_norm}.pdf"
    return None

# Cascade leghe LNP — ordine di tentativo per discovery automatica
LEAGUE_PATHS = ["serie-b", "serie-a2", "serie-a"]

# Mapping leghe → label per data.json (compat con index.html)
LEAGUE_LABELS = {
    "serie-b": "B Nazionale",
    "serie-a2": "A2",
    "serie-a": "A",
}

# Mapping leghe → ID numerico per URL classifica LNP
# URL pattern: https://www.legapallacanestro.com/serie/{id}/classifica
LEAGUE_SERIE_IDS = {
    "serie-b": 4,
    "serie-a2": 1,
}

# Mapping leghe+girone → codice Domino API (risultati in tempo reale)
# URL: https://lnpstat.domino.it/getstatisticsfiles?task=schedule&year=x{YYNN}&league={code}&round={N}
DOMINO_LEAGUE_CODES = {
    ("serie-b", "b"): "ita3_b",
    ("serie-b", "a"): "ita3_a",
    ("serie-a2", None): "ita2",
}

# Numero di partite di regular season per squadra in ogni lega.
# Serve a dedurre automaticamente la data di fine regular season dal
# calendario LNP della squadra: la N-esima partita cronologica è
# l'ultima regular, tutto ciò che viene dopo è postseason.
# Aggiornare se LNP cambia il numero di squadre per girone.
N_REGULAR_GAMES_BY_LEAGUE = {
    "serie-b": 36,    # 19 squadre per girone, 36 partite andata+ritorno
    "serie-a2": 36,   # 19 squadre, 36 partite (con turno di riposo)
    "serie-a": 30,    # 16 squadre, 30 partite andata+ritorno
}

# Default config (compat con data.json esistente)
CONFIG_DEFAULT = {
    "season": "2025-26",
    "next_season": "2026-27",
    "teams": {
        "virtus": {
            "name": "Virtus GVM Roma",
            "name_aliases": [
                "virtus gvm roma", "virtus roma", "virtus gvm roma 1960",
                "pallacanestro virtus roma",
            ],
            "serie": "B Nazionale",
            "girone": "B",
            "venue_name": "PalaTiziano – Palazzetto dello Sport",
            "venue_address": "Piazza Apollodoro 10, 00196 Roma",
            "venue_maps": "https://maps.google.com/?q=Palazzetto+dello+Sport+Piazza+Apollodoro+10+Roma",
        },
        "luiss": {
            "name": "Luiss Roma",
            "name_aliases": ["luiss roma", "luiss", "luiss basketball"],
            "serie": "B Nazionale",
            "girone": "B",
            "venue_name": "PalaTiziano – Palazzetto dello Sport",
            "venue_address": "Piazza Apollodoro 10, 00196 Roma",
            "venue_maps": "https://maps.google.com/?q=Palazzetto+dello+Sport+Piazza+Apollodoro+10+Roma",
        },
    },
}

BASE_STANDINGS = {
    "virtus": {"pos": 1, "pts": 54, "w": 27, "l": 6},
    "luiss":  {"pos": 6, "pts": 38, "w": 19, "l": 13},
}


# ================================================================
# UTILITY
# ================================================================

def fetch(url, timeout=8):
    """Fetch HTTP con UA realistico. Ritorna stringa vuota su errore."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; RomaBasketUpdater/7.0)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "it-IT,it;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        # 404 silenzioso (atteso durante discovery cascade)
        if e.code != 404:
            print(f"  ⚠️  {url[:80]}: HTTP {e.code}", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"  ⚠️  {url[:80]}: {e}", file=sys.stderr)
        return ""


# Sostituzioni per ridurre nomi squadra a token canonici confrontabili.
# L'ordine importa: regole più specifiche prima di quelle generiche.
_NAME_REPLACEMENTS = [
    ("virtus gvm roma 1960", "virtus roma"),
    ("virtus gvm roma", "virtus roma"),
    ("luiss basketball", "luiss"),
    ("luiss roma", "luiss"),
    ("consorzio leonardo dany quarrata", "quarrata"),
    ("consorzio dany quarrata", "quarrata"),
    ("paperdi juvecaserta 2021", "juvecaserta"),
    ("paperdi juvecaserta", "juvecaserta"),
    ("malvin psa basket casoria", "casoria"),
    ("psa basket casoria", "casoria"),
    ("verodol cbd pielle livorno", "pielle livorno"),
    ("up andrea costa imola", "andrea costa"),
    ("andrea costa imola", "andrea costa"),
    ("benacquista assicurazioni latina", "latina"),
    ("benacquista latina", "latina"),
    ("allianz pazienza san severo", "san severo"),
    ("umana san giobbe chiusi", "chiusi"),
    ("general contractor jesi", "jesi"),
    ("solbat golfo piombino", "piombino"),
    ("orasì ravenna", "ravenna"),
    ("orasi ravenna", "ravenna"),
    ("power basket nocera", "nocera"),
    ("adamant ferrara basket 2018", "ferrara"),
    ("adamant ferrara", "ferrara"),
    ("virtus pallacanestro imola", "v.imola"),
    ("virtus imola", "v.imola"),
    ("ristopro janus fabriano", "fabriano"),
    ("ristopro fabriano", "fabriano"),
    ("tema sinergie faenza", "faenza"),
    ("raggisolaris faenza", "faenza"),
    ("consultinvest loreto pesaro", "loreto"),
    ("loreto pesaro", "loreto"),
]


def normalise(s):
    """Riduce un nome squadra a forma canonica per confronti."""
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    for old, new in _NAME_REPLACEMENTS:
        s = s.replace(old, new)
    return s


def slug_to_normalised(slug):
    """Slug LNP → stringa normalizzata confrontabile coi nomi nelle pagine."""
    s = slug.replace("-", " ")
    # Decode caratteri italiani URL-encoded
    s = (s.replace("%c3%ac", "ì").replace("%C3%AC", "ì")
           .replace("%c3%a8", "è").replace("%C3%A8", "è")
           .replace("%c3%a9", "é").replace("%C3%A9", "é")
           .replace("%c3%b9", "ù").replace("%C3%B9", "ù")
           .replace("%c3%b2", "ò").replace("%C3%B2", "ò")
           .replace("%c3%a0", "à").replace("%C3%A0", "à"))
    return normalise(s)


# ================================================================
# PARSING PAGINE LNP
# ================================================================

def parse_lnp_calendar(html):
    """
    Estrae il calendario completo (casa + trasferta) dalla pagina squadra LNP.
    Restituisce lista [{date, time, home, away, sh, sa}].
    Risultato 0-0 = partita non ancora giocata.
    """
    results = []
    td_list = re.findall(r'<td[^>]*>(.*?)</td>', html, re.DOTALL | re.IGNORECASE)
    td_list = [re.sub(r'<[^>]+>', ' ', td) for td in td_list]
    td_list = [re.sub(r'\s+', ' ', td).strip() for td in td_list]

    i = 0
    while i < len(td_list) - 3:
        dt = td_list[i]
        m = re.match(r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})', dt)
        if not m:
            i += 1
            continue

        date_str, time_str = m.groups()
        home_raw = td_list[i + 1].strip()
        away_raw = td_list[i + 2].strip()
        result_raw = td_list[i + 3].strip() if i + 3 < len(td_list) else ""

        if len(home_raw) < 3 or len(away_raw) < 3:
            i += 1
            continue

        rm = re.match(r'(\d+)\s*[-–]\s*(\d+)', result_raw)
        if rm:
            sh_raw, sa_raw = int(rm.group(1)), int(rm.group(2))
            sh = sh_raw if not (sh_raw == 0 and sa_raw == 0) else None
            sa = sa_raw if sh is not None else None
        else:
            sh, sa = None, None

        dd, mm, yyyy = date_str.split('/')
        results.append({
            "date": f"{yyyy}-{mm}-{dd}",
            "time": time_str,
            "home": home_raw,
            "away": away_raw,
            "sh": sh,
            "sa": sa,
        })
        i += 5  # avanza di un'intera riga (5 celle: data, casa, ospite, risultato, impianto)

    return results


def calc_team_stats(lnp_matches, team_aliases):
    """Calcola (W, L, pts) di una squadra dal suo calendario completo LNP.
    In Serie B/A2/A: vittoria = 2pt, sconfitta = 0pt."""
    w, l = 0, 0
    aliases_norm = [normalise(a) for a in team_aliases if a]
    for lm in lnp_matches:
        sh, sa = lm.get("sh"), lm.get("sa")
        if sh is None or sa is None:
            continue
        home_n = normalise(lm["home"])
        team_is_home = any(an in home_n or home_n in an for an in aliases_norm)
        if team_is_home:
            won = sh > sa
        else:
            won = sa > sh
        if won:
            w += 1
        else:
            l += 1
    return w, l, w * 2


def extract_opponents(lnp_matches, team_aliases):
    """Estrae i nomi raw degli avversari della squadra dal suo calendario."""
    opponents = set()
    aliases_norm = [normalise(a) for a in team_aliases if a]
    for m in lnp_matches:
        h_n = normalise(m["home"])
        team_is_home = any(an in h_n or h_n in an for an in aliases_norm)
        opponent_raw = m["away"] if team_is_home else m["home"]
        if opponent_raw and len(opponent_raw) >= 3:
            opponents.add(opponent_raw)
    return opponents


def filter_season(matches, season):
    """Filtra partite alla stagione corrente e deduplica.
    LNP a volte mostra stagioni precedenti o duplica le righe nell'HTML."""
    if not matches:
        return matches
    # Dedup per (data, home, away)
    seen = set()
    deduped = []
    for m in matches:
        key = (m.get("date"), normalise(m.get("home", "")), normalise(m.get("away", "")))
        if key not in seen:
            seen.add(key)
            deduped.append(m)
    # Filtro stagione
    if season:
        try:
            y1 = int(season.split("-")[0])
            y2 = int(f"{str(y1)[:2]}{season.split('-')[1]}")
            lo, hi = f"{y1}-07-01", f"{y2}-06-30"
            filtered = [m for m in deduped if lo <= m.get("date", "") <= hi]
            if filtered:
                deduped = filtered
        except (ValueError, IndexError):
            pass
    return deduped


# ================================================================
# DISCOVERY LEGA E GIRONE
# ================================================================

def discover_team_league(team_slug):
    """
    Determina in quale lega LNP gioca la squadra.
    Cascade su LEAGUE_PATHS, restituisce (league_path, html) o (None, None).

    Resilient ai cambi di lega: se una squadra viene promossa in A2,
    la prossima run la troverà sotto serie-a2 senza intervento manuale.
    """
    for path in LEAGUE_PATHS:
        url = f"https://www.legapallacanestro.com/{path}/{team_slug}"
        html = fetch(url)
        if html and len(html) >= 1000 and "calendario" in html.lower():
            return path, html
    return None, None


# Path da escludere quando si parsano gli slug della pagina indice lega
_INDEX_BLACKLIST_KEYWORDS = [
    "formula", "calendario-dirette", "old-wild-west", "negli-anticipi",
    "guida-al-campionato", "supercoppa", "coppa-italia", "final-four",
    "lnp-pass", "archivio-storico", "leaders", "statistiche",
    "live-match", "mvp", "best-coach", "miglior-under",
]


def discover_girone_slugs(league_path, opponent_names, own_slug):
    """
    Identifica gli slug LNP delle squadre del girone in cui gioca la squadra.

    Strategia:
    1. Fetch della pagina indice lega (es. /serie-b) — HTML statico con
       link a tutte le squadre della lega (es. 38 = girone A + B).
    2. Estrae tutti gli slug /serie-X/[slug] dalla pagina indice.
    3. Filtra quelli i cui nomi normalizzati matchano gli avversari
       della squadra seguita = squadre dello stesso girone.
    4. Aggiunge sempre own_slug (la squadra stessa) al risultato.
    """
    index_url = f"https://www.legapallacanestro.com/{league_path}"
    html = fetch(index_url)
    if not html:
        print(f"  ⚠️  pagina indice {league_path} non disponibile")
        return {own_slug}

    # Estrai tutti gli slug candidati dai link
    pat = re.compile(rf'/{re.escape(league_path)}/([a-zA-Z0-9\-%]+?)(?:["\'\?#/]|$)')
    raw_slugs = set(pat.findall(html))

    # Filtra blacklist e slug troppo corti
    candidate_slugs = set()
    for s in raw_slugs:
        sl = s.lower()
        if any(k in sl for k in _INDEX_BLACKLIST_KEYWORDS):
            continue
        if len(s) < 4:
            continue
        candidate_slugs.add(s)

    # Set di nomi avversari normalizzati
    opp_norm = {normalise(o) for o in opponent_names if o}
    opp_norm = {o for o in opp_norm if len(o) >= 3}

    girone_slugs = {own_slug}
    for slug in candidate_slugs:
        sn = slug_to_normalised(slug)
        if not sn:
            continue
        for on in opp_norm:
            # Match esatto, oppure substring (token significativo, >= 4 char)
            if sn == on:
                girone_slugs.add(slug)
                break
            if len(on) >= 4 and (on in sn or sn in on):
                girone_slugs.add(slug)
                break

    return girone_slugs


def compute_full_standings(league_path, girone_slugs, season=None):
    """
    Per ogni squadra del girone fa fetch della pagina LNP e calcola W/L/pts.
    Restituisce (standings_list, all_matches) dove:
    - standings_list = [{slug, name, w, l, pts, pos}, ...] ordinata
    - all_matches = lista di tutte le partite del girone (con duplicati,
                    una per ogni vista squadra) — usata per round_map

    Tiebreaker semplificato: pts desc, w desc, nome asc.
    Il tiebreaker ufficiale LNP (scontri diretti, quoziente canestri) non è
    implementato — la pos può divergere in caso di parità esatta. Sufficiente
    per uso informativo.
    """
    teams = []
    all_matches_collected = []  # tutte le partite di tutte le squadre
    for slug in sorted(girone_slugs):
        url = f"https://www.legapallacanestro.com/{league_path}/{slug}"
        html = fetch(url)
        if not html or len(html) < 1000:
            print(f"     ⚠️  {slug}: pagina non disponibile")
            continue
        matches = parse_lnp_calendar(html)
        if not matches:
            print(f"     ⚠️  {slug}: calendario non parsabile")
            continue
        matches = filter_season(matches, season)

        all_matches_collected.extend(matches)

        # Trova il nome reale della squadra cercando nelle partite la cella
        # che contiene lo slug normalizzato (è il "self team" della pagina)
        sn = slug_to_normalised(slug)
        team_name = None
        for m in matches:
            for cell in (m["home"], m["away"]):
                cn = normalise(cell)
                if cn == sn or sn in cn or cn in sn:
                    team_name = cell
                    break
            if team_name:
                break
        if not team_name:
            team_name = slug.replace("-", " ").title()

        # Calcola W/L/pts usando il nome trovato come alias unico
        aliases = [team_name, sn, slug.replace("-", " ")]
        w, l, pts = calc_team_stats(matches, aliases)
        # Calcola canestri fatti/subiti per quoziente canestri (tiebreaker)
        pf = pa = 0
        aliases_norm = [normalise(a) for a in aliases]
        for m in matches:
            if m.get("sh") is None or m.get("sa") is None:
                continue
            try:
                sh, sa = int(m["sh"]), int(m["sa"])
            except (ValueError, TypeError):
                continue
            hn = normalise(m["home"])
            is_home = any(an in hn or hn in an for an in aliases_norm)
            if is_home:
                pf += sh; pa += sa
            else:
                pf += sa; pa += sh
        teams.append({
            "slug": slug,
            "name": team_name,
            "w": w, "l": l, "pts": pts,
            "pf": pf, "pa": pa,
        })

    # Costruisci matrice scontri diretti e canestri H2H
    h2h = {}      # (a_norm, b_norm) → wins di A vs B
    h2h_pf = {}   # (a_norm, b_norm) → canestri di A vs B (somma partite)
    for m in all_matches_collected:
        if m.get("sh") is None or m.get("sa") is None:
            continue
        try:
            sh, sa = int(m["sh"]), int(m["sa"])
        except (ValueError, TypeError):
            continue
        hn, an = normalise(m["home"]), normalise(m["away"])
        h2h_pf[(hn, an)] = h2h_pf.get((hn, an), 0) + sh
        h2h_pf[(an, hn)] = h2h_pf.get((an, hn), 0) + sa
        if sh > sa:
            h2h[(hn, an)] = h2h.get((hn, an), 0) + 1
        elif sa > sh:
            h2h[(an, hn)] = h2h.get((an, hn), 0) + 1

    def h2h_wins(tn, rivals):
        return sum(h2h.get((tn, r), 0) for r in rivals)

    def h2h_diff(tn, rivals):
        """Differenza canestri H2H: fatti - subiti contro i rivals."""
        scored = sum(h2h_pf.get((tn, r), 0) for r in rivals)
        conceded = sum(h2h_pf.get((r, tn), 0) for r in rivals)
        return scored - conceded

    # Ordina: pts desc, poi per gruppi a pari punti:
    #   1. H2H wins desc  2. H2H canestri diff desc
    #   3. Overall canestri diff desc  4. W desc
    from itertools import groupby
    teams.sort(key=lambda t: (-t["pts"], -t["w"]))
    ordered = []
    for _key, group in groupby(teams, key=lambda t: t["pts"]):
        tied = list(group)
        if len(tied) > 1:
            norm_set = {normalise(t["name"]) for t in tied}
            tied.sort(key=lambda t: (
                -h2h_wins(normalise(t["name"]), norm_set - {normalise(t["name"])}),
                -h2h_diff(normalise(t["name"]), norm_set - {normalise(t["name"])}),
                -(t["pf"] - t["pa"]),
                -t["w"],
                t["name"].lower(),
            ))
        ordered.extend(tied)
    teams = ordered

    for i, t in enumerate(teams, start=1):
        t["pos"] = i
    return teams, all_matches_collected


# ================================================================
# ROUND MAP — PDF UFFICIALE LNP (FONTE AUTORITATIVA)
# ================================================================

def fetch_pdf_bytes(url):
    """
    Scarica un PDF come bytes. Non usa fetch() perché quello decodifica
    a stringa, mentre i PDF sono binari. Stessa logica di UA/timeout.
    """
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/pdf,*/*",
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read()
    except Exception as e:
        print(f"  ⚠️  PDF fetch fallito {url}: {e}")
        return None


def extract_pdf_text(pdf_bytes):
    """
    Estrae il testo da un PDF. Prova in ordine:
    1. pdftotext (poppler) via subprocess — se installato sul sistema
    2. pypdf (puro Python) — se la libreria è disponibile
    3. Parser stdlib-only minimale — sempre disponibile, estrae text operators
       dagli stream FlateDecode. Funziona per PDF text-based non cifrati.
    """
    if not pdf_bytes:
        return None

    # Tentativo 1: pdftotext (poppler-utils)
    try:
        import subprocess
        result = subprocess.run(
            ["pdftotext", "-layout", "-", "-"],
            input=pdf_bytes, capture_output=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout:
            text = result.stdout.decode("utf-8", errors="replace")
            if text.strip():
                print(f"  🔧 PDF text extracted via pdftotext ({len(text)} chars)")
                return text
            print(f"  ⚠️  pdftotext: output vuoto")
    except FileNotFoundError:
        print(f"  ℹ️  pdftotext non installato, provo fallback")
    except subprocess.TimeoutExpired:
        print(f"  ⚠️  pdftotext timeout")
    except Exception as e:
        print(f"  ⚠️  pdftotext error: {e}")

    # Tentativo 2: pypdf
    try:
        import pypdf
        import io
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if text.strip():
            print(f"  🔧 PDF text extracted via pypdf ({len(text)} chars)")
            return text
        print(f"  ⚠️  pypdf: output vuoto")
    except ImportError:
        print(f"  ℹ️  pypdf non installato, provo fallback stdlib")
    except Exception as e:
        print(f"  ⚠️  pypdf error: {e}")

    # Tentativo 3: parser stdlib-only (FlateDecode + Tj/TJ operators)
    text = extract_pdf_text_stdlib(pdf_bytes)
    if text and text.strip():
        print(f"  🔧 PDF text extracted via stdlib parser ({len(text)} chars)")
        return text
    print(f"  ⚠️  stdlib parser: output vuoto")

    return None


def extract_pdf_text_stdlib(pdf_bytes):
    """
    Parser PDF minimale, solo stdlib. Estrae testo dai text operators
    (Tj e TJ) presenti negli stream del PDF, decomprimendo con zlib.

    Funziona per:
    - PDF non cifrati
    - Stream compressi con FlateDecode (standard)
    - PDF text-based (non scansioni/immagini)

    NON funziona per:
    - PDF cifrati
    - Altri filtri (LZW, RunLengthDecode, ecc.)
    - PDF "image-based" (scansioni)

    Il PDF LNP è generato da Word → FlateDecode + text, quindi funziona.
    """
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        return None

    import zlib

    texts = []
    pos = 0
    while True:
        start = pdf_bytes.find(b"stream", pos)
        if start == -1:
            break
        end = pdf_bytes.find(b"endstream", start)
        if end == -1:
            break

        # Skip newline dopo "stream"
        data_start = start + len(b"stream")
        if pdf_bytes[data_start:data_start + 2] == b"\r\n":
            data_start += 2
        elif pdf_bytes[data_start:data_start + 1] in (b"\n", b"\r"):
            data_start += 1
        # Skip newline prima di "endstream"
        data_end = end
        if pdf_bytes[data_end - 2:data_end] == b"\r\n":
            data_end -= 2
        elif pdf_bytes[data_end - 1:data_end] in (b"\n", b"\r"):
            data_end -= 1

        stream_data = pdf_bytes[data_start:data_end]

        # Tenta decompressione FlateDecode
        decompressed = None
        try:
            decompressed = zlib.decompress(stream_data)
        except zlib.error:
            # Non compresso o altro filtro — prova comunque come-è
            decompressed = stream_data

        try:
            content = decompressed.decode("latin-1", errors="replace")
        except Exception:
            pos = end + len(b"endstream")
            continue

        # Estrai text operators Tj: (testo)Tj
        for m in re.finditer(r"\(((?:[^()\\]|\\[\\()nrtbf])*)\)\s*Tj", content):
            s = _pdf_unescape(m.group(1))
            if s:
                texts.append(s)
                texts.append(" ")  # separator

        # Estrai text operators TJ: [(frag1)num(frag2)num...]TJ
        for m in re.finditer(r"\[([^\]]*)\]\s*TJ", content):
            inner = m.group(1)
            for sm in re.finditer(r"\(((?:[^()\\]|\\[\\()nrtbf])*)\)", inner):
                s = _pdf_unescape(sm.group(1))
                if s:
                    texts.append(s)
            texts.append(" ")

        # Newline dopo ogni "T*" (text move) — euristica per separare righe
        # Lo aggiungo alla fine del processing dello stream
        texts.append("\n")

        pos = end + len(b"endstream")

    return "".join(texts)


def _pdf_unescape(s):
    """Decodifica escape sequences di una stringa PDF."""
    return (s.replace("\\\\", "\\")
            .replace("\\(", "(")
            .replace("\\)", ")")
            .replace("\\n", " ")
            .replace("\\r", " ")
            .replace("\\t", " ")
            .replace("\\b", "")
            .replace("\\f", ""))


def parse_lnp_pdf_calendar(pdf_text, known_teams=None):
    r"""
    Parsa il testo estratto dal PDF calendario ufficiale LNP.
    Formato di ogni partita: <round> <DD/MM/YYYY> <home> <away>
    dove home e away possono contenere spazi interni.

    Il parser gestisce due casi:
    1. TESTO MULTIRIGA (pdftotext/pypdf): ogni partita su una riga separata
    2. TESTO MONORIGA (stdlib parser): tutte le partite concatenate in una
       singola riga con spazi. In questo caso facciamo split preliminare
       sui pattern "<round> <data>" per separare le partite.

    STRATEGIA ROBUSTA: se è disponibile `known_teams` (set di nomi squadra
    noti da LNP HTML), il parser trova quali squadre appaiono come
    substring nel resto della riga. La prima trovata è home, la seconda away.

    Restituisce dict {(home_normalized, away_normalized): round_int}.
    """
    if not pdf_text:
        return {}

    round_map = {}
    known_norm = None
    if known_teams:
        known_norm = sorted(
            {normalise(t): t for t in known_teams if t}.items(),
            key=lambda kv: -len(kv[0]),
        )

    # Pattern per identificare l'inizio di una partita: "<round> <DD/MM/YYYY>"
    match_start = re.compile(r"(\d{1,2})\s+(\d{2}/\d{2}/\d{4})\s+")

    # Split del testo completo in "segmenti partita" usando finditer.
    # Ogni segmento va dall'inizio di un match all'inizio del successivo
    # (o alla fine del testo).
    matches = list(match_start.finditer(pdf_text))
    if not matches:
        return {}

    segments = []  # list of (round_int, rest_text)
    for i, m in enumerate(matches):
        round_num, _date = m.group(1), m.group(2)
        try:
            round_int = int(round_num)
        except ValueError:
            continue
        if not (1 <= round_int <= 80):
            continue
        # Il "rest" è dal dopo-data fino all'inizio della prossima partita
        rest_start = m.end()
        rest_end = matches[i + 1].start() if i + 1 < len(matches) else len(pdf_text)
        rest = pdf_text[rest_start:rest_end].strip()
        # Rimuovi eventuali "Riposa: ..." o contenuti extra che non
        # fanno parte del nome squadra away
        rest = re.split(r"\bRiposa\b[: ]", rest, maxsplit=1)[0].strip()
        segments.append((round_int, rest))

    for round_int, rest in segments:
        home = away = None

        # Strategia 1: match con vocabolario known_teams
        if known_norm:
            rest_norm = normalise(rest)
            found = []
            consumed = [False] * len(rest_norm)
            for tn, _orig in known_norm:
                if not tn or len(tn) < 3:
                    continue
                idx = 0
                while True:
                    pos = rest_norm.find(tn, idx)
                    if pos == -1:
                        break
                    if not any(consumed[pos:pos + len(tn)]):
                        found.append((pos, tn))
                        for i in range(pos, pos + len(tn)):
                            consumed[i] = True
                        break
                    idx = pos + 1
            found.sort(key=lambda x: x[0])
            if len(found) >= 2:
                home = found[0][1]
                away = found[1][1]

        # Strategia 2 (fallback): split per 2+ spazi
        if home is None:
            m2 = re.match(r"^(.+?)\s{2,}(.+?)$", rest)
            if m2:
                home = normalise(m2.group(1))
                away = normalise(m2.group(2))

        if home and away:
            round_map[(home, away)] = round_int

    return round_map


def fetch_lnp_pdf_round_map(league_path, season, girone_letter=None, known_teams=None):
    """
    Scarica il PDF calendario ufficiale LNP e costruisce il round_map
    {(home_norm, away_norm): round}.
    `known_teams`: set/list di nomi squadra noti (da LNP HTML) — fortemente
    raccomandato per parsing robusto quando il PDF non ha layout tabulare.
    Restituisce dict vuoto se il fetch o il parsing falliscono.
    """
    url = lnp_pdf_url(league_path, season, girone_letter)
    if not url:
        return {}

    print(f"  📄 Fetch PDF calendario LNP: {url}")
    pdf_bytes = fetch_pdf_bytes(url)
    if not pdf_bytes:
        return {}
    if not pdf_bytes.startswith(b"%PDF"):
        print(f"  ⚠️  Risposta non è un PDF (magic: {pdf_bytes[:8]!r})")
        return {}

    text = extract_pdf_text(pdf_bytes)
    if not text:
        print(f"  ⚠️  Impossibile estrarre testo dal PDF")
        return {}

    round_map = parse_lnp_pdf_calendar(text, known_teams=known_teams)
    if not round_map:
        print(f"  ⚠️  Parsing PDF non ha prodotto entry")
        return {}

    rounds = set(round_map.values())
    print(f"  ✅ PDF parsato: {len(round_map)} partite, "
          f"round {min(rounds)}..{max(rounds)} ({len(rounds)} giornate)")
    return round_map


def _team_tokens(name_norm):
    """Estrae token significativi (≥4 char) da un nome squadra normalizzato."""
    return {w for w in name_norm.split() if len(w) >= 4}


def _teams_match(name_a, name_b):
    """
    Verifica se due nomi squadra normalizzati si riferiscono alla stessa squadra.
    Gestisce i cambi di sponsor/denominazione:
      "consultinvest loreto pesaro" ↔ "loreto basket pesaro"  (condividono "loreto", "pesaro")
      "raggisolaris faenza" ↔ "tema sinergie faenza"  (condividono "faenza")
      "verodol cbd pielle livorno" ↔ "pielle livorno"  (substring + tokens)

    Regole (in ordine):
    1. Match esatto → True
    2. Substring (una contenuta nell'altra) → True
    3. ≥2 token significativi (≥4 char) in comune → True
    4. ≥1 token significativo (≥5 char) in comune → True
    """
    if name_a == name_b:
        return True
    if name_a in name_b or name_b in name_a:
        return True
    ta = _team_tokens(name_a)
    tb = _team_tokens(name_b)
    shared = ta & tb
    if len(shared) >= 2:
        return True
    # 1 token lungo (≥5) = tipicamente la città (Faenza, Chiusi, Ravenna)
    if any(len(t) >= 5 for t in shared):
        return True
    return False


def round_for_match(pdf_round_map, home, away):
    """
    Cerca il round di una partita nel pdf_round_map (chiavi normalizzate).

    Gestisce le discrepanze tra nomi squadra nel PDF (pubblicato a luglio
    con i nomi ufficiali) e quelli nelle pagine LNP HTML (aggiornati con
    i nuovi sponsor durante la stagione):
    - PDF: "Loreto Basket Pesaro"  →  LNP: "Consultinvest Loreto Pesaro"
    - PDF: "Raggisolaris Faenza"   →  LNP: "Tema Sinergie Faenza"
    - PDF: "Pielle Livorno"        →  LNP: "Verodol CBD Pielle Livorno"
    """
    if not pdf_round_map:
        return None
    h_n = normalise(home)
    a_n = normalise(away)

    # Match esatto
    if (h_n, a_n) in pdf_round_map:
        return pdf_round_map[(h_n, a_n)]

    # Match fuzzy con token overlap
    for (ph, pa), r in pdf_round_map.items():
        if _teams_match(h_n, ph) and _teams_match(a_n, pa):
            return r

    return None


# ================================================================
# DOMINO API — RISULTATI IN TEMPO REALE
# ================================================================

def domino_season_code(season):
    """'2025-26' → 'x2526'"""
    try:
        y1 = int(season.split("-")[0])
        y2_short = season.split("-")[1]
        return f"x{str(y1)[-2:]}{y2_short}"
    except (ValueError, IndexError):
        return None


def fetch_domino_scores(league_path, girone_letter, season, rounds):
    """
    Fetcha i risultati da Domino API per le giornate specificate.
    Restituisce dict {(home_norm, away_norm): (sh, sa)} per partite finite.
    `rounds` = lista/set di numeri di round da fetchare.
    """
    girone_key = (girone_letter or "").lower() or None
    code = DOMINO_LEAGUE_CODES.get((league_path, girone_key))
    if not code:
        return {}
    year = domino_season_code(season)
    if not year:
        return {}

    results = {}
    for rnd in rounds:
        url = (f"https://lnpstat.domino.it/getstatisticsfiles"
               f"?task=schedule&year={year}&league={code}&round={rnd}")
        raw = fetch(url, timeout=5)
        if not raw:
            continue
        try:
            games = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for g in games:
            if g.get("game_status") != "finished":
                continue
            try:
                sh = int(g["score_home"])
                sa = int(g["score_away"])
            except (ValueError, KeyError, TypeError):
                continue
            hn = normalise(g.get("teamname_home", ""))
            an = normalise(g.get("teamname_away", ""))
            if hn and an:
                results[(hn, an)] = (sh, sa)

    return results


def build_round_map(all_girone_matches):
    """
    Costruisce una mappa date→round_di_campionato dal calendario completo
    del girone.

    ALGORITMO IN DUE FASI:

    FASE 1 — Prima passata (può sovra-segmentare):
    Doppia regola per identificare confini di round preliminari:
    a) SQUADRA RIPETUTA: se una delle due squadre ha già giocato nel round
       in corso → nuovo round
    b) INTERVALLO TEMPORALE: se la data corrente è > 3 giorni dopo la prima
       data del round → nuovo round
    Questa fase è semplice ma sovra-segmenta in presenza di recuperi/anticipi
    isolati: una partita di lunedì recuperata produce un mini-round da 1
    partita, poi il weekend successivo apre un altro round → scarto +1.

    FASE 2 — Consolidamento globale:
    Un "round vero" del girone B (19 squadre) ha 9 partite (1 squadra riposa).
    I round con poche partite sono "fantasma" da fondere col vicino.

    Strategia di fusione iterativa:
    - Per ogni round "piccolo" (≤3 partite), prova a fonderlo col round
      successivo o precedente
    - Fusione possibile solo se nessuna squadra del round piccolo è già
      presente nel round target (regola fondamentale: 1 squadra/round)
    - Preferisce fusione col successivo (la partita di recupero appartiene
      logicamente al weekend "in cui dovrebbe stare", che spesso è dopo)
    - Ripeti finché non ci sono più fusioni possibili
    - Rinumera i round consecutivi alla fine

    Restituisce dict {date_str: round_int}.
    """
    if not all_girone_matches:
        return {}

    MAX_ROUND_SPAN_DAYS = 3
    SMALL_ROUND_THRESHOLD = 3  # round con ≤3 partite sono candidati a fusione

    # === Deduplica partite ===
    seen = set()
    unique = []
    for m in all_girone_matches:
        if not m.get("date") or not m.get("home") or not m.get("away"):
            continue
        key = (m["date"], normalise(m["home"]), normalise(m["away"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(m)

    unique.sort(key=lambda x: (x["date"], x.get("time") or "00:00"))

    # === FASE 1: prima passata ===
    # Per ogni partita: round_id provvisorio + set squadre coinvolte
    match_round = []  # list of (match_dict, provisional_round)
    current_round = 1
    teams_in_current_round = set()
    round_start_date = None

    for m in unique:
        h_n = normalise(m["home"])
        a_n = normalise(m["away"])
        m_date = datetime.strptime(m["date"], "%Y-%m-%d").date()

        team_repeated = (h_n in teams_in_current_round or
                         a_n in teams_in_current_round)
        time_exceeded = (round_start_date is not None and
                         (m_date - round_start_date).days > MAX_ROUND_SPAN_DAYS)

        if team_repeated or time_exceeded:
            current_round += 1
            teams_in_current_round = set()
            round_start_date = None

        if round_start_date is None:
            round_start_date = m_date

        teams_in_current_round.add(h_n)
        teams_in_current_round.add(a_n)
        match_round.append((m, current_round))

    # === FASE 2: consolidamento ===
    # Costruisci struttura: round_id → set di squadre + lista partite + first_date
    rounds = {}
    for m, r in match_round:
        m_date = datetime.strptime(m["date"], "%Y-%m-%d").date()
        if r not in rounds:
            rounds[r] = {"teams": set(), "matches": [], "first_date": m_date}
        rounds[r]["teams"].add(normalise(m["home"]))
        rounds[r]["teams"].add(normalise(m["away"]))
        rounds[r]["matches"].append(m)
        if m_date < rounds[r]["first_date"]:
            rounds[r]["first_date"] = m_date

    def can_merge(src_id, dst_id):
        """Verifica se i round src_id e dst_id possono fondersi (no team in conflitto)."""
        if src_id == dst_id or src_id not in rounds or dst_id not in rounds:
            return False
        return len(rounds[src_id]["teams"] & rounds[dst_id]["teams"]) == 0

    def merge(src_id, dst_id):
        """Sposta tutte le partite di src_id in dst_id."""
        rounds[dst_id]["teams"] |= rounds[src_id]["teams"]
        rounds[dst_id]["matches"].extend(rounds[src_id]["matches"])
        if rounds[src_id]["first_date"] < rounds[dst_id]["first_date"]:
            rounds[dst_id]["first_date"] = rounds[src_id]["first_date"]
        del rounds[src_id]

    # Iterazione greedy: ad ogni passo trova il round più piccolo e prova
    # a fonderlo con il candidato più vicino temporalmente (compatibile).
    # Continua finché ci sono fusioni possibili.
    max_iter = 200
    while max_iter > 0:
        max_iter -= 1
        # Trova tutti i round "piccoli" (≤ soglia)
        small_ids = [
            r_id for r_id, info in rounds.items()
            if len(info["matches"]) <= SMALL_ROUND_THRESHOLD
        ]
        if not small_ids:
            break

        # Per ogni piccolo, calcola il miglior target = round compatibile più
        # vicino temporalmente (escluso se stesso)
        best_merge = None  # (src_id, dst_id, distance_days)
        for src_id in small_ids:
            src_date = rounds[src_id]["first_date"]
            best_target = None
            best_distance = None
            for dst_id, info in rounds.items():
                if dst_id == src_id:
                    continue
                if not can_merge(src_id, dst_id):
                    continue
                dist = abs((info["first_date"] - src_date).days)
                if best_distance is None or dist < best_distance:
                    best_distance = dist
                    best_target = dst_id
            if best_target is not None:
                if best_merge is None or best_distance < best_merge[2]:
                    best_merge = (src_id, best_target, best_distance)

        if best_merge is None:
            break  # nessuna fusione possibile

        merge(best_merge[0], best_merge[1])

    # === Rinumerazione cronologica ===
    # Dopo le fusioni, gli ID round non sono più consecutivi né
    # necessariamente in ordine cronologico. Riordino per first_date
    # e rinumero 1..N.
    sorted_round_ids = sorted(rounds.keys(),
                              key=lambda r: rounds[r]["first_date"])
    renumber = {old: new for new, old in enumerate(sorted_round_ids, start=1)}

    # Costruisci la mappa finale date → round
    round_map = {}
    for old_id in sorted_round_ids:
        new_id = renumber[old_id]
        for m in rounds[old_id]["matches"]:
            if m["date"] not in round_map:
                round_map[m["date"]] = new_id
            else:
                round_map[m["date"]] = min(round_map[m["date"]], new_id)

    return round_map


def find_team_in_standings(standings_list, team_aliases):
    """Cerca una squadra tracciata nella classifica completa."""
    aliases_norm = [normalise(a) for a in team_aliases if a]
    for t in standings_list:
        tn = normalise(t["name"])
        sn = slug_to_normalised(t["slug"])
        for an in aliases_norm:
            if not an:
                continue
            if (an == tn or an in tn or tn in an or
                    an == sn or an in sn or sn in an):
                return t
    return None


# ================================================================
# AGGIORNAMENTO PARTITE IN CASA (data.json)
# ================================================================

def update_home_matches(matches, team_key, team_aliases, lnp_matches):
    """
    Aggiorna date, orari e risultati delle partite IN CASA di una squadra.
    Le partite playoff/play-in eventualmente aggiunte manualmente vengono
    aggiornate solo se LNP le pubblica con la stessa data o lo stesso
    avversario riconoscibile.
    """
    aliases_norm = [normalise(a) for a in team_aliases if a]
    updated = 0

    # Solo le partite LNP in cui la nostra squadra gioca in casa
    lnp_home = []
    for lm in lnp_matches:
        h_n = normalise(lm["home"])
        if any(an in h_n or h_n in an for an in aliases_norm):
            lnp_home.append(lm)

    for m in matches:
        if m.get("team") != team_key:
            continue

        # Match per data esatta, fallback per nome avversario
        target = None
        m_away_n = normalise(m.get("away", ""))
        for lm in lnp_home:
            if lm["date"] == m["date"]:
                target = lm
                break
        if not target and m_away_n:
            for lm in lnp_home:
                lm_away_n = normalise(lm.get("away", ""))
                if lm_away_n and (m_away_n in lm_away_n or lm_away_n in m_away_n):
                    target = lm
                    break

        if not target:
            continue

        changed = False
        # Aggiorna data e orario per partite future (sh ancora None)
        if m.get("sh") is None:
            if target["date"] != m["date"]:
                print(f"  📅 [{team_key}] {m['home']} vs {m['away']}: "
                      f"{m['date']} → {target['date']}")
                m["date"] = target["date"]
                changed = True
            if target["time"] and target["time"] != m.get("time"):
                print(f"  🕐 [{team_key}] {m['home']} vs {m['away']}: "
                      f"orario → {target['time']}")
                m["time"] = target["time"]
                changed = True

        # Aggiorna risultato per partite passate
        if m.get("sh") is None and target.get("sh") is not None:
            m["sh"] = target["sh"]
            m["sa"] = target["sa"]
            print(f"  ✅ [{team_key}] {m['home']} vs {m['away']}: "
                  f"{target['sh']}-{target['sa']}")
            changed = True

        if changed:
            updated += 1

    return updated


def detect_phase(round_num, team_pos, match_date=None, regular_end_date=None):
    """
    Inferisce la fase di una partita.

    Doppio check:
    1. round_num: round 1-38 = regular, 39+ = postseason.
    2. match_date: se la data è oltre `regular_end_date`, è postseason
       a prescindere dal round. Necessario perché build_round_map
       (fallback) per le partite playoff può restituire round ancora
       ≤38 (l'algoritmo conta dall'inizio della stagione e non sa
       distinguere recuperi da playoff).

    `regular_end_date` viene calcolato runtime in update_in_season
    dall'N-esima partita LNP della squadra (N = N_REGULAR_GAMES_BY_LEAGUE).
    Se None (es. regular ancora in corso, calendario incompleto), il
    check sulla data viene saltato e si usa solo il round.
    """
    REGULAR_LIMIT = 38

    is_postseason = round_num > REGULAR_LIMIT
    if not is_postseason and match_date and regular_end_date \
            and match_date > regular_end_date:
        is_postseason = True

    if not is_postseason:
        return "regular"
    if isinstance(team_pos, int) and 7 <= team_pos <= 12:
        return "playin"
    return "playoff"


def auto_insert_new_home_matches(matches, team_key, team_aliases,
                                 lnp_matches, team_pos,
                                 pdf_round_map=None, date_round_map=None,
                                 regular_end_date=None):
    """
    Aggiunge a `matches` le partite di CASA presenti in LNP ma non ancora
    in data.json. Funziona per:
    - Recuperi infrasettimanali aggiunti durante la regular
    - Partite di postseason (playoff, play-in) quando LNP le pubblica

    DEDUPLICAZIONE A DUE LIVELLI per evitare falsi positivi quando LNP
    riporta date diverse dalla nostra (anticipi, recuperi, formato cella):
    1. Match per (data, avversario_normalizzato) — caso normale
    2. Match per solo avversario_normalizzato entro ±10 giorni — copre
       il caso "stessa partita, data diversa"

    Round vero (giornata di campionato) determinato in priorità:
    1. pdf_round_map[(home_n, away_n)] — fonte ufficiale LNP
    2. date_round_map[date] — fallback algoritmo basato su date
    3. Indice cronologico nell'array LNP della squadra — ultimo fallback

    ID auto-generati:
    - Regular: v01..v38, l01..l38 (prefisso = prima lettera del team_key)
    - Postseason: v_po_r39, v_po_r40, v_pi_r39, ...
    """
    if pdf_round_map is None:
        pdf_round_map = {}
    if date_round_map is None:
        date_round_map = {}
    aliases_norm = [normalise(a) for a in team_aliases if a]
    inserted = 0
    existing_ids = {m.get("id") for m in matches}

    # Indici delle partite esistenti per quel team
    # - existing_by_date_away: chiave forte (data + avversario)
    # - existing_by_away: chiave debole (solo avversario), con lista date
    existing_by_date_away = set()
    existing_by_away = {}  # away_norm → list[date_str]
    for m in matches:
        if m.get("team") != team_key:
            continue
        away_n = normalise(m.get("away", ""))
        date_s = m.get("date", "")
        if away_n:
            existing_by_date_away.add((date_s, away_n))
            existing_by_away.setdefault(away_n, []).append(date_s)

    def is_duplicate(lm_date, lm_away_n, is_postseason=False):
        """Verifica se una partita LNP è già nel data.json, anche con data shiftata.

        In postseason (playoff/playin) si applica solo il match forte
        (data + avversario esatti), perché in una serie best-of-5 le
        partite vs lo stesso avversario si giocano a 2-3 giorni di
        distanza (es. G1 e G2 in casa) e il dedup ±10 giorni le
        scarterebbe come falsi duplicati.
        """
        if not lm_away_n:
            return False
        # Match forte
        if (lm_date, lm_away_n) in existing_by_date_away:
            return True
        # In postseason fermarsi qui: G1/G2/G5 stesso avversario sono partite distinte
        if is_postseason:
            return False
        # Match debole: stesso avversario entro ±10 giorni (solo regular)
        for existing_date in existing_by_away.get(lm_away_n, []):
            try:
                d1 = datetime.strptime(lm_date, "%Y-%m-%d").date()
                d2 = datetime.strptime(existing_date, "%Y-%m-%d").date()
                if abs((d1 - d2).days) <= 10:
                    return True
            except Exception:
                continue
        # Match per substring sull'avversario (es. "Latina" vs "Benacquista Latina")
        for ex_away_n in existing_by_away:
            if not ex_away_n:
                continue
            if len(ex_away_n) >= 4 and len(lm_away_n) >= 4:
                if ex_away_n in lm_away_n or lm_away_n in ex_away_n:
                    for existing_date in existing_by_away[ex_away_n]:
                        try:
                            d1 = datetime.strptime(lm_date, "%Y-%m-%d").date()
                            d2 = datetime.strptime(existing_date, "%Y-%m-%d").date()
                            if abs((d1 - d2).days) <= 10:
                                return True
                        except Exception:
                            continue
        return False

    # Filtra le partite LNP in cui la squadra gioca in casa
    lnp_home = []
    for lm in lnp_matches:
        h_n = normalise(lm["home"])
        if any(an in h_n or h_n in an for an in aliases_norm):
            lnp_home.append(lm)

    for lm in lnp_home:
        lm_away_n = normalise(lm.get("away", ""))

        # Round e fase calcolati PRIMA del dedup, perché in postseason
        # il dedup deve essere più stretto (best-of-5: stesso avversario
        # in pochi giorni è normale, non un duplicato).
        real_round = round_for_match(pdf_round_map, lm.get("home", ""), lm.get("away", ""))
        if real_round is None:
            real_round = date_round_map.get(lm["date"])
        if real_round is None:
            try:
                real_round = lnp_matches.index(lm) + 1
            except ValueError:
                real_round = len(matches) + 1

        phase = detect_phase(real_round, team_pos, lm["date"], regular_end_date)
        is_postseason = phase != "regular"

        if is_duplicate(lm["date"], lm_away_n, is_postseason):
            continue

        # Genera ID univoco
        prefix = team_key[0]
        if phase == "regular":
            new_id = f"{prefix}{real_round:02d}"
        elif phase == "playin":
            new_id = f"{prefix}_pi_r{real_round}"
        else:
            new_id = f"{prefix}_po_r{real_round}"

        # Evita collisioni di ID
        n = 1
        base_id = new_id
        while new_id in existing_ids:
            n += 1
            new_id = f"{base_id}_{n}"
        existing_ids.add(new_id)

        new_match = {
            "id": new_id,
            "team": team_key,
            "phase": phase,
            "round": real_round,
            "date": lm["date"],
            "time": lm["time"],
            "home": lm["home"],
            "away": lm["away"],
            "sh": lm.get("sh"),
            "sa": lm.get("sa"),
        }
        matches.append(new_match)
        # Aggiorna gli indici per le iterazioni successive nello stesso run
        existing_by_date_away.add((lm["date"], lm_away_n))
        existing_by_away.setdefault(lm_away_n, []).append(lm["date"])

        inserted += 1
        score_info = (f" {lm['sh']}-{lm['sa']}"
                      if lm.get("sh") is not None else "")
        print(f"  ➕ [{team_key}] NUOVA {phase} R{real_round} "
              f"{lm['date']} {lm['time']} vs {lm['away']}{score_info}")

    return inserted


# ================================================================
# MAIN UPDATE LOGIC
# ================================================================

def update_in_season(matches, config, standings):
    initial_snap = json.dumps(standings, sort_keys=True)
    updated = 0
    new_standings = {k: dict(v) for k, v in standings.items()}

    # Cache classifica per league_path: se più squadre seguite sono nello
    # stesso girone, calcoliamo la classifica completa una sola volta.
    classifica_cache = {}

    # Sanity check globale: se TUTTE le squadre vengono saltate per
    # protezione (parse LNP sospetto), abortiamo per non corrompere
    # data.json. Il main rileverà il sentinel -1 ed uscirà con codice 1
    # → GitHub Actions invierà notifica via email.
    teams_total = len(TRACKED_TEAMS)
    teams_safety_skipped = 0

    for team_key, team_info in TRACKED_TEAMS.items():
        slug = team_info["slug"]
        aliases = list(team_info["name_aliases"])

        # Aggiungi alias da config (data.json) se presenti
        cfg_aliases = config.get("teams", {}).get(team_key, {}).get("name_aliases")
        if cfg_aliases:
            for a in cfg_aliases:
                if a not in aliases:
                    aliases.append(a)

        print(f"\n  🔍 [{team_key}] discovery lega per slug '{slug}'...")
        league_path, html = discover_team_league(slug)
        if not league_path:
            print(f"  ⚠️  [{team_key}] nessuna pagina LNP trovata")
            continue
        print(f"  📡 [{team_key}] lega: {league_path}")

        # Auto-aggiornamento del campo serie nel config
        league_label = LEAGUE_LABELS.get(league_path, league_path)
        cfg_team = config.setdefault("teams", {}).setdefault(team_key, {})
        if cfg_team.get("serie") != league_label:
            old = cfg_team.get("serie", "?")
            print(f"  🔄 [{team_key}] cambio lega rilevato: {old} → {league_label}")
            cfg_team["serie"] = league_label
            updated += 1

        # Auto-aggiornamento URL classifica ufficiale LNP
        serie_id = LEAGUE_SERIE_IDS.get(league_path)
        if serie_id:
            classifica_url = f"https://www.legapallacanestro.com/serie/{serie_id}/classifica"
            if config.get("classifica_url") != classifica_url:
                config["classifica_url"] = classifica_url
                updated += 1

        # Parse calendario squadra
        lnp_matches = parse_lnp_calendar(html)
        if not lnp_matches:
            print(f"  ⚠️  [{team_key}] calendario LNP vuoto")
            teams_safety_skipped += 1
            continue
        lnp_matches = filter_season(lnp_matches, config.get("season"))
        print(f"  📋 [{team_key}] {len(lnp_matches)} partite nel calendario LNP")

        # Sanity check: lnp_matches deve essere ≥ partite home già nel
        # data.json (LNP riporta sia home che away, quindi tot LNP ≥ tot
        # home esistenti). Se è meno, è probabile un parse fallito
        # (es. cambio HTML LNP). Skip per non corrompere data.json.
        existing_home = sum(1 for m in matches if m.get("team") == team_key)
        if existing_home > 0 and len(lnp_matches) < existing_home:
            print(f"  🚨 [{team_key}] SAFETY SKIP: lnp_matches={len(lnp_matches)} "
                  f"< home esistenti={existing_home}. Parse sospetto.")
            teams_safety_skipped += 1
            continue

        # Aggiorna partite in casa nel data.json
        updated += update_home_matches(matches, team_key, aliases, lnp_matches)

        # W/L/pts da calendario completo
        w, l, pts = calc_team_stats(lnp_matches, aliases)
        if w + l > 0:
            new_standings.setdefault(team_key, {})
            new_standings[team_key]["w"] = w
            new_standings[team_key]["l"] = l
            new_standings[team_key]["pts"] = pts
            print(f"  📊 [{team_key}] {w}V-{l}P = {pts}pt")

        # Discovery girone + classifica completa (con cache per lega)
        if league_path not in classifica_cache:
            print(f"  🔎 [{team_key}] discovery girone su {league_path}...")
            opponents = extract_opponents(lnp_matches, aliases)
            print(f"     {len(opponents)} avversari distinti")
            girone_slugs = discover_girone_slugs(league_path, opponents, slug)
            print(f"     {len(girone_slugs)} squadre identificate nel girone")

            if len(girone_slugs) >= 4:
                print(f"  📥 Calcolo classifica completa girone...")
                full, all_girone_matches = compute_full_standings(
                    league_path, girone_slugs, season=config.get("season")
                )

                # Round map: prima fonte è il PDF ufficiale LNP (autoritativo).
                # Fallback: algoritmo basato su date (legacy, può sbagliare ±5)
                season = config.get("season", "")
                girone_letter = (cfg_team.get("girone") or "").lower() or None
                # Nomi squadra dal calcolo classifica (usati come vocabolario
                # per il parser del PDF, dove home/away sono separati da
                # spazi singoli)
                known_teams = [t["name"] for t in full] if full else None
                pdf_round_map = fetch_lnp_pdf_round_map(
                    league_path, season, girone_letter, known_teams
                )
                date_round_map = build_round_map(all_girone_matches)

                classifica_cache[league_path] = {
                    "standings": full,
                    "pdf_round_map": pdf_round_map,
                    "date_round_map": date_round_map,
                    "all_girone_matches": all_girone_matches,
                }
                src = "PDF" if pdf_round_map else "date-based"
                pdf_count = len(pdf_round_map)
                date_count = len(date_round_map)
                print(f"  ✅ Classifica: {len(full)} squadre — round_map: "
                      f"{pdf_count or date_count} entries ({src})")
            else:
                print(f"  ⚠️  Girone troppo piccolo, skip classifica")
                classifica_cache[league_path] = None

        cache_entry = classifica_cache.get(league_path)
        full = cache_entry["standings"] if cache_entry else None
        pdf_round_map = cache_entry["pdf_round_map"] if cache_entry else {}
        date_round_map = cache_entry["date_round_map"] if cache_entry else {}

        def lookup_round(m_date, m_home, m_away):
            """Cerca il round vero: prima nel PDF (per coppia), poi per data."""
            r = round_for_match(pdf_round_map, m_home, m_away)
            if r is not None:
                return r
            return date_round_map.get(m_date)

        team_pos = None
        if full:
            entry = find_team_in_standings(full, aliases)
            if entry:
                new_standings[team_key]["pos"] = entry["pos"]
                # Allinea anche w/l/pts ai valori dalla classifica completa
                new_standings[team_key]["w"] = entry["w"]
                new_standings[team_key]["l"] = entry["l"]
                new_standings[team_key]["pts"] = entry["pts"]
                team_pos = entry["pos"]
                print(f"  🏆 [{team_key}] pos: {entry['pos']}° su {len(full)} "
                      f"({entry['w']}V-{entry['l']}P, {entry['pts']}pt)")
            else:
                print(f"  ⚠️  [{team_key}] non trovata nella classifica calcolata")

        # Aggiorna i round delle partite esistenti (correzione retroattiva)
        if pdf_round_map or date_round_map:
            corrected = 0
            for m in matches:
                if m.get("team") != team_key:
                    continue
                real_round = lookup_round(
                    m.get("date"), m.get("home", ""), m.get("away", "")
                )
                if real_round and m.get("round") != real_round:
                    m["round"] = real_round
                    corrected += 1
            if corrected:
                print(f"  🔢 [{team_key}] round corretti: {corrected}")
                updated += corrected

        # Auto-insert: nuove partite di casa (recuperi, postseason)
        # Eseguito DOPO il calcolo di pos e round_map.
        # regular_end_date: dedotto dall'N-esima partita LNP cronologica
        # (N = numero partite regular della lega). Tutto ciò che è dopo
        # questa data è postseason, anche se build_round_map dà round ≤38.
        n_regular = N_REGULAR_GAMES_BY_LEAGUE.get(league_path, 36)
        regular_end_date = None
        if len(lnp_matches) >= n_regular:
            regular_end_date = lnp_matches[n_regular - 1].get("date")
        inserted = auto_insert_new_home_matches(
            matches, team_key, aliases, lnp_matches, team_pos,
            pdf_round_map, date_round_map, regular_end_date
        )
        if inserted:
            updated += inserted

        # Fill punteggi mancanti — fonte 1: Domino API (tempo reale)
        missing = [m for m in matches
                   if m.get("team") == team_key and m.get("sh") is None
                   and m.get("date", "9") < datetime.now().strftime("%Y-%m-%d")]
        if missing:
            missing_rounds = {m["round"] for m in missing if m.get("round")}
            if missing_rounds:
                girone_letter = (cfg_team.get("girone") or "").lower() or None
                domino = fetch_domino_scores(
                    league_path, girone_letter,
                    config.get("season", ""), missing_rounds
                )
                if domino:
                    for m in missing:
                        key = (normalise(m.get("home", "")), normalise(m.get("away", "")))
                        score = domino.get(key)
                        if not score:
                            # Fuzzy match
                            for (dh, da), s in domino.items():
                                if _teams_match(key[0], dh) and _teams_match(key[1], da):
                                    score = s
                                    break
                        if score:
                            m["sh"], m["sa"] = score
                            print(f"  ⚡ [{team_key}] {m['away']}: "
                                  f"{score[0]}-{score[1]} (Domino API)")
                            updated += 1

        # Fill punteggi mancanti — fonte 2: girone completo (19 pagine squadra)
        girone_matches = (cache_entry or {}).get("all_girone_matches", [])
        if girone_matches:
            filled = 0
            for m in matches:
                if m.get("team") != team_key or m.get("sh") is not None:
                    continue
                m_home_n = normalise(m.get("home", ""))
                m_away_n = normalise(m.get("away", ""))
                for gm in girone_matches:
                    gh_n = normalise(gm.get("home", ""))
                    ga_n = normalise(gm.get("away", ""))
                    if gm.get("sh") is None:
                        continue
                    if (_teams_match(m_home_n, gh_n) and _teams_match(m_away_n, ga_n)):
                        m["sh"] = gm["sh"]
                        m["sa"] = gm["sa"]
                        print(f"  ✅ [{team_key}] {m['away']}: "
                              f"{gm['sh']}-{gm['sa']} (da girone)")
                        filled += 1
                        break
            if filled:
                updated += filled

    # Conta cambio standings come aggiornamento (oltre a quelli già contati)
    if json.dumps(new_standings, sort_keys=True) != initial_snap:
        updated += 1

    # Safety check globale: se TUTTE le squadre saltate per protezione,
    # ritorna sentinel -1. main() abortirà la scrittura di data.json
    # ed uscirà con codice 1 (GitHub Actions invierà email).
    if teams_total > 0 and teams_safety_skipped == teams_total:
        print(f"\n🚨 SAFETY ABORT: tutte le {teams_total} squadre saltate.")
        print(f"   Probabile cambio HTML LNP o parse fallito.")
        print(f"   data.json NON sarà aggiornato.")
        return -1, new_standings

    return updated, new_standings


# ================================================================
# FUORI STAGIONE — discovery nuova stagione
# ================================================================

def bootstrap_new_season(config, current_season):
    """
    Genera una nuova struttura matches+standings da zero leggendo le pagine
    squadra LNP. Usato a inizio stagione successiva.

    SOGLIA DI SICUREZZA: pretende ≥ MIN_MATCHES_THRESHOLD partite per ogni
    squadra seguita. Sotto la soglia, considera il calendario "provvisorio"
    e non sovrascrive nulla. Questo evita che un fetch parziale o un
    calendario in costruzione cancelli i dati buoni.

    Restituisce (new_matches, new_standings, new_season_label) oppure
    (None, None, None) se il bootstrap non è sicuro.
    """
    MIN_MATCHES_THRESHOLD = 30  # ≥30 partite/squadra = stagione completa

    print("\n🔍 Controllo nuova stagione...")
    discovered = {}

    for team_key, info in TRACKED_TEAMS.items():
        slug = info["slug"]
        league_path, html = discover_team_league(slug)
        if not league_path:
            print(f"  ⏳ [{team_key}] non ancora disponibile su LNP")
            return None, None, None

        lnp_matches = parse_lnp_calendar(html)
        if len(lnp_matches) < MIN_MATCHES_THRESHOLD:
            print(f"  ⏳ [{team_key}] solo {len(lnp_matches)} partite "
                  f"(soglia: {MIN_MATCHES_THRESHOLD}) → calendario provvisorio")
            return None, None, None

        # Verifica che TUTTE le partite siano della nuova stagione
        # (le date devono essere posteriori alla fine della stagione corrente)
        years = {m["date"][:4] for m in lnp_matches}
        print(f"  ✅ [{team_key}] {len(lnp_matches)} partite su LNP "
              f"(anni: {sorted(years)})")

        discovered[team_key] = {
            "league_path": league_path,
            "lnp_matches": lnp_matches,
            "aliases": list(info["name_aliases"]),
        }

    if len(discovered) < len(TRACKED_TEAMS):
        print("  ⚠️  Non tutte le squadre seguite hanno calendario completo")
        return None, None, None

    print("\n🆕 Bootstrap nuova stagione: tutte le condizioni verificate")

    # Determina la nuova stagione dalle date trovate
    all_dates = []
    for d in discovered.values():
        all_dates.extend(m["date"] for m in d["lnp_matches"])
    if not all_dates:
        return None, None, None

    min_year = min(int(d[:4]) for d in all_dates)
    max_year = max(int(d[:4]) for d in all_dates)
    new_season = f"{min_year}-{str(max_year)[-2:]}"
    print(f"  📅 Stagione rilevata: {new_season}")

    # Filtra partite alla stagione rilevata (pagine LNP possono includere la precedente)
    for d in discovered.values():
        d["lnp_matches"] = filter_season(d["lnp_matches"], new_season)

    # Calcola round_map dal girone completo (necessario per ID/round corretti).
    # Priorità: PDF ufficiale LNP (autoritativo) > algoritmo basato su date.
    # Cache per league_path: se più squadre seguite sono nello stesso girone,
    # discovery e round_map vengono fatti una sola volta.
    pdf_round_map_by_league = {}
    date_round_map_by_league = {}
    for team_key, d in discovered.items():
        lp = d["league_path"]
        if lp in pdf_round_map_by_league:
            continue
        print(f"  🔎 Discovery girone su {lp} per round_map...")
        opponents = extract_opponents(d["lnp_matches"], d["aliases"])
        girone_slugs = discover_girone_slugs(lp, opponents, TRACKED_TEAMS[team_key]["slug"])
        print(f"     {len(girone_slugs)} squadre identificate")
        if len(girone_slugs) >= 4:
            print(f"  📥 Fetch calendari completi del girone...")
            full, all_girone_matches = compute_full_standings(lp, girone_slugs, season=new_season)
            date_round_map_by_league[lp] = build_round_map(all_girone_matches)
            # Tenta fetch PDF ufficiale (per girone noto da config)
            cfg_team = config.get("teams", {}).get(team_key, {})
            girone_letter = (cfg_team.get("girone") or "").lower() or None
            known_teams = [t["name"] for t in full] if full else None
            pdf_round_map_by_league[lp] = fetch_lnp_pdf_round_map(
                lp, new_season, girone_letter, known_teams
            )
            src = "PDF" if pdf_round_map_by_league[lp] else "date-based"
            pdf_n = len(pdf_round_map_by_league[lp])
            date_n = len(date_round_map_by_league[lp])
            print(f"  ✅ round_map: {pdf_n or date_n} entries ({src})")
        else:
            pdf_round_map_by_league[lp] = {}
            date_round_map_by_league[lp] = {}

    # Costruisci matches: solo partite di casa, ID basati sul round vero
    new_matches = []
    for team_key, d in discovered.items():
        aliases_norm = [normalise(a) for a in d["aliases"] if a]
        prefix = team_key[0]
        pdf_rm = pdf_round_map_by_league.get(d["league_path"], {})
        date_rm = date_round_map_by_league.get(d["league_path"], {})
        home_count = 0
        for lm in d["lnp_matches"]:
            h_n = normalise(lm["home"])
            is_home = any(an in h_n or h_n in an for an in aliases_norm)
            if not is_home:
                continue
            home_count += 1
            # Priorità: PDF (per coppia) → date_map → fallback progressivo
            real_round = round_for_match(pdf_rm, lm.get("home", ""), lm.get("away", ""))
            if real_round is None:
                real_round = date_rm.get(lm["date"])
            if real_round is None:
                real_round = home_count
            new_matches.append({
                "id": f"{prefix}{real_round:02d}",
                "team": team_key,
                "phase": "regular",
                "round": real_round,
                "date": lm["date"],
                "time": lm["time"],
                "home": lm["home"],
                "away": lm["away"],
                "sh": lm.get("sh"),
                "sa": lm.get("sa"),
            })
        print(f"  📋 [{team_key}] {home_count} partite di casa")

    # Standings azzerati (la prossima run normale calcolerà quelli reali)
    new_standings = {
        tk: {"pos": "-", "pts": 0, "w": 0, "l": 0}
        for tk in TRACKED_TEAMS
    }

    return new_matches, new_standings, new_season


# ================================================================
# MAIN
# ================================================================

def main():
    print(f"\n🏀 Roma Basket Updater v8.7 — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 55)

    data_path = Path("data.json")
    if data_path.exists():
        with open(data_path) as f:
            current = json.load(f)
        matches = current.get("matches", [])
        standings = current.get("standings", dict(BASE_STANDINGS))
        config = current.get("config", CONFIG_DEFAULT)
        # Retrocompatibilità config: integra campi mancanti
        for tk, td in CONFIG_DEFAULT["teams"].items():
            if tk not in config.get("teams", {}):
                config.setdefault("teams", {})[tk] = td
            else:
                for f, v in td.items():
                    config["teams"][tk].setdefault(f, v)
        config.setdefault("next_season", CONFIG_DEFAULT["next_season"])
        print(f"📂 Caricato — {len(matches)} partite, "
              f"stagione {config.get('season','?')}")
    else:
        matches = []
        standings = dict(BASE_STANDINGS)
        config = dict(CONFIG_DEFAULT)
        print("📂 Primo avvio — dati base")

    today = date.today()
    all_dates = (
        [datetime.strptime(m["date"], "%Y-%m-%d").date() for m in matches]
        if matches else []
    )
    season_end = max(all_dates) if all_dates else date(2026, 6, 30)
    in_season = today <= season_end + timedelta(days=30)

    total_updated = 0
    bootstrapped = False

    # === BOOTSTRAP ON-DEMAND ===
    # Se matches è vuoto, lo script non ha nulla da aggiornare incrementalmente.
    # Triggera il bootstrap che ripopola tutto da LNP. Funziona sia in stagione
    # corrente (uso dichiarativo: "svuota matches per chiedere reset") sia
    # all'inizio di una stagione nuova.
    if not matches:
        print(f"\n🔄 matches vuoto — attivazione bootstrap on-demand")
        new_matches, new_standings, new_season = bootstrap_new_season(
            config, config.get("season", "?")
        )
        if new_matches and new_standings and new_season:
            backup_path = Path("data.json.backup")
            if data_path.exists():
                backup_path.write_text(
                    data_path.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                print(f"  💾 Backup salvato: {backup_path}")

            matches = new_matches
            standings = new_standings
            # Aggiorna season solo se diverso dall'attuale (cambio stagione vero)
            current_season = config.get("season", "?")
            if new_season != current_season:
                try:
                    start_yr = int(new_season.split("-")[0])
                    next_season_label = f"{start_yr + 1}-{str(start_yr + 2)[-2:]}"
                except Exception:
                    next_season_label = config.get("next_season", "?")
                config["season"] = new_season
                config["next_season"] = next_season_label
                print(f"  🆕 Stagione {new_season} attivata")
            else:
                print(f"  🔄 Reset stagione {new_season} (calendario ricostruito)")
            bootstrapped = True
            total_updated = len(new_matches)
        else:
            print("  ⚠️  Bootstrap fallito (calendario LNP non disponibile)")
            print("  ℹ️  Riproverà al prossimo run")
    elif in_season:
        print(f"\n📅 IN STAGIONE")
        total_updated, standings = update_in_season(matches, config, standings)
        if total_updated < 0:
            # Safety abort: data.json non va sovrascritto
            print(f"\n❌ Run abortito per safety. Exit code 1.")
            sys.exit(1)
        print(f"\n📝 Aggiornamenti: {total_updated}")
    else:
        print(f"\n💤 FUORI STAGIONE")
        new_matches, new_standings, new_season = bootstrap_new_season(
            config, config.get("season", "?")
        )
        if new_matches and new_standings and new_season:
            # SOGLIE DI SICUREZZA superate → backup + sostituzione
            backup_path = Path("data.json.backup")
            if data_path.exists():
                backup_path.write_text(
                    data_path.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                print(f"  💾 Backup salvato: {backup_path}")

            # Calcola la prossima stagione (es. 2026-27 → 2027-28)
            try:
                start_yr = int(new_season.split("-")[0])
                next_season_label = f"{start_yr + 1}-{str(start_yr + 2)[-2:]}"
            except Exception:
                next_season_label = config.get("next_season", "?")

            matches = new_matches
            standings = new_standings
            config["season"] = new_season
            config["next_season"] = next_season_label
            bootstrapped = True
            total_updated = len(new_matches)
            print(f"  🆕 Stagione {new_season} attivata "
                  f"({len(new_matches)} partite di casa)")

    output = {
        "last_updated": datetime.now().isoformat(),
        "season": config.get("season", "2025-26"),
        "config": config,
        "matches": matches,
        "standings": standings,
    }
    new_json = json.dumps(output, ensure_ascii=False, indent=2)

    # Skip scrittura se nulla è cambiato (escluso timestamp)
    # Il bootstrap salta sempre questo controllo (la nuova stagione va scritta)
    if data_path.exists() and not bootstrapped:
        old_content = data_path.read_text(encoding="utf-8")
        def strip_ts(s):
            return re.sub(r'"last_updated":\s*"[^"]*"', '"last_updated":""', s)
        if strip_ts(old_content) == strip_ts(new_json):
            print("ℹ️  Nessuna modifica reale — salto scrittura")
            print("\n💾 Invariato — nessun commit necessario")
            print("✅ Completato!\n")
            return 0

    with open(data_path, "w", encoding="utf-8") as f:
        f.write(new_json)

    print(f"\n💾 Salvato — {len(matches)} partite")
    print("✅ Completato!\n")
    return total_updated


if __name__ == "__main__":
    main()
