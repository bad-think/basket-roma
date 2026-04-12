#!/usr/bin/env python3
"""
update_data.py — Roma Basket Casa — Aggiornamento automatico v6
Fonti dati:
  1. LNP (legapallacanestro.com) — date, orari e risultati ufficiali
  2. pianetabasket.com — risultati e classifica (KNOWN_URLS + stima ID)
"""

import json
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime, date, timedelta
from pathlib import Path

# ================================================================
# CONFIGURAZIONE
# ================================================================
CONFIG = {
    "season": "2025-26",
    "next_season": "2026-27",
    "teams": {
        "virtus": {
            "name": "Virtus GVM Roma",
            "name_aliases": [
                "virtus gvm roma", "virtus roma", "virtus gvm roma 1960",
                "pallacanestro virtus roma"
            ],
            "serie": "B Nazionale",
            "girone": "B",
            "venue_name": "PalaTiziano – Palazzetto dello Sport",
            "venue_address": "Piazza Apollodoro 10, 00196 Roma",
            "venue_maps": "https://maps.google.com/?q=Palazzetto+dello+Sport+Piazza+Apollodoro+10+Roma"
        },
        "luiss": {
            "name": "Luiss Roma",
            "name_aliases": ["luiss roma", "luiss", "luiss basketball"],
            "serie": "B Nazionale",
            "girone": "B",
            "venue_name": "PalaTiziano – Palazzetto dello Sport",
            "venue_address": "Piazza Apollodoro 10, 00196 Roma",
            "venue_maps": "https://maps.google.com/?q=Palazzetto+dello+Sport+Piazza+Apollodoro+10+Roma"
        }
    }
}

# URL verificati per giornate già disputate
KNOWN_URLS = {
    31: "https://www.pianetabasket.com/serie-b/serie-b-nazionale-calendario-risultati-le-gare-di-lunedi-classifiche-31-giornata-2025-26-356237",
    32: "https://www.pianetabasket.com/serie-b/serie-b-nazionale-calendario-risultati-sabato-classifiche-32-giornata-2025-26-357140",
    33: "https://www.pianetabasket.com/serie-b/serie-b-nazionale-calendario-risultati-sabato-classifiche-33-giornata-2025-26-357782",
    34: "https://www.pianetabasket.com/serie-b/serie-b-nazionale-calendario-risultati-classifiche-34-giornata-2025-26-358236",
}

# ID base stimati (fallback se non si trova la pagina)
# G33=357782, incremento reale ~642 per giornata
ROUND_BASE_IDS = {
    35: 358696, 36: 359156, 37: 359616, 38: 360076,
}

LEAGUE_SOURCES = {
    "B Nazionale": {
        "pb_home":      "https://www.pianetabasket.com/serie-b/",
        "pb_section":   "/serie-b/",
        "pb_class":     "https://www.pianetabasket.com/serie-b/classifica-serie-b-nazionale-girone-b-2025-26",
        "lnp":          "https://www.legapallacanestro.com/serie/4/classifica",
        "girone_check": "girone b",
        # URL fallback stagione 2025-26: pagine giornata note con ID verificati
        "fallback_urls": [
            "https://www.pianetabasket.com/serie-b/serie-b-nazionale-calendario-risultato-posticipo-classifiche-34-giornata-2025-26-358236",
            "https://www.pianetabasket.com/serie-b/serie-b-nazionale-calendario-risultati-sabato-classifiche-33-giornata-2025-26-357782",
        ],
    },
}

BASE_STANDINGS = {
    "virtus": {"pos": 1, "pts": 52, "w": 26, "l": 6},
    "luiss":  {"pos": 6, "pts": 38, "w": 19, "l": 13},
}

