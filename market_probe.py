#!/usr/bin/env python3
"""
Kalshi / Polymarket connectivity probe
======================================
Run this once, from the same machine (or Action) that runs update_dashboard.py:

    python market_probe.py

It makes no changes to anything. It just asks every endpoint the dashboard depends on
whether it works, and prints a verdict per feed. Paste the output back and the exact
cause of any remaining staleness is visible — which tickers are live, which were
renamed (and to what), and whether the order-book endpoints need an API key.

Why this exists: the live APIs can't be reached from the environment this code was
written in, so this is the one thing that can't be verified without you running it.
"""
import json
import sys

try:
    import requests
except ImportError:
    print("Need requests: pip install requests")
    sys.exit(1)

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
POLY = "https://gamma-api.polymarket.com"
HEADERS = {'Accept': 'application/json', 'User-Agent': 'statum-probe/1.0'}
TIMEOUT = 20

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results = []


def line(ch=None):
    print("-" * 78 if ch is None else ch * 78)


def probe(label, url, params=None, expect_key=None):
    """GET one endpoint and report what came back."""
    try:
        r = requests.get(url, params=params or {}, timeout=TIMEOUT, headers=HEADERS)
    except requests.RequestException as e:
        print(f"  [{FAIL}] {label}\n         network error: {type(e).__name__}: {str(e)[:120]}")
        results.append((FAIL, label, f"network: {type(e).__name__}"))
        return None
    if r.status_code != 200:
        body = r.text[:140].replace("\n", " ")
        print(f"  [{FAIL}] {label}\n         HTTP {r.status_code} · {body}")
        results.append((FAIL, label, f"HTTP {r.status_code}"))
        return None
    try:
        data = r.json()
    except ValueError:
        print(f"  [{FAIL}] {label}\n         200 but body wasn't JSON")
        results.append((FAIL, label, "non-JSON body"))
        return None
    if expect_key:
        items = data.get(expect_key) if isinstance(data, dict) else data
        n = len(items or [])
        if n == 0:
            print(f"  [{WARN}] {label}\n         200 OK but 0 {expect_key} — endpoint alive, this market isn't listed")
            results.append((WARN, label, f"0 {expect_key}"))
            return data
        print(f"  [{PASS}] {label} — {n} {expect_key}")
        results.append((PASS, label, f"{n} {expect_key}"))
        return data
    print(f"  [{PASS}] {label}")
    results.append((PASS, label, "ok"))
    return data


def show_prices(data, n=4):
    for m in (data.get('markets') or [])[:n]:
        name = m.get('yes_sub_title') or m.get('title')
        px = m.get('last_price_dollars') or m.get('yes_bid_dollars') or m.get('last_price') or m.get('yes_bid')
        print(f"           · {str(name)[:48]:<48} {px}")


line("=")
print("KALSHI — basic reachability")
line("=")
root = probe("GET /markets?limit=1 (is the API reachable at all, unauthenticated?)",
             f"{KALSHI}/markets", {"limit": 1}, expect_key="markets")
if root is None:
    print("\n  >>> Kalshi is not reachable from this machine. Everything below will fail too.")
    print("  >>> If this is a GitHub Action, the runner's egress may be restricted,")
    print("  >>> or Kalshi may be blocking the datacenter IP range.\n")

line("=")
print("KALSHI — NFL season leader races (the 'Season Leader Races' cards)")
line("=")
LEADERS = [
    ("Receiving Yards Leader", "KXLEADERNFLRYDS"),
    ("Passing Yards Leader", "KXLEADERNFLPYDS"),
    ("Rushing Yards Leader", "KXLEADERNFLRSHYDS"),
    ("Sacks Leader", "KXLEADERNFLSACK"),
    ("Interceptions Leader", "KXLEADERNFLINT"),
]
for label, ticker in LEADERS:
    d = probe(f"{label} (series_ticker={ticker})", f"{KALSHI}/markets",
              {"series_ticker": ticker, "status": "open", "limit": 10}, expect_key="markets")
    if d:
        show_prices(d)

