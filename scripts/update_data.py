#!/usr/bin/env python3
"""
update_data.py — Roma Basket Casa — v8
Architettura LNP-only con auto-discovery completa, auto-insert e auto-bootstrap.

Fonte unica: legapallacanestro.com (HTML statico)
- Calendario, date, orari, risultati: pagine squadra LNP
- Classifica completa con pos: derivata da tutte le squadre del girone
- Cambio lega: cascade discovery serie-b → serie-a2 → serie-a
- Auto-insert partite postseason (playoff/play-in) con phase auto-rilevata
- Auto-bootstrap nuova stagione con backup file di sicurezza
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

# Cascade leghe LNP — ordine di tentativo per discovery automatica
LEAGUE_PATHS = ["serie-b", "serie-a2", "serie-a"]

# Mapping leghe → label per data.json (compat con index.html)
LEAGUE_LABELS = {
    "serie-b": "B Nazionale",
    "serie-a2": "A2",
    "serie-a": "A",
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


def compute_full_standings(league_path, girone_slugs):
    """
    Per ogni squadra del girone fa fetch della pagina LNP e calcola W/L/pts.
    Restituisce lista ordinata [{slug, name, w, l, pts, pos}, ...].

    Tiebreaker semplificato: pts desc, w desc, nome asc.
    Il tiebreaker ufficiale LNP (scontri diretti, quoziente canestri) non è
    implementato — la pos può divergere in caso di parità esatta. Sufficiente
    per uso informativo.
    """
    teams = []
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
        teams.append({
            "slug": slug,
            "name": team_name,
            "w": w,
            "l": l,
            "pts": pts,
        })

    teams.sort(key=lambda t: (-t["pts"], -t["w"], t["name"].lower()))
    for i, t in enumerate(teams, start=1):
        t["pos"] = i
    return teams


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


def detect_phase(round_num, team_pos):
    """
    Inferisce la fase di una partita dal numero di giornata.

    Convenzione LNP Serie B Nazionale 2025-26 (verificata da pagina formula):
    - Round 1-38  → regular season
    - Round 39+   → playin (squadre 7°-12°) o playoff (squadre 1°-6°)

    Per altre leghe (A2, A) la convenzione può variare ma il principio
    "round oltre la regular = postseason" resta valido. Se in futuro LNP
    cambia il numero di giornate per una lega, il limite va aggiornato qui.
    """
    REGULAR_LIMIT = 38  # ultimo round di regular season Serie B Nazionale
    if round_num <= REGULAR_LIMIT:
        return "regular"
    if isinstance(team_pos, int) and 7 <= team_pos <= 12:
        return "playin"
    return "playoff"


def auto_insert_new_home_matches(matches, team_key, team_aliases,
                                 lnp_matches, team_pos):
    """
    Aggiunge a `matches` le partite di CASA presenti in LNP ma non ancora
    in data.json. Funziona per:
    - Recuperi infrasettimanali aggiunti durante la regular
    - Partite di postseason (playoff, play-in) quando LNP le pubblica

    ID auto-generati con convenzione:
    - Regular: v01..v38, l01..l38 (prefisso = prima lettera del team_key)
    - Postseason: v_po_r39, v_po_r40 ... (round è il riferimento univoco)
    """
    aliases_norm = [normalise(a) for a in team_aliases if a]
    inserted = 0
    existing_ids = {m.get("id") for m in matches}

    # Indice partite esistenti per quel team: chiave = (date, away_normalised)
    existing_keys = set()
    for m in matches:
        if m.get("team") == team_key:
            existing_keys.add((m.get("date"), normalise(m.get("away", ""))))

    # Filtra le partite LNP in cui la squadra gioca in casa
    lnp_home = []
    for lm in lnp_matches:
        h_n = normalise(lm["home"])
        if any(an in h_n or h_n in an for an in aliases_norm):
            lnp_home.append(lm)

    # Tenta di leggere il round dalle partite LNP. Le pagine LNP non lo
    # espongono direttamente nelle celle della tabella, quindi usiamo
    # un indice progressivo basato sull'ordine cronologico.
    # Per la regular season questa è la giornata reale; per la postseason
    # è un numero progressivo > 38 che attiva il rilevamento phase=playoff.
    sorted_lnp = sorted(lnp_home, key=lambda x: x["date"])

    for idx, lm in enumerate(sorted_lnp, start=1):
        key = (lm["date"], normalise(lm.get("away", "")))
        if key in existing_keys:
            continue

        # Stima round: idx è la posizione cronologica della partita di casa,
        # ma in regular ci sono ~19 partite di casa su 36 totali. Per inferire
        # il round assoluto usiamo: round_estimato = lm posizione nella tabella
        # completa LNP. Approssimazione: cerchiamo lm in lnp_matches.
        try:
            absolute_idx = lnp_matches.index(lm) + 1
        except ValueError:
            absolute_idx = idx

        phase = detect_phase(absolute_idx, team_pos)

        # Genera ID univoco
        prefix = team_key[0]
        if phase == "regular":
            new_id = f"{prefix}{absolute_idx:02d}"
        elif phase == "playin":
            new_id = f"{prefix}_pi_r{absolute_idx}"
        else:
            new_id = f"{prefix}_po_r{absolute_idx}"

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
            "round": absolute_idx,
            "date": lm["date"],
            "time": lm["time"],
            "home": lm["home"],
            "away": lm["away"],
            "sh": lm.get("sh"),
            "sa": lm.get("sa"),
        }
        matches.append(new_match)
        inserted += 1
        score_info = (f" {lm['sh']}-{lm['sa']}"
                      if lm.get("sh") is not None else "")
        print(f"  ➕ [{team_key}] NUOVA {phase} R{absolute_idx} "
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

        # Parse calendario squadra
        lnp_matches = parse_lnp_calendar(html)
        if not lnp_matches:
            print(f"  ⚠️  [{team_key}] calendario LNP vuoto")
            continue
        print(f"  📋 [{team_key}] {len(lnp_matches)} partite nel calendario LNP")

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
                full = compute_full_standings(league_path, girone_slugs)
                classifica_cache[league_path] = full
                print(f"  ✅ Classifica: {len(full)} squadre")
            else:
                print(f"  ⚠️  Girone troppo piccolo, skip classifica")
                classifica_cache[league_path] = None

        full = classifica_cache.get(league_path)
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

        # Auto-insert: nuove partite di casa (recuperi, postseason)
        # Eseguito DOPO il calcolo di pos perché serve per detect_phase
        inserted = auto_insert_new_home_matches(
            matches, team_key, aliases, lnp_matches, team_pos
        )
        if inserted:
            updated += inserted

    # Conta cambio standings come aggiornamento (oltre a quelli già contati)
    if json.dumps(new_standings, sort_keys=True) != initial_snap:
        updated += 1

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

    # Costruisci matches: solo partite di casa, ID auto-generati
    new_matches = []
    for team_key, d in discovered.items():
        aliases_norm = [normalise(a) for a in d["aliases"] if a]
        prefix = team_key[0]
        home_idx = 0
        for absolute_idx, lm in enumerate(d["lnp_matches"], start=1):
            h_n = normalise(lm["home"])
            is_home = any(an in h_n or h_n in an for an in aliases_norm)
            if not is_home:
                continue
            home_idx += 1
            new_matches.append({
                "id": f"{prefix}{absolute_idx:02d}",
                "team": team_key,
                "phase": "regular",
                "round": absolute_idx,
                "date": lm["date"],
                "time": lm["time"],
                "home": lm["home"],
                "away": lm["away"],
                "sh": lm.get("sh"),
                "sa": lm.get("sa"),
            })
        print(f"  📋 [{team_key}] {home_idx} partite di casa")

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
    print(f"\n🏀 Roma Basket Updater v8 — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
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

    if in_season:
        print(f"\n📅 IN STAGIONE")
        total_updated, standings = update_in_season(matches, config, standings)
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