# URL pagine squadra LNP e pianetabasket — aggiornare se cambiano lega
TEAM_CONFIG = {
    "B Nazionale": {
        # Pagine squadra su LNP (fonte primaria per calendario e risultati)
        "lnp_virtus": "https://www.legapallacanestro.com/serie-b/virtus-gvm-roma-1960",
        "lnp_luiss":  "https://www.legapallacanestro.com/serie-b/luiss-roma",
        # Prefisso URL risultati pianetabasket (usato in get_urls_for_round)
        "pb_round_url_prefix": "https://www.pianetabasket.com/serie-b/serie-b-nazionale-calendario-risultati-",
        # Template PDF calendario LNP — {season} viene sostituito con es. "2026-27"
        "lnp_pdf_b":  "https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_nazionale_gir._b_{season}.pdf",
        "lnp_pdf_a2": "https://static.legapallacanestro.com/sites/default/files/editor/calendario_a2_{season}.pdf",
    },
}


# ================================================================
# UTILITY
# ================================================================

def fetch(url, timeout=5):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; RomaBasketUpdater/6.0)",
        "Accept": "text/html,application/xhtml+xml,application/json",
        "Accept-Language": "it-IT,it;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ⚠️  {url[:60]}: {e}", file=sys.stderr)
        return ""


def normalise(s):
    s = s.lower()
    for old, new in [
        ("virtus gvm roma 1960", "virtus roma"),
        ("virtus gvm roma", "virtus roma"),
        ("luiss roma", "luiss"), ("luiss basketball", "luiss"),
        ("consorzio leonardo dany quarrata", "quarrata"),
        ("consorzio dany quarrata", "quarrata"),
        ("paperdi juvecaserta 2021", "juvecaserta"),
        ("malvin psa basket casoria", "casoria"),
        ("psa basket casoria", "casoria"),
        ("verodol cbd pielle livorno", "pielle livorno"),
        ("up andrea costa imola", "andrea costa"),
        ("benacquista assicurazioni latina", "latina"),
        ("allianz pazienza san severo", "san severo"),
        ("umana san giobbe chiusi", "chiusi"),
        ("general contractor jesi", "jesi"),
        ("solbat golfo piombino", "piombino"),
        ("orasì ravenna", "ravenna"), ("orasi ravenna", "ravenna"),
        ("power basket nocera", "nocera"),
        ("adamant ferrara basket 2018", "ferrara"),
        ("adamant ferrara", "ferrara"),
        ("virtus pallacanestro imola", "v.imola"),
        ("virtus imola", "v.imola"),
        ("ristopro janus fabriano", "fabriano"),
        ("ristopro fabriano", "fabriano"),
        ("raggisolaris faenza", "faenza"),
        ("consultinvest loreto pesaro", "loreto pesaro"),
    ]:
        s = s.replace(old, new)
    return re.sub(r"\s+", " ", s).strip()