line("=")
print("KALSHI — championship markets (candidate tickers; each one is a guess)")
line("=")
for sport, tickers in [("NFL", ["KXNFLCHAMP", "KXSBCHAMP", "KXSUPERBOWL", "KXNFLGAME-CHAMP"]),
                       ("WNBA", ["KXWNBA", "KXWNBACHAMP"]),
                       ("MLB", ["KXMLBWS", "KXMLBWORLDSERIES", "KXWORLDSERIES"])]:
    print(f"\n  {sport}:")
    for t in tickers:
        d = probe(f"  series_ticker={t}", f"{KALSHI}/markets",
                  {"series_ticker": t, "status": "open", "limit": 10}, expect_key="markets")
        if d and (d.get('markets')):
            show_prices(d, 3)
            break

line("=")
print("KALSHI — discovery fallback (finds markets even if a ticker was renamed)")
line("=")
ev = probe("GET /events?status=open&with_nested_markets=true",
           f"{KALSHI}/events",
           {"status": "open", "with_nested_markets": "true", "limit": 200}, expect_key="events")
if ev:
    events = ev.get('events') or []
    print(f"\n  Searching {len(events)} open events for the markets this dashboard wants:")
    WANTED = {
        "receiving yards": "Receiving Yards Leader",
        "passing yards": "Passing Yards Leader",
        "rushing yards": "Rushing Yards Leader",
        "sacks": "Sacks Leader",
        "interception": "Interceptions Leader",
        "super bowl": "NFL Championship",
        "world series": "MLB Championship",
        "wnba": "WNBA Championship",
    }
    found_any = False
    for e in events:
        title = ((e.get('title') or "") + " " + (e.get('sub_title') or "")).lower()
        for needle, what in WANTED.items():
            if needle in title:
                nm = len(e.get('markets') or e.get('nested_markets') or [])
                print(f"    · {what:<24} series={str(e.get('series_ticker')):<22} "
                      f"event={str(e.get('event_ticker')):<24} ({nm} markets)")
                print(f"      title: {e.get('title')}")
                found_any = True
                break
    if not found_any:
        print("    (none matched — either none are listed right now, or the titles have changed)")
    if ev.get('cursor'):
        print(f"\n  NOTE: more pages exist (cursor present) — this is only the first 200 events.")

line("=")
print("KALSHI — order book + candlesticks (the 'Market Depth & Flow' panel)")
line("=")
print("  These two are the endpoints most likely to require an authenticated API key,")
print("  unlike the price endpoints above. A 401/403 here is the answer to why that")
print("  panel says 'unavailable' while the odds tables work.\n")
sample_ticker = None
if root and root.get('markets'):
    sample_ticker = root['markets'][0].get('ticker')
    sample_series = root['markets'][0].get('series_ticker') or root['markets'][0].get('event_ticker')
    print(f"  Using an arbitrary live market as the test subject: {sample_ticker}\n")
    probe(f"orderbook for {sample_ticker}", f"{KALSHI}/markets/{sample_ticker}/orderbook")
    import time
    end = int(time.time()); start = end - 7 * 24 * 3600
    cp = {"start_ts": start, "end_ts": end, "period_interval": 1440}
    probe(f"candlesticks (documented path: /series/{sample_series}/markets/{sample_ticker}/candlesticks)",
          f"{KALSHI}/series/{sample_series}/markets/{sample_ticker}/candlesticks", cp)
    probe(f"candlesticks (legacy flat path, what the old browser code called)",
          f"{KALSHI}/markets/{sample_ticker}/candlesticks", cp)
else:
    print("  Skipped — couldn't get any market ticker to test with.")

line("=")
print("POLYMARKET")
line("=")
for label, slug in [("NFL champion", "big-game-champion-2027"),
                    ("WNBA champion", "wnba-2026-champion-464"),
                    ("MLB World Series", "mlb-world-series-champion-2026")]:
    d = probe(f"{label} (slug={slug})", f"{POLY}/events", {"slug": slug})
    if d:
        event = d[0] if isinstance(d, list) and d else d
        mk = (event or {}).get('markets') or []
        print(f"           {len(mk)} outcome markets")
        for m in mk[:4]:
            print(f"           · {str(m.get('groupItemTitle') or m.get('question'))[:46]:<46} {m.get('outcomePrices')}")

