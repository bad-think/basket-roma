#!/usr/bin/env python3
"""
update_data.py — Roma Basket Casa — v8.9
Architettura LNP-only con auto-discovery, auto-insert, auto-bootstrap.

Fonte unica: legapallacanestro.com
- Calendario, date, orari, risultati: pagine squadra LNP (HTML)
- Partite playoff/play-in: pagine dedicate LNP (HTML) — v8.8
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

LNP_PDF_BASE = "https://static.legapallacanestro.com/sites/default/files/editor"

def lnp_pdf_url(league_path, season, girone_letter=None):
    season_norm = season.replace("/", "-")
    if league_path == "serie-b" and girone_letter:
        return f"{LNP_PDF_BASE}/calendario_b_nazionale_gir._{girone_letter.lower()}_{season_norm}.pdf"
    if league_path == "serie-a2":
        return f"{LNP_PDF_BASE}/calendario_a2_{season_norm}.pdf"
    if league_path == "serie-a":
        return f"{LNP_PDF_BASE}/calendario_serie_a_{season_norm}.pdf"
    return None

LEAGUE_PATHS = ["serie-b", "serie-a2", "serie-a"]

LEAGUE_LABELS = {
    "serie-b": "B Nazionale",
    "serie-a2": "A2",
    "serie-a": "A",
}

LEAGUE_SERIE_IDS = {
    "serie-b": 4,
    "serie-a2": 1,
}

DOMINO_LEAGUE_CODES = {
    ("serie-b", "b"): "ita3_b",
    ("serie-b", "a"): "ita3_a",
    ("serie-a2", None): "ita2",
}

# Pagine playoff/play-in LNP — codici URL per ogni lega.
# URL: /serie/{serie_id}/playoff-playout/{anno_fine_stagione}/{codice}
# Tutti i tabelloni vengono controllati perché sono incrociati
# (squadra girone B può stare in tabellone 1 e viceversa).
PLAYOFF_PAGE_CODES = {
    "serie-b": [
        "ita3_a_poff", "ita3_b_poff",
        "ita3_a_pin",  "ita3_b_pin",
    ],
    "serie-a2": [
        "ita2_poff", "ita2_pin",
    ],
}

N_REGULAR_GAMES_BY_LEAGUE = {
    "serie-b": 36,
    "serie-a2": 36,
    "serie-a": 30,
}

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
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; RomaBasketUpdater/7.0)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "it-IT,it;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"  ⚠️  {url[:80]}: HTTP {e.code}", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"  ⚠️  {url[:80]}: {e}", file=sys.stderr)
        return ""


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
    ("paffoni fulgor basket omegna", "omegna"),
    ("fulgor omegna", "omegna"),
]


def normalise(s):
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    for old, new in _NAME_REPLACEMENTS:
        s = s.replace(old, new)
    return s


def slug_to_normalised(slug):
    s = slug.replace("-", " ")
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
        i += 5

    return results


def calc_team_stats(lnp_matches, team_aliases):
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
    if not matches:
        return matches
    seen = set()
    deduped = []
    for m in matches:
        key = (m.get("date"), normalise(m.get("home", "")), normalise(m.get("away", "")))
        if key not in seen:
            seen.add(key)
            deduped.append(m)
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
    for path in LEAGUE_PATHS:
        url = f"https://www.legapallacanestro.com/{path}/{team_slug}"
        html = fetch(url)
        if html and len(html) >= 1000 and "calendario" in html.lower():
            return path, html
    return None, None


_INDEX_BLACKLIST_KEYWORDS = [
    "formula", "calendario-dirette", "old-wild-west", "negli-anticipi",
    "guida-al-campionato", "supercoppa", "coppa-italia", "final-four",
    "lnp-pass", "archivio-storico", "leaders", "statistiche",
    "live-match", "mvp", "best-coach", "miglior-under",
]


def discover_girone_slugs(league_path, opponent_names, own_slug):
    index_url = f"https://www.legapallacanestro.com/{league_path}"
    html = fetch(index_url)
    if not html:
        print(f"  ⚠️  pagina indice {league_path} non disponibile")
        return {own_slug}

    pat = re.compile(rf'/{re.escape(league_path)}/([a-zA-Z0-9\-%]+?)(?:["\'\?#/]|$)')
    raw_slugs = set(pat.findall(html))

    candidate_slugs = set()
    for s in raw_slugs:
        sl = s.lower()
        if any(k in sl for k in _INDEX_BLACKLIST_KEYWORDS):
            continue
        if len(s) < 4:
            continue
        candidate_slugs.add(s)

    opp_norm = {normalise(o) for o in opponent_names if o}
    opp_norm = {o for o in opp_norm if len(o) >= 3}

    girone_slugs = {own_slug}
    for slug in candidate_slugs:
        sn = slug_to_normalised(slug)
        if not sn:
            continue
        for on in opp_norm:
            if sn == on:
                girone_slugs.add(slug)
                break
            if len(on) >= 4 and (on in sn or sn in on):
                girone_slugs.add(slug)
                break

    return girone_slugs


def compute_full_standings(league_path, girone_slugs, season=None):
    teams = []
    all_matches_collected = []
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

        aliases = [team_name, sn, slug.replace("-", " ")]
        w, l, pts = calc_team_stats(matches, aliases)
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
            "slug": slug, "name": team_name,
            "w": w, "l": l, "pts": pts, "pf": pf, "pa": pa,
        })

    h2h = {}
    h2h_pf = {}
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
        scored = sum(h2h_pf.get((tn, r), 0) for r in rivals)
        conceded = sum(h2h_pf.get((r, tn), 0) for r in rivals)
        return scored - conceded

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
    if not pdf_bytes:
        return None
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

    text = extract_pdf_text_stdlib(pdf_bytes)
    if text and text.strip():
        print(f"  🔧 PDF text extracted via stdlib parser ({len(text)} chars)")
        return text
    print(f"  ⚠️  stdlib parser: output vuoto")
    return None


def extract_pdf_text_stdlib(pdf_bytes):
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
        data_start = start + len(b"stream")
        if pdf_bytes[data_start:data_start + 2] == b"\r\n":
            data_start += 2
        elif pdf_bytes[data_start:data_start + 1] in (b"\n", b"\r"):
            data_start += 1
        data_end = end
        if pdf_bytes[data_end - 2:data_end] == b"\r\n":
            data_end -= 2
        elif pdf_bytes[data_end - 1:data_end] in (b"\n", b"\r"):
            data_end -= 1
        stream_data = pdf_bytes[data_start:data_end]
        try:
            decompressed = zlib.decompress(stream_data)
        except zlib.error:
            decompressed = stream_data
        try:
            content = decompressed.decode("latin-1", errors="replace")
        except Exception:
            pos = end + len(b"endstream")
            continue
        for m in re.finditer(r"\(((?:[^()\\]|\\[\\()nrtbf])*)\)\s*Tj", content):
            s = _pdf_unescape(m.group(1))
            if s:
                texts.append(s)
                texts.append(" ")
        for m in re.finditer(r"\[([^\]]*)\]\s*TJ", content):
            inner = m.group(1)
            for sm in re.finditer(r"\(((?:[^()\\]|\\[\\()nrtbf])*)\)", inner):
                s = _pdf_unescape(sm.group(1))
                if s:
                    texts.append(s)
            texts.append(" ")
        texts.append("\n")
        pos = end + len(b"endstream")
    return "".join(texts)


def _pdf_unescape(s):
    return (s.replace("\\\\", "\\")
            .replace("\\(", "(")
            .replace("\\)", ")")
            .replace("\\n", " ")
            .replace("\\r", " ")
            .replace("\\t", " ")
            .replace("\\b", "")
            .replace("\\f", ""))


def parse_lnp_pdf_calendar(pdf_text, known_teams=None):
    if not pdf_text:
        return {}
    round_map = {}
    known_norm = None
    if known_teams:
        known_norm = sorted(
            {normalise(t): t for t in known_teams if t}.items(),
            key=lambda kv: -len(kv[0]),
        )
    match_start = re.compile(r"(\d{1,2})\s+(\d{2}/\d{2}/\d{4})\s+")
    matches = list(match_start.finditer(pdf_text))
    if not matches:
        return {}
    segments = []
    for i, m in enumerate(matches):
        round_num, _date = m.group(1), m.group(2)
        try:
            round_int = int(round_num)
        except ValueError:
            continue
        if not (1 <= round_int <= 80):
            continue
        rest_start = m.end()
        rest_end = matches[i + 1].start() if i + 1 < len(matches) else len(pdf_text)
        rest = pdf_text[rest_start:rest_end].strip()
        rest = re.split(r"\bRiposa\b[: ]", rest, maxsplit=1)[0].strip()
        segments.append((round_int, rest))

    for round_int, rest in segments:
        home = away = None
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
        if home is None:
            m2 = re.match(r"^(.+?)\s{2,}(.+?)$", rest)
            if m2:
                home = normalise(m2.group(1))
                away = normalise(m2.group(2))
        if home and away:
            round_map[(home, away)] = round_int
    return round_map


def fetch_lnp_pdf_round_map(league_path, season, girone_letter=None, known_teams=None):
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
    return {w for w in name_norm.split() if len(w) >= 4}


def _teams_match(name_a, name_b):
    if name_a == name_b:
        return True
    if name_a in name_b or name_b in name_a:
        return True
    ta = _team_tokens(name_a)
    tb = _team_tokens(name_b)
    shared = ta & tb
    if len(shared) >= 2:
        return True
    if any(len(t) >= 5 for t in shared):
        return True
    return False


def round_for_match(pdf_round_map, home, away):
    if not pdf_round_map:
        return None
    h_n = normalise(home)
    a_n = normalise(away)
    if (h_n, a_n) in pdf_round_map:
        return pdf_round_map[(h_n, a_n)]
    for (ph, pa), r in pdf_round_map.items():
        if _teams_match(h_n, ph) and _teams_match(a_n, pa):
            return r
    return None


# ================================================================
# DOMINO API — RISULTATI IN TEMPO REALE
# ================================================================

def domino_season_code(season):
    try:
        y1 = int(season.split("-")[0])
        y2_short = season.split("-")[1]
        return f"x{str(y1)[-2:]}{y2_short}"
    except (ValueError, IndexError):
        return None


def fetch_domino_scores(league_path, girone_letter, season, rounds):
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


def _fetch_playoff_scores_domino(league_path, season):
    """
    Prova Domino API per recuperare risultati playoff.
    Due strategie:
    1. Codici playoff dedicati (ita3_b_poff, etc.) con round 1-5
    2. Codice regular (ita3_b) con round 39-50 (continuazione numerazione)
    Se round 1 di un codice non risponde, salta i round successivi.
    """
    year = domino_season_code(season)
    if not year:
        return {}

    results = {}

    # Strategia 1: codici playoff dedicati
    codes = PLAYOFF_PAGE_CODES.get(league_path, [])
    for code in codes:
        for rnd in range(1, 6):
            url = (f"https://lnpstat.domino.it/getstatisticsfiles"
                   f"?task=schedule&year={year}&league={code}&round={rnd}")
            raw = fetch(url, timeout=5)
            if not raw:
                if rnd == 1:
                    break
                continue
            try:
                games = json.loads(raw)
                if not isinstance(games, list):
                    if rnd == 1:
                        break
                    continue
            except (json.JSONDecodeError, TypeError):
                if rnd == 1:
                    break
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

    if results:
        return results

    # Strategia 2: codice regular con round > 38 (playoff come continuazione)
    girone_codes = {
        "serie-b": ["ita3_b", "ita3_a"],
        "serie-a2": ["ita2"],
    }
    for code in girone_codes.get(league_path, []):
        found_any = False
        for rnd in range(39, 51):
            url = (f"https://lnpstat.domino.it/getstatisticsfiles"
                   f"?task=schedule&year={year}&league={code}&round={rnd}")
            raw = fetch(url, timeout=5)
            if not raw:
                if not found_any:
                    break
                continue
            try:
                games = json.loads(raw)
                if not isinstance(games, list) or not games:
                    if not found_any:
                        break
                    continue
            except (json.JSONDecodeError, TypeError):
                if not found_any:
                    break
                continue
            found_any = True
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


def _fetch_scores_from_lnp_calendar(league_path, team_aliases):
    """
    Recupera risultati dal calendario centrale LNP (/serie/{id}/calendario).
    Questa pagina mostra TUTTE le partite della lega e potrebbe includere
    i playoff prima che le pagine squadra siano aggiornate.
    """
    serie_id = LEAGUE_SERIE_IDS.get(league_path)
    if not serie_id:
        return []
    url = f"https://www.legapallacanestro.com/serie/{serie_id}/calendario"
    html = fetch(url, timeout=10)
    if not html or len(html) < 1000:
        return []
    all_matches = parse_lnp_calendar(html)
    if not all_matches:
        return []
    # Filtra solo le partite della nostra squadra con risultato
    aliases_norm = [normalise(a) for a in team_aliases if a]
    results = []
    for m in all_matches:
        if m.get("sh") is None:
            continue
        h_n = normalise(m.get("home", ""))
        a_n = normalise(m.get("away", ""))
        is_ours = any(
            (an in h_n or h_n in an or an in a_n or a_n in an)
            for an in aliases_norm
        )
        if is_ours:
            results.append(m)
    return results


def _parse_last_result(html, team_aliases):
    """
    Parsa l'ultimo risultato dalla pagina squadra LNP.
    Cerca data + punteggio vicino ai nomi squadra nella sezione
    'ultima partita' / 'risultat'. Restituisce {date,home,away,sh,sa} o None.
    """
    if not html:
        return None
    text = re.sub(r'<[^>]+>', '\n', html)
    text = re.sub(r'[ \t]+', ' ', text)
    aliases_norm = [normalise(a) for a in team_aliases if a]
    lower = text.lower()
    idx = lower.find('ultima partita')
    if idx == -1:
        idx = lower.find('risultat')
    if idx == -1:
        return None
    window = text[idx:idx + 600]
    date_pat = re.compile(
        r'(\d{1,2})\s+(gen\w*|feb\w*|mar\w*|apr\w*|mag\w*|'
        r'giu\w*|lug\w*|ago\w*|set\w*|ott\w*|nov\w*|dic\w*)',
        re.IGNORECASE,
    )
    dm = date_pat.search(window)
    if not dm:
        return None
    month = _MONTHS_IT.get(dm.group(2).lower()[:3])
    if not month:
        return None
    date_str = f"{datetime.now().year}-{month}-{int(dm.group(1)):02d}"
    sm = re.search(r'(\d{2,3})\s*[-–]\s*(\d{2,3})', window)
    if not sm:
        return None
    sh, sa = int(sm.group(1)), int(sm.group(2))
    if sh == 0 and sa == 0:
        return None
    around = window[max(0, sm.start()-200):sm.end()+200]
    lines = [ln.strip() for ln in around.split('\n') if len(ln.strip()) >= 8]
    home = away = None
    for ln in lines:
        ln_n = normalise(ln)
        if any(an in ln_n or ln_n in an for an in aliases_norm):
            if not home:
                home = ln.strip()
            continue
        if home and not away and not re.match(r'^[\d\-–:/]', ln.strip()):
            away = ln.strip()
            break
    if not home:
        return None
    return {"date": date_str, "home": home, "away": away or "", "sh": sh, "sa": sa}


def _fetch_playoff_scores_from_rss(team_aliases, season):
    """
    Fonte primaria per punteggi playoff via RSS.
    Fonti affidabili e category-agnostic (seguono la squadra in A2/A):
      1. sportando.basketball/feed/ — testata professionale, copre A/A2/B
      2. basketinside.com/feed/    — testata italiana, buona copertura B
    LNP non ha feed RSS pubblico (410 Gone).
    """
    RSS_SOURCES = [
        "https://sportando.basketball/feed/",
        "https://basketinside.com/feed/",
    ]
    aliases_norm = [normalise(a) for a in team_aliases if a]
    results = []
    today = datetime.now().date()

    for rss_url in RSS_SOURCES:
        raw = fetch(rss_url, timeout=8)
        if not raw or len(raw) < 500:
            continue
        # Accetta sia RSS che Atom
        if "<rss" not in raw.lower() and "<feed" not in raw.lower():
            continue

        items = re.findall(r'<item>(.*?)</item>', raw, re.DOTALL)
        if not items:
            items = re.findall(r'<entry>(.*?)</entry>', raw, re.DOTALL)

        for item in items:
            # Filtra per data (ultimi 7 giorni)
            pub_m = re.search(r'<pubDate>(.*?)</pubDate>|<updated>(.*?)</updated>', item)
            if pub_m:
                try:
                    from email.utils import parsedate
                    raw_date = (pub_m.group(1) or pub_m.group(2) or "").strip()
                    pt = parsedate(raw_date)
                    if pt and (today - datetime(*pt[:6]).date()).days > 7:
                        continue
                except Exception:
                    pass

            # Estrai titolo + corpo
            title_m = re.search(r'<title[^>]*>(.*?)</title>', item, re.DOTALL)
            body_m = (re.search(r'<content:encoded>(.*?)</content:encoded>', item, re.DOTALL)
                      or re.search(r'<description>(.*?)</description>', item, re.DOTALL)
                      or re.search(r'<summary[^>]*>(.*?)</summary>', item, re.DOTALL))
            if not body_m:
                continue
            title = re.sub(r'<[^>]+>|<!\[CDATA\[|\]\]>', '', title_m.group(1) if title_m else "").lower()
            body = re.sub(r'<!\[CDATA\[|\]\]>', '', body_m.group(1))
            body = re.sub(r'<[^>]+>', ' ', body)
            body = re.sub(r'\s+', ' ', body)

            # Solo articoli playoff/play-in
            keywords = ['playoff', 'play-off', 'quarti', 'semifinal',
                        'gara 1', 'gara 2', 'gara 3', 'gara 4', 'gara 5',
                        'gara-1', 'gara-2', 'gara-3']
            if not any(kw in title + body[:300].lower() for kw in keywords):
                continue

            # Estrai punteggi: "TeamA-TeamB NN-NN" con separatori vari
            score_pat = re.compile(
                r'([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\d\'\.]{3,45}?)\s*[-–]\s*'
                r'([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\d\'\.]{3,45}?)\s+'
                r'(\d{2,3})\s*[-–]\s*(\d{2,3})'
            )
            for m in score_pat.finditer(body):
                h_raw = m.group(1).strip()
                a_raw = m.group(2).strip()
                sh, sa = int(m.group(3)), int(m.group(4))
                if sh == 0 and sa == 0:
                    continue
                h_n = normalise(h_raw)
                a_n = normalise(a_raw)
                is_ours = any(
                    an in h_n or h_n in an or an in a_n or a_n in an
                    for an in aliases_norm
                )
                if not is_ours:
                    continue
                # Cerca data nell'articolo (DD/MM/YYYY o YYYY-MM-DD)
                date_str = None
                for dp in (r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})',
                           r'(\d{4})-(\d{2})-(\d{2})'):
                    dm = re.search(dp, body)
                    if dm:
                        g = dm.groups()
                        if len(g[0]) == 4:
                            date_str = f"{g[0]}-{g[1]}-{g[2]}"
                        else:
                            date_str = f"{g[2]}-{g[1].zfill(2)}-{g[0].zfill(2)}"
                        break
                results.append({
                    "home": h_raw, "away": a_raw,
                    "sh": sh, "sa": sa, "date": date_str,
                })

        if results:
            break

    return results
    """
    Parsa l'ultimo risultato dalla pagina squadra LNP.
    Cerca data + punteggio vicino ai nomi squadra nella sezione
    'ultima partita' o 'risultat'. Restituisce {date, home, away, sh, sa} o None.
    """
    if not html:
        return None
    text = re.sub(r'<[^>]+>', '\n', html)
    text = re.sub(r'[ \t]+', ' ', text)
    aliases_norm = [normalise(a) for a in team_aliases if a]
    lower = text.lower()
    idx = lower.find('ultima partita')
    if idx == -1:
        idx = lower.find('risultat')
    if idx == -1:
        return None
    window = text[idx:idx + 600]
    date_pat = re.compile(
        r'(\d{1,2})\s+'
        r'(gen(?:\w*)?|feb(?:\w*)?|mar(?:\w*)?|apr(?:\w*)?|mag(?:\w*)?|'
        r'giu(?:\w*)?|lug(?:\w*)?|ago(?:\w*)?|set(?:\w*)?|ott(?:\w*)?|'
        r'nov(?:\w*)?|dic(?:\w*)?)',
        re.IGNORECASE,
    )
    dm = date_pat.search(window)
    if not dm:
        return None
    day = int(dm.group(1))
    month = _MONTHS_IT.get(dm.group(2).lower()[:3])
    if not month:
        return None
    date_str = f"{datetime.now().year}-{month}-{day:02d}"
    score_m = re.search(r'(\d{2,3})\s*[-–]\s*(\d{2,3})', window)
    if not score_m:
        return None
    sh, sa = int(score_m.group(1)), int(score_m.group(2))
    if sh == 0 and sa == 0:
        return None
    around = window[max(0, score_m.start()-200):score_m.end()+200]
    lines = [ln.strip() for ln in around.split('\n') if len(ln.strip()) >= 8]
    home = away = None
    for ln in lines:
        ln_n = normalise(ln)
        if any(an in ln_n or ln_n in an for an in aliases_norm):
            if not home:
                home = ln.strip()
            continue
        if home and not away and not re.match(r'^[\d\-–:/]', ln.strip()):
            away = ln.strip()
            break
    if not home:
        return None
    return {"date": date_str, "home": home, "away": away or "", "sh": sh, "sa": sa}


def _parse_match_page_score(html):
    """
    Parsa data, home, away, score da una match page LNP.
    Formato: "Data: DD/MM/YYYY" + "Casa · TeamA · NN — NN · Ospite · TeamB"
    Restituisce dict {date, home, away, sh, sa} o None.
    """
    if not html or "Data:" not in html:
        return None

    dm = re.search(r'Data:\s*(\d{2}/\d{2}/\d{4})', html)
    if not dm:
        return None
    dd, mm, yyyy = dm.group(1).split('/')
    date_str = f"{yyyy}-{mm}-{dd}"

    # Punteggio: "NN — NN" o "NN – NN" o "NN - NN"
    sm = re.search(r'(\d{2,3})\s*[—–\-]\s*(\d{2,3})', html)
    if not sm:
        return None
    sh, sa = int(sm.group(1)), int(sm.group(2))
    if sh == 0 and sa == 0:
        return None

    # Squadre: "Casa" e "Ospite" nei tag adiacenti
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text)
    home_m = re.search(r'Casa\s*[·•]\s*([A-Za-z\s\d\'\.]+?)\s*(?:[·•]|\d{2,3}\s*[—–\-])', text)
    away_m = re.search(r'Ospite\s*[·•]\s*([A-Za-z\s\d\'\.]+?)(?:\s*[·•]|$|\s{2,})', text)
    if not home_m or not away_m:
        return None

    return {
        "date": date_str,
        "home": home_m.group(1).strip(),
        "away": away_m.group(1).strip(),
        "sh": sh,
        "sa": sa,
    }


def _fetch_playoff_match_page_scores(league_path, season, team_aliases):
    """
    Soluzione definitiva per punteggi playoff.
    Le match page LNP (/wp/match/...) contengono il punteggio in HTML statico
    e si aggiornano entro minuti dalla fine della partita.

    Strategia di discovery del match ID (2 fasi):
    1. SCAN della pagina playoff: cerca link /wp/match/ direttamente nell'HTML
    2. BRUTE FORCE: prova URL sequenziali (codice playoff _1.._20, poi regular _343.._380)

    Una volta trovato l'URL della match page, il parsing è immediato e robusto.
    """
    codes = PLAYOFF_PAGE_CODES.get(league_path, [])
    serie_id = LEAGUE_SERIE_IDS.get(league_path)
    if not codes or not serie_id:
        return []

    try:
        y1 = int(season.split("-")[0])
        year = y1 + 1
        season_code = f"x{str(y1)[-2:]}{season.split('-')[1]}"  # "x2526"
    except (ValueError, IndexError):
        return []

    aliases_norm = [normalise(a) for a in team_aliases if a]
    found_urls = set()

    # --- Fase 1: scan pagine playoff per link /wp/match/ ---
    for code in codes:
        url = (f"https://www.legapallacanestro.com/serie/{serie_id}"
               f"/playoff-playout/{year}/{code}")
        html = fetch(url)
        if not html:
            continue
        for m in re.finditer(r'/wp/match/([^/"\'>\s]+)/([^/"\'>\s]+)/([^/"\'>\s]+)', html):
            full_url = f"https://www.legapallacanestro.com{m.group(0)}"
            found_urls.add(full_url)

    # --- Fase 2: brute force se Fase 1 non ha trovato nulla ---
    if not found_urls:
        # Codici playoff dedicati (ita3_b_poff_1..20)
        for code in codes:
            consecutive_404 = 0
            for n in range(1, 21):
                url = (f"https://www.legapallacanestro.com/wp/match"
                       f"/{code}_{n}/{code}/{season_code}")
                html = fetch(url, timeout=5)
                if not html or len(html) < 500 or "Data:" not in html:
                    consecutive_404 += 1
                    if consecutive_404 >= 3:
                        break
                    continue
                consecutive_404 = 0
                found_urls.add(url)

        # Continuazione regular (ita3_b_343..380)
        if not found_urls:
            regular_codes = {"serie-b": ["ita3_b", "ita3_a"],
                             "serie-a2": ["ita2"]}.get(league_path, [])
            for code in regular_codes:
                # Stima: regular arriva a ~342, playoff inizia da 343
                consecutive_404 = 0
                for n in range(343, 381):
                    url = (f"https://www.legapallacanestro.com/wp/match"
                           f"/{code}_{n}/{code}/{season_code}")
                    html = fetch(url, timeout=5)
                    if not html or len(html) < 500 or "Data:" not in html:
                        consecutive_404 += 1
                        if consecutive_404 >= 5:
                            break
                        continue
                    consecutive_404 = 0
                    found_urls.add(url)

    if not found_urls:
        return []

    # --- Parsing di ogni match page trovata ---
    results = []
    for url in found_urls:
        html = fetch(url, timeout=5)
        if not html:
            continue
        m_data = _parse_match_page_score(html)
        if not m_data or m_data.get("sh") is None:
            continue
        h_n = normalise(m_data["home"])
        a_n = normalise(m_data["away"])
        is_ours = any(
            (an in h_n or h_n in an or an in a_n or a_n in an)
            for an in aliases_norm
        )
        if is_ours:
            results.append(m_data)

    return results
    """
    Parsa l'ultimo risultato dalla pagina squadra LNP.
    Cerca pattern di punteggio (es. "92 - 76") vicino ai nomi delle squadre
    nella zona "ultima partita" o "risultat" della pagina.
    Restituisce dict {date, home, away, sh, sa} o None.
    """
    if not html:
        return None

    text = re.sub(r'<[^>]+>', '\n', html)
    text = re.sub(r'[ \t]+', ' ', text)
    aliases_norm = [normalise(a) for a in team_aliases if a]

    # Cerca "ultima partita" o "risultat"
    lower = text.lower()
    idx = lower.find('ultima partita')
    if idx == -1:
        idx = lower.find('risultat')
    if idx == -1:
        return None

    window = text[idx:idx + 600]

    # Cerca data italiana: "D{1,2} Mmm"
    date_pat = re.compile(
        r'(\d{1,2})\s+'
        r'(gen(?:\w*)?|feb(?:\w*)?|mar(?:\w*)?|apr(?:\w*)?|mag(?:\w*)?|'
        r'giu(?:\w*)?|lug(?:\w*)?|ago(?:\w*)?|set(?:\w*)?|ott(?:\w*)?|'
        r'nov(?:\w*)?|dic(?:\w*)?)',
        re.IGNORECASE,
    )
    dm = date_pat.search(window)
    if not dm:
        return None

    day = int(dm.group(1))
    month = _MONTHS_IT.get(dm.group(2).lower()[:3])
    if not month:
        return None
    year = datetime.now().year
    date_str = f"{year}-{month}-{day:02d}"

    # Cerca punteggio: "NN - NN" o "NN – NN"
    score_m = re.search(r'(\d{2,3})\s*[-–]\s*(\d{2,3})', window)
    if not score_m:
        return None
    sh, sa = int(score_m.group(1)), int(score_m.group(2))
    if sh == 0 and sa == 0:
        return None

    # Cerca nomi squadra vicino al punteggio
    around = window[max(0, score_m.start()-200):score_m.end()+200]
    lines = [ln.strip() for ln in around.split('\n') if len(ln.strip()) >= 8]

    home = away = None
    for ln in lines:
        ln_n = normalise(ln)
        if any(an in ln_n or ln_n in an for an in aliases_norm):
            if not home:
                home = ln.strip()
            continue
        if home and not away and len(ln.strip()) >= 8:
            if not re.match(r'^[\d\-–:/]', ln.strip()):
                away = ln.strip()
                break

    if not home:
        return None

    return {"date": date_str, "home": home, "away": away or "", "sh": sh, "sa": sa}


# ================================================================
# PLAYOFF/PLAY-IN — FETCH DA PAGINE DEDICATE LNP (v8.8)
# ================================================================

def fetch_playoff_matches(league_path, season, team_aliases):
    """
    Fetcha le pagine playoff/play-in di LNP e restituisce le partite
    che coinvolgono la squadra specificata.

    Pipeline a due livelli:
    1. Parsing tabella calendario <td> (per quando LNP pubblica il DOM).
    2. Parsing TESTO tabellone + date → genera tutte le gare in casa
       della serie corrente (best-of-5: CCFFC).

    Le gare non disputate vengono poi pulite da
    cleanup_unplayed_playoff_matches().
    """
    codes = PLAYOFF_PAGE_CODES.get(league_path, [])
    serie_id = LEAGUE_SERIE_IDS.get(league_path)
    if not codes or not serie_id:
        return []

    try:
        y1 = int(season.split("-")[0])
        year = y1 + 1
    except (ValueError, IndexError):
        return []

    aliases_norm = [normalise(a) for a in team_aliases if a]
    playoff_matches = []
    pages_html = []

    # === Livello 1: parsing tabella calendario ===
    for code in codes:
        url = (f"https://www.legapallacanestro.com/serie/{serie_id}"
               f"/playoff-playout/{year}/{code}")
        html = fetch(url)
        if not html or len(html) < 1000:
            continue
        pages_html.append(html)

        page_matches = parse_lnp_calendar(html)
        if not page_matches:
            continue

        for m in page_matches:
            h_n = normalise(m.get("home", ""))
            a_n = normalise(m.get("away", ""))
            is_ours = any(
                (an in h_n or h_n in an or an in a_n or a_n in an)
                for an in aliases_norm
            )
            if is_ours:
                playoff_matches.append(m)

    if playoff_matches:
        print(f"  📡 {len(playoff_matches)} partite playoff da calendario LNP")
        return playoff_matches

    # === Livello 2: genera gare casa da testo tabellone + date ===
    for html in pages_html:
        generated = _generate_home_games_from_bracket(
            html, aliases_norm, team_aliases, year
        )
        if generated:
            print(f"  📡 {len(generated)} gare casa generate "
                  f"da tabellone playoff (best-of-5)")
            return generated

    return playoff_matches


def _generate_home_games_from_bracket(html, aliases_norm, team_aliases_raw, year):
    """
    Parsa il testo descrittivo della pagina playoff per estrarre il matchup
    e le date del turno, poi genera tutte le gare IN CASA della serie.

    Formato LNP:
      "Serie N - TeamA (1^ girone X) - TeamB (N^ girone Y, ...)"
      TeamA = higher seed → casa G1, G2, G5
      TeamB = lower seed  → casa G3, G4

    Date:
      "Quarti di Finale - Venerdì 8, domenica 10, ..."
    """
    text = re.sub(r'<[^>]+>', '\n', html)
    text = re.sub(r'[ \t]+', ' ', text)

    # --- Cerca matchup della nostra squadra ---
    serie_pat = re.compile(
        r'Serie\s+\d+\s*[-–]\s*'
        r'(.+?)\s*\(\d+\^[^)]*\)\s*[-–]\s*'
        r'(.+?)\s*\(\d+\^[^)]*\)',
        re.IGNORECASE,
    )

    our_team_raw = None
    opponent_raw = None
    is_higher_seed = None
    match_pos = None

    for m in serie_pat.finditer(text):
        team_a = m.group(1).strip()
        team_b = m.group(2).strip()
        ta_n = normalise(team_a)
        tb_n = normalise(team_b)

        for an in aliases_norm:
            if an in ta_n or ta_n in an:
                our_team_raw = team_a
                opponent_raw = team_b
                is_higher_seed = True
                match_pos = m.start()
                break
            if an in tb_n or tb_n in an:
                our_team_raw = team_b
                opponent_raw = team_a
                is_higher_seed = False
                match_pos = m.start()
                break
        if our_team_raw:
            break

    if not our_team_raw or not opponent_raw:
        return []

    # --- Determina il turno (QF/SF/F) ---
    # Cerca la heading di sezione PIÙ VICINA al matchup (rfind = ultima occorrenza).
    # La pagina ha le date ("Semifinali - ...") PRIMA del tabellone ("QUARTI DI FINALE"),
    # quindi la semplice presenza di "SEMIFINAL" nel testo precedente non è affidabile.
    before_upper = text[:match_pos].upper()
    candidates = [
        (before_upper.rfind('QUARTI'), 'quarti'),
        (before_upper.rfind('SEMIFINAL'), 'semifinali'),
    ]
    candidates = [(pos, key) for pos, key in candidates if pos >= 0]
    if candidates:
        round_key = max(candidates, key=lambda x: x[0])[1]
    else:
        round_key = 'quarti'

    # --- Parsa date del turno ---
    dates = _parse_round_dates(text, round_key, year)
    if len(dates) < 3:
        return []

    # --- Genera gare in casa ---
    # Best-of-5: CASA-CASA-FUORI-FUORI-CASA (higher seed)
    # G1-G3 sempre disputate. G4 tentativa (se non 3-0). G5 tentativa (se 2-2).
    # Tupla: (indice_data, numero_gara, tentativa)
    if is_higher_seed:
        home_specs = [(0, 1, False), (1, 2, False), (4, 5, True)]
    else:
        home_specs = [(2, 3, False), (3, 4, True)]

    matches = []
    for date_idx, game_num, tentative in home_specs:
        if date_idx < len(dates):
            m = {
                "date": dates[date_idx],
                "time": "20:00",
                "home": our_team_raw,
                "away": opponent_raw,
                "sh": None,
                "sa": None,
                "game_num": game_num,
            }
            if tentative:
                m["tentative"] = True
            matches.append(m)

    return matches


def _parse_round_dates(text, round_key, year):
    """
    Estrae le 5 date di un turno playoff dal testo della pagina LNP.
    "Quarti di Finale - Venerdì 8, domenica 10, ... maggio"
    → ["2026-05-08", "2026-05-10", ...]
    """
    ROUND_PATTERNS = {
        'quarti': r'Quarti\s+di\s+Finale\s*[-–]\s*(.+?)(?:\n|Semifinal)',
        'semifinali': r'Semifinali\s*[-–]\s*(.+?)(?:\n|Final[^i])',
        'finali': r'Finali\s*[-–]\s*(.+?)(?:\n|NOTE|$)',
    }
    pat = ROUND_PATTERNS.get(round_key)
    if not pat:
        return []
    m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
    if not m:
        return []
    line = m.group(1).strip()

    month_match = re.search(
        r'(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|'
        r'agosto|settembre|ottobre|novembre|dicembre)',
        line, re.IGNORECASE,
    )
    if not month_match:
        return []
    month = _MONTHS_IT.get(month_match.group(1).lower()[:3])
    if not month:
        return []

    days = [int(d) for d in re.findall(r'\b(\d{1,2})\b', line)]
    return [f"{year}-{month}-{d:02d}" for d in days]


def cleanup_unplayed_playoff_matches(matches):
    """
    Rimuove SOLO partite playoff/play-in TENTATIVE (G4/G5) con sh=None
    la cui data è passata da più di 2 giorni (serie finita prima).
    G1/G2/G3 non vengono mai rimosse anche se sh=None.
    """
    cutoff = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")
    to_remove = []
    for i, m in enumerate(matches):
        if m.get("phase") in ("playoff", "playin") \
                and m.get("tentative") == True \
                and m.get("sh") is None \
                and m.get("date", "9") < cutoff:
            to_remove.append(i)
            print(f"  🗑️  Rimossa {m.get('phase')} tentative: "
                  f"{m.get('date')} vs {m.get('away')}")
    for i in reversed(to_remove):
        matches.pop(i)
    return len(to_remove)

_MONTHS_IT = {
    'gen': '01', 'feb': '02', 'mar': '03', 'apr': '04',
    'mag': '05', 'giu': '06', 'lug': '07', 'ago': '08',
    'set': '09', 'ott': '10', 'nov': '11', 'dic': '12',
}


def parse_upcoming_from_team_page(html, team_aliases, season=""):
    """
    Parsa il widget "Prossima partita" dalla pagina squadra LNP.
    Questo widget è presente nell'HTML statico della pagina squadra e
    mostra la prossima partita schedulata, incluse le partite playoff
    che NON appaiono nella tabella calendario.

    Formato tipico nel testo HTML:
      "Prossima partita ... 8 Mag ... h20:30 ... Team A ... Team B"

    Restituisce lista (0 o 1 match) di dict {date, time, home, away, sh, sa}.
    La partita viene restituita SOLO se è successiva alla data odierna
    e coinvolge una delle squadre tracked (verifica con aliases).
    """
    if not html:
        return []

    # Strip HTML, collassa spazi
    text = re.sub(r'<[^>]+>', '\n', html)
    text = re.sub(r'[ \t]+', ' ', text)

    # Cerca "prossima partita"
    lower = text.lower()
    idx = lower.find('prossima partita')
    if idx == -1:
        return []

    # Finestra di ricerca: 800 char dopo "prossima partita"
    window = text[idx:idx + 800]

    # Cerca pattern data: "D{1,2} Mmm" seguito opzionalmente da "h HH:MM"
    date_pat = re.compile(
        r'(\d{1,2})\s+'
        r'(gen(?:naio)?|feb(?:braio)?|mar(?:zo)?|apr(?:ile)?|mag(?:gio)?|'
        r'giu(?:gno)?|lug(?:lio)?|ago(?:sto)?|set(?:tembre)?|ott(?:obre)?|'
        r'nov(?:embre)?|dic(?:embre)?)',
        re.IGNORECASE,
    )
    dm = date_pat.search(window)
    if not dm:
        return []

    day = int(dm.group(1))
    month_key = dm.group(2).lower()[:3]
    month = _MONTHS_IT.get(month_key)
    if not month:
        return []

    # Anno: secondo anno della stagione (playoff = mag-giu)
    try:
        y1 = int(season.split("-")[0])
        year = y1 + 1
    except (ValueError, IndexError):
        year = datetime.now().year

    date_str = f"{year}-{month}-{day:02d}"

    # Cerca orario dopo la data
    time_str = "20:00"  # default
    after_date = window[dm.end():]
    tm = re.search(r'h\s*(\d{2}:\d{2})', after_date[:100])
    if tm:
        time_str = tm.group(1)
        after_time = after_date[tm.end():]
    else:
        tm2 = re.search(r'(\d{2}:\d{2})', after_date[:100])
        if tm2:
            time_str = tm2.group(1)
            after_time = after_date[tm2.end():]
        else:
            after_time = after_date

    # Scarta se la data è nel passato
    try:
        match_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        if match_date < date.today() - timedelta(days=1):
            return []
    except ValueError:
        return []

    # Cerca nomi squadra DOPO l'orario per non catturare frammenti time
    lines = [ln.strip() for ln in after_time.split('\n') if ln.strip()]
    team_names = []
    for ln in lines:
        # Filtra righe troppo corte o che sembrano etichette/date/orari
        if len(ln) < 8:
            continue
        if re.match(r'^[\d\-–:/h]', ln):
            continue
        if ln.lower().startswith(('ore ', 'playoff', 'play-in', 'serie',
                                  'acquista', 'bigliett', 'prossim')):
            continue
        # Sembra un nome squadra
        team_names.append(ln)
        if len(team_names) >= 2:
            break

    if len(team_names) < 2:
        return []

    home = team_names[0].strip()
    away = team_names[1].strip()

    # Verifica che almeno una sia la nostra squadra
    aliases_norm = [normalise(a) for a in team_aliases if a]
    h_n = normalise(home)
    a_n = normalise(away)
    is_ours = any(
        (an in h_n or h_n in an or an in a_n or a_n in an)
        for an in aliases_norm
    )
    if not is_ours:
        return []

    return [{
        "date": date_str,
        "time": time_str,
        "home": home,
        "away": away,
        "sh": None,
        "sa": None,
    }]


# ================================================================
# BUILD ROUND MAP (FALLBACK BASATO SU DATE)
# ================================================================

def build_round_map(all_girone_matches):
    if not all_girone_matches:
        return {}
    MAX_ROUND_SPAN_DAYS = 3
    SMALL_ROUND_THRESHOLD = 3
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

    match_round = []
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
        if src_id == dst_id or src_id not in rounds or dst_id not in rounds:
            return False
        return len(rounds[src_id]["teams"] & rounds[dst_id]["teams"]) == 0

    def merge(src_id, dst_id):
        rounds[dst_id]["teams"] |= rounds[src_id]["teams"]
        rounds[dst_id]["matches"].extend(rounds[src_id]["matches"])
        if rounds[src_id]["first_date"] < rounds[dst_id]["first_date"]:
            rounds[dst_id]["first_date"] = rounds[src_id]["first_date"]
        del rounds[src_id]

    max_iter = 200
    while max_iter > 0:
        max_iter -= 1
        small_ids = [
            r_id for r_id, info in rounds.items()
            if len(info["matches"]) <= SMALL_ROUND_THRESHOLD
        ]
        if not small_ids:
            break
        best_merge = None
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
            break
        merge(best_merge[0], best_merge[1])

    sorted_round_ids = sorted(rounds.keys(),
                              key=lambda r: rounds[r]["first_date"])
    renumber = {old: new for new, old in enumerate(sorted_round_ids, start=1)}
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
    aliases_norm = [normalise(a) for a in team_aliases if a]
    updated = 0
    lnp_home = []
    for lm in lnp_matches:
        h_n = normalise(lm["home"])
        if any(an in h_n or h_n in an for an in aliases_norm):
            lnp_home.append(lm)

    for m in matches:
        if m.get("team") != team_key:
            continue
        target = None
        m_away_n = normalise(m.get("away", ""))
        for lm in lnp_home:
            if lm["date"] == m["date"]:
                target = lm
                break
        if not target and m_away_n and m.get("phase", "regular") == "regular":
            # Fallback per nome avversario — SOLO regular season.
            # In playoff/playin lo stesso avversario appare in tutte le gare
            # della serie: il fallback corromperebbe le date.
            for lm in lnp_home:
                lm_away_n = normalise(lm.get("away", ""))
                if lm_away_n and (m_away_n in lm_away_n or lm_away_n in m_away_n):
                    target = lm
                    break
        if not target:
            continue
        changed = False
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
    if pdf_round_map is None:
        pdf_round_map = {}
    if date_round_map is None:
        date_round_map = {}
    aliases_norm = [normalise(a) for a in team_aliases if a]
    inserted = 0
    existing_ids = {m.get("id") for m in matches}

    existing_by_date_away = set()
    existing_by_away = {}
    for m in matches:
        if m.get("team") != team_key:
            continue
        away_n = normalise(m.get("away", ""))
        date_s = m.get("date", "")
        if away_n:
            existing_by_date_away.add((date_s, away_n))
            existing_by_away.setdefault(away_n, []).append(date_s)

    def is_duplicate(lm_date, lm_away_n, is_postseason=False):
        if not lm_away_n:
            return False
        if (lm_date, lm_away_n) in existing_by_date_away:
            return True
        if is_postseason:
            return False
        for existing_date in existing_by_away.get(lm_away_n, []):
            try:
                d1 = datetime.strptime(lm_date, "%Y-%m-%d").date()
                d2 = datetime.strptime(existing_date, "%Y-%m-%d").date()
                if abs((d1 - d2).days) <= 10:
                    return True
            except Exception:
                continue
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

    lnp_home = []
    for lm in lnp_matches:
        h_n = normalise(lm["home"])
        if any(an in h_n or h_n in an for an in aliases_norm):
            lnp_home.append(lm)

    for lm in lnp_home:
        lm_away_n = normalise(lm.get("away", ""))
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

        prefix = team_key[0]
        if phase == "regular":
            new_id = f"{prefix}{real_round:02d}"
        elif phase == "playin":
            new_id = f"{prefix}_pi_r{real_round}"
        else:
            new_id = f"{prefix}_po_r{real_round}"

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
        # Campi playoff opzionali (v8.9)
        if lm.get("game_num"):
            new_match["game_num"] = lm["game_num"]
        if lm.get("tentative"):
            new_match["tentative"] = True
        matches.append(new_match)
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
    classifica_cache = {}
    teams_total = len(TRACKED_TEAMS)
    teams_safety_skipped = 0

    # Cleanup: rimuovi gare playoff passate non disputate (serie finite in <5)
    removed = cleanup_unplayed_playoff_matches(matches)
    if removed:
        updated += removed

    for team_key, team_info in TRACKED_TEAMS.items():
        slug = team_info["slug"]
        aliases = list(team_info["name_aliases"])

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

        league_label = LEAGUE_LABELS.get(league_path, league_path)
        cfg_team = config.setdefault("teams", {}).setdefault(team_key, {})
        if cfg_team.get("serie") != league_label:
            old = cfg_team.get("serie", "?")
            print(f"  🔄 [{team_key}] cambio lega rilevato: {old} → {league_label}")
            cfg_team["serie"] = league_label
            updated += 1

        serie_id = LEAGUE_SERIE_IDS.get(league_path)
        if serie_id:
            classifica_url = f"https://www.legapallacanestro.com/serie/{serie_id}/classifica"
            if config.get("classifica_url") != classifica_url:
                config["classifica_url"] = classifica_url
                updated += 1

        # Parse calendario squadra (regular season)
        lnp_matches = parse_lnp_calendar(html)
        if not lnp_matches:
            print(f"  ⚠️  [{team_key}] calendario LNP vuoto")
            teams_safety_skipped += 1
            continue
        lnp_matches = filter_season(lnp_matches, config.get("season"))
        n_from_team_page = len(lnp_matches)
        print(f"  📋 [{team_key}] {n_from_team_page} partite nel calendario LNP")

        # Sanity check usa solo il conteggio regular (pre-playoff)
        existing_home = sum(1 for m in matches if m.get("team") == team_key)
        if existing_home > 0 and n_from_team_page < existing_home:
            print(f"  🚨 [{team_key}] SAFETY SKIP: lnp_matches={n_from_team_page} "
                  f"< home esistenti={existing_home}. Parse sospetto.")
            teams_safety_skipped += 1
            continue

        # regular_end_date: dedotto PRIMA di aggiungere partite playoff
        n_regular_league = N_REGULAR_GAMES_BY_LEAGUE.get(league_path, 36)
        regular_end_date = None
        lnp_sorted = sorted(lnp_matches, key=lambda m: m.get("date", ""))
        if len(lnp_sorted) >= n_regular_league:
            regular_end_date = lnp_sorted[n_regular_league - 1].get("date")

        # v8.8: Fetch partite playoff/play-in da pagine dedicate LNP
        playoff_extra = fetch_playoff_matches(
            league_path, config.get("season", ""), aliases
        )
        # v8.9: fallback — widget "Prossima partita" dalla pagina squadra
        if not playoff_extra:
            upcoming = parse_upcoming_from_team_page(
                html, aliases, config.get("season", "")
            )
            if upcoming:
                playoff_extra = upcoming
                print(f"  📡 [{team_key}] {len(upcoming)} partita/e "
                      f"da widget 'Prossima partita'")
        else:
            # Bracket parser ha orari placeholder (20:00). Il widget ha
            # l'orario reale della prossima gara: usalo per affinare.
            upcoming = parse_upcoming_from_team_page(
                html, aliases, config.get("season", "")
            )
            if upcoming:
                for w_m in upcoming:
                    for p_m in playoff_extra:
                        if p_m["date"] == w_m["date"] and p_m["time"] != w_m["time"]:
                            p_m["time"] = w_m["time"]
        if playoff_extra:
            existing_keys = {
                (m["date"], normalise(m["home"]), normalise(m["away"]))
                for m in lnp_matches
            }
            new_po = [
                m for m in playoff_extra
                if (m["date"], normalise(m["home"]), normalise(m["away"]))
                   not in existing_keys
            ]
            if new_po:
                lnp_matches.extend(new_po)
                print(f"  🏆 [{team_key}] +{len(new_po)} partite "
                      f"playoff/play-in da pagine LNP")

        # Aggiorna partite esistenti
        updated += update_home_matches(matches, team_key, aliases, lnp_matches)

        # W/L/pts solo da regular (lnp_sorted = pre-playoff)
        w, l, pts = calc_team_stats(lnp_sorted, aliases)
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
                season = config.get("season", "")
                girone_letter = (cfg_team.get("girone") or "").lower() or None
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
            r = round_for_match(pdf_round_map, m_home, m_away)
            if r is not None:
                return r
            return date_round_map.get(m_date)

        team_pos = None
        if full:
            entry = find_team_in_standings(full, aliases)
            if entry:
                new_standings[team_key]["pos"] = entry["pos"]
                new_standings[team_key]["w"] = entry["w"]
                new_standings[team_key]["l"] = entry["l"]
                new_standings[team_key]["pts"] = entry["pts"]
                team_pos = entry["pos"]
                print(f"  🏆 [{team_key}] pos: {entry['pos']}° su {len(full)} "
                      f"({entry['w']}V-{entry['l']}P, {entry['pts']}pt)")
            else:
                print(f"  ⚠️  [{team_key}] non trovata nella classifica calcolata")

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

        # Auto-insert nuove partite (regular + postseason)
        # regular_end_date già calcolato sopra (pre-playoff extension)
        inserted = auto_insert_new_home_matches(
            matches, team_key, aliases, lnp_matches, team_pos,
            pdf_round_map, date_round_map, regular_end_date
        )
        if inserted:
            updated += inserted

        # Fill punteggi — Domino API
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
                            for (dh, da), s in domino.items():
                                if _teams_match(key[0], dh) and _teams_match(key[1], da):
                                    score = s
                                    break
                        if score:
                            m["sh"], m["sa"] = score
                            print(f"  ⚡ [{team_key}] {m['away']}: "
                                  f"{score[0]}-{score[1]} (Domino API)")
                            updated += 1

        # Fill punteggi playoff — cascade a 4 fonti
        # Priorità: match pages > Domino playoff > calendario LNP > pagina squadra
        def get_missing_po():
            return [m for m in matches
                    if m.get("team") == team_key and m.get("sh") is None
                    and m.get("phase") in ("playoff", "playin")
                    and m.get("date", "9") < datetime.now().strftime("%Y-%m-%d")]

        missing_po = get_missing_po()
        if missing_po:

            # 0. Feed RSS (reggioacanestro / sportando) — entro ~12h dalla partita
            rss_results = _fetch_playoff_scores_from_rss(
                aliases, config.get("season", "")
            )
            for rss in rss_results:
                for m in missing_po:
                    h_n = normalise(m.get("home", ""))
                    a_n = normalise(m.get("away", ""))
                    if _teams_match(h_n, normalise(rss["home"])) and \
                            _teams_match(a_n, normalise(rss["away"])):
                        # La data nell'RSS può essere imprecisa: accetta se entro ±1 gg
                        date_ok = True
                        if rss.get("date") and m.get("date"):
                            try:
                                d1 = datetime.strptime(m["date"], "%Y-%m-%d").date()
                                d2 = datetime.strptime(rss["date"], "%Y-%m-%d").date()
                                date_ok = abs((d1 - d2).days) <= 1
                            except Exception:
                                pass
                        if date_ok:
                            m["sh"], m["sa"] = rss["sh"], rss["sa"]
                            print(f"  📰 [{team_key}] {m['away']}: "
                                  f"{rss['sh']}-{rss['sa']} (RSS)")
                            updated += 1
                            break

            missing_po = get_missing_po()

            # 1. Match pages LNP (fonte più affidabile: HTML statico, aggiornate in minuti)
            mp_results = _fetch_playoff_match_page_scores(
                league_path, config.get("season", ""), aliases
            )
            for mp in mp_results:
                for m in missing_po:
                    if m["date"] == mp["date"] and \
                            _teams_match(normalise(m["home"]), normalise(mp["home"])) and \
                            _teams_match(normalise(m["away"]), normalise(mp["away"])):
                        m["sh"], m["sa"] = mp["sh"], mp["sa"]
                        print(f"  ⚡ [{team_key}] {m['away']}: "
                              f"{mp['sh']}-{mp['sa']} (match page LNP)")
                        updated += 1
                        break

            missing_po = get_missing_po()

            # 2. Domino API con codici playoff + round 39+
            if missing_po:
                po_scores = _fetch_playoff_scores_domino(
                    league_path, config.get("season", "")
                )
                if po_scores:
                    for m in missing_po:
                        key = (normalise(m.get("home", "")), normalise(m.get("away", "")))
                        score = po_scores.get(key)
                        if not score:
                            for (dh, da), s in po_scores.items():
                                if _teams_match(key[0], dh) and _teams_match(key[1], da):
                                    score = s
                                    break
                        if score:
                            m["sh"], m["sa"] = score
                            print(f"  ⚡ [{team_key}] {m['away']}: "
                                  f"{score[0]}-{score[1]} (Domino playoff)")
                            updated += 1

            missing_po = get_missing_po()

            # 3. Calendario centrale LNP
            if missing_po:
                cal_matches = _fetch_scores_from_lnp_calendar(league_path, aliases)
                for m in missing_po:
                    m_h = normalise(m.get("home", ""))
                    m_a = normalise(m.get("away", ""))
                    for cm in cal_matches:
                        if cm["date"] == m["date"] and \
                                _teams_match(m_h, normalise(cm["home"])) and \
                                _teams_match(m_a, normalise(cm["away"])):
                            m["sh"], m["sa"] = cm["sh"], cm["sa"]
                            print(f"  ✅ [{team_key}] {m['away']}: "
                                  f"{cm['sh']}-{cm['sa']} (calendario LNP)")
                            updated += 1
                            break

            missing_po = get_missing_po()

            # 4. Pagina squadra — ultimo risultato
            if missing_po:
                last = _parse_last_result(html, aliases)
                if last:
                    for m in missing_po:
                        if m["date"] == last["date"] and \
                                _teams_match(normalise(m.get("home", "")),
                                             normalise(last.get("home", ""))):
                            m["sh"], m["sa"] = last["sh"], last["sa"]
                            print(f"  ✅ [{team_key}] {m['away']}: "
                                  f"{last['sh']}-{last['sa']} (pagina squadra)")
                            updated += 1

        # Fill punteggi — girone completo
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

    if json.dumps(new_standings, sort_keys=True) != initial_snap:
        updated += 1

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
    MIN_MATCHES_THRESHOLD = 30
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
    all_dates = []
    for d in discovered.values():
        all_dates.extend(m["date"] for m in d["lnp_matches"])
    if not all_dates:
        return None, None, None

    min_year = min(int(d[:4]) for d in all_dates)
    max_year = max(int(d[:4]) for d in all_dates)
    new_season = f"{min_year}-{str(max_year)[-2:]}"
    print(f"  📅 Stagione rilevata: {new_season}")

    for d in discovered.values():
        d["lnp_matches"] = filter_season(d["lnp_matches"], new_season)

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

    new_standings = {
        tk: {"pos": "-", "pts": 0, "w": 0, "l": 0}
        for tk in TRACKED_TEAMS
    }
    return new_matches, new_standings, new_season


# ================================================================
# MAIN
# ================================================================

def main():
    print(f"\n🏀 Roma Basket Updater v8.9 — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 55)

    data_path = Path("data.json")
    if data_path.exists():
        with open(data_path) as f:
            current = json.load(f)
        matches = current.get("matches", [])
        standings = current.get("standings", dict(BASE_STANDINGS))
        config = current.get("config", CONFIG_DEFAULT)
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

    if not matches:
        print(f"\n🔄 matches vuoto — attivazione bootstrap on-demand")
        new_matches, new_standings, new_season = bootstrap_new_season(
            config, config.get("season", "?")
        )
        if new_matches and new_standings and new_season:
            backup_path = Path("data.json.backup")
            if data_path.exists():
                backup_path.write_text(
                    data_path.read_text(encoding="utf-8"), encoding="utf-8")
                print(f"  💾 Backup salvato: {backup_path}")
            matches = new_matches
            standings = new_standings
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
            print(f"\n❌ Run abortito per safety. Exit code 1.")
            sys.exit(1)
        print(f"\n📝 Aggiornamenti: {total_updated}")
    else:
        print(f"\n💤 FUORI STAGIONE")
        new_matches, new_standings, new_season = bootstrap_new_season(
            config, config.get("season", "?")
        )
        if new_matches and new_standings and new_season:
            backup_path = Path("data.json.backup")
            if data_path.exists():
                backup_path.write_text(
                    data_path.read_text(encoding="utf-8"), encoding="utf-8")
                print(f"  💾 Backup salvato: {backup_path}")
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