def parse_results(html):
    """Estrae risultati e orari futuri da HTML pianetabasket.
    Resiliente a variazioni di formato: prova prima il pattern stretto,
    poi un pattern più permissivo se non trova nulla.
    """
    results = []
    plain = html.replace("&#x27;", "'").replace("&amp;", "&")
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r"\s+", " ", plain)
    seen = set()

    # Con risultato — pattern stretto (data + orario + squadre + score)
    pat_score = re.compile(
        r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+"
        r"([A-Za-zÀ-ÿ0-9 '\.\-]+?)\s*-\s*([A-Za-zÀ-ÿ0-9 '\.\-]+?)\s+"
        r"(\d{2,3})-(\d{2,3})(?:\s|$)"
    )
    for m in pat_score.finditer(plain):
        dr, t, h, a, sh, sa = m.groups()
        h = h.strip(); a = a.strip()
        if len(h) < 4 or len(a) < 4:
            continue
        try:
            dd, mm, yyyy = dr.split("/")
            key = f"{yyyy}-{mm}-{dd}|{normalise(h)}"
            results.append({
                "date": f"{yyyy}-{mm}-{dd}", "time": t,
                "home": h, "away": a, "sh": int(sh), "sa": int(sa)
            })
            seen.add(key)
        except Exception:
            continue

    # Solo orario (partite future)
    pat_time = re.compile(
        r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+"
        r"([A-Za-zÀ-ÿ0-9 '\.\-]{5,50}?)\s*-\s*([A-Za-zÀ-ÿ0-9 '\.\-]{5,50}?)"
        r"(?=\s+\d{2}/\d{2}/|\s*$)"
    )
    for m in pat_time.finditer(plain):
        dr, t, h, a = m.groups()
        h = h.strip(); a = a.strip()
        if len(h) < 4 or len(a) < 4:
            continue
        try:
            dd, mm, yyyy = dr.split("/")
            key = f"{yyyy}-{mm}-{dd}|{normalise(h)}"
            if key not in seen:
                results.append({
                    "date": f"{yyyy}-{mm}-{dd}", "time": t,
                    "home": h, "away": a, "sh": None, "sa": None
                })
                seen.add(key)
        except Exception:
            continue

    # Pattern alternativo — più permissivo
    if not results:
        pat_loose = re.compile(
            r"(\d{2}/\d{2}/\d{4})\s*"
            r"([A-Za-zÀ-ÿ0-9 '\.\-]{5,50}?)\s*-\s*([A-Za-zÀ-ÿ0-9 '\.\-]{5,50}?)\s+"
            r"(\d{2,3})\s*-\s*(\d{2,3})(?:\s|$)"
        )
        for m in pat_loose.finditer(plain):
            dr, h, a, sh, sa = m.groups()
            h, a = h.strip(), a.strip()
            if len(h) < 4 or len(a) < 4:
                continue
            try:
                dd, mm, yyyy = dr.split("/")
                key = f"{yyyy}-{mm}-{dd}|{normalise(h)}"
                if key not in seen:
                    results.append({
                        "date": f"{yyyy}-{mm}-{dd}", "time": "20:00",
                        "home": h, "away": a, "sh": int(sh), "sa": int(sa)
                    })
                    seen.add(key)
            except Exception:
                continue

    return results


def parse_lnp_calendar(html, home_aliases):
    """
    Estrae il calendario dalla pagina squadra LNP.
    Restituisce lista di {date, time, home, away, sh, sa}.
    Il punteggio 0-0 viene trattato come partita non ancora giocata.
    """
    results = []

    # Estrai celle <td> dalla tabella calendario
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
        # Campi successivi: home, away, result, [venue]
        home_raw = td_list[i + 1].strip()
        away_raw = td_list[i + 2].strip()
        result_raw = td_list[i + 3].strip() if i + 3 < len(td_list) else ""

        # Salta se il nome squadra è troppo corto (intestazione o cella vuota)
        if len(home_raw) < 3 or len(away_raw) < 3:
            i += 1
            continue

        # Risultato: "NN - NN" oppure "0 - 0" (non giocata) oppure "—"
        rm = re.match(r'(\d+)\s*[-–]\s*(\d+)', result_raw)
        if rm:
            sh_raw, sa_raw = int(rm.group(1)), int(rm.group(2))
            # 0-0 = non giocata
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


def parse_standings_from_html(html, aliases_v, aliases_l):
    """Estrae la classifica Girone B più aggiornata dalla pagina."""
    plain = html.replace("&#x27;", "'").replace("&amp;", "&")
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r" {2,}", " ", plain)

    best = None
    best_total = 0

    for idx in [m.start() for m in re.finditer(r"[Cc]lassifica\s+girone\s+[Bb]", plain)]:
        block = plain[idx:idx + 2500]
        for stop in ["classifica girone a", "nota -"]:
            cut = block.lower().find(stop, 20)
            if cut != -1:
                block = block[:cut]
                break

        candidate = {}
        pos = 1
        pat = re.compile(
            r"([A-Za-zÀ-ÿ0-9 '\.\-]{4,50}?)\s+(\d{1,3})\s+(\d{1,2})-(\d{1,2})(?:\s|$)"
        )
        for m in pat.finditer(block):
            name = m.group(1).strip()
            pts, w, l = int(m.group(2)), int(m.group(3)), int(m.group(4))
            nl = name.lower()
            if any(a in nl for a in aliases_v) and "virtus" not in candidate:
                candidate["virtus"] = {"pos": pos, "pts": pts, "w": w, "l": l}
            elif any(a in nl for a in aliases_l) and "luiss" not in candidate:
                candidate["luiss"] = {"pos": pos, "pts": pts, "w": w, "l": l}
            pos += 1
            if len(candidate) == 2:
                break

        if len(candidate) == 2:
            total = candidate["virtus"]["pts"] + candidate["luiss"]["pts"]
            if total > best_total:
                best_total = total
                best = candidate

    return best