print("\n  Discovery fallback (highest-volume open events, in case a slug was renamed):")
d = probe("  GET /events?closed=false&order=volume", f"{POLY}/events",
          {"closed": "false", "order": "volume", "ascending": "false", "limit": 100})
if isinstance(d, list):
    for e in d:
        t = (e.get('title') or "").lower()
        if any(k in t for k in ["super bowl", "world series", "wnba", "nfl champion"]):
            print(f"    · {e.get('title')[:56]:<56} slug={e.get('slug')}")

line("=")
print("NEWS FEEDS — the Daily Brief on the Research tab")
line("=")
print("  These are plain RSS/Atom. A dead one just thins the brief; the computed read")
print("  above each game's headlines does not depend on any of them.\n")
NEWS_FEEDS = [
    ("ESPN NFL", "https://www.espn.com/espn/rss/nfl/news"),
    ("CBS Sports NFL", "https://www.cbssports.com/rss/headlines/nfl/"),
    ("Yahoo Sports NFL", "https://sports.yahoo.com/nfl/rss.xml"),
    ("Pro Football Talk", "https://profootballtalk.nbcsports.com/feed/"),
    ("Pro Football Rumors", "https://www.profootballrumors.com/feed"),
    ("SB Nation NFL", "https://www.sbnation.com/rss/nfl/index.xml"),
    ("Sharp Football Analysis", "https://www.sharpfootballanalysis.com/feed/"),
    ("RotoWire NFL", "https://www.rotowire.com/rss/news.php?sport=NFL"),
    ("NFL.com", "https://www.nfl.com/feeds/rss/news"),
    ("The Ringer NFL", "https://www.theringer.com/rss/nfl/index.xml"),
]
import xml.etree.ElementTree as _ET
for name, url in NEWS_FEEDS:
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={
            'User-Agent': 'statum-probe/1.0',
            'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml'})
    except requests.RequestException as e:
        print(f"  [{FAIL}] {name}\n         network error: {type(e).__name__}")
        results.append((FAIL, f"news:{name}", "network"))
        continue
    if r.status_code != 200:
        print(f"  [{FAIL}] {name} — HTTP {r.status_code}")
        results.append((FAIL, f"news:{name}", f"HTTP {r.status_code}"))
        continue
    try:
        root_el = _ET.fromstring(r.content)
    except _ET.ParseError:
        print(f"  [{FAIL}] {name} — 200 but the body isn't parseable XML (probably an HTML page)")
        results.append((FAIL, f"news:{name}", "not XML"))
        continue
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    nodes = root_el.findall('.//item') or root_el.findall('.//atom:entry', ns)
    if not nodes:
        tag = root_el.tag.split('}')[-1]
        print(f"  [{WARN}] {name} — parsed, but 0 items (root <{tag}>)")
        results.append((WARN, f"news:{name}", "0 items"))
        continue
    print(f"  [{PASS}] {name} — {len(nodes)} items")
    results.append((PASS, f"news:{name}", f"{len(nodes)} items"))
    for n in nodes[:2]:
        t = n.find('title') if n.find('title') is not None else n.find('atom:title', ns)
        if t is not None and t.text:
            print(f"           · {t.text.strip()[:70]}")

