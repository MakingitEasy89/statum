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