def find_match(scraped, match):
    mh = normalise(match["home"])
    for s in scraped:
        if s.get("date") and match.get("date"):
            try:
                md = datetime.strptime(match["date"], "%Y-%m-%d").date()
                sd = datetime.strptime(s["date"], "%Y-%m-%d").date()
                if abs((sd - md).days) > 4:
                    continue
            except Exception:
                pass
        sh_n = normalise(s["home"])
        if (sh_n in mh or mh in sh_n or
                ("virtus roma" in mh and "virtus" in sh_n) or
                ("luiss" in mh and "luiss" in sh_n)):
            return s
    return None


# ================================================================
# LNP — FONTE PRIMARIA PER CALENDARIO E RISULTATI
# ================================================================

def update_from_lnp(matches, config):
    """
    STEP 0 — Aggiorna date, orari e risultati dalle pagine ufficiali LNP.
    Fonte più affidabile: dati ufficiali, nessuna dipendenza da API esterne.

    Per ogni squadra:
    - Partite future: aggiorna date/orario se LNP mostra valori diversi
    - Partite passate senza risultato: aggiorna sh/sa se LNP ha il punteggio
    """
    serie = config["teams"]["virtus"].get("serie", "B Nazionale")
    tc = TEAM_CONFIG.get(serie, TEAM_CONFIG["B Nazionale"])
    updated = 0

    team_urls = {
        "virtus": tc.get("lnp_virtus"),
        "luiss":  tc.get("lnp_luiss"),
    }

    for team_key, lnp_url in team_urls.items():
        if not lnp_url:
            continue

        html = fetch(lnp_url, timeout=8)
        if not html or len(html) < 1000:
            continue

        aliases = config["teams"][team_key].get("name_aliases", [team_key])
        lnp_matches = parse_lnp_calendar(html, aliases)

        if not lnp_matches:
            print(f"  ⚠️  LNP [{team_key}]: nessuna partita estratta")
            continue

        # Costruisci indice LNP per ricerca rapida per data+casa
        lnp_index = {}
        for lm in lnp_matches:
            key = f"{lm['date']}|{normalise(lm['home'])}"
            lnp_index[key] = lm

        for m in matches:
            if m.get("team") != team_key:
                continue

            # Cerca la partita nell'indice LNP
            m_key = f"{m['date']}|{normalise(m['home'])}"
            lm = lnp_index.get(m_key)

            # Se non trovata per data esatta, prova a trovare per away team
            if not lm:
                m_away_n = normalise(m.get("away", ""))
                for lnp_m in lnp_matches:
                    if normalise(lnp_m["home"]) in normalise(m["home"]) or \
                       normalise(m["home"]) in normalise(lnp_m["home"]):
                        lnp_away_n = normalise(lnp_m.get("away", ""))
                        if (m_away_n and lnp_away_n and
                                (m_away_n in lnp_away_n or lnp_away_n in m_away_n)):
                            lm = lnp_m
                            break

            if not lm:
                continue

            # Aggiorna data e orario per partite future
            if m.get("sh") is None:
                changed = False
                if lm["date"] != m["date"]:
                    print(f"  📅 LNP [{team_key}] {m['home']} vs {m['away']}: "
                          f"data {m['date']} → {lm['date']}")
                    m["date"] = lm["date"]
                    changed = True
                if lm["time"] and lm["time"] != m.get("time"):
                    print(f"  🕐 LNP [{team_key}] {m['home']} vs {m['away']}: "
                          f"orario → {lm['time']}")
                    m["time"] = lm["time"]
                    changed = True
                if changed:
                    updated += 1

            # Aggiorna risultato per partite senza punteggio
            if m.get("sh") is None and lm.get("sh") is not None:
                m["sh"] = lm["sh"]
                m["sa"] = lm["sa"]
                print(f"  ✅ LNP [{team_key}] {m['home']} vs {m['away']}: "
                      f"{lm['sh']}-{lm['sa']}")
                updated += 1

    print(f"  📡 LNP: {updated} aggiornamenti")
    return updated