line("=")
print("NBA — stats.nba.com (the Matchups tab depends entirely on this)")
line("=")
print("  This host is the one most likely to refuse a cloud/CI IP range outright. If the")
print("  calls below fail while everything else on this page passes, that's an IP block,")
print("  not a bug — and the CDN schedule check at the end should still succeed, which is")
print("  how you tell the two apart.\n")
NBA_HEADERS = {
    'Host': 'stats.nba.com',
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.nba.com/',
    'Origin': 'https://www.nba.com',
    'x-nba-stats-origin': 'stats',
    'x-nba-stats-token': 'true',
}
NBA_SEASON = "2025-26"
NBA_CALLS = [
    ("player season stats", "leaguedashplayerstats", {
        'College': '', 'Conference': '', 'Country': '', 'DateFrom': '', 'DateTo': '', 'Division': '',
        'DraftPick': '', 'DraftYear': '', 'GameScope': '', 'GameSegment': '', 'Height': '',
        'LastNGames': 0, 'LeagueID': '00', 'Location': '', 'MeasureType': 'Base', 'Month': 0,
        'OpponentTeamID': 0, 'Outcome': '', 'PORound': 0, 'PaceAdjust': 'N', 'PerMode': 'Totals',
        'Period': 0, 'PlayerExperience': '', 'PlayerPosition': '', 'PlusMinus': 'N', 'Rank': 'N',
        'Season': NBA_SEASON, 'SeasonSegment': '', 'SeasonType': 'Regular Season',
        'ShotClockRange': '', 'StarterBench': '', 'TeamID': 0, 'TwoWay': 0, 'VsConference': '',
        'VsDivision': '', 'Weight': ''}),
    ("defender ratings", "leaguedashptdefend", {
        'College': '', 'Conference': '', 'Country': '', 'DateFrom': '', 'DateTo': '',
        'DefenseCategory': 'Overall', 'Division': '', 'DraftPick': '', 'DraftYear': '',
        'GameSegment': '', 'Height': '', 'LastNGames': 0, 'LeagueID': '00', 'Location': '',
        'Month': 0, 'OpponentTeamID': 0, 'Outcome': '', 'PORound': 0, 'PaceAdjust': 'N',
        'PerMode': 'Totals', 'Period': 0, 'PlayerExperience': '', 'PlayerPosition': '',
        'PlusMinus': 'N', 'Rank': 'N', 'Season': NBA_SEASON, 'SeasonSegment': '',
        'SeasonType': 'Regular Season', 'StarterBench': '', 'TeamID': 0, 'VsConference': '',
        'VsDivision': '', 'Weight': ''}),
    ("SEASON MATCHUPS (the critical one)", "leagueseasonmatchups", {
        'LeagueID': '00', 'PerMode': 'Totals', 'Season': NBA_SEASON,
        'SeasonType': 'Regular Season', 'OffPlayerID': '', 'DefPlayerID': '',
        'OffTeamID': '', 'DefTeamID': ''}),
]
# The probe has to use the same transport as the pipeline, or it reports failures the
# pipeline doesn't have. Both NBA hosts are behind Akamai, which tarpits connections whose
# TLS fingerprint doesn't match the browser they claim to be: measured, the same endpoint
# hung for 75s over plain `requests` and answered in 0.4s over a Chrome fingerprint.
NBA_TIMEOUT = (15, 75)
NBA_HEAVY_TIMEOUT = (15, 180)
try:
    from curl_cffi import requests as nba_requests
    NBA_SESSION = nba_requests.Session(impersonate="chrome")
    NBA_IMPERSONATES = True
    print("  transport: curl_cffi (Chrome TLS fingerprint)")
except ImportError:
    NBA_SESSION = requests.Session()
    NBA_IMPERSONATES = False
    print("  transport: plain requests — curl_cffi NOT installed, so timeouts below are")
    print("             expected. Fix with:  pip install curl_cffi")
NBA_SESSION.headers.update(NBA_HEADERS)
try:        # pick up the cookies nba.com sets, the way a browser would
    NBA_SESSION.get("https://www.nba.com/stats/", timeout=45 if NBA_IMPERSONATES else NBA_TIMEOUT)
except Exception:
    pass

