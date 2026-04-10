#!/usr/bin/env python3
"""
update_data.py — Roma Basket Casa — Aggiornamento automatico v5
Usa Google Custom Search API per trovare gli URL reali di pianetabasket
senza dover stimare gli ID.

Google API Key: letta da variabile d'ambiente GOOGLE_API_KEY
Google CSE ID:  letta da variabile d'ambiente GOOGLE_CSE_ID
"""

import json
import os
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

# ID base stimati (fallback se Google non trova nulla)
# G33=357782, incremento reale ~642 per giornata
ROUND_BASE_IDS = {
    35: 358696, 36: 359156, 37: 359616, 38: 360076,
}

LEAGUE_SOURCES = {
    "B Nazionale": {
        "pb_home":      "https://www.pianetabasket.com/serie-b/",
        "pb_section":   "/serie-b/",
        "pb_rss":       "https://www.pianetabasket.com/feed/serie-b/",
        "pb_class":     "https://www.pianetabasket.com/serie-b/classifica-serie-b-nazionale-girone-b-2025-26",
        "lnp":          "https://www.legapallacanestro.com/serie/4/classifica",
        "girone_check": "girone b",
    },
}

BASE_STANDINGS = {
    "virtus": {"pos": 2, "pts": 52, "w": 26, "l": 6},
    "luiss":  {"pos": 6, "pts": 38, "w": 19, "l": 12},
}

# ================================================================
# GOOGLE CUSTOM SEARCH API
# ================================================================

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CSE_ID  = os.getenv("GOOGLE_CSE_ID",  "e57483d3719974bc0")