# ================================================================
# RICERCA URL — Homepage pianetabasket + fallback stima
# ================================================================

def find_urls_from_rss_and_homepage(serie, last_round):
    """
    Cerca URL reali delle giornate successive all'ultima con risultati.
    Priorità: 1) Homepage pianetabasket  2) Fallback URL noti
    """
    sources = LEAGUE_SOURCES.get(serie, LEAGUE_SOURCES["B Nazionale"])
    pb_section = sources["pb_section"]
    found = []

    # 1. Homepage pianetabasket
    pb_home = sources["pb_home"]
    html = fetch(pb_home)
    if html:
        pat2 = re.compile(r"(/serie-b/[^<>]{5,80})")
        for m in pat2.finditer(html):
            path = m.group(1)
            if any(k in path.lower() for k in ["risultati", "risultato", "calendario", "classifiche"]):
                url = "https://www.pianetabasket.com" + path
                rnd_m = re.search(r"-([0-9]+)-giornata-", url)
                rnd = int(rnd_m.group(1)) if rnd_m else None
                if rnd and rnd <= last_round:
                    continue
                if url not in found:
                    found.append(url)
        print(f"  🔍 Homepage: {len(found)} URL trovati")

    # 2. Fallback stagionale: URL noti recenti per classifica aggiornata
    if not found:
        fallback = sources.get("fallback_urls", [])
        if fallback:
            print(f"  🔁 Fallback stagionale: {len(fallback)} URL noti")
            found.extend(fallback)

    return found


def get_urls_for_round(rnd):
    """
    Restituisce URL da provare per una giornata specifica.
    1) URL noto verificato  2) Stima ID
    """
    # 1. URL noto
    if rnd in KNOWN_URLS:
        return [KNOWN_URLS[rnd]]

    # 2. Stima ID (fallback finale)
    base_id = ROUND_BASE_IDS.get(rnd, 357782 + (rnd - 33) * 642)
    urls = []
    for suf, delta in [
        ("classifiche", 0),
        ("sabato-classifiche", 0),
        ("domenica-classifiche", 0),
        ("classifiche", -300),
        ("classifiche", +300),
    ]:
        url = (
            f"https://www.pianetabasket.com/serie-b/"
            f"serie-b-nazionale-calendario-risultati-{suf}-"
            f"{rnd}-giornata-2025-26-{base_id + delta}"
        )
        if url not in urls:
            urls.append(url)
    return urls


# ================================================================
# AGGIORNAMENTO CLASSIFICA
# ================================================================