for label, endpoint, params in NBA_CALLS:
    url = f"https://stats.nba.com/stats/{endpoint}"
    tmo = NBA_HEAVY_TIMEOUT if endpoint == 'leagueseasonmatchups' else NBA_TIMEOUT
    if NBA_IMPERSONATES:
        tmo = tmo[1]        # curl_cffi takes one number, not a (connect, read) pair
    try:
        r = NBA_SESSION.get(url, params=params, timeout=tmo)
    except Exception as e:
        name = type(e).__name__
        if 'imeout' in name or 'imed out' in str(e).lower():
            hint = ("curl_cffi isn't installed — that is the likely cause"
                    if not NBA_IMPERSONATES else
                    "a Chrome fingerprint was already in use, so this host is refusing "
                    "this machine specifically")
            print(f"  [{FAIL}] {label} ({endpoint})\n         ReadTimeout — connection accepted, "
                  f"no reply.\n         Akamai tarpitting, not a network fault: {hint}.")
            results.append((FAIL, f"nba:{endpoint}", "ReadTimeout (bot mitigation)"))
        else:
            print(f"  [{FAIL}] {label} ({endpoint})\n         network error: {name}")
            results.append((FAIL, f"nba:{endpoint}", "network"))
        continue
    if r.status_code != 200:
        print(f"  [{FAIL}] {label} ({endpoint}) — HTTP {r.status_code}")
        results.append((FAIL, f"nba:{endpoint}", f"HTTP {r.status_code}"))
        continue
    try:
        payload = r.json()
    except ValueError:
        print(f"  [{FAIL}] {label} ({endpoint}) — 200 but not JSON (a block/challenge page)")
        results.append((FAIL, f"nba:{endpoint}", "not JSON"))
        continue
    sets = payload.get('resultSets') or payload.get('resultSet') or []
    total = sum(len(rs.get('rowSet') or []) for rs in sets if isinstance(rs, dict))
    if total == 0:
        print(f"  [{WARN}] {label} ({endpoint}) — 200 with 0 rows")
        results.append((WARN, f"nba:{endpoint}", "0 rows"))
        continue
    print(f"  [{PASS}] {label} ({endpoint}) — {total} rows")
    results.append((PASS, f"nba:{endpoint}", f"{total} rows"))
    for rs in sets:
        if isinstance(rs, dict) and rs.get('rowSet'):
            cols = rs.get('headers') or []
            print(f"           columns: {', '.join(str(c) for c in cols[:9])}"
                  + (" …" if len(cols) > 9 else ""))
            break

print("\n  NBA schedule — the CDN first, then ESPN (the pipeline's actual fallback order):")
cdn_live = False
try:
    r = NBA_SESSION.get("https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json",
                        timeout=60 if NBA_IMPERSONATES else (15, 60))
    if r.status_code == 200:
        dates = ((r.json().get('leagueSchedule') or {}).get('gameDates') or [])
        n = sum(len(d.get('games') or []) for d in dates)
        print(f"  [{PASS}] CDN schedule — {n} games across {len(dates)} dates")
        results.append((PASS, "nba:cdn-schedule", f"{n} games"))
        cdn_live = True
    else:
        # This host has been seen returning 403 even to a Chrome fingerprint that
        # stats.nba.com accepts, so it is not treated as fatal — ESPN covers it.
        print(f"  [{WARN}] CDN schedule — HTTP {r.status_code} (pipeline falls back to ESPN)")
        results.append((WARN, "nba:cdn-schedule", f"HTTP {r.status_code}"))
except Exception as e:
    print(f"  [{WARN}] CDN schedule — {type(e).__name__} (pipeline falls back to ESPN)")
    results.append((WARN, "nba:cdn-schedule", "unreachable"))

if not cdn_live:
    try:
        r = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
                         timeout=(15, 45), headers={'User-Agent': 'statum-probe/1.0'})
        if r.status_code == 200:
            n = len(r.json().get('events') or [])
            print(f"  [{PASS}] ESPN scoreboard — {n} games today (schedule is covered)")
            results.append((PASS, "nba:espn-schedule", f"{n} games"))
        else:
            print(f"  [{FAIL}] ESPN scoreboard — HTTP {r.status_code} (no schedule source left)")
            results.append((FAIL, "nba:espn-schedule", f"HTTP {r.status_code}"))
    except (requests.RequestException, ValueError) as e:
        print(f"  [{FAIL}] ESPN scoreboard — {type(e).__name__} (no schedule source left)")
        results.append((FAIL, "nba:espn-schedule", "network"))

line("=")
print("VERDICT")
line("=")
n_pass = sum(1 for r in results if r[0] == PASS)
n_warn = sum(1 for r in results if r[0] == WARN)
n_fail = sum(1 for r in results if r[0] == FAIL)
print(f"  {n_pass} passed · {n_warn} alive-but-empty · {n_fail} failed")
if n_fail:
    print("\n  Failures:")
    for status, label, note in results:
        if status == FAIL:
            print(f"    · {label.strip()} — {note}")
if n_pass == 0:
    print("\n  Nothing reached either API. That points at the network this ran on,")
    print("  not at the tickers — try it from a normal machine to confirm.")
print()