def google_search(query, num=5):
    """
    Cerca su Google tramite Custom Search API.
    Restituisce lista di URL trovati nei risultati.
    """
    if not GOOGLE_API_KEY:
        print("  ⚠️  GOOGLE_API_KEY non impostata", file=sys.stderr)
        return []
    url = (
        "https://www.googleapis.com/customsearch/v1"
        f"?key={GOOGLE_API_KEY}"
        f"&cx={GOOGLE_CSE_ID}"
        f"&q={urllib.parse.quote(query)}"
        f"&num={num}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
            items = data.get("items", [])
            urls = [item["link"] for item in items if "link" in item]
            snippets = [item.get("snippet", "") for item in items]
            return urls, snippets
    except Exception as e:
        print(f"  ⚠️  Google Search error: {e}", file=sys.stderr)
        return [], []


def google_search_result(home, away):
    """
    Cerca il risultato di una partita direttamente negli snippet Google.
    Non serve trovare l'URL né scaricare la pagina — il punteggio
    e spesso gia nello snippet (es. "Virtus Roma-Latina 85-72").
    Restituisce (sh, sa) o None.

    Logica ordine home/away:
    - pianetabasket scrive sempre "casa-ospite score-score"
    - se home appare prima di away nello snippet -> s1=home, s2=away
    - se away appare prima -> sh=s2, sa=s1
    - se non determinabile -> s1=home per convenzione
    """
    query = f'"{home}" "{away}" risultato basket serie B 2026'
    urls, snippets = google_search(query, num=5)

    home_n = normalise(home)
    away_n  = normalise(away)
    pat = re.compile(r"(\d{2,3})\s*[-\u2013]\s*(\d{2,3})")

    for snippet in snippets:
        sl = snippet.lower()
        if home_n[:8] not in sl and away_n[:8] not in sl:
            continue
        m = pat.search(snippet)
        if not m:
            continue
        s1, s2 = int(m.group(1)), int(m.group(2))
        if not (20 <= s1 <= 150 and 20 <= s2 <= 150 and s1 != s2):
            continue
        # Determina l'ordine dei nomi rispetto al punteggio
        score_pos = sl.find(m.group(0))
        pos_home = sl.rfind(home_n[:8], 0, score_pos)
        pos_away = sl.rfind(away_n[:8], 0, score_pos)
        if pos_home != -1 and pos_away != -1:
            sh, sa = (s1, s2) if pos_home < pos_away else (s2, s1)
        elif pos_home != -1:
            sh, sa = s1, s2
        elif pos_away != -1:
            sh, sa = s2, s1
        else:
            sh, sa = s1, s2
        print(f"  \u2705 Google snippet \u2192 {home} vs {away}: {sh}-{sa}")
        return sh, sa
    return None

def find_url_via_google(rnd, season="2025-26"):
    """
    Usa Google per trovare l'URL reale della pagina risultati
    di pianetabasket per la giornata indicata.
    """
    query = f"site:pianetabasket.com serie B nazionale risultati classifiche {rnd} giornata {season}"
    urls, _ = google_search(query, num=5)
    pat = re.compile(
        r"https://www\.pianetabasket\.com/serie-b/[^\s]*"
        + str(rnd) + r"-giornata-" + re.escape(season) + r"-\d+"
    )
    for url in urls:
        if pat.search(url):
            print(f"  🔍 Google → G{rnd}: {url[-45:]}")
            return url
    return None


def find_calendar_change_via_google(team_name, opponent, rnd):
    """
    Usa Google per trovare variazioni di calendario (anticipi, posticipi).
    Cerca articoli su pianetabasket, legapallacanestro, siti squadre.
    """
    query = f'"{team_name}" "{opponent}" giornata {rnd} data orario basket 2026 spostata anticipo'
    urls, snippets = google_search(query, num=5)

    months_it = {
        "gennaio":1,"febbraio":2,"marzo":3,"aprile":4,
        "maggio":5,"giugno":6,"luglio":7,"agosto":8,
        "settembre":9,"ottobre":10,"novembre":11,"dicembre":12
    }

    all_text = " ".join(snippets).lower()

    # Cerca pattern data negli snippet: "11 aprile ore 20" o "04/04/2026 20:00"
    m1 = re.search(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2})", all_text)
    if m1:
        dd, mm, yyyy, t = m1.groups()
        print(f"  📅 Google calendario: {yyyy}-{mm}-{dd} ore {t}")
        return {"date": f"{yyyy}-{mm}-{dd}", "time": t}

    m2 = re.search(
        r"(\d{1,2})\s+(\w+)(?:\s+2026)?\s+(?:ore|alle)\s+(\d{1,2}(?::\d{2})?)",
        all_text, re.IGNORECASE
    )
    if m2:
        day, mon_str, t = m2.groups()
        mon = months_it.get(mon_str.lower())
        if mon:
            if ":" not in t:
                t += ":00"
            print(f"  📅 Google calendario: 2026-{mon:02d}-{int(day):02d} ore {t}")
            return {"date": f"2026-{mon:02d}-{int(day):02d}", "time": t}

    return None


# ================================================================
# UTILITY
# ================================================================

def fetch(url, timeout=5):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; RomaBasketUpdater/5.0)",
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
    """Estrae risultati e orari futuri da HTML pianetabasket."""
    results = []
    plain = html.replace("&#x27;", "'").replace("&amp;", "&")
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r"\s+", " ", plain)
    seen = set()

    # Con risultato
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
# RICERCA URL — Google prima, poi RSS, poi fallback stima
# ================================================================