def update_standings_multi(standings, config, scraped_htmls):
    """Aggiorna classifica da più fonti, prende quella con punteggio più alto."""
    aliases_v = config["teams"]["virtus"].get("name_aliases", ["virtus roma"])
    aliases_l = config["teams"]["luiss"].get("name_aliases", ["luiss roma", "luiss"])
    serie = config["teams"]["virtus"].get("serie", "B Nazionale")
    sources = LEAGUE_SOURCES.get(serie, LEAGUE_SOURCES["B Nazionale"])
    candidates = []

    # Da pagine già scaricate
    for label, html in scraped_htmls:
        if not html:
            continue
        st = parse_standings_from_html(html, aliases_v, aliases_l)
        if st:
            candidates.append((label, st))

    # Pagina classifica pianetabasket
    pb_class = sources.get("pb_class")
    if pb_class:
        html = fetch(pb_class)
        if html:
            st = parse_standings_from_html(html, aliases_v, aliases_l)
            if st:
                candidates.append(("pb-class", st))

    # LNP ufficiale
    lnp_url = sources.get("lnp")
    if lnp_url:
        html = fetch(lnp_url)
        if html:
            st = parse_standings_from_html(html, aliases_v, aliases_l)
            if st:
                candidates.append(("lnp", st))

    if not candidates:
        print("  ⚠️  Nessuna classifica trovata")
        return standings

    # TODO — Tiebreaker classifica LNP (parità di punti):
    # La classifica ufficiale LNP risolve i pareggi in quest'ordine:
    # 1. Scontro diretto  2. Quoziente canestri scontri diretti  3. Quoziente generale
    # Il parser usa solo i punti — corretto per uso informativo, ma può divergere
    # dalla classifica ufficiale in caso di parità esatta.
    best_label, best = max(
        candidates,
        key=lambda x: x[1]["virtus"]["pts"] + x[1]["luiss"]["pts"]
    )
    current_total = (
        standings.get("virtus", {}).get("pts", 0) +
        standings.get("luiss", {}).get("pts", 0)
    )
    new_total = best["virtus"]["pts"] + best["luiss"]["pts"]

    if new_total >= current_total:
        print(
            f"  ✅ Classifica [{best_label}]: "
            f"Virtus {best['virtus']['pos']}° {best['virtus']['pts']}pt "
            f"({best['virtus']['w']}V-{best['virtus']['l']}P) | "
            f"LUISS {best['luiss']['pos']}° {best['luiss']['pts']}pt "
            f"({best['luiss']['w']}V-{best['luiss']['l']}P)"
        )
        return best

    print("  ℹ️  Classifica già aggiornata")
    return standings


# ================================================================
# AGGIORNAMENTO CALENDARIO (variazioni)
# ================================================================

def fetch_calendar_changes(config):
    """
    Cerca variazioni di calendario su pianetabasket.
    Rileva anticipi, posticipi, recuperi per le squadre seguite.
    """
    changes = []
    aliases_v = config["teams"]["virtus"].get("name_aliases", ["virtus roma"])
    aliases_l = config["teams"]["luiss"].get("name_aliases", ["luiss roma", "luiss"])
    months_it = {
        "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
        "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
        "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12
    }
    keywords = ["modif", "anticip", "posticip", "spostata", "rinviata", "recupero"]
    candidate_urls = []

    print(f"  🔍 Articoli modifica calendario: {len(candidate_urls)}")

    for url in candidate_urls[:5]:
        art = fetch(url)
        if not art:
            continue
        plain = re.sub(r"<[^>]+>", " ", art)
        plain = re.sub(r"\s+", " ", plain)
        pl = plain.lower()

        is_virtus = any(a in pl for a in aliases_v)
        is_luiss  = any(a in pl for a in aliases_l)
        if not is_virtus and not is_luiss:
            continue
        team = "virtus" if is_virtus else "luiss"

        m1 = re.search(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2})", plain)
        if m1:
            dd, mm, yyyy, t = m1.groups()
            changes.append({"team": team, "date": f"{yyyy}-{mm}-{dd}", "time": t, "source": url})
            print(f"  📅 [{team}] {yyyy}-{mm}-{dd} ore {t}")
            continue

        m2 = re.search(
            r"(\d{1,2})\s+(\w+)(?:\s+2026)?\s+(?:ore|alle)\s+(\d{1,2}(?::\d{2})?)",
            plain, re.IGNORECASE
        )
        if m2:
            day, mon_str, t = m2.groups()
            mon = months_it.get(mon_str.lower())
            if mon:
                if ":" not in t:
                    t += ":00"
                changes.append({
                    "team": team,
                    "date": f"2026-{mon:02d}-{int(day):02d}",
                    "time": t, "source": url
                })
                print(f"  📅 [{team}] 2026-{mon:02d}-{int(day):02d} ore {t}")

    return changes


# ================================================================
# AGGIORNAMENTO IN STAGIONE
# ================================================================

def update_in_season(matches, config, standings):
    today = date.today()
    rounds_done = [
        m["round"] for m in matches
        if m.get("sh") is not None and m.get("phase") == "regular"
    ]
    last_round = max(rounds_done) if rounds_done else 0
    print(f"  Ultima giornata con risultati: {last_round}")

    serie = config["teams"]["virtus"].get("serie", "B Nazionale")
    sources = LEAGUE_SOURCES.get(serie, LEAGUE_SOURCES["B Nazionale"])
    girone_check = sources.get("girone_check")

    all_scraped = []
    scraped_htmls = []

    # STEP 0: Aggiornamento da LNP (fonte primaria)
    print("\n  📡 STEP 0 — LNP ufficiale...")
    lnp_updated = update_from_lnp(matches, config)

    # STEP 1: URL dalla homepage pianetabasket
    home_urls = find_urls_from_rss_and_homepage(serie, last_round)
    for url in home_urls:
        html = fetch(url)
        if not html or len(html) < 1000:
            continue
        if girone_check and girone_check not in html.lower():
            continue
        scraped = parse_results(html)
        if scraped:
            rnd_m = re.search(r"-(\d+)-giornata-", url)
            rnd = rnd_m.group(1) if rnd_m else "?"
            print(f"  ✅ RSS/Homepage G{rnd}: {len(scraped)} risultati")
            all_scraped.extend(scraped)
            scraped_htmls.append((f"G{rnd}", html))

    # STEP 2: URL mirati per giornate senza risultato
    found_rounds = set()
    for lbl, _ in scraped_htmls:
        m_rnd = re.search(r"G(\d+)", lbl)
        if m_rnd:
            found_rounds.add(int(m_rnd.group(1)))

    for m in matches:
        md = datetime.strptime(m["date"], "%Y-%m-%d").date()
        rnd = m.get("round")
        if not rnd or m.get("sh") is not None:
            continue
        if md > today + timedelta(days=60):
            continue
        if rnd in found_rounds:
            continue

        urls = get_urls_for_round(rnd)
        for url in urls:
            html = fetch(url)
            if not html or len(html) < 1000:
                continue
            if girone_check and girone_check not in html.lower():
                continue
            scraped = parse_results(html)
            if scraped:
                print(f"  ✅ G{rnd}: {len(scraped)} risultati")
                all_scraped.extend(scraped)
                scraped_htmls.append((f"G{rnd}", html))
                found_rounds.add(rnd)
                break

    # STEP 3: Variazioni di calendario
    print("\n  📅 Ricerca variazioni calendario...")
    calendar_changes = fetch_calendar_changes(config)

    # Applica variazioni calendario
    for m in matches:
        md = datetime.strptime(m["date"], "%Y-%m-%d").date()
        if md < today or m.get("sh") is not None:
            continue
        for chg in calendar_changes:
            if chg.get("team") != m["team"]:
                continue
            try:
                chg_d = datetime.strptime(chg["date"], "%Y-%m-%d").date()
                away_n = normalise(chg.get("away", m.get("away", "")))
                m_away_n = normalise(m.get("away", ""))
                same_match = (abs((chg_d - md).days) <= 7 and
                              (away_n in m_away_n or m_away_n in away_n or away_n == ""))
                if same_match and (chg["date"] != m["date"] or chg["time"] != m.get("time")):
                    print(f"  📅 {m['home']} vs {m['away']}: {m['date']} → {chg['date']} ore {chg['time']}")
                    m["date"] = chg["date"]
                    m["time"] = chg["time"]
                    break
            except Exception:
                continue

    # STEP 4: Applica risultati e orari da pianetabasket
    updated = lnp_updated
    for m in matches:
        md = datetime.strptime(m["date"], "%Y-%m-%d").date()

        if md < today and m.get("sh") is None:
            found = find_match(all_scraped, m)
            if found and found.get("sh") is not None:
                m["sh"] = found["sh"]
                m["sa"] = found["sa"]
                if found.get("time"):
                    m["time"] = found["time"]
                print(f"  ✅ pianetabasket → {m['home']} vs {m['away']}: {found['sh']}-{found['sa']}")
                updated += 1

        if md >= today:
            found = find_match(all_scraped, m)
            if found and found.get("time") and found["time"] != m.get("time"):
                print(f"  🕐 {m['home']} vs {m['away']}: orario → {found['time']}")
                m["time"] = found["time"]
                updated += 1

    # STEP 5: Classifica
    print("\n  🏆 Aggiornamento classifica...")
    standings = update_standings_multi(standings, config, scraped_htmls)

    return updated, standings