def find_urls_from_rss_and_homepage(serie, last_round):
    """
    Cerca URL reali delle giornate successive all'ultima con risultati.
    Priorità: 1) RSS pianetabasket  2) Homepage  3) Google Search
    """
    sources = LEAGUE_SOURCES.get(serie, LEAGUE_SOURCES["B Nazionale"])
    pb_section = sources["pb_section"]
    pb_rss = sources.get("pb_rss", "https://www.pianetabasket.com/feed/serie-b/")
    found = []

    # 1. RSS feed
    rss_html = fetch(pb_rss)
    if rss_html:
        pat = re.compile(
            r"<link[^>]*>(https://www[.]pianetabasket[.]com"
            + re.escape(pb_section)
            + r"[^<]*(risultati|calendario)[^<]*2025-26[^<]*)</link>"
        )
        for m in pat.finditer(rss_html):
            url = m.group(1).strip()
            rnd_m = re.search(r"-([0-9]+)-giornata-", url)
            rnd = int(rnd_m.group(1)) if rnd_m else None
            if rnd and rnd <= last_round:
                continue
            if url not in found:
                found.append(url)
        print(f"  🔍 RSS: {len(found)} URL trovati")

    # 2. Homepage fallback
    if not found:
        pb_home = sources["pb_home"]
        html = fetch(pb_home)
        if html:
            pat2 = re.compile(
                r"(/serie-b/[^<>]{5,80})"
            )
            for m in pat2.finditer(html):
                path = m.group(1)
                if "risultati" in path.lower() or "calendario" in path.lower():
                    url = "https://www.pianetabasket.com" + path
                    rnd_m = re.search(r"-([0-9]+)-giornata-", url)
                    rnd = int(rnd_m.group(1)) if rnd_m else None
                    if rnd and rnd <= last_round:
                        continue
                    if url not in found:
                        found.append(url)
            print(f"  🔍 Homepage: {len(found)} URL trovati")

    # 3. Google Search per la prossima giornata non trovata
    if not found:
        next_rnd = last_round + 1
        url = find_url_via_google(next_rnd)
        if url:
            found.append(url)

    return found


def get_urls_for_round(rnd):
    """
    Restituisce URL da provare per una giornata specifica.
    1) URL noto verificato  2) Google Search  3) Stima ID
    """
    # 1. URL noto
    if rnd in KNOWN_URLS:
        return [KNOWN_URLS[rnd]]

    # 2. Google Search
    url = find_url_via_google(rnd)
    if url:
        return [url]

    # 3. Stima ID (fallback finale)
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

    # Google Search per classifica
    if GOOGLE_API_KEY:
        q = "classifica serie B nazionale girone B 2025-26 pianetabasket"
        urls, _ = google_search(q, num=3)
        for url in urls:
            if "pianetabasket" in url:
                html = fetch(url)
                if html:
                    st = parse_standings_from_html(html, aliases_v, aliases_l)
                    if st:
                        candidates.append(("google-class", st))
                        break

    if not candidates:
        print("  ⚠️  Nessuna classifica trovata")
        return standings

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
# AGGIORNAMENTO CALENDARIO (variazioni LNP)
# ================================================================