# ================================================================
# FUORI STAGIONE
# ================================================================

def search_new_calendar(next_season, config):
    print(f"\n🔍 Ricerca calendario {next_season}...")
    serie = config["teams"]["virtus"].get("serie", "B Nazionale")
    tc = TEAM_CONFIG.get(serie, TEAM_CONFIG["B Nazionale"])

    pdf_urls = [
        tc["lnp_pdf_b"].format(season=next_season),
        tc["lnp_pdf_a2"].format(season=next_season),
    ]
    serie_map = ["B Nazionale", "A2"]

    for pdf_url, serie_name in zip(pdf_urls, serie_map):
        html = fetch(pdf_url, timeout=8)
        if not html or len(html) < 500:
            continue
        for team_key, team_cfg in config["teams"].items():
            for alias in team_cfg.get("name_aliases", []):
                if alias in html.lower():
                    print(f"  📄 {team_cfg['name']} trovato in {serie_name}")
                    return None, next_season

    print(f"  ℹ️  Calendario {next_season} non ancora disponibile")
    return None, None


# ================================================================
# MAIN
# ================================================================

def main():
    print(f"\n🏀 Roma Basket Updater v6 — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 55)

    data_path = Path("data.json")
    if data_path.exists():
        with open(data_path) as f:
            current = json.load(f)
        matches   = current.get("matches", [])
        standings = current.get("standings", dict(BASE_STANDINGS))
        config    = current.get("config", CONFIG)
        # Retrocompatibilità
        for team_key, team_default in CONFIG["teams"].items():
            if team_key not in config.get("teams", {}):
                config.setdefault("teams", {})[team_key] = team_default
            else:
                for field, val in team_default.items():
                    config["teams"][team_key].setdefault(field, val)
        config.setdefault("next_season", CONFIG["next_season"])
        print(f"📂 Caricato — {len(matches)} partite, stagione {config.get('season','?')}")
    else:
        matches   = []
        standings = dict(BASE_STANDINGS)
        config    = CONFIG
        print("📂 Primo avvio — dati base")

    today       = date.today()
    next_season = config.get("next_season", "2026-27")
    all_dates   = [datetime.strptime(m["date"], "%Y-%m-%d").date() for m in matches] if matches else []
    season_end  = max(all_dates) if all_dates else date(2026, 6, 30)
    in_season   = today <= season_end + timedelta(days=30)

    total_updated = 0

    if in_season:
        serie_v = config["teams"]["virtus"].get("serie", "?")
        print(f"\n📅 IN STAGIONE — {serie_v}")
        total_updated, standings = update_in_season(matches, config, standings)
        print(f"\n📝 Aggiornamenti: {total_updated}")
    else:
        print(f"\n💤 FUORI STAGIONE — cerco {next_season}")
        _, found = search_new_calendar(next_season, config)
        if found:
            print(f"ℹ️  Stagione {found} rilevata")

    output = {
        "last_updated": datetime.now().isoformat(),
        "season": config.get("season", "2025-26"),
        "config": config,
        "matches": matches,
        "standings": standings,
    }
    # Scrivi solo se qualcosa è cambiato (evita commit inutili sul timestamp)
    new_json = json.dumps(output, ensure_ascii=False, indent=2)
    if data_path.exists():
        old_content = data_path.read_text(encoding="utf-8")
        import re as _re
        def strip_ts(s): return _re.sub(r'"last_updated":\s*"[^"]*"', '"last_updated":""', s)
        if strip_ts(old_content) == strip_ts(new_json) and total_updated == 0:
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