def fetch_calendar_changes(config):
    """
    Cerca variazioni di calendario su pianetabasket e tramite Google.
    Rileva anticipi, posticipi, recuperi per le squadre seguite.
    """
    changes = []
    aliases_v = config["teams"]["virtus"].get("name_aliases", ["virtus roma"])
    aliases_l = config["teams"]["luiss"].get("name_aliases", ["luiss roma", "luiss"])
    months_it = {
        "gennaio":1,"febbraio":2,"marzo":3,"aprile":4,
        "maggio":5,"giugno":6,"luglio":7,"agosto":8,
        "settembre":9,"ottobre":10,"novembre":11,"dicembre":12
    }
    keywords = ["modif", "anticip", "posticip", "spostata", "rinviata", "recupero"]
    candidate_urls = []

    # 1. RSS feed
    rss_html = fetch("https://www.pianetabasket.com/feed/serie-b/")
    if rss_html:
        for m in re.finditer(
            r"<link[^>]*>(https://www[.]pianetabasket[.]com/serie-b/[^<]+)</link>",
            rss_html
        ):
            url = m.group(1).strip()
            if any(k in url.lower() for k in keywords):
                candidate_urls.append(url)

    # 2. Google Search per variazioni calendario
    if GOOGLE_API_KEY:
        for team_name in ["Virtus Roma", "Luiss Roma"]:
            q = f"{team_name} basket serie B variazione calendario anticipo posticipo 2026"
            urls, snippets = google_search(q, num=3)
            all_text = " ".join(snippets).lower()
            # Cerca pattern data negli snippet
            m1 = re.search(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2})", all_text)
            if m1:
                dd, mm, yyyy, t = m1.groups()
                team = "virtus" if "virtus" in team_name.lower() else "luiss"
                changes.append({"team": team, "date": f"{yyyy}-{mm}-{dd}", "time": t, "source": "google"})
                print(f"  📅 Google variazione [{team}]: {yyyy}-{mm}-{dd} ore {t}")
            # Aggiungi URL trovati da Google per analisi più approfondita
            for url in urls:
                if "pianetabasket" in url and any(k in url.lower() for k in keywords):
                    if url not in candidate_urls:
                        candidate_urls.append(url)

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

        # Cerca DD/MM/YYYY HH:MM
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

    # STEP 1: URL dalla RSS/homepage
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

    # Applica risultati e orari
    updated = 0
    for m in matches:
        md = datetime.strptime(m["date"], "%Y-%m-%d").date()

        if md < today and m.get("sh") is None:
            # Tentativo 1: pagina pianetabasket già scaricata
            found = find_match(all_scraped, m)
            if found and found.get("sh") is not None:
                m["sh"] = found["sh"]
                m["sa"] = found["sa"]
                if found.get("time"):
                    m["time"] = found["time"]
                print(f"  \u2705 pianetabasket \u2192 {m['home']} vs {m['away']}: {found['sh']}-{found['sa']}")
                updated += 1
            elif GOOGLE_API_KEY:
                # Tentativo 2: punteggio direttamente dagli snippet Google
                # Non serve scaricare nessuna pagina — il risultato è già nello snippet
                result = google_search_result(m["home"], m["away"])
                if result:
                    m["sh"], m["sa"] = result
                    updated += 1

        if md >= today:
            found = find_match(all_scraped, m)
            if found and found.get("time") and found["time"] != m.get("time"):
                print(f"  🕐 {m['home']} vs {m['away']}: orario → {found['time']}")
                m["time"] = found["time"]
                updated += 1

    # STEP 4: Classifica
    print("\n  🏆 Aggiornamento classifica...")
    standings = update_standings_multi(standings, config, scraped_htmls)

    return updated, standings


# ================================================================
# FUORI STAGIONE
# ================================================================

def search_new_calendar(next_season, config):
    print(f"\n🔍 Ricerca calendario {next_season}...")
    pdf_urls = [
        f"https://static.legapallacanestro.com/sites/default/files/editor/calendario_b_nazionale_gir._b_{next_season}.pdf",
        f"https://static.legapallacanestro.com/sites/default/files/editor/calendario_a2_{next_season}.pdf",
    ]
    serie_map = ["B Nazionale", "A2"]

    for pdf_url, serie in zip(pdf_urls, serie_map):
        html = fetch(pdf_url, timeout=8)
        if not html or len(html) < 500:
            continue
        for team_key, team_cfg in config["teams"].items():
            for alias in team_cfg.get("name_aliases", []):
                if alias in html.lower():
                    print(f"  📄 {team_cfg['name']} trovato in {serie}")
                    return None, next_season

    # Cerca anche tramite Google
    if GOOGLE_API_KEY:
        q = f"serie B nazionale basket calendario {next_season} girone B pianetabasket"
        urls, snippets = google_search(q, num=3)
        all_text = " ".join(snippets).lower()
        for team_cfg in config["teams"].values():
            for alias in team_cfg.get("name_aliases", []):
                if alias in all_text:
                    print(f"  🌐 Nuova stagione {next_season} rilevata via Google")
                    return None, next_season

    print(f"  ℹ️  Calendario {next_season} non ancora disponibile")
    return None, None


# ================================================================
# MAIN
# ================================================================

def main():
    print(f"\n🏀 Roma Basket Updater v5+Google — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 55)

    if GOOGLE_API_KEY:
        print(f"🔍 Google Custom Search: attiva (CSE: {GOOGLE_CSE_ID[:8]}...)")
    else:
        print("⚠️  Google Custom Search: non configurata (usa RSS/stima)")

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

    today      = date.today()
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
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n💾 Salvato — {len(matches)} partite")
    print("✅ Completato!\n")
    return total_updated


if __name__ == "__main__":
    main()
