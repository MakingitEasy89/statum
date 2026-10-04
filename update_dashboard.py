#!/usr/bin/env python3
"""
NFL Dashboard Auto-Updater
==========================
Run this script (manually, or via Windows Task Scheduler twice a day) to:
  1. Pull the latest nflverse play-by-play, participation, roster, and game data
  2. Rebuild every stat, split, and prop-floor ladder in the dashboard
  3. Blend in the current in-progress season (once it starts) at a weight based
     on how many games have been played so far
  4. Rebuild index.html from the template and push it to GitHub automatically

Expects to live inside your cloned repo folder (dashboard-repo), alongside
dashboard_template.jsx. Run with: python update_dashboard.py
"""

import json
import re
import subprocess
import sys
import math
import datetime
import os
import time
import random
from pathlib import Path

try:
    import pandas as pd
    import numpy as np
    import requests
except ImportError:
    print("Missing packages. Run: pip install pandas pyarrow requests --user")
    sys.exit(1)

# =====================================================================
# CONFIG
# =====================================================================
SCRIPT_DIR = Path(__file__).parent.resolve()
CACHE_DIR = SCRIPT_DIR / "_data_cache"
CACHE_DIR.mkdir(exist_ok=True)

# =====================================================================
# REAL SPORTSBOOK ODDS (the-odds-api.com — verified legitimate, hyphenated
# domain only; theoddsapi.com with no hyphens is a confirmed impersonator).
# Key lives in a local file that never gets committed — see ensure_gitignored().
# Entirely optional: if the key file doesn't exist, this whole section is
# skipped gracefully and the site works exactly as before, manual-entry only.
# =====================================================================
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_API_KEY_PATH = SCRIPT_DIR / "odds_api_key.txt"
GITIGNORE_PATH = SCRIPT_DIR / ".gitignore"

# Statum stat label -> real sportsbook market key, per sport.
ODDS_MARKET_MAP = {
    'nfl': {
        'Receptions': 'player_receptions', 'Receiving Yards': 'player_reception_yds',
        'Rush Yards': 'player_rush_yds', 'Rush Attempts': 'player_rush_attempts',
        'Passing Yards': 'player_pass_yds', 'Completions': 'player_pass_completions',
    },
    'wnba': {
        'Points': 'player_points', 'Rebounds': 'player_rebounds', 'Assists': 'player_assists',
        'Three-Pointers Made': 'player_threes', 'Blocks': 'player_blocks', 'Steals': 'player_steals',
    },
    'mlb': {
        'Hits': 'batter_hits', 'HR': 'batter_home_runs', 'RBI': 'batter_rbis',
        'Runs': 'batter_runs_scored', 'Total Bases': 'batter_total_bases', 'Strikeouts': 'pitcher_strikeouts',
    },
}
ODDS_SPORT_KEYS = {'nfl': 'americanfootball_nfl', 'wnba': 'basketball_wnba', 'mlb': 'baseball_mlb'}


# ESPN's team abbreviations mostly match nflverse's, with a few known exceptions.
ESPN_TEAM_ABBR_OVERRIDES = {'WAS': 'wsh', 'LA': 'lar', 'LAC': 'lac', 'JAX': 'jax'}

# ESPN roster endpoints to try, in order, per team. Kept as a list (not a single URL)
# because ESPN has silently rotated which unofficial host actually serves this data at
# least twice in 2026 -- if one starts blanket-403ing again (e.g. a datacenter/CI IP range
# getting flagged), the others get a real shot before we give up on live data entirely.
ESPN_ROSTER_URL_TEMPLATES = [
    "https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/teams/{code}/roster",
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{code}/roster",
]
ESPN_CACHE_PATH = CACHE_DIR / "espn_current_teams.json"

def fetch_espn_current_rosters():
    """Real, current team assignment — direct from ESPN's own roster pages, not inferred
    from play-by-play or a periodic nflverse snapshot. Built this after finding that the
    nflverse roster fix from earlier was ITSELF stale for very recent transactions (players
    who signed or got traded within the last few weeks of the offseason) — nflverse's
    roster file updates on its own schedule, which doesn't always catch up before Week 1.
    This is an unofficial, undocumented endpoint (no formal ESPN API docs exist for it),
    so this prints exactly what it finds — if ESPN changes their response shape, that
    will show up immediately here rather than silently returning nothing.

    Resilience, added after a run came back 0/32 (every team 403ing at once — the
    signature of an IP-range block on the runner, not a per-request rate limit, since
    retries/headers can't fix that): each team gets a couple of retries across a couple of
    known ESPN hosts with a small randomized delay between requests, and the result is
    merged into a local cache file (_data_cache/espn_current_teams.json) rather than
    replacing it outright. A team ESPN failed to serve THIS run keeps its last known-good
    value from the cache instead of silently falling all the way back to (potentially
    older) nflverse-based resolution. If literally nothing can be reached this run, the
    whole cache is reused as-is and clearly logged as stale, rather than treated as a
    fresh, trustworthy 0-team result.
    Returns {player_name: team_abbr}."""
    espn_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.espn.com/',
    }

    cached_teams = {}
    cached_at = None
    if ESPN_CACHE_PATH.exists():
        try:
            cache_blob = json.loads(ESPN_CACHE_PATH.read_text(encoding='utf-8'))
            cached_teams = cache_blob.get('teams', {})
            cached_at = cache_blob.get('fetched_at')
        except Exception as e:
            print(f"  [!] Couldn't read ESPN cache ({e}) — proceeding without it")

    live = {}
    teams_checked = 0
    teams_failed = []
    for team in NFL_TEAM_FULL_NAMES:
        espn_code = ESPN_TEAM_ABBR_OVERRIDES.get(team, team.lower())
        found_this_team = 0
        last_err = None
        for template in ESPN_ROSTER_URL_TEMPLATES:
            success = False
            for attempt in range(2):  # up to 2 tries per host before moving to the next host
                try:
                    resp = requests.get(template.format(code=espn_code), timeout=15, headers=espn_headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        for group in data.get('athletes', []):
                            for athlete in group.get('items', []):
                                name = athlete.get('fullName') or athlete.get('displayName')
                                if name:
                                    live[name] = team
                                    found_this_team += 1
                        success = True
                        break
                    last_err = f"HTTP {resp.status_code}"
                    if resp.status_code not in (403, 429, 500, 502, 503, 504):
                        break  # not a transient/blocking error — retrying won't help
                except Exception as e:
                    last_err = str(e)
                time.sleep(0.4 + random.random() * 0.5)  # brief backoff before retry/next host
            if success:
                break
        teams_checked += 1
        if found_this_team == 0:
            teams_failed.append(f"{team} ({last_err or '0 players parsed'})")
        time.sleep(0.15 + random.random() * 0.2)  # small jitter between teams — avoid a bursty request pattern

    print(f"  ESPN current-roster fetch: {32 - len(teams_failed)}/32 teams reached live, {len(live)} players parsed live")
    if teams_failed:
        print(f"  [!] {len(teams_failed)} teams had issues: {teams_failed[:5]}{'...' if len(teams_failed) > 5 else ''}")

    if len(live) == 0 and cached_teams:
        # Total block this run (the "0/32, all 403" failure mode) -- reuse the cache as-is
        # rather than wiping out every player's current-team accuracy for one bad run.
        age_note = f" from {cached_at}" if cached_at else ""
        print(f"  [!] ESPN unreachable this run (likely blocked, not a data-shape issue) — "
              f"falling back to the last cached roster snapshot{age_note} ({len(cached_teams)} players). "
              f"Team assignments for very recent transactions may be stale until ESPN is reachable again.")
        out = cached_teams
    else:
        # Merge: fresh, live-verified entries win; any team ESPN didn't serve this run
        # keeps its last known-good cached value instead of losing that player entirely.
        out = {**cached_teams, **live}
        if live:
            try:
                ESPN_CACHE_PATH.write_text(json.dumps({
                    'fetched_at': datetime.date.today().isoformat(),
                    'teams': out,
                }), encoding='utf-8')
            except Exception as e:
                print(f"  [!] Couldn't write ESPN cache ({e}) — non-fatal, continuing")

    # spot-check specific players known to have moved recently, so a wrong assumption
    # about the response shape shows up immediately and specifically, not just as a
    # generic count
    for check_name in ['A.J. Brown', 'Stefon Diggs', 'Kenneth Walker III', 'Kayshon Boutte']:
        match = next((out[n] for n in out if check_name.lower() in n.lower() or n.lower() in check_name.lower()), None)
        print(f"    Spot-check: {check_name} -> {match or 'NOT FOUND'}")
    return out


def build_redzone_tendencies(baseline, current):
    """Real red-zone tendencies per team: offensive pass-vs-rush lean inside the 20, real
    drive-level TD conversion rate once a team reaches the red zone, and — for defenses —
    the real TD rate allowed specifically on red-zone PASS plays vs RUSH plays. This last
    piece is what actually connects to an opposing offense's own red-zone tendency: a
    pass-heavy red-zone offense against a defense that's specifically leaky against red-zone
    passing (not just leaky overall) is a real, checkable signal.
    Blends baseline (2024-2025) with current season if there's enough current data,
    matching how the rest of the app blends its backtest windows."""
    df = pd.concat([baseline, current]) if len(current) else baseline
    rz = df[(df['yardline_100'] <= 20) & (df['play_type'].isin(['pass', 'run']))].copy()
    if len(rz) == 0:
        return {}

    # Offensive tendency: real pass rate on red-zone plays specifically
    off_tendency = rz.groupby('posteam')['play_type'].apply(lambda s: round((s == 'pass').mean() * 100, 1))
    off_volume = rz.groupby('posteam').size()

    # Drive-level conversion: does a drive that touched the red zone end in a real TD?
    # (a play-level "did this play score" flag, rolled up per game+drive+team)
    df2 = df.copy()
    df2['scored_td'] = (df2['pass_touchdown'] == 1) | (df2['rush_touchdown'] == 1)
    df2['entered_rz'] = df2['yardline_100'] <= 20
    drives = df2.groupby(['game_id', 'posteam', 'defteam', 'drive']).agg(
        entered_rz=('entered_rz', 'any'), scored_td=('scored_td', 'any')
    ).reset_index()
    rz_drives = drives[drives['entered_rz']]

    off_conversion = rz_drives.groupby('posteam')['scored_td'].mean() * 100
    off_conversion_n = rz_drives.groupby('posteam').size()
    def_conversion = rz_drives.groupby('defteam')['scored_td'].mean() * 100
    def_conversion_n = rz_drives.groupby('defteam').size()

    # Defensive vulnerability by play type: of red-zone PASS plays run against this defense,
    # what % were touchdowns — same question for RUSH plays. This is play-level (not
    # drive-level) since it's asking about a specific play type's effectiveness, not a
    # whole drive's outcome.
    rz['is_td'] = (rz['pass_touchdown'] == 1) | (rz['rush_touchdown'] == 1)
    def_by_type = rz.groupby(['defteam', 'play_type'])['is_td'].agg(['mean', 'count'])

    out = {}
    all_teams = set(off_tendency.index) | set(def_conversion.index)
    for team in all_teams:
        pass_row = def_by_type.loc[(team, 'pass')] if (team, 'pass') in def_by_type.index else None
        run_row = def_by_type.loc[(team, 'run')] if (team, 'run') in def_by_type.index else None
        out[team] = {
            'offPassRate': float(off_tendency.get(team)) if team in off_tendency.index else None,
            'offVolume': int(off_volume.get(team, 0)),
            'offConversionRate': round(float(off_conversion.get(team)), 1) if team in off_conversion.index else None,
            'offConversionN': int(off_conversion_n.get(team, 0)),
            'defConversionRate': round(float(def_conversion.get(team)), 1) if team in def_conversion.index else None,
            'defConversionN': int(def_conversion_n.get(team, 0)),
            'defPassTDRate': round(float(pass_row['mean']) * 100, 1) if pass_row is not None and pass_row['count'] >= 15 else None,
            'defPassTDN': int(pass_row['count']) if pass_row is not None else 0,
            'defRunTDRate': round(float(run_row['mean']) * 100, 1) if run_row is not None and run_row['count'] >= 15 else None,
            'defRunTDN': int(run_row['count']) if run_row is not None else 0,
        }
    return out


def compute_team_defense(games_df, pbp_df, pos_map, min_games=1):
    """Team defense profile (points allowed/scored, scheme tendencies, TDs allowed by
    position group) computed from WHATEVER games+pbp slice is passed in -- this is what
    lets the same logic build both the 2024-2025 historical profile and the current-season
    profile, rather than hardcoding one fixed window like the original version of this did.

    TDs-allowed-by-position now also includes a QB group: real rushing TDs allowed to
    OPPOSING quarterbacks (goal-line sneaks, scrambles) -- previously this only covered
    WR/TE/RB via receiving, which meant a defense's real vulnerability to a mobile QB in
    the red zone (Hurts-style sneaks, e.g.) was invisible here even though the site tracks
    that same QB rushing production everywhere else (Anytime TD, prop ladders).

    QB is shown on the same footing as WR/TE/RB -- any real rush attempt/TD data at all is
    enough to appear, no separate minimum-sample gate. A real rushing TD against a defense
    is a real rushing TD regardless of how many QB rush attempts it has faced on the season;
    this used to require 8+ cumulative attempts before the QB row would even render, which
    silently hid real events (e.g. two real rushing TDs) for a team only a few games into a
    season. The small-sample context (rush attempts faced, games played) is still shown
    right alongside the number in the UI, same as every other position here."""
    if len(games_df) == 0:
        return {}
    pa_rows = []
    for _, g in games_df.iterrows():
        if pd.isna(g.home_score) or pd.isna(g.away_score):
            continue
        pa_rows.append({'team': g.home_team, 'allowed': g.away_score, 'scored': g.home_score})
        pa_rows.append({'team': g.away_team, 'allowed': g.home_score, 'scored': g.away_score})
    pa = pd.DataFrame(pa_rows)
    if len(pa) == 0:
        return {}
    points_allowed = pa.groupby('team').agg(gamesPlayed=('allowed', 'count'), totalAllowed=('allowed', 'sum'), totalScored=('scored', 'sum')).reset_index()
    points_allowed['ppgAllowed'] = points_allowed['totalAllowed'] / points_allowed['gamesPlayed']
    points_allowed['ppgScored'] = points_allowed['totalScored'] / points_allowed['gamesPlayed']
    points_allowed['rank'] = points_allowed['ppgAllowed'].rank(ascending=False).astype(int)
    points_allowed['scoredRank'] = points_allowed['ppgScored'].rank(ascending=False).astype(int)
    points_allowed = points_allowed.set_index('team')

    if len(pbp_df) == 0:
        return {}
    targets_all = pbp_df[pbp_df['receiver_player_id'].notna()].copy()
    targets_all['recv_pos'] = targets_all['receiver_player_id'].map(pos_map).replace('FB', 'RB')
    targets_all = targets_all[targets_all['recv_pos'].isin(['WR', 'TE', 'RB'])]
    games_played_by_def = pbp_df.groupby('defteam')['game_id'].nunique()
    pos_allowed = targets_all.groupby(['defteam', 'recv_pos']).agg(
        targets=('week', 'count'), catches=('complete_pass', 'sum'), yards=('yards_gained', 'sum'),
        tds=('pass_touchdown', 'sum'), epaAllowed=('epa', 'sum')
    ).reset_index()
    pos_allowed = pos_allowed.join(games_played_by_def.rename('gp'), on='defteam')
    pos_allowed['ypg'] = pos_allowed['yards'] / pos_allowed['gp']
    pos_allowed['epaPerTgt'] = pos_allowed['epaAllowed'] / pos_allowed['targets']
    pos_allowed['rank'] = pos_allowed.groupby('recv_pos')['ypg'].rank(ascending=False).astype(int)

    # Real rushing TDs allowed to opposing QBs -- a defense doesn't "allow a target" to a
    # QB the way it does a receiver, so this is keyed off the rusher's own position instead.
    rush_all = pbp_df[pbp_df['rusher_player_id'].notna()].copy()
    rush_all['rush_pos'] = rush_all['rusher_player_id'].map(pos_map)
    qb_rush = rush_all[rush_all['rush_pos'] == 'QB']
    qb_rush_allowed = pd.DataFrame()
    if len(qb_rush):
        qb_rush_allowed = qb_rush.groupby('defteam').agg(
            rushAtt=('rush_attempt', 'count'), rushYards=('rushing_yards', 'sum'), tds=('rush_touchdown', 'sum')
        )
        qb_rush_allowed = qb_rush_allowed.join(games_played_by_def.rename('gp'))
        qb_rush_allowed['ypg'] = qb_rush_allowed['rushYards'] / qb_rush_allowed['gp']
        # ranked across every team that has faced ANY opposing QB rush attempt -- no minimum
        # sample gate, same as WR/TE/RB below (see the docstring for why)
        qb_rush_allowed['rank'] = qb_rush_allowed['tds'].rank(ascending=False).astype(int)

    def_plays = pbp_df[pbp_df['defteam'].notna() & (pbp_df['pass'] == 1)]
    out = {}
    for team, g in def_plays.groupby('defteam'):
        gp = int(games_played_by_def.get(team, 0))
        if gp < min_games:
            continue
        front_counts = g['front_bucket'].value_counts(normalize=True) * 100
        cov_counts = g['coverage'].value_counts(normalize=True) * 100
        if len(front_counts) == 0 or len(cov_counts) == 0:
            continue
        top_front_bucket = front_counts.idxmax()
        sub = g[g['front_bucket'] == top_front_bucket]
        top_front_exact = sub['front'].value_counts().idxmax() if len(sub) else None
        top_cov = cov_counts.idxmax()
        pa_row = points_allowed.loc[team] if team in points_allowed.index else None
        pos_rows = pos_allowed[pos_allowed.defteam == team]
        pos_by_group = {r['recv_pos']: {'ypg': round(r['ypg'], 1), 'rank': int(r['rank']), 'tds': int(r['tds']),
                                          'targets': int(r['targets']), 'catches': int(r['catches']),
                                          'epaPerTgt': round(r['epaPerTgt'], 3)} for _, r in pos_rows.iterrows()}
        if len(qb_rush_allowed) and team in qb_rush_allowed.index:
            qr = qb_rush_allowed.loc[team]
            pos_by_group['QB'] = {'ypg': round(float(qr['ypg']), 1), 'rank': int(qr['rank']), 'tds': int(qr['tds']),
                                    'rushAtt': int(qr['rushAtt']), 'targets': None, 'catches': None, 'epaPerTgt': None}
        weakest = max(pos_by_group.items(), key=lambda kv: -kv[1]['rank']) if pos_by_group else None
        out[team] = {
            'pointsAllowedPerGame': round(float(pa_row['ppgAllowed']), 1) if pa_row is not None else None,
            'pointsAllowedRank': int(pa_row['rank']) if pa_row is not None else None,
            'pointsScoredPerGame': round(float(pa_row['ppgScored']), 1) if pa_row is not None else None,
            'pointsScoredRank': int(pa_row['scoredRank']) if pa_row is not None else None,
            'gamesPlayed': gp,
            'scheme': {'primaryFrontBucket': top_front_bucket, 'primaryFrontBucketPct': round(float(front_counts.max()), 1),
                       'primaryFrontExact': top_front_exact, 'primaryCoverage': top_cov,
                       'primaryCoveragePct': round(float(cov_counts.max()), 1),
                       'nickelPct': round(float(front_counts.get('Nickel', 0)), 1),
                       'basePct': round(float(front_counts.get('Base', 0)), 1),
                       'dimePct': round(float(front_counts.get('Dime', 0)), 1)},
            'allowedByPosition': pos_by_group,
            'weakestPosition': weakest[0] if weakest else None,
            'weakestPositionRank': weakest[1]['rank'] if weakest else None,
        }
    return out


def compute_team_offense(games_df, pbp_df, pos_map, min_games=1):
    """The offense's own side of TDs-by-position -- a direct mirror of
    compute_team_defense's allowedByPosition, but from the scoring team's perspective:
    of THIS team's own real touchdowns, what share came from each position group.
    Receiving TDs are credited to the receiver's position (WR/TE/RB); rushing TDs are
    credited to the rusher's position (WR/TE/RB via jet sweeps etc., and QB via
    scrambles/sneaks) -- so a team's true full TD distribution, not just receiving."""
    if len(games_df) == 0 or len(pbp_df) == 0:
        return {}
    pf_rows = []
    for _, g in games_df.iterrows():
        if pd.isna(g.home_score) or pd.isna(g.away_score):
            continue
        pf_rows.append({'team': g.home_team, 'scored': g.home_score})
        pf_rows.append({'team': g.away_team, 'scored': g.away_score})
    pf = pd.DataFrame(pf_rows)
    if len(pf) == 0:
        return {}
    points_scored = pf.groupby('team').agg(gamesPlayed=('scored', 'count'), totalScored=('scored', 'sum')).reset_index()
    points_scored['ppgScored'] = points_scored['totalScored'] / points_scored['gamesPlayed']
    points_scored['rank'] = points_scored['ppgScored'].rank(ascending=False).astype(int)
    points_scored = points_scored.set_index('team')

    df = pbp_df
    rec_td = df[(df['pass_touchdown'] == 1) & df['receiver_player_id'].notna()].copy()
    rec_td['pos_group'] = rec_td['receiver_player_id'].map(pos_map).replace('FB', 'RB')
    rec_td = rec_td[rec_td['pos_group'].isin(['WR', 'TE', 'RB'])]
    rec_counts = rec_td.groupby(['posteam', 'pos_group']).size()

    rush_td = df[(df['rush_touchdown'] == 1) & df['rusher_player_id'].notna()].copy()
    rush_td['pos_group'] = rush_td['rusher_player_id'].map(pos_map).replace('FB', 'RB')
    rush_td = rush_td[rush_td['pos_group'].isin(['WR', 'TE', 'RB', 'QB'])]
    rush_counts = rush_td.groupby(['posteam', 'pos_group']).size()

    out = {}
    for team in points_scored.index:
        gp = int(points_scored.loc[team, 'gamesPlayed'])
        if gp < min_games:
            continue
        by_position = {}
        total_tds = 0
        for pg in ['WR', 'TE', 'RB', 'QB']:
            rec_n = int(rec_counts.get((team, pg), 0)) if pg != 'QB' else 0
            rush_n = int(rush_counts.get((team, pg), 0))
            tds = rec_n + rush_n
            total_tds += tds
            by_position[pg] = {'tds': tds, 'receivingTDs': rec_n, 'rushingTDs': rush_n, 'perGame': round(tds / gp, 2) if gp else 0.0}
        for pg, d in by_position.items():
            d['pct'] = round(d['tds'] / total_tds * 100, 1) if total_tds else 0.0
        top_scorer = max(by_position.items(), key=lambda kv: kv[1]['tds'])[0] if total_tds else None
        pr = points_scored.loc[team]
        out[team] = {
            'pointsPerGame': round(float(pr['ppgScored']), 1),
            'pointsRank': int(pr['rank']),
            'gamesPlayed': gp,
            'totalTDs': total_tds,
            'tdsByPosition': by_position,
            'primaryScorer': top_scorer,
        }
    return out


def build_usage_bump_analysis(receivers, injury_df):
    """For each real historical instance where a skill player was ruled Out, checks what
    actually happened to same-team, same-position-group teammates' usage that same week,
    compared to each teammate's own baseline in games where nobody at their position was
    out. This is a real historical correlation, not a guess about what "should" happen —
    it only reports a bump when there's a real, repeated pattern (2+ real instances)."""
    if len(injury_df) == 0:
        return {}
    POSITION_GROUPS = {'WR': 'WR', 'TE': 'TE', 'RB': 'RB', 'FB': 'RB'}

    usage_by_key = {}   # (team, posgroup, season, week) -> [(player_name, targets), ...]
    player_all_games = {}  # player_name -> [(season, week, targets), ...]
    for p in receivers:
        pos_group = POSITION_GROUPS.get(p['pos'])
        if not pos_group:
            continue
        team = p['team']
        games = []
        for g in p.get('gamelog', []):
            try:
                parts = g['game_id'].split('_')
                season, week = int(parts[0]), int(parts[1])
            except Exception:
                continue
            targets = g.get('targets', 0) or 0
            games.append((season, week, targets))
            key = (team, pos_group, season, week)
            usage_by_key.setdefault(key, []).append((p['name'], targets))
        player_all_games[p['name']] = games

    inj_out = injury_df[
        (injury_df['report_status'] == 'Out') & (injury_df['position'].isin(['WR', 'TE', 'RB', 'FB']))
    ]

    bump_instances = {}  # player_name -> [{'bump','outPlayer','season','week'}, ...]
    for _, row in inj_out.iterrows():
        try:
            team, season, week = row['team'], int(row['season']), int(row['week'])
        except Exception:
            continue
        pos_group = POSITION_GROUPS.get(row['position'])
        if not pos_group:
            continue
        out_player = row['full_name']
        key = (team, pos_group, season, week)
        for teammate_name, actual_targets in usage_by_key.get(key, []):
            if teammate_name == out_player:
                continue
            other_games = [t for (s, w, t) in player_all_games.get(teammate_name, []) if not (s == season and w == week)]
            if len(other_games) < 3:
                continue  # not enough of their own baseline to compare against
            baseline_avg = sum(other_games) / len(other_games)
            bump_instances.setdefault(teammate_name, []).append({
                'bump': actual_targets - baseline_avg, 'outPlayer': out_player,
                'season': season, 'week': week,
            })

    out = {}
    for player_name, instances in bump_instances.items():
        if len(instances) < 2:
            continue  # need a real, repeated pattern, not a single data point
        avg_bump = sum(i['bump'] for i in instances) / len(instances)
        trigger_players = list(dict.fromkeys(i['outPlayer'] for i in instances))[:3]
        out[player_name] = {
            'avgTargetBump': round(avg_bump, 1), 'instances': len(instances), 'triggerPlayers': trigger_players,
        }
    return out


def _train_lean_model(per_game, pid_to_name, pid_to_team, p_line_by_name, opp_rank, upcoming, label):
    """Shared engine behind every per-stat XGBoost lean model (see build_xgboost_lean_models()
    below for the full honesty/safety contract this runs under). Trains a classifier that
    predicts P(this player clears their own real P50 line in this game), pooled across every
    player for ONE stat at a time.

    `per_game` needs one row per player-game: pid, season, week, is_home, defteam, value
    (whatever this stat means for that single game -- summed yards, a raw count, etc).
    `opp_rank` is a {team: rank} dict, 1 = allows the most of this stat (pass {} to skip this
    feature for stats where a defensive proxy doesn't really apply, e.g. kicking). `upcoming`
    is NFL_UPCOMING-shaped ({team: {opp, isHome, ...}}) -- used only so the CURRENT lean (the
    one actually shown) reflects the real next opponent/home-away instead of a neutral guess;
    it never touches the historical training rows, which already have the real thing."""
    import xgboost as xgb

    rows, targets, meta = [], [], []
    for pid, grp in per_game.sort_values(['season', 'week']).groupby('pid'):
        name = pid_to_name.get(pid)
        p50 = p_line_by_name.get(name) if name else None
        if p50 is None:
            continue
        hist = []
        for _, row in grp.iterrows():
            if len(hist) >= 3:  # only once there's real trailing history to compute from -- no leakage
                trailing_3 = np.mean(hist[-3:])
                season_avg = np.mean(hist)
                opp_r = opp_rank.get(row['defteam'], np.median(list(opp_rank.values())) if opp_rank else 16.0)
                rows.append([trailing_3, season_avg, 1.0 if row['is_home'] else 0.0, opp_r])
                targets.append(1 if row['value'] >= p50 else 0)
                meta.append({'name': name, 'season': row['season']})
            hist.append(row['value'])

    if len(rows) < 200:  # not enough pooled real data yet to train something trustworthy
        print(f"  XGBoost lean model [{label}]: only {len(rows)} real training rows -- skipping (needs 200+)")
        return {}, None

    X = np.array(rows)
    y = np.array(targets)
    # real train/test split by SEASON, not randomly -- tested on a season it never trained
    # on, matching the same real backtest discipline used everywhere else in this app rather
    # than a random shuffle that could leak information
    seasons = np.array([m['season'] for m in meta])
    train_mask = seasons < seasons.max()
    test_mask = ~train_mask
    if train_mask.sum() < 100 or test_mask.sum() < 30:
        print(f"  XGBoost lean model [{label}]: not enough real rows in both a train and a held-out test season -- skipping")
        return {}, None

    model = xgb.XGBClassifier(n_estimators=60, max_depth=3, learning_rate=0.1, eval_metric='logloss')
    model.fit(X[train_mask], y[train_mask])
    preds = model.predict(X[test_mask])
    real_accuracy = float((preds == y[test_mask]).mean()) * 100
    naive_baseline = float(max(y[test_mask].mean(), 1 - y[test_mask].mean())) * 100  # "always guess the majority class"
    print(f"  XGBoost lean model [{label}]: {len(rows)} pooled training rows, {int(test_mask.sum())} held-out test games -- "
          f"{real_accuracy:.1f}% real accuracy (naive baseline {naive_baseline:.1f}%)")

    # retrain on ALL real data (train+test) for the version actually used on current games --
    # the held-out split above was only to honestly measure real accuracy first
    model.fit(X, y)

    # build current lean scores for players with enough real trailing history right now,
    # using their REAL upcoming opponent/home-away when it's known rather than a neutral guess
    med_rank = float(np.median(list(opp_rank.values()))) if opp_rank else 16.0
    leans = {}
    for pid, grp in per_game.sort_values(['season', 'week']).groupby('pid'):
        name = pid_to_name.get(pid)
        if not name or name not in p_line_by_name or len(grp) < 3:
            continue
        recent = grp['value'].values
        trailing_3 = float(np.mean(recent[-3:]))
        season_avg = float(np.mean(recent))
        up = upcoming.get(pid_to_team.get(pid))
        is_home_guess = (1.0 if up['isHome'] else 0.0) if up else 0.5
        opp_r = opp_rank.get(up['opp'], med_rank) if up else med_rank
        prob = float(model.predict_proba([[trailing_3, season_avg, is_home_guess, opp_r]])[0][1])
        leans[name] = {'leanProb': round(prob * 100, 1), 'trailing3': round(trailing_3, 1)}

    return leans, {'accuracy': round(real_accuracy, 1), 'baseline': round(naive_baseline, 1),
                   'trainingRows': len(rows), 'testGames': int(test_mask.sum())}


def build_xgboost_lean_models(baseline, current, full_pool, receivers, qbs, kickers, games_all):
    """Supplementary, model-based signal layered ON TOP OF the real percentile ladders --
    never a replacement for them (those stay the primary, transparent display; see
    dashboard_template.jsx, which always shows a ladder's real p25/p50/p75 regardless of
    anything here). Originally shipped for Receiving Yards only; this generalizes the same
    engine to every real ladder stat (receiving, rushing, passing, kicking), training and
    grading each one independently -- a stat that doesn't clear the naive-baseline bar is
    skipped for THAT stat alone, never for the others.

    Honest limitations (unchanged from the original, true for every stat below):
    - Pooled across players, not per-player -- no single player has 30-40 games to train an
      individual model on; pooling many players' games together is what makes this workable.
    - Opponent strength is that team's END-OF-BASELINE average allowed, not a true
      week-by-week rolling value -- a disclosed simplification, not a claim of perfect
      historical precision.
    - Real accuracy is measured on real held-out games every time (train on the older
      baseline season, test on the newer one), never assumed."""
    try:
        import xgboost  # noqa: F401 -- import-check only; _train_lean_model imports its own copy
    except ImportError:
        # Never a required part of the pipeline -- real game data, props, team stats, etc.
        # all still need to ship with or without this. Run `pip install xgboost` locally to
        # enable it; the GitHub Actions workflow already installs it.
        print("  XGBoost lean models: 'xgboost' package not installed locally -- skipping entirely "
              "(run `pip install xgboost` to enable; everything else is unaffected)")
        return {}, {}

    # Real next opponent/home-away per team -- used only so the CURRENT lean (never the
    # historical training rows, which already have the real thing) reflects the real
    # upcoming matchup instead of a neutral guess. Safe to compute again here (pure function
    # of the already-loaded schedule) even though the main pipeline also builds this later.
    upcoming = build_nfl_upcoming(games_all)

    def p_lines(stat):
        return {e['player']: e['p50']['line'] for e in full_pool if e['stat'] == stat and e['kind'] == 'ladder'}

    def opp_rank_for(df, value_col):
        if len(df) == 0:
            return {}
        per_team_game = df.groupby(['defteam', 'game_id'])[value_col].sum().reset_index()
        avg_allowed = per_team_game.groupby('defteam')[value_col].mean()
        return avg_allowed.rank(ascending=False).to_dict()  # rank 1 = allows the most (weakest D)

    # Match by player ID via the already-built player lists, not the raw play-by-play name
    # column -- raw names are often abbreviated ("T.Hill") while full_pool uses the properly
    # resolved roster name ("Tyreek Hill"). Matching on name directly was a real bug that
    # silently produced zero rows the first time this was built.
    combined = pd.concat([baseline, current]) if len(current) else baseline
    rec = combined[combined['receiver_player_id'].notna()]
    rush = combined[combined['rusher_player_id'].notna()]
    passes = combined[combined['passer_player_id'].notna()]
    try:
        fgs = combined[combined['field_goal_attempt'] == 1].copy()
        if len(fgs):
            fgs['made'] = (fgs['field_goal_result'] == 'made').astype(int)
            fgs['made3'] = fgs['made'] * 3  # per-attempt-row value that sums correctly to real game points
    except Exception as e:
        # kicker-specific setup failing (e.g. a column quirk) must not take the receiving/
        # rushing/passing stats below down with it -- an empty frame just skips FG Made/
        # Kicking Points via the `if len(fgs):` guard further down, same as having no data.
        print(f"  [!] XGBoost lean models: kicker data setup raised an unexpected error ({e}) -- skipping FG/kicking stats only")
        fgs = combined.iloc[0:0]

    pass_def_rank = opp_rank_for(rec, 'yards_gained')
    rush_def_rank = opp_rank_for(rush, 'rushing_yards')

    rec_pid_to_name = {r['id']: r['name'] for r in receivers}
    rec_pid_to_team = {r['id']: r['team'] for r in receivers}
    qb_pid_to_name = {q['id']: q['name'] for q in qbs}
    qb_pid_to_team = {q['id']: q['team'] for q in qbs}
    k_pid_to_name = {k['id']: k['name'] for k in kickers}
    k_pid_to_team = {k['id']: k['team'] for k in kickers}

    all_leans, all_meta = {}, {}

    def run(df, pid_col, value_agg, pid_to_name, pid_to_team, stat_label, opp_rank):
        if len(df) == 0:
            return
        try:
            per_game = df.groupby([pid_col, 'season', 'game_id']).agg(
                value=value_agg, is_home=('is_home', 'first'), defteam=('defteam', 'first'), week=('week', 'first')
            ).reset_index().rename(columns={pid_col: 'pid'})
            leans, meta = _train_lean_model(per_game, pid_to_name, pid_to_team, p_lines(stat_label), opp_rank, upcoming, stat_label)
            if leans:
                all_leans[stat_label] = leans
            if meta:
                all_meta[stat_label] = meta
        except Exception as e:
            # one stat's own training hiccup (a library quirk, a numpy edge case) must never
            # take the other stats down with it
            print(f"  [!] XGBoost lean model [{stat_label}] raised an unexpected error ({e}) -- skipping this stat only")

    run(rec, 'receiver_player_id', ('yards_gained', 'sum'), rec_pid_to_name, rec_pid_to_team, 'Receiving Yards', pass_def_rank)
    run(rec, 'receiver_player_id', ('complete_pass', 'sum'), rec_pid_to_name, rec_pid_to_team, 'Receptions', pass_def_rank)
    run(rec, 'receiver_player_id', ('week', 'count'), rec_pid_to_name, rec_pid_to_team, 'Targets', pass_def_rank)
    run(rush, 'rusher_player_id', ('rush_attempt', 'sum'), rec_pid_to_name, rec_pid_to_team, 'Rush Attempts', rush_def_rank)
    run(rush, 'rusher_player_id', ('rushing_yards', 'sum'), rec_pid_to_name, rec_pid_to_team, 'Rush Yards', rush_def_rank)
    run(rush, 'rusher_player_id', ('rushing_yards', 'sum'), qb_pid_to_name, qb_pid_to_team, 'QB Rush Yards', rush_def_rank)
    run(passes, 'passer_player_id', ('passing_yards', 'sum'), qb_pid_to_name, qb_pid_to_team, 'Passing Yards', pass_def_rank)
    run(passes, 'passer_player_id', ('complete_pass', 'sum'), qb_pid_to_name, qb_pid_to_team, 'Completions', pass_def_rank)
    run(passes, 'passer_player_id', ('pass_touchdown', 'sum'), qb_pid_to_name, qb_pid_to_team, 'Passing Touchdowns', pass_def_rank)
    if len(fgs):
        run(fgs, 'kicker_player_id', ('made', 'sum'), k_pid_to_name, k_pid_to_team, 'FG Made', {})
        run(fgs, 'kicker_player_id', ('made3', 'sum'), k_pid_to_name, k_pid_to_team, 'Kicking Points', {})

    return all_leans, all_meta


def build_atd_pool(baseline, current, receivers, qbs=None):
    """Real Anytime Touchdown rate per skill player — the fraction of real games where they
    scored at least one touchdown (rushing OR receiving combined, since either counts for
    this market). Vectorized across all players at once rather than looping per-player,
    since the raw play-by-play here can be 100k+ rows. Backtested the same way as other
    props: rate comes from the 2024-2025 baseline, checked against real current-season
    games for an honest confidence read — not just fit to its own training data.
    QBs included too — a QB doesn't score on a TD pass, but real rushing scores (goal-line
    sneaks, scrambles) genuinely count for this market, and the same rusher_player_id
    matching below already captures that correctly, it just wasn't being checked for QBs
    at all before."""
    def per_game_scores(df):
        if len(df) == 0:
            return pd.DataFrame(columns=['pid', 'season', 'week', 'td'])
        rec = df[df['receiver_player_id'].notna()][['receiver_player_id', 'season', 'week', 'pass_touchdown']].rename(
            columns={'receiver_player_id': 'pid', 'pass_touchdown': 'td'})
        rush = df[df['rusher_player_id'].notna()][['rusher_player_id', 'season', 'week', 'rush_touchdown']].rename(
            columns={'rusher_player_id': 'pid', 'rush_touchdown': 'td'})
        combined = pd.concat([rec, rush])
        combined['td'] = combined['td'].fillna(0)
        return combined.groupby(['pid', 'season', 'week'])['td'].max().reset_index()

    base_games = per_game_scores(baseline)
    cur_games = per_game_scores(current)
    base_stats = base_games.groupby('pid')['td'].agg(['mean', 'count']) if len(base_games) else pd.DataFrame()
    cur_stats = cur_games.groupby('pid')['td'].agg(['mean', 'count']) if len(cur_games) else pd.DataFrame()

    pool = []
    for r in receivers + (qbs or []):
        pid = r['id']
        if r.get('isRookie'):
            # New-to-the-dataset player (see receivers/QBs build in main()) -- there is no
            # baseline TD history to fall back to at all, so judge them purely on their own
            # real current-season games, once there are enough to say anything real.
            if pid not in cur_stats.index or cur_stats.loc[pid, 'count'] < ROOKIE_MIN_GAMES:
                continue
            test_rate = float(cur_stats.loc[pid, 'mean']) * 100
            test_games = int(cur_stats.loc[pid, 'count'])
            pool.append({
                'id': f"atd_{pid}", 'player': r['name'], 'pos': r['pos'], 'team': r['team'],
                'stat': 'Anytime TD', 'kind': 'binary',
                'testRate': round(test_rate, 1), 'testGames': test_games,
                'baselineRate': None, 'baselineGames': 0, 'isRookie': True,
            })
            continue
        if pid not in base_stats.index or base_stats.loc[pid, 'count'] < 12:
            continue
        baseline_rate = float(base_stats.loc[pid, 'mean']) * 100
        if pid in cur_stats.index and cur_stats.loc[pid, 'count'] > 0:
            test_rate = float(cur_stats.loc[pid, 'mean']) * 100
            test_games = int(cur_stats.loc[pid, 'count'])
        else:
            test_rate, test_games = baseline_rate, int(base_stats.loc[pid, 'count'])
        pool.append({
            'id': f"atd_{pid}", 'player': r['name'], 'pos': r['pos'], 'team': r['team'],
            'stat': 'Anytime TD', 'kind': 'binary',
            'testRate': round(test_rate, 1), 'testGames': test_games,
            'baselineRate': round(baseline_rate, 1), 'baselineGames': int(base_stats.loc[pid, 'count']),
            'isRookie': False,
        })
    pool.sort(key=lambda p: -p['testRate'])
    return pool


def fetch_nfl_atd_odds(events, api_key, player_names):
    """Real sportsbook Anytime TD prices via the-odds-api.com's player_anytime_td market
    (confirmed as a real, documented market key — not a guess). The exact outcome naming
    convention for a binary yes/no market isn't something I can verify without a live key,
    so this prints the raw shape from the first real response it sees, and only acts on
    outcomes it can confidently identify as the 'yes' side — if the naming differs from
    what's expected here, that will show up in the diagnostic rather than silently
    returning nothing. Returns {player_name: {price, book}}."""
    out = {}
    diagnostic_printed = False
    for event in events[:25]:
        data = fetch_event_props('nfl', event['id'], api_key, ['player_anytime_td'])
        if not data:
            continue
        for bookmaker in data.get('bookmakers', []):
            for market in bookmaker.get('markets', []):
                if market['key'] != 'player_anytime_td':
                    continue
                if not diagnostic_printed:
                    print(f"  ATD market raw outcome sample: {market.get('outcomes', [])[:2]}")
                    diagnostic_printed = True
                for outcome in market.get('outcomes', []):
                    book_pname = outcome.get('description')
                    side = (outcome.get('name') or '').strip().lower()
                    if not book_pname or side not in ('yes', 'over', 'anytime'):
                        continue  # only the "yes" side matters here — skip "no" entirely
                    matched = fuzzy_match_player(book_pname, player_names)
                    if not matched or matched in out:
                        continue
                    out[matched] = {'price': outcome.get('price'), 'book': bookmaker.get('title')}
    print(f"  NFL: matched real Anytime TD prices for {len(out)} players")
    return out


def fetch_nfl_game_lines(events, api_key):
    """Real spread/total for upcoming NFL games, decomposed into each team's implied
    score. This is genuinely different information than a player's own season average —
    it's what the market currently expects for THIS specific matchup. Kept as its own
    function (not merged into the player-props fetch) since game-level outcomes have a
    completely different shape (per-team, not per-player) — cleaner to keep separate
    than to complicate the tested player-prop parsing logic. Returns
    {team_name: {impliedTotal, spread, total}}."""
    out = {}
    for event in events[:25]:
        data = fetch_event_props('nfl', event['id'], api_key, ['spreads', 'totals'])
        if not data:
            continue
        home_team, away_team = data.get('home_team'), data.get('away_team')
        for bookmaker in data.get('bookmakers', []):
            spread_market = next((m for m in bookmaker.get('markets', []) if m['key'] == 'spreads'), None)
            total_market = next((m for m in bookmaker.get('markets', []) if m['key'] == 'totals'), None)
            if not spread_market or not total_market:
                continue
            try:
                home_spread = next(o['point'] for o in spread_market['outcomes'] if o['name'] == home_team)
                total = next(o['point'] for o in total_market['outcomes'] if o['name'] in ('Over', 'over'))
            except (StopIteration, KeyError):
                continue
            # standard spread+total decomposition: home_score = (total - spread)/2, away = (total + spread)/2
            # (spread here is negative when home team favored, matching the odds API's own convention)
            home_implied = round((total - home_spread) / 2, 1)
            away_implied = round((total + home_spread) / 2, 1)
            if home_team and home_team not in out:
                out[home_team] = {'impliedTotal': home_implied, 'spread': home_spread, 'total': total, 'opponent': away_team}
            if away_team and away_team not in out:
                out[away_team] = {'impliedTotal': away_implied, 'spread': -home_spread, 'total': total, 'opponent': home_team}
            break  # one bookmaker's game line is enough here — this isn't a shopping comparison like props
    return out


def ensure_gitignored():
    """API keys must never reach the public repo. This makes that automatic rather
    than relying on remembering to edit .gitignore by hand."""
    entries = ["odds_api_key.txt", "cfbd_api_key.txt"]
    existing = GITIGNORE_PATH.read_text(encoding='utf-8') if GITIGNORE_PATH.exists() else ""
    missing = [e for e in entries if e not in existing]
    if not missing:
        return
    new_content = existing.rstrip('\n') + '\n' + '\n'.join(missing) + '\n' if existing else '\n'.join(missing) + '\n'
    GITIGNORE_PATH.write_text(new_content, encoding='utf-8')


def load_odds_api_key():
    # GitHub Actions injects secrets as environment variables — checked first so the exact
    # same script works unmodified whether it's running on your PC or in the cloud.
    env_key = os.environ.get('ODDS_API_KEY')
    if env_key and env_key.strip():
        return env_key.strip()
    if not ODDS_API_KEY_PATH.exists():
        return None
    key = ODDS_API_KEY_PATH.read_text(encoding='utf-8').strip()
    return key if key else None


def fetch_odds_events(sport, api_key, days_ahead):
    sport_key = ODDS_SPORT_KEYS[sport]
    try:
        r = requests.get(f"{ODDS_API_BASE}/sports/{sport_key}/events",
                          params={'apiKey': api_key}, timeout=20)
        if r.status_code != 200:
            return []
        events = r.json()
    except requests.RequestException:
        return []
    cutoff = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days_ahead)
    out = []
    for e in events:
        try:
            commence = datetime.datetime.fromisoformat(e['commence_time'].replace('Z', '+00:00'))
        except Exception:
            continue
        if commence <= cutoff:
            out.append(e)
    return out


def fetch_event_props(sport, event_id, api_key, markets):
    sport_key = ODDS_SPORT_KEYS[sport]
    try:
        r = requests.get(f"{ODDS_API_BASE}/sports/{sport_key}/events/{event_id}/odds",
                          params={'apiKey': api_key, 'regions': 'us', 'markets': ','.join(markets), 'oddsFormat': 'american'},
                          timeout=20)
        remaining = r.headers.get('x-requests-remaining')
        if remaining is not None:
            global ODDS_CREDITS_REMAINING
            ODDS_CREDITS_REMAINING = remaining
        if r.status_code != 200:
            return None
        return r.json()
    except requests.RequestException:
        return None


ODDS_CREDITS_REMAINING = None  # updated from the API's own response headers as calls happen


def fuzzy_match_player(book_name, known_names):
    """Real sportsbook name formatting doesn't always match ours exactly — this finds
    the closest known player by normalized substring/token overlap, not an exact match."""
    norm = lambda s: re.sub(r'[^a-z\s]', '', s.lower()).strip()
    condensed = lambda s: re.sub(r'[^a-z]', '', s.lower())  # catches apostrophe-vs-space quirks, e.g. "Ja Marr" vs "Ja'Marr"
    target = norm(book_name)
    target_condensed = condensed(book_name)
    if not target:
        return None
    for name in known_names:
        if condensed(name) == target_condensed:
            return name
    best, best_score = None, 0
    for name in known_names:
        n = norm(name)
        if n == target:
            return name
        target_tokens = set(target.split())
        n_tokens = set(n.split())
        overlap = len(target_tokens & n_tokens)
        if overlap > best_score and overlap >= 2:  # first+last name both matching, minimum
            best_score = overlap
            best = name
    return best


def build_real_odds(sport, api_key, player_names, days_ahead):
    """Returns {(player_name, stat_label): [{line, overPrice, underPrice, book}, ...]} — one
    entry per bookmaker that has this player/stat, so the site can show every real price
    instead of just whichever book happened to come back first. No extra API cost: the
    response already includes every requested US bookmaker per event, this just stops
    throwing the rest away."""
    market_map = ODDS_MARKET_MAP[sport]
    markets = list(market_map.values())
    reverse_map = {v: k for k, v in market_map.items()}
    events = fetch_odds_events(sport, api_key, days_ahead)
    out = {}
    for event in events[:25]:  # widened now that you're on the paid tier (was capped at 8 for the
                                # free tier's 500/month budget). Your real observed cost at 8 events/sport
                                # was ~37 credits total across all 3 sports — well under my conservative
                                # worst-case estimate — so 25 should land roughly 3x that (~110-150 credits/run),
                                # comfortable even with both the 2x/day automation and manual test runs on
                                # top. Real usage will vary run to run; ask if you want this tuned further
                                # once you've seen a few real runs' actual credit cost.
        data = fetch_event_props(sport, event['id'], api_key, markets)
        if not data:
            continue
        for bookmaker in data.get('bookmakers', []):
            for market in bookmaker.get('markets', []):
                stat_label = reverse_map.get(market['key'])
                if not stat_label:
                    continue
                # group Over/Under outcome pairs by player
                by_player = {}
                for outcome in market.get('outcomes', []):
                    pname = outcome.get('description')
                    if not pname:
                        continue
                    by_player.setdefault(pname, {})[outcome['name']] = outcome
                for book_pname, sides in by_player.items():
                    matched = fuzzy_match_player(book_pname, player_names)
                    if not matched:
                        continue
                    over = sides.get('Over')
                    under = sides.get('Under')
                    if not over:
                        continue
                    key = (matched, stat_label)
                    book_name = bookmaker.get('title')
                    entry_list = out.setdefault(key, [])
                    if any(e['book'] == book_name for e in entry_list):
                        continue  # this exact book already recorded for this player/stat this run
                    entry_list.append({
                        'line': over.get('point'), 'overPrice': over.get('price'),
                        'underPrice': under.get('price') if under else None, 'book': book_name,
                    })
        # bookmakers key present but no matching markets still counts against quota — nothing else to do here
    return out

TEMPLATE_PATH = SCRIPT_DIR / "dashboard_template.jsx"
OUTPUT_HTML = SCRIPT_DIR / "index.html"

BASELINE_SEASONS = [2024, 2025]   # the validated historical train/test backtest — never changes

# Static mapping, not guessed at runtime — NFL franchise names are stable (unlike API field
# names), so hardcoding this is safe. Needed to match nflverse's team abbreviations against
# the-odds-api.com's full-name team identifiers for the game-script signal.
NFL_TEAM_FULL_NAMES = {
    'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens', 'BUF': 'Buffalo Bills',
    'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears', 'CIN': 'Cincinnati Bengals', 'CLE': 'Cleveland Browns',
    'DAL': 'Dallas Cowboys', 'DEN': 'Denver Broncos', 'DET': 'Detroit Lions', 'GB': 'Green Bay Packers',
    'HOU': 'Houston Texans', 'IND': 'Indianapolis Colts', 'JAX': 'Jacksonville Jaguars', 'KC': 'Kansas City Chiefs',
    'LA': 'Los Angeles Rams', 'LAC': 'Los Angeles Chargers', 'LV': 'Las Vegas Raiders', 'MIA': 'Miami Dolphins',
    'MIN': 'Minnesota Vikings', 'NE': 'New England Patriots', 'NO': 'New Orleans Saints', 'NYG': 'New York Giants',
    'NYJ': 'New York Jets', 'PHI': 'Philadelphia Eagles', 'PIT': 'Pittsburgh Steelers', 'SEA': 'Seattle Seahawks',
    'SF': 'San Francisco 49ers', 'TB': 'Tampa Bay Buccaneers', 'TEN': 'Tennessee Titans', 'WAS': 'Washington Commanders',
}
CANDIDATE_CURRENT_SEASONS = [2026, 2027]  # script auto-detects whichever of these has real data

# Re-enabled (2026-09-28) now that a missing local `xgboost` install can no longer crash the
# pipeline: the import itself is wrapped in try/except (prints a one-line skip notice and
# returns cleanly if the package isn't there), and the call site below is also wrapped in
# try/except as a second layer. Extended (2026-10-03) from Receiving Yards only to every
# real ladder stat (receiving, rushing, passing, kicking) -- each one is trained and graded
# independently, and only ever attaches to a real prop entry if IT genuinely beats its own
# naive baseline by 3+ points; a stat that doesn't is just a printed, tracked number.
ENABLE_XGBOOST_DIAGNOSTIC = True

# Shrinkage constant for blending current-season-to-date with the historical baseline.
# weight_current = games_this_season / (games_this_season + SHRINKAGE_K)
# e.g. with K=4: 2 games in -> 33% current-season weight, 8 games in -> 67%, 16 games in -> 80%
SHRINKAGE_K = 4

# Minimum real current-season games before a player with ZERO 2024-25 baseline history
# (a true rookie, a practice-squad call-up now starting, anyone new to the dataset) gets
# their own entry at all -- receivers/QBs/kickers/sacks/Anytime-TD/prop-ladder pools are
# all otherwise built by iterating the baseline season's players ONLY, which makes a
# brand-new player 100% invisible no matter how much real production they have this
# season. This is the single knob controlling how early that player shows up once real
# data exists for them.
ROOKIE_MIN_GAMES = 3

NFLVERSE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"


# =====================================================================
# DOWNLOAD HELPERS
# =====================================================================
def download(url, dest_path, retries=3):
    """Download url to dest_path if not already cached. Returns True on success.

    Nearly every real data fetch in this pipeline (NFL pbp/participation/rosters, WNBA
    pbp/schedules, injuries, depth charts) funnels through this one function, so a single
    unretried request with a bare except was a single point of failure for an entire
    sport's data on any transient network blip -- silently, with nothing printed to say
    why. Now retries a couple of times with a short backoff and prints the real reason
    when it ultimately fails, same fix as season_has_data()/wnba_season_has_data() below.
    """
    if dest_path.exists():
        return True
    last_detail = None
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=180)
            if r.status_code == 200:
                dest_path.write_bytes(r.content)
                return True
            last_detail = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last_detail = f"{type(e).__name__}: {e}"
        if attempt < retries - 1:
            time.sleep(0.5 + random.random() * 0.5)
    print(f"  [!] download failed after {retries} attempt(s) for {url}: {last_detail}")
    return False


def season_has_data(season):
    """Check whether a season's play-by-play file exists on nflverse yet.

    A single unretried HEAD request used to decide this, with any failure (timeout,
    dropped redirect, transient network blip) silently swallowed into "no data" -- so
    a real current season could get missed for reasons that were never visible in the
    console output. Now: retries the HEAD a couple of times, falls back to a 1-byte
    ranged GET (some networks/CDNs mishandle HEAD-through-redirect but are fine with
    GET), and always prints exactly what happened so a "no data" result is diagnosable
    instead of a guess.
    """
    url = f"{NFLVERSE_BASE}/pbp/play_by_play_{season}.parquet"
    last_detail = None
    for attempt in range(3):
        try:
            r = requests.head(url, timeout=30, allow_redirects=True)
            if r.status_code == 200:
                return True
            last_detail = f"HEAD -> HTTP {r.status_code}"
        except requests.RequestException as e:
            last_detail = f"HEAD raised {type(e).__name__}: {e}"
        time.sleep(0.5 + random.random() * 0.5)

    try:
        r = requests.get(url, timeout=30, allow_redirects=True, headers={'Range': 'bytes=0-0'}, stream=True)
        ok = r.status_code in (200, 206)
        r.close()
        if ok:
            print(f"  [{season}] HEAD check failed ({last_detail}) but a ranged GET succeeded -- treating as available")
            return True
        last_detail = f"{last_detail}; ranged GET -> HTTP {r.status_code}"
    except requests.RequestException as e:
        last_detail = f"{last_detail}; ranged GET raised {type(e).__name__}: {e}"

    print(f"  [{season}] season_has_data check failed after retries: {last_detail}")
    return False


def fetch_season_files(season):
    """Download pbp, participation, and roster files for a season into the cache."""
    files = {
        "pbp": (f"{NFLVERSE_BASE}/pbp/play_by_play_{season}.parquet", CACHE_DIR / f"pbp_{season}.parquet"),
        "participation": (f"{NFLVERSE_BASE}/pbp_participation/pbp_participation_{season}.parquet",
                           CACHE_DIR / f"participation_{season}.parquet"),
        "roster": (f"{NFLVERSE_BASE}/rosters/roster_{season}.parquet", CACHE_DIR / f"roster_{season}.parquet"),
    }
    ok = True
    for key, (url, path) in files.items():
        # always re-download the current season's files (data changes weekly);
        # baseline seasons are cached permanently once complete.
        if season not in BASELINE_SEASONS and path.exists():
            path.unlink()
        success = download(url, path)
        if not success:
            print(f"  [!] Could not fetch {key} for {season} (may not exist yet)")
            ok = False
    return ok


def fetch_games_file():
    path = CACHE_DIR / "games.csv"
    if path.exists():
        path.unlink()  # schedules update every week; always refresh
    download(f"{NFLVERSE_BASE}/schedules/games.csv", path)
    return path


# =====================================================================
# WNBA PIPELINE (sportsdataverse — same free-data pattern as nflverse)
# =====================================================================
WNBA_BASE = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_wnba_pbp"
WNBA_TRAIN_SEASON = 2025
WNBA_CANDIDATE_TEST_SEASONS = [2026, 2027]


def fetch_wnba_pbp(season):
    path = CACHE_DIR / f"wnba_pbp_{season}.parquet"
    if path.exists():
        path.unlink()  # always refresh — WNBA in-season data updates constantly
    ok = download(f"{WNBA_BASE}/play_by_play_{season}.parquet", path)
    return path if ok else None


def wnba_season_has_data(season):
    """Check whether a WNBA season's play-by-play file exists yet.

    Same bug and same fix as NFL's season_has_data(): a single unretried HEAD request
    wrapped in a bare except was deciding this, so any transient network blip silently
    reported "no data" for the whole season -- indistinguishable from the season
    genuinely not existing yet, with nothing printed to tell the two apart. Retries the
    HEAD, falls back to a ranged GET, and prints exactly what failed at each step.
    """
    url = f"{WNBA_BASE}/play_by_play_{season}.parquet"
    last_detail = None
    reachable = False
    for attempt in range(3):
        try:
            r = requests.head(url, timeout=30, allow_redirects=True)
            if r.status_code == 200:
                reachable = True
                break
            last_detail = f"HEAD -> HTTP {r.status_code}"
        except requests.RequestException as e:
            last_detail = f"HEAD raised {type(e).__name__}: {e}"
        time.sleep(0.5 + random.random() * 0.5)

    if not reachable:
        try:
            r = requests.get(url, timeout=30, allow_redirects=True, headers={'Range': 'bytes=0-0'}, stream=True)
            ok = r.status_code in (200, 206)
            r.close()
            if ok:
                print(f"  [WNBA {season}] HEAD check failed ({last_detail}) but a ranged GET succeeded -- treating as available")
                reachable = True
            else:
                last_detail = f"{last_detail}; ranged GET -> HTTP {r.status_code}"
        except requests.RequestException as e:
            last_detail = f"{last_detail}; ranged GET raised {type(e).__name__}: {e}"

    if not reachable:
        print(f"  [WNBA {season}] season_has_data check failed after retries: {last_detail}")
        return False

    test_path = CACHE_DIR / f"_wnba_probe_{season}.parquet"
    if not download(url, test_path):
        print(f"  [WNBA {season}] file is reachable but the full download failed -- treating as unavailable this run")
        return False
    try:
        df = pd.read_parquet(test_path, columns=['game_id'])
        n = df['game_id'].nunique()
        if n < 5:
            print(f"  [WNBA {season}] file downloaded but only has {n} unique game(s) so far -- not enough data yet")
        return n >= 5
    except Exception as e:
        print(f"  [WNBA {season}] file downloaded but failed to parse: {type(e).__name__}: {e}")
        return False


def build_wnba_box_scores(df):
    df = df.copy()
    df['is_three'] = df['text'].str.contains('three point', case=False, na=False)
    df['made_shot'] = (df['shooting_play'] == True) & (df['score_value'] > 0)
    df['missed_shot'] = (df['shooting_play'] == True) & (df['score_value'] == 0)
    df['is_ft'] = df['type_text'].str.contains('Free Throw', na=False)
    df['ft_made'] = df['is_ft'] & df['text'].str.contains(' makes ', case=False, na=False)
    df['is_oreb'] = df['type_text'] == 'Offensive Rebound'
    df['is_dreb'] = df['type_text'] == 'Defensive Rebound'
    df['is_to'] = df['type_text'].str.contains('Turnover', na=False)
    df['is_assist'] = df['made_shot'] & df['text'].str.contains('assists', case=False, na=False)
    df['is_block'] = df['missed_shot'] & df['text'].str.contains('blocks', case=False, na=False)
    df['is_steal'] = df['is_to'] & df['text'].str.contains('steals', case=False, na=False)
    df['is_home'] = df['team_id'] == df['home_team_id']
    return df


def wnba_game_logs(df):
    shots = df[df.shooting_play == True].copy()
    shots['pts_scored'] = np.where(shots.made_shot, shots.score_value, 0)
    shots['tpm_flag'] = shots.is_three & shots.made_shot
    fg_agg = shots.groupby(['game_id', 'athlete_name_1']).agg(
        fga=('id', 'count'), fgm=('made_shot', 'sum'), tpa=('is_three', 'sum'), tpm=('tpm_flag', 'sum'), pts=('pts_scored', 'sum'))
    fg_agg.index = fg_agg.index.set_names(['game_id', 'player'])
    home_by_gp = shots.groupby(['game_id', 'athlete_name_1'])['is_home'].first()
    home_by_gp.index = home_by_gp.index.set_names(['game_id', 'player'])

    ft = df[df.is_ft].copy()
    ft_agg = ft.groupby(['game_id', 'athlete_name_1']).agg(fta=('id', 'count'), ftm=('ft_made', 'sum'))
    ft_agg.index = ft_agg.index.set_names(['game_id', 'player'])

    def reindex(s):
        s = s.copy(); s.index = s.index.set_names(['game_id', 'player']); return s
    reb = reindex(df[df.is_oreb | df.is_dreb].groupby(['game_id', 'athlete_name_1']).size().rename('reb'))
    tov = reindex(df[df.is_to].groupby(['game_id', 'athlete_name_1']).size().rename('tov'))
    ast = reindex(df[df.is_assist].groupby(['game_id', 'athlete_name_2']).size().rename('ast'))
    stl = reindex(df[df.is_steal].groupby(['game_id', 'athlete_name_2']).size().rename('stl'))
    blk = reindex(df[df.is_block].groupby(['game_id', 'athlete_name_2']).size().rename('blk'))

    combined = pd.concat([fg_agg, ft_agg, reb, tov, ast, stl, blk, home_by_gp.rename('is_home')], axis=1).fillna(0)
    combined['pts'] = combined['pts'] + combined['ftm']
    combined = combined.reset_index()

    team_id_map = shots.groupby('athlete_name_1')['team_id'].agg(lambda x: x.mode().iloc[0])
    combined['team_id'] = combined.player.map(team_id_map)
    team_totals = combined.groupby(['game_id', 'team_id']).agg(team_fga=('fga', 'sum'), team_fta=('fta', 'sum'), team_tov=('tov', 'sum')).reset_index()
    combined = combined.merge(team_totals, on=['game_id', 'team_id'], how='left')
    combined['usage_raw'] = 100 * (combined.fga + 0.44*combined.fta + combined.tov) / (combined.team_fga + 0.44*combined.team_fta + combined.team_tov).replace(0, np.nan)

    # opponent + date context — "who did they play and when"
    game_ctx = df.drop_duplicates('game_id').set_index('game_id')[['home_team_id', 'away_team_id', 'home_team_name', 'away_team_name', 'game_date']]
    combined = combined.merge(game_ctx, on='game_id', how='left')
    combined['opp_team_name'] = np.where(combined['team_id'] == combined['home_team_id'], combined['away_team_name'], combined['home_team_name'])
    combined['game_date'] = combined['game_date'].astype(str)
    return combined


def build_wnba_team_names(df):
    names = {}
    for tid, row in df.drop_duplicates('home_team_id').set_index('home_team_id').iterrows():
        names[tid] = row['home_team_name']
    for tid, row in df.drop_duplicates('away_team_id').set_index('away_team_id').iterrows():
        if tid not in names:
            names[tid] = row['away_team_name']
    return names


def agg_wnba_opponent_games(g):
    """Real per-game average line for whatever slice of games is passed in -- used both for
    a player's overall averages and, sliced by opp_team_name, for their real history against
    one specific opponent. Same shape either way so the two are directly comparable."""
    n = len(g)
    if n == 0:
        return None
    fga = g.fga.sum(); fgm = g.fgm.sum(); tpa = g.tpa.sum(); tpm = g.tpm.sum()
    return {
        'games': int(n), 'pts': round(g.pts.mean(), 1), 'reb': round(g.reb.mean(), 1), 'ast': round(g.ast.mean(), 1),
        'fgPct': round(100 * fgm / max(fga, 1), 1),
        'tpPct': round(100 * tpm / tpa, 1) if tpa > 0 else None,
        'tpaPerGame': round(tpa / n, 1),
    }


def build_wnba_players(gl_train, gl_test, team_names):
    players = []
    for player in gl_train.player.unique():
        train_g = gl_train[gl_train.player == player]
        test_g = gl_test[gl_test.player == player]
        if len(train_g) < 8:
            continue
        all_g = pd.concat([train_g, test_g])
        team_id = all_g.team_id.mode().iloc[0] if len(all_g) else None
        team_name = team_names.get(team_id, str(team_id))
        overall = {
            'games': int(len(all_g)), 'pts': round(all_g.pts.mean(), 1), 'reb': round(all_g.reb.mean(), 1),
            'ast': round(all_g.ast.mean(), 1), 'stl': round(all_g.stl.mean(), 1), 'blk': round(all_g.blk.mean(), 1),
            'tov': round(all_g.tov.mean(), 1) if 'tov' in all_g.columns else None,
            'fgPct': round(100 * all_g.fgm.sum() / max(all_g.fga.sum(), 1), 1),
            'tpPct': round(100 * all_g.tpm.sum() / max(all_g.tpa.sum(), 1), 1),
            'usage': round(all_g.usage_raw.mean(), 1) if all_g.usage_raw.notna().any() else None,
        }
        home_g = all_g[all_g.is_home == True]; away_g = all_g[all_g.is_home == False]
        # Real per-opponent history -- across the 2025 baseline plus this season to date, so a
        # WNBA team met this many times gives a real (if thin) sample. This is the WNBA analog
        # of the NFL per-coverage split: no scheme classification is possible from ESPN's WNBA
        # play-by-play (no shot location/zone or defender data at all), so "this specific
        # opponent" stands in for "this specific coverage" as the real, checkable signal.
        vs_opp = {opp: agg_wnba_opponent_games(gg) for opp, gg in all_g.groupby('opp_team_name') if len(gg) >= 2}
        players.append({
            'name': player, 'team': team_name, 'overall': overall,
            'home': {'pts': round(home_g.pts.mean(), 1) if len(home_g) else None, 'games': int(len(home_g))},
            'away': {'pts': round(away_g.pts.mean(), 1) if len(away_g) else None, 'games': int(len(away_g))},
            'gamelog': test_g[['game_id', 'pts', 'reb', 'ast', 'stl', 'blk', 'fga', 'fgm', 'tpa', 'tpm', 'opp_team_name', 'game_date', 'is_home']].to_dict('records'),
            'vsOpp': vs_opp,
            'isRookie': False,
        })

    # New-to-the-dataset players -- a WNBA rookie, or anyone who didn't play enough (or at
    # all) in the WNBA_TRAIN_SEASON baseline -- are otherwise invisible here no matter how
    # many real games they've played this season, same root issue as the NFL pools above.
    train_players = set(gl_train.player.unique())
    for player in gl_test.player.unique():
        if player in train_players:
            continue
        test_g = gl_test[gl_test.player == player]
        if len(test_g) < ROOKIE_MIN_GAMES:
            continue
        team_id = test_g.team_id.mode().iloc[0] if len(test_g) else None
        team_name = team_names.get(team_id, str(team_id))
        overall = {
            'games': int(len(test_g)), 'pts': round(test_g.pts.mean(), 1), 'reb': round(test_g.reb.mean(), 1),
            'ast': round(test_g.ast.mean(), 1), 'stl': round(test_g.stl.mean(), 1), 'blk': round(test_g.blk.mean(), 1),
            'tov': round(test_g.tov.mean(), 1) if 'tov' in test_g.columns else None,
            'fgPct': round(100 * test_g.fgm.sum() / max(test_g.fga.sum(), 1), 1),
            'tpPct': round(100 * test_g.tpm.sum() / max(test_g.tpa.sum(), 1), 1),
            'usage': round(test_g.usage_raw.mean(), 1) if test_g.usage_raw.notna().any() else None,
        }
        home_g = test_g[test_g.is_home == True]; away_g = test_g[test_g.is_home == False]
        vs_opp = {opp: agg_wnba_opponent_games(gg) for opp, gg in test_g.groupby('opp_team_name') if len(gg) >= 2}
        players.append({
            'name': player, 'team': team_name, 'overall': overall,
            'home': {'pts': round(home_g.pts.mean(), 1) if len(home_g) else None, 'games': int(len(home_g))},
            'away': {'pts': round(away_g.pts.mean(), 1) if len(away_g) else None, 'games': int(len(away_g))},
            'gamelog': test_g[['game_id', 'pts', 'reb', 'ast', 'stl', 'blk', 'fga', 'fgm', 'tpa', 'tpm', 'opp_team_name', 'game_date', 'is_home']].to_dict('records'),
            'vsOpp': vs_opp,
            'isRookie': True,
        })
    players.sort(key=lambda p: -p['overall']['pts'])
    return players


def build_wnba_pool(gl_train, gl_test):
    MIN25 = {'Points': 6, 'Rebounds': 2, 'Assists': 1, 'Steals': 0, 'Blocks': 0, 'Three-Pointers Made': 0}
    MIN50 = {'Points': 12, 'Rebounds': 4, 'Assists': 2, 'Steals': 1, 'Blocks': 1, 'Three-Pointers Made': 1}

    def ladder(train_vals, test_vals, label):
        if len(train_vals) < 8 or len(test_vals) < 6:
            return None
        p25 = np.floor(np.percentile(train_vals, 25)); p50 = np.floor(np.percentile(train_vals, 50)); p75 = np.floor(np.percentile(train_vals, 75))
        if p25 < MIN25[label] or p50 < MIN50[label] or p75 <= p50:
            return None
        def hit(line): return round(float((test_vals >= line).mean()) * 100, 1)
        return {'p25': {'line': float(p25), 'testHit': hit(p25)}, 'p50': {'line': float(p50), 'testHit': hit(p50)},
                'p75': {'line': float(p75), 'testHit': hit(p75)}, 'trainGames': int(len(train_vals)), 'testGames': int(len(test_vals))}

    def ladder_rookie(ordered_vals, label, min_games=ROOKIE_MIN_GAMES):
        """Same math as ladder(), but split WITHIN this season's own games for a player
        with no WNBA_TRAIN_SEASON baseline at all -- see pctile_ladder_rookie in the NFL
        section above for the full reasoning (held-out test slice, never self-graded)."""
        n = len(ordered_vals)
        if n < min_games:
            return None
        test_n = max(1, n // 3)
        train_vals = np.array(ordered_vals[:-test_n], dtype=float)
        test_vals = np.array(ordered_vals[-test_n:], dtype=float)
        if len(train_vals) == 0:
            return None
        p25 = np.floor(np.percentile(train_vals, 25)); p50 = np.floor(np.percentile(train_vals, 50)); p75 = np.floor(np.percentile(train_vals, 75))
        if p25 < MIN25[label] or p50 < MIN50[label] or p75 <= p50:
            return None
        def hit(line): return round(float((test_vals >= line).mean()) * 100, 1)
        return {'p25': {'line': float(p25), 'testHit': hit(p25)}, 'p50': {'line': float(p50), 'testHit': hit(p50)},
                'p75': {'line': float(p75), 'testHit': hit(p75)}, 'trainGames': int(len(train_vals)), 'testGames': int(len(test_vals))}

    stat_map = [('pts', 'Points'), ('reb', 'Rebounds'), ('ast', 'Assists'), ('stl', 'Steals'), ('blk', 'Blocks'), ('tpm', 'Three-Pointers Made')]
    pool = []
    train_players = set(gl_train.player.unique())
    for player in gl_train.player.unique():
        train_g = gl_train[gl_train.player == player]
        test_g = gl_test[gl_test.player == player]
        if len(train_g) < 8 or len(test_g) < 6:
            continue
        for key, label in stat_map:
            l = ladder(train_g[key].values, test_g[key].values, label)
            if l:
                pool.append({'player': player, 'stat': label, 'kind': 'ladder', **l, 'isRookie': False,
                             'id': f"{player}|{label}".replace(' ', '_')})

    # New-to-the-dataset players (see build_wnba_players above) -- no WNBA_TRAIN_SEASON
    # baseline to split against, so the line comes from this season's own games alone.
    for player in gl_test.player.unique():
        if player in train_players:
            continue
        test_g = gl_test[gl_test.player == player].sort_values('game_date')
        if len(test_g) < ROOKIE_MIN_GAMES:
            continue
        for key, label in stat_map:
            l = ladder_rookie(test_g[key].values, label)
            if l:
                pool.append({'player': player, 'stat': label, 'kind': 'ladder', **l, 'isRookie': True,
                             'id': f"{player}|{label}".replace(' ', '_')})
    return pool


def build_wnba_upcoming(wnba_test_season):
    """Next scheduled game per team, from the real published WNBA schedule."""
    sched_path = CACHE_DIR / f"wnba_schedule_{wnba_test_season}.parquet"
    if sched_path.exists():
        sched_path.unlink()
    ok = download(f"{WNBA_BASE.replace('espn_wnba_pbp','espn_wnba_schedules')}/wnba_schedule_{wnba_test_season}.parquet", sched_path)
    if not ok:
        return {}
    try:
        sched = pd.read_parquet(sched_path)
    except Exception:
        return {}
    today = pd.Timestamp.now(tz='UTC')
    sched['date_parsed'] = pd.to_datetime(sched['date'], utc=True, errors='coerce')
    future = sched[sched['date_parsed'] > today].sort_values('date_parsed')
    upcoming = {}
    for _, g in future.iterrows():
        for team, opp in [(g['home_display_name'], g['away_display_name']), (g['away_display_name'], g['home_display_name'])]:
            city = team.rsplit(' ', 1)[0] if ' ' in team else team
            if city not in upcoming:
                upcoming[city] = {'opp': opp, 'date': g['date_parsed'].strftime('%Y-%m-%d')}
    return upcoming


def build_nfl_upcoming(games_all):
    """Next scheduled game per team, from the already-published NFL schedule. Includes the
    real Vegas spread/total already sitting in nflverse's schedule data, previously unused."""
    today = pd.Timestamp.now().normalize()
    games_all = games_all.copy()
    games_all['gameday_parsed'] = pd.to_datetime(games_all['gameday'], errors='coerce')
    future = games_all[games_all['gameday_parsed'] >= today].sort_values('gameday_parsed')
    upcoming = {}
    for _, g in future.iterrows():
        spread = g.get('spread_line')
        total = g.get('total_line')
        for team, opp, is_home in [(g['home_team'], g['away_team'], True), (g['away_team'], g['home_team'], False)]:
            if team not in upcoming:
                # spread_line is from the home team's perspective in nflverse convention
                team_spread = None
                if pd.notna(spread):
                    team_spread = float(spread) if is_home else -float(spread)
                upcoming[team] = {
                    'opp': opp, 'date': g['gameday_parsed'].strftime('%Y-%m-%d'), 'isHome': is_home, 'week': int(g['week']),
                    'spread': team_spread, 'total': float(total) if pd.notna(total) else None,
                }
    return upcoming


def build_wnba_team_defense(df):
    final = df.groupby('game_id').agg(home_score=('home_score', 'max'), away_score=('away_score', 'max'),
                                       home_team=('home_team_name', 'first'), away_team=('away_team_name', 'first')).reset_index()
    rows = []
    for _, g in final.iterrows():
        rows.append({'team': g.home_team, 'allowed': g.away_score, 'scored': g.home_score})
        rows.append({'team': g.away_team, 'allowed': g.home_score, 'scored': g.away_score})
    pa = pd.DataFrame(rows)
    agg = pa.groupby('team').agg(games=('allowed', 'count'), total_allowed=('allowed', 'sum'), total_scored=('scored', 'sum')).reset_index()
    agg = agg[agg.games >= 10]
    agg['ppgAllowed'] = agg['total_allowed'] / agg['games']
    agg['ppgScored'] = agg['total_scored'] / agg['games']
    agg['rank'] = agg['ppgAllowed'].rank(ascending=False).astype(int)
    agg['scoredRank'] = agg['ppgScored'].rank(ascending=False).astype(int)
    return {row['team']: {'ppgAllowed': round(row['ppgAllowed'], 1), 'rank': int(row['rank']),
                           'ppgScored': round(row['ppgScored'], 1), 'scoredRank': int(row['scoredRank']),
                           'games': int(row['games'])}
            for _, row in agg.iterrows()}


def build_wnba_defense_profile(df, team_names):
    """Real 3-point rate allowed per team -- the one genuine defensive-shape signal available
    from ESPN's WNBA play-by-play. There's no shot location/zone or defender tracking in this
    feed, so zone-vs-man can't be classified the way NFL coverage can; this is the finest real
    signal that actually exists: a defense that helps off shooters or packs the paint gives up
    a higher share of its opponents' shots as threes, whatever the specific scheme is called."""
    shots = df[df['shooting_play'] == True].copy()
    shots['def_team_id'] = np.where(shots['team_id'] == shots['home_team_id'], shots['away_team_id'], shots['home_team_id'])
    agg = shots.groupby('def_team_id').agg(fgaFaced=('id', 'count'), tpaFaced=('is_three', 'sum'),
                                             games=('game_id', 'nunique')).reset_index()
    agg = agg[agg['games'] >= 3]
    if len(agg) == 0:
        return {}
    agg['threePtRateAllowed'] = 100 * agg['tpaFaced'] / agg['fgaFaced'].replace(0, np.nan)
    agg['rank'] = agg['threePtRateAllowed'].rank(ascending=False).astype(int)
    out = {}
    for _, row in agg.iterrows():
        team = team_names.get(row['def_team_id'], str(row['def_team_id']))
        out[team] = {'threePtRateAllowed': round(float(row['threePtRateAllowed']), 1), 'rank': int(row['rank']), 'games': int(row['games'])}
    return out


# =====================================================================
# MLB PIPELINE (official MLB Stats API — statsapi.mlb.com, free, no key)
# NOTE: could not be test-executed against live data from this environment
# (statsapi.mlb.com is outside this sandbox's network allowlist). Built
# defensively against documented API conventions — every player fetch is
# individually try/excepted so a bad assumption fails quietly per-player
# rather than breaking the whole run. The first real run is the real test.
# =====================================================================
MLB_API = "https://statsapi.mlb.com/api/v1"
MLB_TRAIN_SEASON = 2025
MLB_CANDIDATE_TEST_SEASONS = [2026, 2027]


def mlb_get(path, params=None, timeout=20):
    try:
        r = requests.get(f"{MLB_API}{path}", params=params or {}, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.json()
    except requests.RequestException:
        return None


def mlb_season_has_data(season):
    data = mlb_get("/schedule", {"sportId": 1, "season": season, "gameType": "R"})
    if not data or 'dates' not in data:
        return False
    total_games = sum(len(d.get('games', [])) for d in data.get('dates', []))
    return total_games >= 5


def fetch_mlb_teams():
    data = mlb_get("/teams", {"sportId": 1, "activeStatus": "Yes"})
    if not data or 'teams' not in data:
        return {}
    return {t['id']: t.get('name', str(t['id'])) for t in data['teams']}


def fetch_mlb_qualified_players(season, group, limit=175):
    """Season leaderboard call to identify which players have enough volume to bother
    fetching a full game log for (avoids hitting the API for every player in the league)."""
    data = mlb_get("/stats", {"stats": "season", "group": group, "season": season, "sportId": 1, "limit": limit})
    if not data or 'stats' not in data or len(data['stats']) == 0:
        return []
    splits = data['stats'][0].get('splits', [])
    out = []
    for s in splits:
        player = s.get('player', {})
        team = s.get('team', {})
        if player.get('id'):
            out.append({'id': player['id'], 'name': player.get('fullName', str(player['id'])),
                        'teamId': team.get('id'), 'teamName': team.get('name')})
    return out


def fetch_mlb_game_log(player_id, season, group):
    data = mlb_get(f"/people/{player_id}/stats", {"stats": "gameLog", "group": group, "season": season})
    if not data or 'stats' not in data or len(data['stats']) == 0:
        return []
    splits = data['stats'][0].get('splits', [])
    rows = []
    for s in splits:
        stat = s.get('stat', {})
        opp = s.get('opponent', {})
        row = {'date': s.get('date'), 'gamePk': s.get('game', {}).get('gamePk'),
               'isHome': s.get('isHome'), 'opp': opp.get('name')}
        if group == 'hitting':
            row.update({
                'hits': int(stat.get('hits', 0) or 0), 'runs': int(stat.get('runs', 0) or 0),
                'rbi': int(stat.get('rbi', 0) or 0), 'hr': int(stat.get('homeRuns', 0) or 0),
                'sb': int(stat.get('stolenBases', 0) or 0), 'bb': int(stat.get('baseOnBalls', 0) or 0),
                'so': int(stat.get('strikeOuts', 0) or 0), 'ab': int(stat.get('atBats', 0) or 0),
                'tb': int(stat.get('totalBases', 0) or 0),
            })
        else:  # pitching
            row.update({
                'ip': float(stat.get('inningsPitched', 0) or 0), 'er': int(stat.get('earnedRuns', 0) or 0),
                'so': int(stat.get('strikeOuts', 0) or 0), 'bb': int(stat.get('baseOnBalls', 0) or 0),
                'hitsAllowed': int(stat.get('hits', 0) or 0), 'wins': int(stat.get('wins', 0) or 0),
                'saves': int(stat.get('saves', 0) or 0), 'er': int(stat.get('earnedRuns', 0) or 0),
            })
        rows.append(row)
    return rows


def build_mlb_players(train_season, test_season, team_names):
    """Batters + pitchers, same overall/home/away/gamelog shape as WNBA_PLAYERS."""
    players = []
    for group, stat_keys in [('hitting', ['hits','runs','rbi','hr','sb','bb','so','ab','tb']),
                              ('pitching', ['ip','er','so','bb','hitsAllowed','wins','saves'])]:
        qualified = fetch_mlb_qualified_players(train_season, group)
        print(f"    {len(qualified)} qualified {group} players from {train_season} leaderboard")
        for p in qualified:
            try:
                train_log = fetch_mlb_game_log(p['id'], train_season, group)
                test_log = fetch_mlb_game_log(p['id'], test_season, group)
            except Exception:
                continue
            if len(train_log) < 8:
                continue
            all_log = train_log + test_log
            if len(all_log) == 0:
                continue

            def avg(key, log=all_log):
                vals = [g.get(key, 0) for g in log]
                return round(sum(vals) / len(vals), 2) if vals else None

            overall = {'games': len(all_log), 'group': group}
            if group == 'hitting':
                total_ab = sum(g.get('ab', 0) for g in all_log)
                total_hits = sum(g.get('hits', 0) for g in all_log)
                total_bb = sum(g.get('bb', 0) for g in all_log)
                total_tb = sum(g.get('tb', 0) for g in all_log)
                total_sb = sum(g.get('sb', 0) for g in all_log)
                obp = round((total_hits + total_bb) / (total_ab + total_bb), 3) if (total_ab + total_bb) else None
                slg = round(total_tb / total_ab, 3) if total_ab else None
                overall.update({
                    'avg_hits': avg('hits'), 'avg_hr': avg('hr'), 'avg_rbi': avg('rbi'), 'avg_runs': avg('runs'),
                    'battingAvg': round(total_hits / total_ab, 3) if total_ab else None,
                    'totalHR': sum(g.get('hr', 0) for g in all_log), 'totalRBI': sum(g.get('rbi', 0) for g in all_log),
                    'totalSB': total_sb, 'obp': obp, 'slg': slg, 'ops': round(obp + slg, 3) if (obp is not None and slg is not None) else None,
                })
            else:
                total_ip = sum(g.get('ip', 0) for g in all_log)
                total_er = sum(g.get('er', 0) for g in all_log)
                total_bb = sum(g.get('bb', 0) for g in all_log)
                total_hits_allowed = sum(g.get('hitsAllowed', 0) for g in all_log)
                total_so = sum(g.get('so', 0) for g in all_log)
                whip = round((total_bb + total_hits_allowed) / total_ip, 2) if total_ip else None
                k9 = round((total_so * 9) / total_ip, 2) if total_ip else None
                overall.update({
                    'avg_so': avg('so'), 'avg_ip': avg('ip'),
                    'era': round((total_er * 9) / total_ip, 2) if total_ip else None,
                    'totalWins': sum(g.get('wins', 0) for g in all_log), 'totalSaves': sum(g.get('saves', 0) for g in all_log),
                    'whip': whip, 'k9': k9,
                })

            home_log = [g for g in all_log if g.get('isHome')]
            away_log = [g for g in all_log if not g.get('isHome')]
            players.append({
                'name': p['name'], 'team': team_names.get(p['teamId'], p.get('teamName', '?')), 'group': group,
                'overall': overall,
                'home': {'games': len(home_log)}, 'away': {'games': len(away_log)},
                'gamelog': test_log,
                'isRookie': False,
            })

        # New-to-the-dataset players -- a true MLB rookie, or anyone who didn't qualify
        # for the train_season leaderboard, never shows up above no matter how much
        # real production they have THIS season, because `qualified` only ever comes
        # from the train_season leaderboard call. Pull the same leaderboard for the
        # test/current season too, and give anyone who only shows up there their own
        # entry built entirely from their own real test_season game log.
        qualified_train_ids = {p['id'] for p in qualified}
        qualified_test = fetch_mlb_qualified_players(test_season, group)
        print(f"    {len(qualified_test)} qualified {group} players from {test_season} leaderboard "
              f"({sum(1 for p in qualified_test if p['id'] not in qualified_train_ids)} new-to-the-dataset)")
        for p in qualified_test:
            if p['id'] in qualified_train_ids:
                continue  # already covered above (qualifies in both seasons)
            try:
                test_log = fetch_mlb_game_log(p['id'], test_season, group)
            except Exception:
                continue
            if len(test_log) < ROOKIE_MIN_GAMES:
                continue

            def avg(key, log=test_log):
                vals = [g.get(key, 0) for g in log]
                return round(sum(vals) / len(vals), 2) if vals else None

            overall = {'games': len(test_log), 'group': group}
            if group == 'hitting':
                total_ab = sum(g.get('ab', 0) for g in test_log)
                total_hits = sum(g.get('hits', 0) for g in test_log)
                total_bb = sum(g.get('bb', 0) for g in test_log)
                total_tb = sum(g.get('tb', 0) for g in test_log)
                total_sb = sum(g.get('sb', 0) for g in test_log)
                obp = round((total_hits + total_bb) / (total_ab + total_bb), 3) if (total_ab + total_bb) else None
                slg = round(total_tb / total_ab, 3) if total_ab else None
                overall.update({
                    'avg_hits': avg('hits'), 'avg_hr': avg('hr'), 'avg_rbi': avg('rbi'), 'avg_runs': avg('runs'),
                    'battingAvg': round(total_hits / total_ab, 3) if total_ab else None,
                    'totalHR': sum(g.get('hr', 0) for g in test_log), 'totalRBI': sum(g.get('rbi', 0) for g in test_log),
                    'totalSB': total_sb, 'obp': obp, 'slg': slg, 'ops': round(obp + slg, 3) if (obp is not None and slg is not None) else None,
                })
            else:
                total_ip = sum(g.get('ip', 0) for g in test_log)
                total_er = sum(g.get('er', 0) for g in test_log)
                total_bb = sum(g.get('bb', 0) for g in test_log)
                total_hits_allowed = sum(g.get('hitsAllowed', 0) for g in test_log)
                total_so = sum(g.get('so', 0) for g in test_log)
                whip = round((total_bb + total_hits_allowed) / total_ip, 2) if total_ip else None
                k9 = round((total_so * 9) / total_ip, 2) if total_ip else None
                overall.update({
                    'avg_so': avg('so'), 'avg_ip': avg('ip'),
                    'era': round((total_er * 9) / total_ip, 2) if total_ip else None,
                    'totalWins': sum(g.get('wins', 0) for g in test_log), 'totalSaves': sum(g.get('saves', 0) for g in test_log),
                    'whip': whip, 'k9': k9,
                })

            home_log = [g for g in test_log if g.get('isHome')]
            away_log = [g for g in test_log if not g.get('isHome')]
            players.append({
                'name': p['name'], 'team': team_names.get(p['teamId'], p.get('teamName', '?')), 'group': group,
                'overall': overall,
                'home': {'games': len(home_log)}, 'away': {'games': len(away_log)},
                'gamelog': test_log,
                'isRookie': True,
            })
    players.sort(key=lambda p: -(p['overall'].get('totalHR', 0) if p['group']=='hitting' else p['overall'].get('totalSaves', 0)))
    return players


def build_mlb_pool(train_season, test_season, team_names):
    """Same P25/P50/P75 ladder methodology as every other sport tonight."""
    MIN25 = {'Hits':0,'HR':0,'RBI':0,'Runs':0,'Strikeouts':2,'Total Bases':0}
    MIN50 = {'Hits':1,'HR':0,'RBI':0,'Runs':0,'Strikeouts':3,'Total Bases':1}

    def ladder(train_vals, test_vals, label):
        if len(train_vals) < 8 or len(test_vals) < 6:
            return None
        p25 = math.floor(np.percentile(train_vals, 25)); p50 = math.floor(np.percentile(train_vals, 50)); p75 = math.floor(np.percentile(train_vals, 75))
        if p25 < MIN25.get(label,0) or p50 < MIN50.get(label,0) or p75 <= p50:
            return None
        def hit(line): return round(float((test_vals >= line).mean()) * 100, 1)
        return {'p25': {'line': float(p25), 'testHit': hit(p25)}, 'p50': {'line': float(p50), 'testHit': hit(p50)},
                'p75': {'line': float(p75), 'testHit': hit(p75)}, 'trainGames': int(len(train_vals)), 'testGames': int(len(test_vals))}

    def ladder_rookie(ordered_vals, label, min_games=ROOKIE_MIN_GAMES):
        """Same math as ladder(), but split WITHIN this season's own games for a player
        with no train_season qualified-leaderboard history at all -- see
        pctile_ladder_rookie in the NFL section above for the full reasoning."""
        n = len(ordered_vals)
        if n < min_games:
            return None
        test_n = max(1, n // 3)
        train_vals = np.array(ordered_vals[:-test_n], dtype=float)
        test_vals = np.array(ordered_vals[-test_n:], dtype=float)
        if len(train_vals) == 0:
            return None
        p25 = math.floor(np.percentile(train_vals, 25)); p50 = math.floor(np.percentile(train_vals, 50)); p75 = math.floor(np.percentile(train_vals, 75))
        if p25 < MIN25.get(label, 0) or p50 < MIN50.get(label, 0) or p75 <= p50:
            return None
        def hit(line): return round(float((test_vals >= line).mean()) * 100, 1)
        return {'p25': {'line': float(p25), 'testHit': hit(p25)}, 'p50': {'line': float(p50), 'testHit': hit(p50)},
                'p75': {'line': float(p75), 'testHit': hit(p75)}, 'trainGames': int(len(train_vals)), 'testGames': int(len(test_vals))}

    pool = []
    hit_stat_map = [('hits','Hits'), ('hr','HR'), ('rbi','RBI'), ('runs','Runs'), ('tb','Total Bases')]
    pitch_stat_map = [('so','Strikeouts')]
    qualified_hit = fetch_mlb_qualified_players(train_season, 'hitting')
    qualified_pitch = fetch_mlb_qualified_players(train_season, 'pitching')
    qualified_hit_ids = {p['id'] for p in qualified_hit}
    qualified_pitch_ids = {p['id'] for p in qualified_pitch}

    for p in qualified_hit:
        try:
            train_log = fetch_mlb_game_log(p['id'], train_season, 'hitting')
            test_log = fetch_mlb_game_log(p['id'], test_season, 'hitting')
        except Exception:
            continue
        if len(train_log) < 8 or len(test_log) < 6:
            continue
        for key, label in hit_stat_map:
            train_vals = np.array([g.get(key, 0) for g in train_log], dtype=float)
            test_vals = np.array([g.get(key, 0) for g in test_log], dtype=float)
            l = ladder(train_vals, test_vals, label)
            if l:
                pool.append({'player': p['name'], 'stat': label, 'kind': 'ladder', **l, 'isRookie': False,
                             'id': f"{p['name']}|{label}".replace(' ', '_')})

    for p in qualified_pitch:
        try:
            train_log = fetch_mlb_game_log(p['id'], train_season, 'pitching')
            test_log = fetch_mlb_game_log(p['id'], test_season, 'pitching')
        except Exception:
            continue
        if len(train_log) < 8 or len(test_log) < 6:
            continue
        for key, label in pitch_stat_map:
            train_vals = np.array([g.get(key, 0) for g in train_log], dtype=float)
            test_vals = np.array([g.get(key, 0) for g in test_log], dtype=float)
            l = ladder(train_vals, test_vals, label)
            if l:
                pool.append({'player': p['name'], 'stat': label, 'kind': 'ladder', **l, 'isRookie': False,
                             'id': f"{p['name']}|{label}".replace(' ', '_')})

    # New-to-the-dataset players (see build_mlb_players above) -- no train_season
    # qualified-leaderboard history to split against, so the line comes from this
    # season's own games alone, once there are enough of them.
    for p in fetch_mlb_qualified_players(test_season, 'hitting'):
        if p['id'] in qualified_hit_ids:
            continue
        try:
            test_log = fetch_mlb_game_log(p['id'], test_season, 'hitting')
        except Exception:
            continue
        if len(test_log) < ROOKIE_MIN_GAMES:
            continue
        for key, label in hit_stat_map:
            vals = [g.get(key, 0) for g in test_log]
            l = ladder_rookie(vals, label)
            if l:
                pool.append({'player': p['name'], 'stat': label, 'kind': 'ladder', **l, 'isRookie': True,
                             'id': f"{p['name']}|{label}".replace(' ', '_')})
    for p in fetch_mlb_qualified_players(test_season, 'pitching'):
        if p['id'] in qualified_pitch_ids:
            continue
        try:
            test_log = fetch_mlb_game_log(p['id'], test_season, 'pitching')
        except Exception:
            continue
        if len(test_log) < ROOKIE_MIN_GAMES:
            continue
        for key, label in pitch_stat_map:
            vals = [g.get(key, 0) for g in test_log]
            l = ladder_rookie(vals, label)
            if l:
                pool.append({'player': p['name'], 'stat': label, 'kind': 'ladder', **l, 'isRookie': True,
                             'id': f"{p['name']}|{label}".replace(' ', '_')})
    return pool


def build_mlb_team_defense(test_season, team_names):
    """Runs allowed AND scored per game, per team. Standard MLB Stats API TeamRecord fields —
    runsScored specifically isn't verified against live data from this sandbox (same limitation
    as the rest of the MLB pipeline), so it's read defensively and simply omitted if absent."""
    data = mlb_get("/standings", {"leagueId": "103,104", "season": test_season, "standingsTypes": "regularSeason"})
    out = {}
    if not data or 'records' not in data:
        return out
    for rec in data['records']:
        for team in rec.get('teamRecords', []):
            tid = team.get('team', {}).get('id')
            games = team.get('gamesPlayed', 0)
            runs_allowed = team.get('runsAllowed')
            runs_scored = team.get('runsScored')
            if tid and games and runs_allowed is not None:
                entry = {'runsAllowedPerGame': round(runs_allowed / games, 2), 'games': games}
                if runs_scored is not None:
                    entry['runsScoredPerGame'] = round(runs_scored / games, 2)
                out[team_names.get(tid, str(tid))] = entry
    ranked = sorted(out.items(), key=lambda kv: -kv[1]['runsAllowedPerGame'])
    for rank, (name, _) in enumerate(ranked, 1):
        out[name]['rank'] = rank
    scored_ranked = sorted([kv for kv in out.items() if 'runsScoredPerGame' in kv[1]], key=lambda kv: -kv[1]['runsScoredPerGame'])
    for rank, (name, _) in enumerate(scored_ranked, 1):
        out[name]['scoredRank'] = rank
    return out


def build_mlb_upcoming(test_season, team_names):
    today = datetime.date.today().isoformat()
    end = (datetime.date.today() + datetime.timedelta(days=14)).isoformat()
    data = mlb_get("/schedule", {"sportId": 1, "startDate": today, "endDate": end, "gameType": "R"})
    upcoming = {}
    if not data or 'dates' not in data:
        return upcoming
    for d in data['dates']:
        for g in d.get('games', []):
            home = g.get('teams', {}).get('home', {}).get('team', {})
            away = g.get('teams', {}).get('away', {}).get('team', {})
            game_date = g.get('gameDate', '')[:10]
            for team, opp, is_home in [(home, away, True), (away, home, False)]:
                tname = team_names.get(team.get('id'), team.get('name'))
                if tname and tname not in upcoming:
                    upcoming[tname] = {'opp': team_names.get(opp.get('id'), opp.get('name')), 'date': game_date, 'isHome': is_home}
    return upcoming


def fetch_injuries_and_depthcharts(season):
    """Injury reports and depth charts for a given season. Always re-fetched (both update frequently)."""
    inj_path = CACHE_DIR / f"injuries_{season}.csv"
    dc_path = CACHE_DIR / f"depth_charts_{season}.csv"
    if inj_path.exists():
        inj_path.unlink()
    if dc_path.exists():
        dc_path.unlink()
    ok_inj = download(f"{NFLVERSE_BASE}/injuries/injuries_{season}.csv", inj_path)
    ok_dc = download(f"{NFLVERSE_BASE}/depth_charts/depth_charts_{season}.csv", dc_path)
    return (inj_path if ok_inj else None), (dc_path if ok_dc else None)


def build_ol_starters(dc_path):
    """Current starting LT/LG/C/RG/RT per team, from the most recent depth chart snapshot."""
    if dc_path is None or not dc_path.exists():
        return {}
    dc = pd.read_csv(dc_path, low_memory=False)
    if len(dc) == 0:
        return {}
    latest_dt = dc['dt'].max()
    latest = dc[dc['dt'] == latest_dt]
    ol = latest[latest.pos_abb.isin(['LT', 'LG', 'C', 'RG', 'RT']) & (latest.pos_rank == 1)]
    ol_map = {}
    for team, g in ol.groupby('team'):
        ol_map[team] = {row['pos_abb']: row['player_name'] for _, row in g.iterrows()}
    return ol_map


def build_injury_status(inj_path):
    """Per-player current injury designation — only populated if there's a genuinely recent
    (current season, most recent reported week) report. Stays empty in the offseason rather
    than surfacing stale designations from last season's final week."""
    if inj_path is None or not inj_path.exists():
        return {}
    inj = pd.read_csv(inj_path, low_memory=False)
    real = inj[inj.report_status.notna()]
    if len(real) == 0:
        return {}
    latest_week = real['week'].max()
    recent = real[real.week == latest_week]
    status_map = {}
    for _, row in recent.iterrows():
        # A missing injury description comes through as NaN, which json.dumps writes as a
        # bare NaN literal — fine inline in JS, but invalid JSON anywhere it gets parsed.
        detail = row.get('report_primary_injury')
        if detail is None or (isinstance(detail, float) and math.isnan(detail)):
            detail = None
        status_map[row['full_name']] = {
            'status': str(row['report_status']),
            'injury': detail,
            'week': int(latest_week),
        }
    out_count = sum(1 for v in status_map.values() if str(v['status']).lower().startswith('out'))
    doubt_count = sum(1 for v in status_map.values() if 'doubtful' in str(v['status']).lower())
    print(f"  Week {int(latest_week)} injury report: {len(status_map)} designations "
          f"({out_count} Out, {doubt_count} Doubtful)")
    return status_map


# =====================================================================
# CLASSIFICATION (front / coverage / weather / primetime)
# =====================================================================
def parse_personnel(s):
    if not isinstance(s, str):
        return {}
    out = {}
    for p in s.split(','):
        p = p.strip()
        m = re.match(r'(\d+)\s+([A-Z]+)', p)
        if m:
            out[m.group(2)] = int(m.group(1))
    return out


def classify_front(s):
    d = parse_personnel(s)
    dl = d.get('DE', 0) + d.get('DT', 0) + d.get('NT', 0) + d.get('DL', 0)
    lb = d.get('ILB', 0) + d.get('OLB', 0) + d.get('LB', 0) + d.get('MLB', 0)
    db = d.get('CB', 0) + d.get('FS', 0) + d.get('SS', 0) + d.get('S', 0) + d.get('DB', 0)
    if dl == 0 and lb == 0:
        return 'Unknown'
    if db >= 6:
        sub = 'Dime'
    elif db == 5:
        sub = 'Nickel'
    elif db <= 4:
        sub = 'Base'
    else:
        sub = ''
    return f"{dl}-{lb} ({sub})" if sub else f"{dl}-{lb}"


def bucket_front(f):
    if 'Base' in f:
        return 'Base'
    if 'Nickel' in f:
        return 'Nickel'
    if 'Dime' in f:
        return 'Dime'
    return 'Other'


def weather_bucket(row):
    if row['roof'] in ('dome', 'closed'):
        return 'Dome/Closed'
    tags = []
    if pd.notna(row['wind']) and row['wind'] >= 15:
        tags.append('Windy')
    if pd.notna(row['temp']) and row['temp'] <= 40:
        tags.append('Cold')
    return ', '.join(tags) if tags else 'Clear/Mild'


def primetime(row):
    try:
        hr = int(str(row['gametime']).split(':')[0])
    except (ValueError, TypeError):
        return False
    if row['weekday'] in ['Thursday', 'Monday']:
        return True
    if row['weekday'] == 'Sunday' and hr >= 20:
        return True
    return False


def build_merged(season, games_all):
    # Participation (personnel/formation) data is a separate nflverse feed from play-by-play,
    # sourced from NFL charting data, and it runs well behind pbp -- for the current
    # in-progress season it's frequently not published at all until much later (sometimes
    # not until the season's over). This used to require BOTH files to exist, so a missing
    # participation file silently deleted the ENTIRE current season everywhere downstream
    # (QB/skill stats, TDs allowed/scored by position, redzone tendencies -- all of it),
    # even though every one of those is computable from pbp alone. Now: pbp is the only
    # hard requirement; participation is used when available and skipped gracefully when
    # not, with only the defense-personnel/coverage detail (front/scheme breakdowns)
    # falling back to 'Unknown' for that season until nflverse publishes it.
    pbp_path = CACHE_DIR / f"pbp_{season}.parquet"
    part_path = CACHE_DIR / f"participation_{season}.parquet"
    if not pbp_path.exists():
        return None
    pbp = pd.read_parquet(pbp_path)
    pbp['play_id'] = pbp['play_id'].astype(float)
    if part_path.exists():
        part = pd.read_parquet(part_path)
        part['play_id'] = part['play_id'].astype(float)
        merged = pbp.merge(part, left_on=['game_id', 'play_id'], right_on=['nflverse_game_id', 'play_id'],
                            how='left', suffixes=('', '_part'))
    else:
        print(f"  [!] No participation data for {season} yet -- proceeding pbp-only "
              f"(front/coverage/scheme detail will show as 'Unknown' for {season} until nflverse publishes it; "
              f"yards, TDs, QB/skill stats, and team defense/offense profiles are unaffected)")
        merged = pbp.copy()
    if 'defense_personnel' in merged.columns:
        merged['front'] = merged['defense_personnel'].apply(classify_front)
    else:
        merged['front'] = 'Unknown'
    merged['front_bucket'] = merged['front'].apply(bucket_front)
    if 'defense_coverage_type' in merged.columns:
        merged['coverage'] = merged['defense_coverage_type'].fillna('Unknown')
    else:
        merged['coverage'] = 'Unknown'
    merged['is_home'] = merged['posteam'] == merged['home_team']
    gctx = games_all[games_all.season == season].set_index('game_id')[['weekday', 'gametime', 'location', 'roof', 'temp', 'wind']]
    merged = merged.join(gctx, on='game_id', rsuffix='_g')
    merged['primetime'] = merged.apply(primetime, axis=1)
    merged['weather'] = merged.apply(weather_bucket, axis=1)
    merged['season'] = season
    return merged


# =====================================================================
# PREDICTION MARKETS (Kalshi + Polymarket) — FETCHED SERVER-SIDE
# =====================================================================
# Why this lives here now instead of in the browser: the dashboard used to
# fetch Kalshi/Polymarket client-side on page load. That fails in production —
# a static GitHub Pages origin calling those APIs gets blocked (CORS/origin
# policy), the fetch throws, and the catch silently served a hardcoded
# snapshot that was months old. Every other data source on the site is pulled
# here and baked into the page, so these now work the same way: fetched on the
# GitHub Actions schedule (2x/day baseline + game-day crons), timestamped, and
# cached so one bad run keeps the previous good values instead of falling all
# the way back to a stale constant.
#
# Two things make this self-healing rather than another set of guesses:
#   1. Every ticker is TRIED, not assumed — and whatever actually works gets
#      printed in the Actions log, so a rename shows up as a log line.
#   2. If the known tickers yield nothing, it falls back to DISCOVERY: scan
#      open events and keyword-match titles. That survives Kalshi renaming a
#      series, which is the most likely cause of a silent, permanent failure.
# =====================================================================
KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
POLY_GAMMA_API = "https://gamma-api.polymarket.com"
MARKET_CACHE_PATH = SCRIPT_DIR / "market_cache.json"
MARKET_HTTP_TIMEOUT = 20

# Diagnostics collected during the market step and printed in one block at the
# end, so a single real Actions run tells you exactly which feed broke and why.
MARKET_LOG = []


def _mklog(msg):
    MARKET_LOG.append(msg)


def kalshi_get(path, params=None, timeout=MARKET_HTTP_TIMEOUT):
    """GET against Kalshi's public market-data API. Returns (json|None, status_note)."""
    url = f"{KALSHI_API}{path}"
    try:
        r = requests.get(url, params=params or {}, timeout=timeout,
                         headers={'Accept': 'application/json', 'User-Agent': 'statum-dashboard/1.0'})
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        return r.json(), "ok"
    except requests.RequestException as e:
        return None, f"{type(e).__name__}"


def poly_get(path, params=None, timeout=MARKET_HTTP_TIMEOUT):
    """GET against Polymarket's public Gamma API. Returns (json|None, status_note)."""
    url = f"{POLY_GAMMA_API}{path}"
    try:
        r = requests.get(url, params=params or {}, timeout=timeout,
                         headers={'Accept': 'application/json', 'User-Agent': 'statum-dashboard/1.0'})
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        return r.json(), "ok"
    except requests.RequestException as e:
        return None, f"{type(e).__name__}"


def _kalshi_price_pct(m):
    """Kalshi returns prices as integer cents on most fields and dollars on the
    *_dollars variants. Take whichever is present, in the order that's most
    likely to be a real traded price rather than a stale resting quote."""
    for field, scale in (('last_price_dollars', 100.0), ('yes_bid_dollars', 100.0),
                         ('last_price', 1.0), ('yes_bid', 1.0)):
        v = m.get(field)
        if v in (None, ""):
            continue
        try:
            pct = float(v) * scale
        except (TypeError, ValueError):
            continue
        if 0 < pct <= 100:
            return round(pct, 1)
    return None


def kalshi_markets_for_series(series_ticker, limit=60, status="open"):
    """Every open market in one Kalshi series (e.g. all players in a leader race)."""
    data, note = kalshi_get("/markets", {"series_ticker": series_ticker, "status": status, "limit": limit})
    if not data:
        return [], note
    markets = data.get('markets') or []
    return markets, ("ok" if markets else "no open markets")


def kalshi_series_top(series_ticker, top=3):
    """Top N outcomes in a series by implied probability — the shape the leader-race cards want."""
    markets, note = kalshi_markets_for_series(series_ticker)
    if not markets:
        return None, note
    options = []
    for m in markets:
        name = m.get('yes_sub_title') or m.get('title')
        pct = _kalshi_price_pct(m)
        if name and pct is not None:
            options.append({'name': name, 'pct': pct})
    if not options:
        return None, "no priceable markets"
    options.sort(key=lambda o: -o['pct'])
    return {'options': options[:top], 'totalMarkets': len(markets)}, "ok"


def kalshi_discover_open_events(max_pages=8, page_size=200):
    """Page through Kalshi's open events (with their markets nested) so we can
    keyword-match real, currently-listed markets instead of relying on ticker
    names staying stable. Capped so a pathological response can't stall a run."""
    events, cursor, pages = [], None, 0
    while pages < max_pages:
        params = {'status': 'open', 'with_nested_markets': 'true', 'limit': page_size}
        if cursor:
            params['cursor'] = cursor
        data, note = kalshi_get("/events", params)
        if not data:
            _mklog(f"  discovery: events page {pages + 1} failed ({note})")
            break
        batch = data.get('events') or []
        events.extend(batch)
        cursor = data.get('cursor')
        pages += 1
        if not cursor or not batch:
            break
    return events


def _event_markets(ev):
    return ev.get('markets') or ev.get('nested_markets') or []


def kalshi_match_events(events, include_terms, exclude_terms=(), limit=6):
    """Find open events whose title matches all/any of some keywords. Used as the
    fallback path when a hardcoded series ticker stops resolving."""
    out = []
    for ev in events:
        title = (ev.get('title') or "") + " " + (ev.get('sub_title') or "")
        low = title.lower()
        if not any(t.lower() in low for t in include_terms):
            continue
        if any(t.lower() in low for t in exclude_terms):
            continue
        markets = _event_markets(ev)
        if not markets:
            continue
        options = []
        for m in markets:
            name = m.get('yes_sub_title') or m.get('title')
            pct = _kalshi_price_pct(m)
            if name and pct is not None:
                options.append({'name': name, 'pct': pct})
        if not options:
            continue
        options.sort(key=lambda o: -o['pct'])
        out.append({'title': ev.get('title') or ev.get('event_ticker'),
                    'eventTicker': ev.get('event_ticker'),
                    'seriesTicker': ev.get('series_ticker'),
                    'options': options[:3],
                    'totalMarkets': len(markets)})
        if len(out) >= limit:
            break
    return out


# ---- NFL ----
KALSHI_LEADER_SERIES = [
    ("Receiving Yards Leader", "KXLEADERNFLRYDS", ["receiving yards leader", "most receiving yards"]),
    ("Passing Yards Leader", "KXLEADERNFLPYDS", ["passing yards leader", "most passing yards"]),
    ("Rushing Yards Leader", "KXLEADERNFLRSHYDS", ["rushing yards leader", "most rushing yards"]),
    ("Sacks Leader", "KXLEADERNFLSACK", ["sacks leader", "most sacks"]),
    ("Interceptions Leader", "KXLEADERNFLINT", ["interceptions leader", "most interceptions"]),
]
NFL_CHAMP_TICKERS = ["KXNFLCHAMP", "KXSBCHAMP", "KXSUPERBOWL", "KXNFLGAME-CHAMP"]
WNBA_CHAMP_TICKERS = ["KXWNBA", "KXWNBACHAMP"]
MLB_CHAMP_TICKERS = ["KXMLBWS", "KXMLBWORLDSERIES", "KXWORLDSERIES"]


def fetch_kalshi_leaders(discovered_events=None):
    """The five NFL season-long leader races. Tries the known series ticker first,
    then keyword discovery, so a Kalshi rename degrades to 'found it anyway'."""
    out, live_count = [], 0
    for label, ticker, search_terms in KALSHI_LEADER_SERIES:
        card, note = kalshi_series_top(ticker)
        if card:
            out.append({'category': label, 'source': 'kalshi', 'ticker': ticker, **card})
            live_count += 1
            _mklog(f"  NFL leaders · {label}: live via {ticker} ({card['totalMarkets']} markets)")
            continue
        found = None
        if discovered_events:
            matches = kalshi_match_events(discovered_events, search_terms, limit=1)
            if matches:
                found = matches[0]
        if found:
            out.append({'category': label, 'source': 'kalshi-discovered',
                        'ticker': found.get('seriesTicker') or found.get('eventTicker'),
                        'options': found['options'], 'totalMarkets': found['totalMarkets']})
            live_count += 1
            _mklog(f"  NFL leaders · {label}: ticker {ticker} dead ({note}) — DISCOVERED as "
                   f"{found.get('seriesTicker')} / event {found.get('eventTicker')}")
        else:
            _mklog(f"  NFL leaders · {label}: unavailable ({note}, discovery found nothing)")
    return out, live_count


# Nickname -> code, so a Kalshi/Polymarket outcome label ("Chiefs", "Kansas City Chiefs")
# can be matched back to our team codes. Mirrors TEAM_NAMES in dashboard_template.jsx.
NFL_NICKNAME_TO_CODE = {
    'chargers': 'LAC', 'ravens': 'BAL', 'panthers': 'CAR', 'steelers': 'PIT', 'browns': 'CLE',
    'broncos': 'DEN', 'saints': 'NO', 'dolphins': 'MIA', 'rams': 'LA', 'chiefs': 'KC',
    'titans': 'TEN', 'bengals': 'CIN', 'packers': 'GB', 'vikings': 'MIN', 'jets': 'NYJ',
    'texans': 'HOU', 'cowboys': 'DAL', 'jaguars': 'JAX', 'buccaneers': 'TB', 'seahawks': 'SEA',
    'falcons': 'ATL', 'bills': 'BUF', 'colts': 'IND', 'patriots': 'NE', '49ers': 'SF',
    'cardinals': 'ARI', 'lions': 'DET', 'eagles': 'PHI', 'commanders': 'WAS', 'giants': 'NYG',
    'bears': 'CHI', 'raiders': 'LV',
}


def nfl_code_from_label(label):
    low = str(label or "").lower()
    for nick, code in NFL_NICKNAME_TO_CODE.items():
        if nick in low:
            return code
    return None


def fetch_nfl_win_totals(discovered_events, limit=24):
    """Season win-total markets, one card per team. These were the hardcoded 'SNAPSHOT'
    cards on Market Pulse — there's no stable series ticker to fetch them by, so they come
    from the discovery pass: any open event whose title names a team and talks about wins."""
    if not discovered_events:
        return []
    by_team = {}
    for ev in discovered_events:
        title = ((ev.get('title') or "") + " " + (ev.get('sub_title') or ""))
        low = title.lower()
        if 'win' not in low:
            continue
        if any(t in low for t in ('super bowl', 'division', 'conference', 'champion', 'mvp', 'playoff')):
            continue
        code = nfl_code_from_label(title)
        if not code:
            continue
        options = []
        for m in _event_markets(ev):
            name = m.get('yes_sub_title') or m.get('title')
            pct = _kalshi_price_pct(m)
            if name and pct is not None:
                options.append({'line': name, 'pct': pct})
        if not options:
            continue
        options.sort(key=lambda o: -o['pct'])
        # Keep the three closest to a coin flip — those are the ones with real information
        # in them; a 2%-or-98% line tells you nothing you didn't already know.
        options.sort(key=lambda o: abs(o['pct'] - 50))
        prev = by_team.get(code)
        if prev is None or len(options) > len(prev['options']):
            by_team[code] = {'team': code, 'options': options[:3],
                             'eventTicker': ev.get('event_ticker'), 'totalMarkets': len(_event_markets(ev))}
    out = list(by_team.values())[:limit]
    if out:
        _mklog(f"  NFL win totals: {len(out)} teams found via discovery")
    else:
        _mklog("  NFL win totals: none found in open events — keeping the manual snapshot")
    return out


# Season-long player threshold markets ("75+ receptions", "1,200+ rushing yards"). Same
# situation as win totals: no stable ticker, so keyword discovery is the only honest route.
_THRESHOLD_TERMS = ['receptions', 'receiving yards', 'rushing yards', 'passing yards',
                    'touchdowns', 'sacks', 'interceptions', 'field goals']
_THRESHOLD_EXCLUDE = ['leader', 'most ', 'champion', 'mvp', 'super bowl']


def fetch_nfl_player_thresholds(discovered_events, limit=6):
    if not discovered_events:
        return []
    cards = []
    for ev in discovered_events:
        title = (ev.get('title') or "")
        low = title.lower()
        if not any(t in low for t in _THRESHOLD_TERMS):
            continue
        if any(t in low for t in _THRESHOLD_EXCLUDE):
            continue
        # A threshold market has a number in it ("75+", "1,000 or more")
        if not re.search(r'\d', title):
            continue
        options = []
        for m in _event_markets(ev):
            name = m.get('yes_sub_title') or m.get('title')
            pct = _kalshi_price_pct(m)
            if name and pct is not None:
                options.append({'name': name, 'pct': pct})
        if not options:
            continue
        options.sort(key=lambda o: -o['pct'])
        cards.append({'title': title, 'options': options[:3],
                      'totalMarkets': len(_event_markets(ev)),
                      'eventTicker': ev.get('event_ticker')})
        if len(cards) >= limit:
            break
    if cards:
        _mklog(f"  NFL player thresholds: {len(cards)} markets found via discovery")
    else:
        _mklog("  NFL player thresholds: none found in open events — keeping the manual snapshot")
    return cards


def fetch_kalshi_championship(tickers, discovered_events=None, search_terms=(), exclude_terms=()):
    """Multi-outcome championship market -> {outcome_name: pct}. Outcome names come
    back exactly as Kalshi labels them; the JSX matches them to our team naming."""
    for ticker in tickers:
        markets, note = kalshi_markets_for_series(ticker, limit=60)
        if not markets:
            continue
        out = {}
        for m in markets:
            name = m.get('yes_sub_title') or m.get('title')
            pct = _kalshi_price_pct(m)
            if name and pct is not None:
                out[name] = pct
        if out:
            _mklog(f"  championship: live via {ticker} ({len(out)} outcomes)")
            return out, ticker
    if discovered_events and search_terms:
        matches = kalshi_match_events(discovered_events, search_terms, exclude_terms, limit=1)
        if matches:
            ev = matches[0]
            # re-pull the full outcome set for the discovered event, not just top 3
            data, _ = kalshi_get("/markets", {"event_ticker": ev['eventTicker'], "status": "open", "limit": 60})
            markets = (data or {}).get('markets') or []
            out = {}
            for m in markets:
                name = m.get('yes_sub_title') or m.get('title')
                pct = _kalshi_price_pct(m)
                if name and pct is not None:
                    out[name] = pct
            if out:
                _mklog(f"  championship: tickers {tickers} all dead — DISCOVERED as "
                       f"{ev.get('seriesTicker')} / event {ev.get('eventTicker')} ({len(out)} outcomes)")
                return out, ev.get('seriesTicker') or ev.get('eventTicker')
    _mklog(f"  championship: unavailable (tried {tickers}, discovery found nothing)")
    return None, None


def fetch_poly_event_prices(slug, strip_suffix_re=None):
    """One Polymarket multi-outcome event -> {outcome_name: pct}."""
    data, note = poly_get("/events", {"slug": slug})
    if not data:
        return None, note
    event = data[0] if isinstance(data, list) and data else data
    if not isinstance(event, dict) or not event.get('markets'):
        return None, "no markets in response"
    out = {}
    for m in event['markets']:
        title = (m.get('groupItemTitle') or m.get('question') or "").strip()
        if strip_suffix_re:
            title = re.sub(strip_suffix_re, "", title, flags=re.I).strip()
        price = None
        raw = m.get('outcomePrices')
        try:
            prices = json.loads(raw) if isinstance(raw, str) else (raw or [])
            if prices:
                price = float(prices[0]) * 100
        except (ValueError, TypeError):
            price = None
        if title and price is not None and 0 < price <= 100:
            out[title] = round(price, 1)
    if not out:
        return None, "no outcomes parsed"
    return out, "ok"


def fetch_poly_discover(search_terms, limit=200):
    """Fallback when a Polymarket slug 404s (they get renamed/re-slugged every season):
    pull the highest-volume open events and keyword-match the title."""
    data, note = poly_get("/events", {"closed": "false", "order": "volume",
                                      "ascending": "false", "limit": limit})
    if not isinstance(data, list):
        return None, None, note
    for ev in data:
        title = (ev.get('title') or "").lower()
        if any(t.lower() in title for t in search_terms):
            slug = ev.get('slug')
            if not slug:
                continue
            prices, pnote = fetch_poly_event_prices(slug)
            if prices:
                return prices, slug, "ok"
    return None, None, "no matching open event"


def fetch_poly_with_fallback(slug, search_terms, strip_suffix_re=None, label=""):
    prices, note = fetch_poly_event_prices(slug, strip_suffix_re)
    if prices:
        _mklog(f"  {label} Polymarket: live via slug {slug} ({len(prices)} outcomes)")
        return prices, slug
    prices, found_slug, dnote = fetch_poly_discover(search_terms)
    if prices:
        _mklog(f"  {label} Polymarket: slug {slug} dead ({note}) — DISCOVERED as slug {found_slug}")
        return prices, found_slug
    _mklog(f"  {label} Polymarket: unavailable (slug {slug}: {note}; discovery: {dnote})")
    return None, None


# ---- GEX-style depth & flow ----
def fetch_market_depth(ticker):
    """Resting order-book size by side — where the real 'gravity walls' sit."""
    data, note = kalshi_get(f"/markets/{ticker}/orderbook")
    if not data:
        return None
    ob = data.get('orderbook') or data
    yes_levels, no_levels = ob.get('yes') or [], ob.get('no') or []
    if not yes_levels and not no_levels:
        return None

    def size_of(lvl):
        if isinstance(lvl, (list, tuple)):
            return float(lvl[1]) if len(lvl) > 1 else 0.0
        return float(lvl.get('count') or lvl.get('size') or 0)

    def price_of(lvl):
        if isinstance(lvl, (list, tuple)):
            return float(lvl[0]) if lvl else None
        return lvl.get('price')

    def top(levels):
        return max(levels, key=size_of) if levels else None

    yes_top, no_top = top(yes_levels), top(no_levels)
    return {
        'yesTotal': int(sum(size_of(l) for l in yes_levels)),
        'noTotal': int(sum(size_of(l) for l in no_levels)),
        'yesTopPrice': price_of(yes_top) if yes_top else None,
        'yesTopSize': int(size_of(yes_top)) if yes_top else None,
        'noTopPrice': price_of(no_top) if no_top else None,
        'noTopSize': int(size_of(no_top)) if no_top else None,
    }


def fetch_market_flow(ticker, series_ticker=None):
    """7 days of daily candles -> volume traded and the open-interest trend.
    Kalshi's documented path is /series/{series}/markets/{ticker}/candlesticks;
    the older flat /markets/{ticker}/candlesticks shape is tried as a fallback
    because that's what this used to call (and which may be why it never worked)."""
    end = int(time.time())
    start = end - 7 * 24 * 3600
    params = {'start_ts': start, 'end_ts': end, 'period_interval': 1440}
    paths = []
    if series_ticker:
        paths.append(f"/series/{series_ticker}/markets/{ticker}/candlesticks")
    paths.append(f"/markets/{ticker}/candlesticks")
    candles = []
    for p in paths:
        data, note = kalshi_get(p, params)
        if data:
            candles = data.get('candlesticks') or []
            if candles:
                break
    if not candles:
        return None

    def num(c, *keys):
        for k in keys:
            v = c.get(k)
            if isinstance(v, dict):
                v = v.get('close') or v.get('mean')
            if v not in (None, ""):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
        return 0.0

    oi_series = [num(c, 'open_interest_fp', 'open_interest') for c in candles]
    return {
        'totalVolume': sum(num(c, 'volume_fp', 'volume') for c in candles),
        'latestOI': oi_series[-1] if oi_series else 0,
        'oiChange': (oi_series[-1] - oi_series[0]) if len(oi_series) > 1 else 0,
        'oiSeries': oi_series,
    }


def fetch_depth_flow_panel(series_tickers, limit=3):
    """Depth + flow for the top few markets in whichever of these series resolves."""
    for series_ticker in series_tickers:
        markets, note = kalshi_markets_for_series(series_ticker, limit=20)
        if not markets:
            continue
        scored = []
        for m in markets:
            pct = _kalshi_price_pct(m)
            if m.get('ticker') and pct is not None:
                scored.append({'ticker': m['ticker'], 'name': m.get('yes_sub_title') or m.get('title'), 'price': pct})
        scored.sort(key=lambda m: -m['price'])
        rows = []
        for m in scored[:limit]:
            depth = fetch_market_depth(m['ticker'])
            flow = fetch_market_flow(m['ticker'], series_ticker)
            if depth or flow:
                rows.append({**m, 'depth': depth, 'flow': flow})
        if rows:
            _mklog(f"  depth/flow: {len(rows)} markets via {series_ticker}")
            return rows
        _mklog(f"  depth/flow: {series_ticker} listed markets but orderbook/candles both empty "
               f"(these endpoints may require an authenticated Kalshi key)")
    _mklog(f"  depth/flow: unavailable (tried {series_tickers})")
    return None


def load_market_cache():
    if MARKET_CACHE_PATH.exists():
        try:
            return json.loads(MARKET_CACHE_PATH.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_market_cache(cache):
    try:
        MARKET_CACHE_PATH.write_text(json.dumps(cache, indent=1), encoding='utf-8')
    except OSError as e:
        print(f"  [!] Couldn't write {MARKET_CACHE_PATH.name}: {e}")


def build_market_live():
    """Fetch every prediction market feed, falling back per-section to the last
    successful fetch (from market_cache.json) rather than to a stale constant.
    Every section carries its own fetchedAt so the UI can show real age."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    cache = load_market_cache()
    sections = cache.get('sections', {})

    def commit(key, value):
        """Store a fresh value, or keep the cached one (with its original age) on failure."""
        if value:
            sections[key] = {'data': value, 'fetchedAt': now_iso, 'stale': False}
            return True
        prev = sections.get(key)
        if prev:
            prev['stale'] = True
            _mklog(f"  → {key}: keeping cached value from {prev.get('fetchedAt')}")
        return False

    # One discovery pass, shared by every section that needs a fallback.
    discovered = kalshi_discover_open_events()
    if discovered:
        _mklog(f"  discovery: {len(discovered)} open Kalshi events available for keyword fallback")
    else:
        _mklog("  discovery: no open events retrieved — Kalshi may be unreachable from this runner")

    leaders, live_leaders = fetch_kalshi_leaders(discovered)
    commit('nflLeaders', leaders)
    commit('nflWinTotals', fetch_nfl_win_totals(discovered))
    commit('nflThresholds', fetch_nfl_player_thresholds(discovered))

    nfl_k, nfl_k_ticker = fetch_kalshi_championship(
        NFL_CHAMP_TICKERS, discovered,
        search_terms=["super bowl champion", "nfl champion", "win the super bowl"],
        exclude_terms=["mvp", "coach"])
    commit('nflChampKalshi', nfl_k)
    nfl_p, _ = fetch_poly_with_fallback("big-game-champion-2027",
                                        ["super bowl champion", "nfl champion"], label="NFL")
    commit('nflChampPoly', nfl_p)

    wnba_k, _ = fetch_kalshi_championship(
        WNBA_CHAMP_TICKERS, discovered,
        search_terms=["wnba champion", "wnba finals"], exclude_terms=["mvp"])
    commit('wnbaChampKalshi', wnba_k)
    wnba_p, _ = fetch_poly_with_fallback(
        "wnba-2026-champion-464", ["wnba champion"],
        strip_suffix_re=r"\s+(Lynx|Liberty|Aces|Dream|Fever|Wings|Valkyries|Sparks|Mercury|Tempo|Mystics|Fire|Storm|Sky|Sun)$",
        label="WNBA")
    commit('wnbaChampPoly', wnba_p)

    mlb_k, _ = fetch_kalshi_championship(
        MLB_CHAMP_TICKERS, discovered,
        search_terms=["world series champion", "win the world series"], exclude_terms=["mvp"])
    commit('mlbChampKalshi', mlb_k)
    mlb_p, _ = fetch_poly_with_fallback("mlb-world-series-champion-2026",
                                        ["world series champion"], label="MLB")
    commit('mlbChampPoly', mlb_p)

    commit('nflDepthFlow', fetch_depth_flow_panel(
        [t for t in ([nfl_k_ticker] if nfl_k_ticker else []) + NFL_CHAMP_TICKERS]))
    commit('wnbaDepthFlow', fetch_depth_flow_panel(WNBA_CHAMP_TICKERS))

    cache = {'lastRun': now_iso, 'sections': sections}
    save_market_cache(cache)

    # Flatten to the shape the JSX consumes: value + the age of that value.
    payload = {'generatedAt': now_iso, 'liveLeaderCount': live_leaders,
               'leaderSeriesCount': len(KALSHI_LEADER_SERIES)}
    for key, entry in sections.items():
        payload[key] = entry.get('data')
        payload[key + 'At'] = entry.get('fetchedAt')
        payload[key + 'Stale'] = bool(entry.get('stale'))
    return payload


# =====================================================================
# STRONG PICKS — composite weekly ranking
# =====================================================================
# What this replaces: the old "Top 5 Strong Picks" widget sorted the pool by one number,
# season-long P50 hit rate. That number barely moves from one week to the next, so the
# widget showed effectively the same five names all season and had no idea who those
# players were actually about to line up against.
#
# This scores each line on five independent things instead, three of which are specific to
# the week being played — which is what makes the list genuinely turn over week to week:
#
#   1. RELIABILITY (40%) — the real backtested hit rate, floor-weighted. A line's P25 is
#      the one you'd actually bet, so its hit rate counts double the P50's.
#   2. COVERAGE MATCHUP (20%) — this player's own real yards-per-target against the exact
#      coverage shell their next opponent plays most, versus their own overall average.
#      Weighted by how often that opponent actually plays it.
#   3. POSITION MATCHUP (15%) — where that defense ranks in production allowed to this
#      player's position (1 = most generous).
#   4. XGBOOST LEAN (15%) — the trained model's P(clears their P50 this game), which
#      already accounts for the real upcoming opponent and home/away.
#   5. CURRENT FORM (10%) — trailing-3-game average against the line itself.
#
# Sample size shrinks the whole score toward neutral rather than being a hard cutoff, and
# anyone listed Out or Doubtful is removed outright — a 95% hit rate is irrelevant if the
# player isn't dressing. Every pick carries the reasons it scored well, so the list is
# inspectable rather than a black box.
# =====================================================================
STRONG_PICK_WEIGHTS = {'reliability': 0.40, 'coverage': 0.20, 'position': 0.15, 'model': 0.15, 'form': 0.10}
STRONG_PICK_MIN_TEST_GAMES = 4      # below this a hit rate is noise, not a signal
STRONG_PICK_SHRINK_GAMES = 10       # full trust at this many real held-out games


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def _is_unplayable(name, injuries):
    """Out and Doubtful mean there's no line to bet, whatever the history says."""
    inj = (injuries or {}).get(name)
    if not inj:
        return False
    s = str(inj.get('status', '')).lower()
    return ('out' in s) or ('doubtful' in s) or ('injured reserve' in s)


def _injury_note(name, injuries):
    inj = (injuries or {}).get(name)
    if not inj:
        return None
    s = str(inj.get('status', '')).lower()
    if 'question' in s:
        return f"Questionable ({inj.get('injury') or 'no detail'}) — discounted"
    return None


# Which per-coverage RATE to compare, per stat. This has to be a rate, not a count: the
# per-coverage split covers a subset of a player's snaps while `overall` covers all of them,
# so dividing one count by the other measures how often the opponent plays that shell, not
# how well the player does against it. 'Targets' vs 'targets' was exactly that mistake —
# it produced a ratio near 0.3 for everyone, clamped to a coverage score of ~0, and
# silently docked every Targets prop about 20 points of composite score.
#   (bucket, numerator, denominator|None, sample_field)
# denominator=None means the numerator is already a rate; otherwise the rate is derived as
# numerator/denominator on both sides before comparing. 'Targets' is absent on purpose:
# raw target volume has no per-coverage denominator in this data, so it scores neutral
# rather than being given a fabricated number.
_COVERAGE_RATE_FIELD = {
    'Receiving Yards': ('coverages', 'yptTarget', None, 'targets'),
    'Receptions': ('coverages', 'catchRate', None, 'targets'),
    'Passing Yards': ('coverages', 'yptAtt', None, 'attempts'),
    'Completions': ('coverages', 'compPct', None, 'attempts'),
    'Passing Touchdowns': ('coverages', 'tds', 'attempts', 'attempts'),
}


def score_coverage_matchup(player_obj, opp_def, stat):
    """This player's real production against the shell the next opponent plays most, as a
    0-100 score where 50 is 'exactly their own average'. Returns (score, explanation|None).
    None explanation means there wasn't enough real data to say anything, and the caller
    treats it as neutral rather than inventing a number."""
    if not player_obj or not opp_def:
        return 50.0, None
    spec = _COVERAGE_RATE_FIELD.get(stat)
    if not spec:
        return 50.0, None
    bucket_key, num_field, den_field, sample_field = spec
    scheme = (opp_def.get('scheme') or {})
    cov = scheme.get('primaryCoverage')
    cov_pct = scheme.get('primaryCoveragePct') or 0
    if not cov or cov == 'Unknown':
        return 50.0, None
    buckets = player_obj.get(bucket_key) or {}
    vs = buckets.get(cov)
    overall = player_obj.get('overall') or {}
    if not vs or not overall:
        return 50.0, None

    def rate_of(d):
        num = d.get(num_field)
        if num is None:
            return None
        if den_field is None:
            return float(num)
        den = d.get(den_field)
        if not den:
            return None
        return float(num) / float(den)

    vs_rate = rate_of(vs)
    base_rate = rate_of(overall)
    sample = vs.get(sample_field) or 0
    if not vs_rate or not base_rate or sample < 8:
        return 50.0, None
    ratio = float(vs_rate) / float(base_rate)
    # +/-40% vs their own average maps to the full 0-100 range; then scaled down by how
    # much of the game that shell actually represents (a 35%-usage shell shouldn't swing
    # the score as hard as an 80%-usage one).
    raw = 50.0 + (ratio - 1.0) * 125.0
    usage_weight = _clamp(cov_pct / 60.0, 0.25, 1.0)
    score = 50.0 + (_clamp(raw) - 50.0) * usage_weight
    direction = "better" if ratio > 1.02 else "worse" if ratio < 0.98 else "even"
    if direction == "even":
        return score, None
    pct = abs(ratio - 1.0) * 100
    return score, (f"{pct:.0f}% {direction} than his own average vs {COVERAGE_LABEL_PY.get(cov, cov)}, "
                   f"which {opp_def.get('_teamLabel', 'this defense')} plays {cov_pct:.0f}% of the time "
                   f"({int(sample)} real reps)")


COVERAGE_LABEL_PY = {
    'COVER_0': 'Cover 0', 'COVER_1': 'Cover 1', 'COVER_2': 'Cover 2', 'COVER_3': 'Cover 3',
    'COVER_4': 'Cover 4', 'COVER_6': 'Cover 6', 'COVER_9': 'Cover 9', '2_MAN': '2-Man',
    'COMBO': 'Combo', 'BLOWN': 'Blown Coverage', 'Unknown': 'Unlabeled',
}


def score_position_matchup(opp_def, pos):
    """Where the next opponent ranks in production allowed to this position (1 = most
    generous, 32 = stingiest). Returns (score, explanation|None)."""
    if not opp_def or not pos:
        return 50.0, None
    allowed = (opp_def.get('allowedByPosition') or {}).get(pos)
    if not allowed or allowed.get('rank') in (None, 0):
        return 50.0, None
    rank = int(allowed['rank'])
    n = 32.0
    score = _clamp((n - rank) / (n - 1) * 100.0)
    if rank <= 10:
        return score, (f"{opp_def.get('_teamLabel', 'opponent')} allows the {_ordinal(rank)}-most "
                       f"production to {pos}s ({allowed.get('ypg')} yds/gm)")
    if rank >= 24:
        return score, (f"tough spot — {opp_def.get('_teamLabel', 'opponent')} is {_ordinal(33 - rank)}-stingiest "
                       f"against {pos}s")
    return score, None


def _ordinal(n):
    n = int(n)
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"


def score_reliability(entry):
    """Floor-weighted real backtest hit rate. The P25 line is the one most people actually
    bet, so it carries the most weight; P75 is included but discounted as the reach."""
    p25 = entry['p25']['testHit']
    p50 = entry['p50']['testHit']
    p75 = entry['p75']['testHit']
    return _clamp((p25 * 0.5) + (p50 * 0.35) + (p75 * 0.15)), p25, p50


def score_model_lean(entry):
    lean = entry.get('modelLean') or {}
    prob = lean.get('leanProb')
    if prob is None:
        return 50.0, None
    score = _clamp(float(prob))
    if prob >= 65:
        return score, f"model gives {prob:.0f}% to clear the P50 in this specific matchup"
    if prob <= 35:
        return score, f"model only gives {prob:.0f}% to clear the P50 here"
    return score, None


def score_current_form(entry):
    """Trailing-3-game average against this line's own P50. Comes from the same model
    feature set, so it's real per-game production, not a vibe."""
    lean = entry.get('modelLean') or {}
    t3 = lean.get('trailing3')
    p50_line = entry['p50']['line']
    if t3 is None or not p50_line:
        return 50.0, None
    ratio = float(t3) / float(p50_line)
    score = _clamp(50.0 + (ratio - 1.0) * 100.0)
    if ratio >= 1.15:
        return score, f"last 3 games averaging {t3:.1f} against a {p50_line:.0f} line"
    if ratio <= 0.85:
        return score, f"cooling off — last 3 games averaging {t3:.1f} against a {p50_line:.0f} line"
    return score, None


def build_strong_picks(full_pool, receivers, qbs, kickers, team_defense, upcoming,
                       injuries, top_n=5, team_names=None):
    """Score every NFL ladder line, attach the score + reasoning to the entry, and return
    the top N as a ready-to-render list. Position-diversified so the list isn't five
    receiving-yards props off the same kind of matchup."""
    by_name = {}
    for group in (receivers or []), (qbs or []), (kickers or []):
        for p in group:
            by_name.setdefault(p['name'], p)

    scored = []
    for e in full_pool:
        if e.get('kind') != 'ladder':
            continue
        if e.get('testGames', 0) < STRONG_PICK_MIN_TEST_GAMES:
            continue
        if _is_unplayable(e['player'], injuries):
            continue

        up = (upcoming or {}).get(e.get('team')) or {}
        opp = up.get('opp')
        opp_def = dict(team_defense.get(opp) or {}) if opp else {}
        if opp_def:
            opp_def['_teamLabel'] = (team_names or {}).get(opp, opp)

        player_obj = by_name.get(e['player'])
        reliability, p25_hit, p50_hit = score_reliability(e)
        cov_score, cov_why = score_coverage_matchup(player_obj, opp_def, e['stat'])
        pos_score, pos_why = score_position_matchup(opp_def, e.get('pos'))
        model_score, model_why = score_model_lean(e)
        form_score, form_why = score_current_form(e)

        w = STRONG_PICK_WEIGHTS
        raw = (reliability * w['reliability'] + cov_score * w['coverage'] + pos_score * w['position']
               + model_score * w['model'] + form_score * w['form'])

        # Thin held-out samples get pulled toward neutral instead of being trusted or
        # excluded outright -- the same shrinkage logic used on the stat blends elsewhere.
        games = e.get('testGames', 0)
        trust = _clamp(games / STRONG_PICK_SHRINK_GAMES, 0.0, 1.0)
        score = 50.0 + (raw - 50.0) * trust

        inj_note = _injury_note(e['player'], injuries)
        if inj_note:
            score -= 6.0  # Questionable is a real discount, not a disqualification

        why = [x for x in [cov_why, pos_why, model_why, form_why] if x]
        why.insert(0, f"hit its P25 line in {p25_hit:.0f}% of {games} real held-out games")
        if inj_note:
            # Second, not last: `why` is capped at 4 entries for display, and a line with
            # four good reasons would otherwise push the injury caveat off the card — which
            # is precisely the one thing the reader must not miss.
            why.insert(1, inj_note)

        scored.append({
            **{k: v for k, v in e.items() if not k.startswith('_')},
            'pickScore': round(score, 1),
            'pickWhy': why[:4],
            'pickComponents': {
                'reliability': round(reliability, 1), 'coverage': round(cov_score, 1),
                'position': round(pos_score, 1), 'model': round(model_score, 1),
                'form': round(form_score, 1), 'sampleTrust': round(trust * 100),
            },
            'opponent': opp, 'isHome': up.get('isHome'), 'gameWeek': up.get('week'),
            'gameDate': up.get('date'),
        })

    # Attach the score back onto the live pool entries so the UI can sort/filter by it
    score_by_id = {s['id']: s for s in scored}
    for e in full_pool:
        s = score_by_id.get(e.get('id'))
        if s:
            e['pickScore'] = s['pickScore']
            e['pickWhy'] = s['pickWhy']
            e['pickComponents'] = s['pickComponents']
            e['pickOpponent'] = s.get('opponent')

    # One line per player (their best), then cap any single position at 2 of 5 so the list
    # spreads across the slate instead of stacking one matchup type.
    best_per_player = {}
    for s in scored:
        cur = best_per_player.get(s['player'])
        if cur is None or s['pickScore'] > cur['pickScore']:
            best_per_player[s['player']] = s
    ranked = sorted(best_per_player.values(), key=lambda s: (-s['pickScore'], -s['testGames']))

    picks, pos_count = [], {}
    for s in ranked:
        pos = s.get('pos') or '?'
        if pos_count.get(pos, 0) >= 2:
            continue
        picks.append(s)
        pos_count[pos] = pos_count.get(pos, 0) + 1
        if len(picks) >= top_n:
            break
    # If position diversity left us short -- a thin pool early in the season, or a slate
    # where one position dominates -- top up by raw score rather than shipping a list of
    # three. The relaxation is recorded so the UI can say the cap was lifted instead of
    # quietly presenting a stacked list as a diversified one.
    diversity_relaxed = False
    if len(picks) < top_n:
        have = {p['id'] for p in picks}
        for s in ranked:
            if s['id'] not in have:
                picks.append(s)
                diversity_relaxed = True
                if len(picks) >= top_n:
                    break

    week = None
    for u in (upcoming or {}).values():
        if u.get('week'):
            week = u['week'] if week is None else min(week, u['week'])
    return {
        'picks': picks,
        'week': week,
        'generatedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
        'scoredCount': len(scored),
        'weights': STRONG_PICK_WEIGHTS,
        'diversityRelaxed': diversity_relaxed,
        'excludedInjured': sum(1 for e in full_pool
                               if e.get('kind') == 'ladder' and _is_unplayable(e['player'], injuries)),
    }


def build_simple_strong_picks(pool, players, team_defense, upcoming, top_n=5, sport='wnba'):
    """WNBA/MLB version. There's no coverage-scheme data in either feed (ESPN's WNBA
    play-by-play has no defender/zone tracking at all, and MLB's equivalent isn't
    comparable), so this scores on what IS real for those sports: the backtested hit
    rate, form, and the specific next opponent's points/runs allowed."""
    by_name = {}
    for p in (players or []):
        by_name.setdefault(p['name'], p)

    # opponent generosity, ranked -- 1 = allows the most
    allowed = {}
    for t in (team_defense or []):
        name = t.get('team') if isinstance(t, dict) else None
        val = (t.get('ppgAllowed') if isinstance(t, dict) else None)
        if name and val is not None:
            allowed[name] = float(val)
    ranked_teams = sorted(allowed, key=lambda k: -allowed[k])
    opp_rank = {t: i + 1 for i, t in enumerate(ranked_teams)}
    n_teams = max(len(ranked_teams), 2)

    scored = []
    for e in pool:
        if e.get('kind') != 'ladder' or e.get('testGames', 0) < STRONG_PICK_MIN_TEST_GAMES:
            continue
        reliability, p25_hit, p50_hit = score_reliability(e)
        player_obj = by_name.get(e['player'])
        team = (player_obj or {}).get('team')
        up = (upcoming or {}).get(team) if isinstance(upcoming, dict) else None
        opp = (up or {}).get('opp')

        pos_score, pos_why = 50.0, None
        if opp and opp in opp_rank:
            r = opp_rank[opp]
            pos_score = _clamp((n_teams - r) / max(n_teams - 1, 1) * 100.0)
            if r <= max(3, n_teams // 4):
                pos_why = f"{opp} allows the {_ordinal(r)}-most points in the league"
            elif r >= n_teams - max(2, n_teams // 4):
                pos_why = f"tough spot — {opp} is {_ordinal(n_teams - r + 1)}-stingiest"

        # form: this player's real production in their own most recent games vs the line
        form_score, form_why = 50.0, None
        gl = (player_obj or {}).get('gamelog') or []
        stat_key = {'Points': 'pts', 'Rebounds': 'reb', 'Assists': 'ast', 'Steals': 'stl',
                    'Blocks': 'blk', 'Three-Pointers Made': 'tpm'}.get(e['stat'])
        if stat_key and len(gl) >= 3:
            recent = [g.get(stat_key) for g in gl[-3:] if g.get(stat_key) is not None]
            if recent and e['p50']['line']:
                t3 = sum(recent) / len(recent)
                ratio = t3 / float(e['p50']['line'])
                form_score = _clamp(50.0 + (ratio - 1.0) * 100.0)
                if ratio >= 1.15:
                    form_why = f"last 3 games averaging {t3:.1f} against a {e['p50']['line']:.0f} line"
                elif ratio <= 0.85:
                    form_why = f"cooling off — {t3:.1f} over the last 3 against a {e['p50']['line']:.0f} line"

        raw = reliability * 0.55 + pos_score * 0.25 + form_score * 0.20
        trust = _clamp(e.get('testGames', 0) / STRONG_PICK_SHRINK_GAMES, 0.0, 1.0)
        score = 50.0 + (raw - 50.0) * trust
        why = [f"hit its P25 line in {p25_hit:.0f}% of {e.get('testGames', 0)} real held-out games"]
        why += [x for x in [pos_why, form_why] if x]
        scored.append({**e, 'pickScore': round(score, 1), 'pickWhy': why[:4], 'opponent': opp,
                       'pickComponents': {'reliability': round(reliability, 1), 'position': round(pos_score, 1),
                                          'form': round(form_score, 1), 'sampleTrust': round(trust * 100)}})

    score_by_id = {s['id']: s for s in scored}
    for e in pool:
        s = score_by_id.get(e.get('id'))
        if s:
            e['pickScore'] = s['pickScore']
            e['pickWhy'] = s['pickWhy']
            e['pickComponents'] = s['pickComponents']

    best = {}
    for s in scored:
        if s['player'] not in best or s['pickScore'] > best[s['player']]['pickScore']:
            best[s['player']] = s
    picks = sorted(best.values(), key=lambda s: (-s['pickScore'], -s['testGames']))[:top_n]
    return {'picks': picks, 'scoredCount': len(scored),
            'generatedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}


# =====================================================================
# QUAD BOX — 4-leg card: 3 P25 legs + 1 Anytime TD scorer
# =====================================================================
# The shape: three floor-tranche (P25) legs off strong-performing players, plus exactly one
# Anytime-TD leg. The P25 legs come straight out of the Strong Picks scoring above, which is
# what "that same criteria" means. The TD leg is scored on its own terms, because an Anytime
# TD is a different kind of bet than a yardage floor and the things that predict it are
# different:
#
#   · TD RATE (35%)   — real share of games with a TD, current season weighted over baseline
#   · USAGE (30%)     — targets + carries per game now vs. their own historical rate; volume
#                       is what actually creates scoring chances, and a usage trend up is the
#                       single most predictive thing available here
#   · RZ MATCHUP(25%) — the opponent's real red-zone TD rate allowed, matched to HOW this
#                       player scores (through the air vs on the ground), plus their own
#                       offense's real red-zone conversion rate
#   · CURRENT TDs(10%)— TDs actually scored this season, as a direct recency check on the rate
#
# Three presets are generated (Safest / Balanced / Upside) and the full scored candidate
# lists ship too, so the UI can build custom boxes without another round trip.
#
# One thing stated plainly and never fudged: the combined probability multiplies the legs,
# which assumes they're independent. They are not — same-game legs correlate, and a blowout
# or a weather game moves several at once. The real number is lower than the math says. The
# UI says this on the card rather than burying it.
# =====================================================================
QUAD_TD_WEIGHTS = {'tdRate': 0.35, 'usage': 0.30, 'rzMatchup': 0.25, 'currentTds': 0.10}

# Gate-by-gate diagnostics for the Quad Box. "It didn't populate" is a useless symptom
# without knowing WHICH gate ate the candidates, so every filter reports its own count and
# the whole block is printed in the run log and shipped to the UI.
QUAD_LOG = []


def _qlog(msg):
    QUAD_LOG.append(msg)


def prob_to_american(p):
    if p is None or p <= 0 or p >= 1:
        return None
    if p >= 0.5:
        return int(round(-100 * p / (1 - p)))
    return int(round(100 * (1 - p) / p))


def _player_td_mix(player_obj):
    """Does this player score through the air or on the ground? Returns the receiving share
    of their real touchdowns (0 = all rushing, 1 = all receiving), or None if they have none."""
    if not player_obj:
        return None
    overall = player_obj.get('overall') or {}
    rec_td = overall.get('tds') or 0
    rush_td = overall.get('rushTD') or 0
    total = rec_td + rush_td
    if total == 0:
        return None
    return rec_td / total


def score_td_usage(player_obj):
    """Usage now vs. their own historical usage, plus absolute volume. Touches per game is
    the thing that creates scoring chances, so a real usage increase matters more here than
    a good TD rate from a smaller role."""
    if not player_obj:
        return 50.0, None
    blend = player_obj.get('currentSeasonBlend') or {}
    overall = player_obj.get('overall') or {}
    gl = player_obj.get('gamelog') or []
    hist_games = max(len(gl), 1)

    hist_touches_pg = ((overall.get('targets') or 0) + (overall.get('rushAtt') or 0)) / hist_games
    cur_games = blend.get('currentSeasonGames') or 0
    cur = blend.get('currentSeasonStats') or {}
    cur_touches_pg = None
    if cur_games > 0:
        cur_targets = cur.get('targets') or 0
        # rushAttPerGame is already per-game and already blended; use the raw current rush
        # rate when it's there, otherwise fall back to the blended figure
        cur_rush_pg = blend.get('rushAttPerGame') or 0
        cur_touches_pg = (cur_targets / cur_games) + cur_rush_pg

    # Absolute volume: ~8 touches/gm is a real role, ~16 is a featured one.
    volume_ref = cur_touches_pg if cur_touches_pg is not None else hist_touches_pg
    volume_score = _clamp((volume_ref / 16.0) * 100.0)

    if cur_touches_pg is None or hist_touches_pg <= 0:
        return volume_score, (f"{volume_ref:.1f} touches/gm" if volume_ref >= 6 else None)

    trend = cur_touches_pg / hist_touches_pg
    trend_score = _clamp(50.0 + (trend - 1.0) * 125.0)
    score = volume_score * 0.5 + trend_score * 0.5
    if trend >= 1.15:
        return score, (f"usage up — {cur_touches_pg:.1f} touches/gm this season vs "
                       f"{hist_touches_pg:.1f} historically ({cur_games} games)")
    if trend <= 0.85:
        return score, (f"usage down — {cur_touches_pg:.1f} touches/gm this season vs "
                       f"{hist_touches_pg:.1f} historically")
    return score, (f"steady {cur_touches_pg:.1f} touches/gm" if cur_touches_pg >= 8 else None)


def score_rz_matchup(player_obj, own_team, opp, redzone, team_names=None):
    """Opponent's real red-zone TD rate allowed, matched to how this player scores, plus
    their own offense's real red-zone conversion rate."""
    if not opp or not redzone:
        return 50.0, None
    opp_rz = redzone.get(opp) or {}
    own_rz = redzone.get(own_team) or {}
    mix = _player_td_mix(player_obj)

    pass_rate = opp_rz.get('defPassTDRate')
    run_rate = opp_rz.get('defRunTDRate')
    if pass_rate is None and run_rate is None:
        return 50.0, None
    if mix is None:
        relevant = [r for r in (pass_rate, run_rate) if r is not None]
        allowed = sum(relevant) / len(relevant)
        how = "in the red zone"
    elif mix >= 0.65 and pass_rate is not None:
        allowed, how = pass_rate, "on red-zone passes"
    elif mix <= 0.35 and run_rate is not None:
        allowed, how = run_rate, "on red-zone runs"
    else:
        relevant = [r for r in (pass_rate, run_rate) if r is not None]
        allowed = sum(relevant) / len(relevant)
        how = "in the red zone"

    # League red-zone TD rates per play sit around 18-22%; centre the scale there.
    score = _clamp(50.0 + (allowed - 20.0) * 4.0)
    opp_label = (team_names or {}).get(opp, opp)
    parts = []
    if allowed >= 24:
        parts.append(f"{opp_label} allows a TD on {allowed:.0f}% of plays {how}")
    elif allowed <= 15:
        parts.append(f"tough red zone — {opp_label} allows just {allowed:.0f}% {how}")

    own_conv = own_rz.get('offConversionRate')
    if own_conv is not None:
        score = score * 0.75 + _clamp(50.0 + (own_conv - 55.0) * 2.0) * 0.25
        if own_conv >= 65:
            parts.append(f"his offense converts {own_conv:.0f}% of red-zone drives into TDs")
        elif own_conv <= 45:
            parts.append(f"his offense only converts {own_conv:.0f}% of red-zone drives")
    return score, ("; ".join(parts) if parts else None)


def build_td_candidates(atd_pool, receivers, qbs, redzone, upcoming, injuries,
                        team_names=None, limit=15):
    """Score every Anytime-TD line on rate + usage + red-zone matchup + TDs actually
    scored this season. Out/Doubtful players are dropped outright."""
    by_name = {}
    for group in (receivers or []), (qbs or []):
        for p in group:
            by_name.setdefault(p['name'], p)

    out = []
    skipped = {'injured': 0, 'thinSample': 0, 'noRate': 0}
    for e in (atd_pool or []):
        name = e['player']
        if _is_unplayable(name, injuries):
            skipped['injured'] += 1
            continue
        if e.get('testGames', 0) < 3:
            skipped['thinSample'] += 1
            continue
        player_obj = by_name.get(name)
        up = (upcoming or {}).get(e.get('team')) or {}
        opp = up.get('opp')

        # Rate: lean on the current-season rate, but don't let a 3-game sample swing it
        # fully away from a two-season baseline.
        cur_rate = e.get('testRate')
        base_rate = e.get('baselineRate')
        games = e.get('testGames', 0)
        if cur_rate is None and base_rate is None:
            skipped['noRate'] += 1   # nothing real to score against; never a fabricated 0
            continue
        if base_rate is None:
            rate = cur_rate
        elif cur_rate is None:
            rate = base_rate
        else:
            w = _clamp(games / 8.0, 0.0, 1.0)
            rate = cur_rate * w + base_rate * (1 - w)
        # ~45% is an elite Anytime-TD rate; scale against that rather than 100%.
        rate_score = _clamp((rate / 45.0) * 100.0)

        usage_score, usage_why = score_td_usage(player_obj)
        rz_score, rz_why = score_rz_matchup(player_obj, e.get('team'), opp, redzone, team_names)

        # TDs actually scored this season — a direct recency check on the rate above.
        cur_tds = 0
        if player_obj:
            cur_blend = (player_obj.get('currentSeasonBlend') or {})
            cur_stats = cur_blend.get('currentSeasonStats') or {}
            cur_tds = (cur_stats.get('tds') or 0)
        cur_td_score = _clamp((cur_tds / 6.0) * 100.0)

        w = QUAD_TD_WEIGHTS
        raw = (rate_score * w['tdRate'] + usage_score * w['usage']
               + rz_score * w['rzMatchup'] + cur_td_score * w['currentTds'])
        inj_note = _injury_note(name, injuries)
        if inj_note:
            raw -= 6.0

        why = [f"scored in {rate:.0f}% of his real games ({games} this season)"]
        if inj_note:
            why.append(inj_note)   # before the flattering reasons, for the same reason as above
        if cur_tds:
            why.append(f"{int(cur_tds)} TD{'s' if cur_tds != 1 else ''} already this season")
        why += [x for x in [usage_why, rz_why] if x]
        # Cap at 5, not 4: there are four scoring components here plus a possible injury
        # caveat, and a 4-entry cap silently dropped the red-zone matchup — one of the
        # components the score is actually built from.

        out.append({
            'id': e['id'], 'player': name, 'pos': e.get('pos'), 'team': e.get('team'),
            'stat': 'Anytime TD', 'kind': 'binary', 'line': None,
            'hitPct': round(rate, 1), 'testGames': games,
            'realOdds': e.get('realOdds'),
            'score': round(_clamp(raw), 1), 'why': why[:5],
            'opponent': opp, 'isHome': up.get('isHome'),
            'components': {'tdRate': round(rate_score, 1), 'usage': round(usage_score, 1),
                           'rzMatchup': round(rz_score, 1), 'currentTds': round(cur_td_score, 1)},
            'currentSeasonTds': int(cur_tds),
            'isRookie': e.get('isRookie', False),
        })
    out.sort(key=lambda x: -x['score'])
    _qlog(f"  TD legs: {len(out)} candidates from {len(atd_pool or [])} Anytime-TD pool entries · skipped "
          f"{skipped['injured']} Out/Doubtful, {skipped['thinSample']} under 3 games, "
          f"{skipped['noRate']} with no usable TD rate")
    return out[:limit]


def build_ladder_candidates(full_pool, limit=30, min_test_games=STRONG_PICK_MIN_TEST_GAMES,
                            injuries=None):
    """The P25 legs available to a quad box: one entry per player, their best line.

    Normally these carry pickScore from the Strong Picks pass. They don't have to. If that
    pass failed or was skipped, scoring here falls back to the P25 hit rate alone, the same
    way the Top 5 widget falls back client-side. That matters because the two features used
    to be coupled: a single exception inside build_strong_picks left every pool entry without
    a pickScore, which emptied this list, which made the Quad Box render its "not enough
    qualifying lines" state -- while the Top 5 quietly fell back and looked perfectly fine.
    One failure, two very different symptoms, and nothing on the page said why."""
    scored_available = any(e.get('pickScore') is not None for e in full_pool)
    best, skipped = {}, {'kind': 0, 'noLine': 0, 'thinSample': 0, 'injured': 0}
    for e in full_pool:
        if e.get('kind') != 'ladder':
            skipped['kind'] += 1
            continue
        if not e.get('p25', {}).get('line'):
            skipped['noLine'] += 1
            continue
        if (e.get('testGames') or 0) < min_test_games:
            skipped['thinSample'] += 1
            continue
        if _is_unplayable(e['player'], injuries):
            skipped['injured'] += 1
            continue
        # Fall back to the real backtested floor hit rate when there's no composite score.
        score = e.get('pickScore')
        if score is None:
            score = e['p25']['testHit']
        cur = best.get(e['player'])
        if cur is None or score > cur[0]:
            best[e['player']] = (score, e)
    out = []
    for score, e in sorted(best.values(), key=lambda x: -x[0])[:limit]:
        why = e.get('pickWhy') or [
            f"hit its P25 line in {e['p25']['testHit']:.0f}% of {e.get('testGames', 0)} real held-out games"]
        out.append({
            'id': e['id'], 'player': e['player'], 'pos': e.get('pos'), 'team': e.get('team'),
            'stat': e['stat'], 'kind': 'ladder', 'tranche': 'p25',
            'line': e['p25']['line'], 'hitPct': e['p25']['testHit'], 'testGames': e.get('testGames'),
            'score': round(float(score), 1), 'why': why,
            'components': e.get('pickComponents'),
            'opponent': e.get('pickOpponent'),
            'isRookie': e.get('isRookie', False),
            'realLines': e.get('realLines'),
            'scoreIsFallback': not scored_available,
        })
    if not scored_available:
        _qlog("  [!] No pickScore on any pool entry — Strong Picks scoring didn't run or failed. "
              "Ranking Quad Box legs by P25 hit rate instead (degraded, but populated).")
    _qlog(f"  P25 legs: {len(out)} candidates from {len(best)} eligible players · skipped "
          f"{skipped['kind']} non-ladder, {skipped['noLine']} with no P25 line, "
          f"{skipped['thinSample']} under {min_test_games} test games, {skipped['injured']} Out/Doubtful")
    return out


def assemble_quad_box(ladder_candidates, td_candidates, name, blurb,
                      ladder_pool_slice, td_index, max_per_pos=2, max_per_team=2):
    """Build one 4-leg card: 3 P25 legs + exactly 1 TD leg. Enforces distinct players and
    caps how much of the card can ride on one position or one team, so a 'diversified' box
    isn't secretly four legs on the same drive."""
    td_pool = td_candidates[td_index:] if td_index < len(td_candidates) else td_candidates
    if not td_pool:
        _qlog(f"  [{name}] not built: no Anytime-TD candidate available")
        return None
    if len(ladder_candidates) < 3:
        _qlog(f"  [{name}] not built: only {len(ladder_candidates)} P25 legs available, needs 3")
        return None
    td_leg = td_pool[0]

    def pick_legs(pos_cap, team_cap):
        used = {td_leg['player']}
        pos_count = {td_leg.get('pos') or '?': 1}
        team_count = {td_leg.get('team') or '?': 1}
        chosen = []
        for c in ladder_pool_slice:
            if c['player'] in used:
                continue
            pos = c.get('pos') or '?'
            team = c.get('team') or '?'
            if pos_count.get(pos, 0) >= pos_cap or team_count.get(team, 0) >= team_cap:
                continue
            chosen.append(c)
            used.add(c['player'])
            pos_count[pos] = pos_count.get(pos, 0) + 1
            team_count[team] = team_count.get(team, 0) + 1
            if len(chosen) == 3:
                break
        return chosen

    legs = pick_legs(max_per_pos, max_per_team)
    relaxed = False
    if len(legs) < 3:
        # The candidate list is one line per player ranked by score, and at NFL scale the top
        # of it skews heavily to one position (there are simply more WRs posting receiving
        # lines than there are QBs or kickers). A 2-per-position cap can therefore starve the
        # card even with 30 candidates on hand. Shipping three legs instead of four, or
        # nothing at all, is worse than shipping a less diversified card and labelling it.
        legs = pick_legs(3, 3)
        relaxed = len(legs) >= 3
        if relaxed:
            _qlog(f"  [{name}] position/team caps relaxed to 3 — the candidate pool was too "
                  f"concentrated to fill the card at 2")
    if len(legs) < 3:
        _qlog(f"  [{name}] not built: could only fill {len(legs)} of 3 P25 legs from "
              f"{len(ladder_pool_slice)} candidates without repeating a player")
        return None

    all_legs = legs + [td_leg]
    probs = [(l['hitPct'] or 0) / 100.0 for l in all_legs]
    combined = 1.0
    for p in probs:
        combined *= p
    avg_score = sum(l['score'] for l in all_legs) / len(all_legs)
    return {
        'name': name, 'blurb': blurb, 'legs': all_legs,
        'combinedProb': round(combined * 100, 2),
        'americanOdds': prob_to_american(combined),
        'decimalOdds': round(1 / combined, 2) if combined > 0 else None,
        'avgScore': round(avg_score, 1),
        'weakestLeg': min(all_legs, key=lambda l: l['hitPct'] or 0)['player'],
        'diversityRelaxed': relaxed,
    }


def build_quad_box(full_pool, atd_pool, receivers, qbs, redzone, upcoming, injuries,
                   team_names=None, week=None):
    # `injuries` has to reach the floor-leg builder too. It used to be safe not to pass it,
    # because only playable players ever received a pickScore and the builder required one.
    # The hit-rate fallback added above removed that implicit protection, so the Out/Doubtful
    # filter now has to be explicit here or an unavailable player can land on a card.
    #
    # limit=60, not 30: the candidate list is one line per player ranked by score, and at
    # real scale the top of that list is almost entirely WR receiving lines. At 30 there
    # weren't enough non-WR candidates left for the 2-per-position cap to be satisfiable,
    # so every card had to fall back to the relaxed cap. A deeper list fixes the cause
    # rather than loosening the rule, and gives the custom builder more to work with.
    ladder_candidates = build_ladder_candidates(full_pool, limit=60, injuries=injuries)
    td_candidates = build_td_candidates(atd_pool, receivers, qbs, redzone, upcoming,
                                        injuries, team_names, limit=15)

    presets = []
    if ladder_candidates and td_candidates:

        def build_preset(name, blurb, ladder_slice, td_slice):
            """Try the narrowed slice this preset is meant to express; if the slice can't
            fill a legal card, retry against the full candidate list before giving up.
            Counting the slice first isn't sufficient — the caps need positional variety,
            not just three bodies, so four same-position candidates still can't build."""
            box = assemble_quad_box(ladder_candidates, td_slice, name, blurb, ladder_slice, 0)
            if box is None and ladder_slice is not ladder_candidates:
                _qlog(f"  [{name}] narrowed slice couldn't fill a card — retrying on the full pool")
                box = assemble_quad_box(ladder_candidates, td_slice, name, blurb, ladder_candidates, 0)
            if box:
                presets.append(box)

        # Safest: highest P25 hit rates available, paired with the most reliable TD scorer.
        build_preset("Safest",
                     "Highest real hit rates on the board, paired with the most consistent "
                     "TD scorer. Lowest payout, best chance of cashing.",
                     sorted(ladder_candidates, key=lambda c: -(c['hitPct'] or 0)),
                     sorted(td_candidates, key=lambda c: -(c['hitPct'] or 0)))
        # Balanced: straight composite score order on both sides.
        build_preset("Balanced",
                     "Top composite scores on both sides — the hit rate, this week's matchup, "
                     "the model lean and usage all weighted together.",
                     ladder_candidates, td_candidates)
        # Upside: the best-scoring lines whose hit rate is lower, which is where the price is.
        build_preset("Upside",
                     "Strong-scoring lines that the hit rate alone would pass over — where the "
                     "matchup and usage signals are doing the work. Bigger price, more variance.",
                     [c for c in ladder_candidates if (c['hitPct'] or 0) < 70] or ladder_candidates,
                     [c for c in td_candidates if (c['hitPct'] or 0) < 45] or td_candidates)

    if not presets:
        _qlog("  No preset cards built — see the gate counts above for which filter emptied "
              "the pool. The UI shows these same counts instead of a generic empty message.")

    return {
        'presets': presets,
        'ladderCandidates': ladder_candidates,
        'tdCandidates': td_candidates,
        'week': week,
        'generatedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
        'tdWeights': QUAD_TD_WEIGHTS,
        # Shipped to the browser on purpose: when the generator comes up empty, the page
        # should say which gate did it rather than making you read the Actions log.
        'diagnostics': list(QUAD_LOG),
        'poolSize': sum(1 for e in full_pool if e.get('kind') == 'ladder'),
        'atdPoolSize': len(atd_pool or []),
        'scoredAvailable': any(e.get('pickScore') is not None for e in full_pool),
    }


# =====================================================================
# MAIN PIPELINE
# =====================================================================
# =====================================================================
# JSX PRECOMPILATION (mobile-safety fix)
# Ships plain, already-transformed JavaScript instead of raw JSX + the
# in-browser Babel library — avoids the memory/CPU spike that was crashing
# the page on mobile Safari. Requires Node.js + npm (one-time package
# install, auto-bootstrapped below). Falls back to the old in-browser-Babel
# approach if Node/npm aren't available, so the script never hard-fails.
# =====================================================================
BABEL_TOOLS_DIR = SCRIPT_DIR / "_babel_tools"


def node_and_npm_available():
    is_windows = sys.platform.startswith('win')
    try:
        subprocess.run(['node', '--version'], capture_output=True, check=True, timeout=10)
        # npm ships as npm.cmd on Windows, not a plain .exe — needs shell=True to resolve correctly
        subprocess.run('npm --version', capture_output=True, check=True, timeout=10, shell=True)
        return True
    except Exception:
        return False


def ensure_babel_installed():
    """One-time local install of @babel/core + @babel/preset-react, isolated in its own
    folder (no package.json needed at the repo root, doesn't touch anything else)."""
    core_path = BABEL_TOOLS_DIR / "node_modules" / "@babel" / "core"
    if core_path.exists():
        return True
    print("  Installing Babel (one-time, ~15 seconds)...")
    BABEL_TOOLS_DIR.mkdir(exist_ok=True)
    try:
        result = subprocess.run(
            'npm install @babel/core@7 @babel/preset-react@7 --no-save --no-audit --no-fund',
            cwd=BABEL_TOOLS_DIR, capture_output=True, text=True, timeout=180, shell=True
        )
        if result.returncode != 0:
            print(f"  npm install failed: {result.stderr[-500:]}")
            return False
        return core_path.exists()
    except Exception as e:
        print(f"  npm install error: {e}")
        return False


def precompile_jsx(jsx_code):
    """Returns plain JS, or None if precompilation isn't available/fails for any reason."""
    if not node_and_npm_available():
        print("  Node.js/npm not found — falling back to in-browser Babel (works, just heavier on mobile).")
        return None
    if not ensure_babel_installed():
        print("  Babel install failed — falling back to in-browser Babel.")
        return None

    jsx_path = BABEL_TOOLS_DIR / "_input.jsx"
    out_path = BABEL_TOOLS_DIR / "_output.js"
    jsx_path.write_text(jsx_code, encoding='utf-8')

    node_script = f"""
const babel = require({json.dumps(str(BABEL_TOOLS_DIR / 'node_modules' / '@babel' / 'core'))});
const fs = require('fs');
const code = fs.readFileSync({json.dumps(str(jsx_path))}, 'utf8');
const result = babel.transformSync(code, {{
  presets: [[{json.dumps(str(BABEL_TOOLS_DIR / 'node_modules' / '@babel' / 'preset-react'))}, {{ runtime: 'classic' }}]]
}});
fs.writeFileSync({json.dumps(str(out_path))}, result.code);
"""
    runner_path = BABEL_TOOLS_DIR / "_runner.js"
    runner_path.write_text(node_script, encoding='utf-8')
    try:
        result = subprocess.run(['node', str(runner_path)], capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print(f"  Precompile failed: {result.stderr[-500:]}")
            return None
        return out_path.read_text(encoding='utf-8')
    except Exception as e:
        print(f"  Precompile error: {e}")
        return None


# =====================================================================
# COLLEGE FOOTBALL PIPELINE (College Football Data API — collegefootballdata.com,
# free tier: 1,000 calls/month, includes historical betting lines).
# Different market structure than the other 3 sports: no player props (CFB books
# rarely offer them), so this is built around game-level markets — spread, total,
# moneyline — with team-level offense/defense stats, matching the Teams tab pattern
# already used elsewhere.
#
# NOTE: like the MLB pipeline, this could not be test-executed against live data
# from this sandbox (api.collegefootballdata.com is outside its network allowlist).
# Built defensively — every game/line parse is individually try/excepted so one bad
# assumption fails quietly rather than breaking the whole run. Confirmed field names
# only for the core /games response (home_team, away_team, completed, season, week,
# start_date) via a verified schema; /lines parsing uses documented community
# conventions and is the piece most likely to need a real-world adjustment.
# =====================================================================
CFBD_API_BASE = "https://api.collegefootballdata.com"
CFBD_API_KEY_PATH = SCRIPT_DIR / "cfbd_api_key.txt"
CFB_TRAIN_SEASON = 2025
CFB_HOME_FIELD_DEFAULT = 2.5  # empirically overridden once we have enough real games to compute it ourselves


def load_cfbd_api_key():
    env_key = os.environ.get('CFBD_API_KEY')
    if env_key and env_key.strip():
        return env_key.strip()
    if not CFBD_API_KEY_PATH.exists():
        return None
    key = CFBD_API_KEY_PATH.read_text(encoding='utf-8').strip()
    return key if key else None


def cfbd_get(path, params, api_key, timeout=25):
    try:
        r = requests.get(f"{CFBD_API_BASE}{path}", params=params,
                          headers={'Authorization': f'Bearer {api_key}'}, timeout=timeout)
        if r.status_code != 200:
            print(f"    CFBD {path} -> HTTP {r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
        print(f"    CFBD {path} -> HTTP 200, {len(data) if isinstance(data, list) else 'non-list'} items")
        return data
    except requests.RequestException as e:
        print(f"    CFBD {path} -> request failed: {e}")
        return None


def fetch_cfb_teams(api_key):
    data = cfbd_get("/teams/fbs", {"year": datetime.date.today().year}, api_key)
    if not data:
        return {}
    out = {}
    for t in data:
        tid = t.get('id')
        school = t.get('school')
        if tid and school:
            out[tid] = school
    return out


def fetch_cfb_games(season, api_key):
    """Field names confirmed directly from a real successful response (2026-09-06 debug
    session) — the live API uses camelCase (homeTeam, awayTeam, homePoints, startDate,
    neutralSite), not the snake_case a community schema reference had suggested. This
    was a real bug: team names were coming back as None, silently collapsing every game
    into one fake team. Fixed now with the confirmed real keys, not another guess.
    classification='fbs' matters — without it, CFBD returns games across every division
    (FBS, FCS, D2, D3), which is exactly what was inflating the team count to 670+ and
    producing nonsense rank numbers like '#521 of X' instead of a real 1-134 FBS ranking."""
    data = cfbd_get("/games", {"year": season, "seasonType": "regular", "classification": "fbs"}, api_key)
    if not data:
        return []
    games = []
    for g in data:
        try:
            games.append({
                'id': g.get('id'), 'season': g.get('season'), 'week': g.get('week'),
                'start_date': g.get('startDate'), 'completed': bool(g.get('completed')),
                'home_team': g.get('homeTeam'), 'away_team': g.get('awayTeam'),
                'home_points': g.get('homePoints'), 'away_points': g.get('awayPoints'),
                'neutral_site': bool(g.get('neutralSite')),
            })
        except Exception:
            continue
    return games


def fetch_cfb_lines(season, api_key):
    """Real historical spread/total/moneyline, per game, per provider. Used to backtest
    our own model's real accuracy — this is what makes the confidence numbers genuine
    rather than self-graded. Defensive: unknown/renamed fields just get skipped per-line
    rather than crashing the whole fetch."""
    data = cfbd_get("/lines", {"year": season, "seasonType": "regular"}, api_key)
    if not data:
        return {}
    out = {}
    for g in data:
        gid = g.get('id')
        lines = g.get('lines') or []
        if not gid or not lines:
            continue
        # take the first provider with a usable spread+overUnder; good enough for backtesting purposes
        for line in lines:
            try:
                spread = line.get('spread')
                total = line.get('overUnder')
                if spread is None and total is None:
                    continue
                out[gid] = {
                    'spread': float(spread) if spread is not None else None,
                    'total': float(total) if total is not None else None,
                    'homeMoneyline': line.get('homeMoneyline'), 'awayMoneyline': line.get('awayMoneyline'),
                    'provider': line.get('provider'),
                }
                break
            except (TypeError, ValueError):
                continue
    return out


def build_cfb_team_ratings(games, season_names):
    """Real power-rating differential per team: avg points scored, avg points allowed,
    from actual completed games only. Same 'derive from real results' approach used for
    every other sport tonight — no external rating service, just real scoring data."""
    scored = {}
    allowed = {}
    games_count = {}
    home_margins = []  # for empirically computing home-field advantage from real data
    for g in games:
        if g['home_points'] is None or g['away_points'] is None:  # real scores present = actually completed, more reliable than the API's own flag
            continue
        h, a = g['home_team'], g['away_team']
        hp, ap = g['home_points'], g['away_points']
        for team, pf, pa in [(h, hp, ap), (a, ap, hp)]:
            scored.setdefault(team, []).append(pf)
            allowed.setdefault(team, []).append(pa)
        if not g['neutral_site']:
            home_margins.append(hp - ap)

    home_field = round(sum(home_margins) / len(home_margins), 2) if len(home_margins) >= 20 else CFB_HOME_FIELD_DEFAULT

    ratings = {}
    for team in scored:
        n = len(scored[team])
        if n < 4:
            continue
        avg_scored = sum(scored[team]) / n
        avg_allowed = sum(allowed[team]) / n
        ratings[team] = {
            'avgPointsScored': round(avg_scored, 1), 'avgPointsAllowed': round(avg_allowed, 1),
            'powerRating': round(avg_scored - avg_allowed, 2), 'games': n,
        }
    return ratings, home_field


def predict_cfb_game(home_team, away_team, ratings, home_field):
    if home_team not in ratings or away_team not in ratings:
        return None
    h, a = ratings[home_team], ratings[away_team]
    predicted_margin = round((h['powerRating'] - a['powerRating']) + home_field, 1)
    predicted_total = round((h['avgPointsScored'] + h['avgPointsAllowed'] + a['avgPointsScored'] + a['avgPointsAllowed']) / 2, 1)
    return {'predictedMargin': predicted_margin, 'predictedTotal': predicted_total}


def backtest_cfb_model(train_games, test_games, test_lines):
    """The real validation step: build ratings from train_games only, generate predictions
    for every completed test_games matchup, then compare against the REAL historical line
    for that game (from test_lines) to see how often our predicted side would have covered
    and how often our total call was right. This is what makes any confidence badge here
    trustworthy rather than a self-graded number."""
    ratings, home_field = build_cfb_team_ratings(train_games, {})
    spread_correct, spread_total = 0, 0
    total_correct, total_total = 0, 0
    ml_correct, ml_total = 0, 0

    for g in test_games:
        if g['home_points'] is None or g['away_points'] is None:  # real scores present = actually completed, more reliable than the API's own flag
            continue
        pred = predict_cfb_game(g['home_team'], g['away_team'], ratings, home_field)
        if not pred:
            continue
        actual_margin = g['home_points'] - g['away_points']
        actual_total = g['home_points'] + g['away_points']

        # moneyline: did our predicted favorite actually win?
        ml_total += 1
        predicted_home_favorite = pred['predictedMargin'] > 0
        actual_home_won = actual_margin > 0
        if predicted_home_favorite == actual_home_won:
            ml_correct += 1

        line = test_lines.get(g['id'])
        if line and line.get('spread') is not None:
            # CFBD spread convention: negative = home favored. Our predicted_margin is
            # home-minus-away, so the comparable market number is -spread.
            market_home_margin = -line['spread']
            spread_total += 1
            # did the home side cover the REAL market spread, and did we predict that side?
            home_covered = actual_margin > market_home_margin
            we_predicted_home_covers = pred['predictedMargin'] > market_home_margin
            if home_covered == we_predicted_home_covers:
                spread_correct += 1
        if line and line.get('total') is not None:
            total_total += 1
            actual_over = actual_total > line['total']
            we_predicted_over = pred['predictedTotal'] > line['total']
            if actual_over == we_predicted_over:
                total_correct += 1

    return {
        'spreadHitRate': round(100 * spread_correct / spread_total, 1) if spread_total >= 10 else None,
        'spreadSample': spread_total,
        'totalHitRate': round(100 * total_correct / total_total, 1) if total_total >= 10 else None,
        'totalSample': total_total,
        'moneylineHitRate': round(100 * ml_correct / ml_total, 1) if ml_total >= 10 else None,
        'moneylineSample': ml_total,
    }


def build_cfb_upcoming(games, ratings, home_field, lines_by_game, team_names_by_id):
    today = datetime.date.today().isoformat()

    # Targeted diagnostic — a user reported a real, known game (Ole Miss) missing from
    # the upcoming list despite it being scheduled for that same night. Rather than guess
    # again, this checks exactly which of the three real filter conditions a team's game
    # is failing, so the actual cause shows up directly in the next real run's output.
    for check_team in ['Ole Miss', 'LSU']:
        matches = [g for g in games if g['home_team'] == check_team or g['away_team'] == check_team]
        print(f"  [diagnostic] '{check_team}': {len(matches)} total games found in raw CFBD data")
        for g in matches[:3]:
            already_played = g['home_points'] is not None and g['away_points'] is not None
            has_date = bool(g['start_date'])
            has_rating = check_team in ratings
            opp = g['away_team'] if g['home_team'] == check_team else g['home_team']
            opp_has_rating = opp in ratings
            print(f"    vs {opp} on {g['start_date']}: already_played={already_played}, has_start_date={has_date}, "
                  f"'{check_team}'_has_rating={has_rating}, '{opp}'_has_rating={opp_has_rating}")

    upcoming = []
    for g in games:
        if (g['home_points'] is not None and g['away_points'] is not None) or not g['start_date']:  # has a real score already = already played, not upcoming
            continue
        game_date = g['start_date'][:10]
        if game_date < today:
            continue
        pred = predict_cfb_game(g['home_team'], g['away_team'], ratings, home_field)
        if not pred:
            continue
        # Real kickoff time, converted from the UTC timestamp CFBD provides to US/Eastern —
        # this is what actually lets games be organized by start time, not just by date.
        kickoff_et = None
        try:
            from zoneinfo import ZoneInfo
            dt_utc = datetime.datetime.fromisoformat(g['start_date'].replace('Z', '+00:00'))
            dt_et = dt_utc.astimezone(ZoneInfo("America/New_York"))
            # %-I (strip leading zero) is Linux/Mac-only and crashes on Windows — this
            # user runs the pipeline on Windows, so formatting normally then stripping
            # a leading zero manually is what actually works cross-platform.
            hour_min = dt_et.strftime("%I:%M %p ET")
            kickoff_et = hour_min.lstrip("0")
        except Exception:
            pass
        upcoming.append({
            'id': g['id'], 'date': game_date, 'startDateTime': g['start_date'], 'kickoffET': kickoff_et, 'week': g['week'],
            'homeTeam': g['home_team'], 'awayTeam': g['away_team'],
            'predictedMargin': pred['predictedMargin'], 'predictedTotal': pred['predictedTotal'],
        })
    # Sort by the FULL timestamp (not just the date) so games on the same day are correctly
    # ordered by actual kickoff time, not left in whatever order the source data happened to be in.
    upcoming.sort(key=lambda g: g['startDateTime'])
    # Widened from 60 — FBS alone runs ~65-70 games per week, so 60 didn't even cover a
    # single full week, let alone let you see games happening a bit further out. 200
    # comfortably covers several weeks forward without meaningfully affecting payload size
    # (each entry here is small — a few hundred bytes at most).
    return upcoming[:200]


# =====================================================================
# ACCURACY LEDGER — backend-only, never shown in the UI. Snapshots today's
# real predictions (P25/P50/P75 lines for NFL, spread/total for CFB), then
# on later runs checks whether a real result now exists for that specific
# player-game or game, and grades the earlier snapshot against it. This is
# what lets accuracy get graded against REAL FUTURE outcomes as they
# happen, rather than only backtesting against past seasons. Persisted to
# a JSON file that accumulates across runs (committed to the repo like the
# other data files) so the track record survives between script runs.
# =====================================================================
ACCURACY_LEDGER_PATH = SCRIPT_DIR / "accuracy_ledger.json"

def load_accuracy_ledger():
    if ACCURACY_LEDGER_PATH.exists():
        try:
            return json.loads(ACCURACY_LEDGER_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {"pending": [], "graded": [], "summary": {}}

def save_accuracy_ledger(ledger):
    summary = {}
    for entry in ledger["graded"]:
        key = f"{entry['sport']}_{entry['tranche']}"
        summary.setdefault(key, {"graded": 0, "hits": 0})
        summary[key]["graded"] += 1
        if entry["hit"]:
            summary[key]["hits"] += 1
    for key, s in summary.items():
        s["rate"] = round(100 * s["hits"] / s["graded"], 1) if s["graded"] else None
    ledger["summary"] = summary
    ACCURACY_LEDGER_PATH.write_text(json.dumps(ledger, indent=2), encoding='utf-8')
    return summary

def update_nfl_accuracy_ledger(ledger, full_pool, nfl_upcoming, receivers, qbs, kickers):
    # full_pool entries carry a composite "name|stat" id (for slip-tracking purposes), NOT
    # the player's real id — so the lookup here has to go by name, matching what full_pool
    # actually provides, not by the receivers/qbs/kickers' own pid-based id field.
    all_players = {p['name']: p for p in receivers + qbs + kickers}
    today = pd.Timestamp.now().strftime('%Y-%m-%d')
    stat_field_map = {
        "Receiving Yards": "yards", "Receptions": "catches",
        "Rush Yards": "rush_yards", "Rush Attempts": "rush_att",
        "Passing Yards": "yards", "Completions": "catches",
    }

    still_pending = []
    graded_count = 0
    for snap in ledger["pending"]:
        if snap["sport"] != "nfl":
            still_pending.append(snap)
            continue
        player = all_players.get(snap["player"])
        gl = player.get('gamelog', []) if player else []
        if not player or len(gl) <= snap["gamelogLenAtSnapshot"]:
            still_pending.append(snap)  # game hasn't been played yet (or player vanished from pool -- rare)
            continue
        field = stat_field_map.get(snap["stat"])
        actual = gl[-1].get(field) if field else None
        if actual is None:
            still_pending.append(snap)
            continue
        for tranche in ["p25", "p50", "p75"]:
            ledger["graded"].append({
                "sport": "nfl", "tranche": tranche, "player": snap["player"], "stat": snap["stat"],
                "line": snap[tranche], "actual": round(float(actual), 1),
                "hit": actual >= snap[tranche], "snapshotDate": snap["snapshotDate"], "gradedDate": today,
            })
        graded_count += 1
    ledger["pending"] = still_pending

    existing_keys = {(s["player"], s["stat"]) for s in ledger["pending"] if s["sport"] == "nfl"}
    new_snapshots = 0
    for entry in full_pool:
        if entry.get('kind') != 'ladder' or entry.get('team') not in nfl_upcoming:
            continue
        key = (entry['player'], entry['stat'])
        if key in existing_keys:
            continue
        player = all_players.get(entry['player'])
        if not player:
            continue
        ledger["pending"].append({
            "sport": "nfl", "player": entry['player'], "stat": entry['stat'],
            "p25": entry['p25']['line'], "p50": entry['p50']['line'], "p75": entry['p75']['line'],
            "gamelogLenAtSnapshot": len(player.get('gamelog', [])), "snapshotDate": today,
        })
        new_snapshots += 1
    print(f"  NFL accuracy ledger: graded {graded_count} newly-completed games, snapshotted {new_snapshots} new predictions")
    return ledger

def update_cfb_accuracy_ledger(ledger, cfb_games, cfb_upcoming_list):
    today = pd.Timestamp.now().strftime('%Y-%m-%d')
    games_by_id = {g['id']: g for g in cfb_games}

    still_pending = []
    graded_count = 0
    for snap in ledger["pending"]:
        if snap["sport"] != "cfb":
            still_pending.append(snap)
            continue
        g = games_by_id.get(snap["gameId"])
        if not g or g['home_points'] is None or g['away_points'] is None:
            still_pending.append(snap)  # not played yet
            continue
        real_margin = g['home_points'] - g['away_points']
        real_total = g['home_points'] + g['away_points']
        for market, predicted, actual in [("spread", snap["predictedMargin"], real_margin), ("total", snap["predictedTotal"], real_total)]:
            hit = (predicted > 0) == (actual > 0) if market == "spread" else abs(predicted - actual) <= 3
            ledger["graded"].append({
                "sport": "cfb", "tranche": market, "player": f"{snap['awayTeam']} @ {snap['homeTeam']}", "stat": market,
                "line": predicted, "actual": actual, "hit": hit, "snapshotDate": snap["snapshotDate"], "gradedDate": today,
            })
        graded_count += 1
    ledger["pending"] = still_pending

    existing_ids = {s["gameId"] for s in ledger["pending"] if s["sport"] == "cfb"}
    new_snapshots = 0
    for g in cfb_upcoming_list:
        if g['id'] in existing_ids:
            continue
        ledger["pending"].append({
            "sport": "cfb", "gameId": g['id'], "homeTeam": g['homeTeam'], "awayTeam": g['awayTeam'],
            "predictedMargin": g['predictedMargin'], "predictedTotal": g['predictedTotal'], "snapshotDate": today,
        })
        new_snapshots += 1
    print(f"  CFB accuracy ledger: graded {graded_count} newly-completed games, snapshotted {new_snapshots} new predictions")
    return ledger



def main():
    print("=" * 60)
    print("NFL Dashboard Auto-Updater")
    print("=" * 60)

    # ---- 1. Determine which seasons have real data ----
    print("\n[1/7] Checking which seasons have data...")
    all_seasons = list(BASELINE_SEASONS)
    current_season = None
    for s in CANDIDATE_CURRENT_SEASONS:
        if season_has_data(s):
            print(f"  Found data for {s} — treating as current in-progress season")
            all_seasons.append(s)
            current_season = s
            break
    if current_season is None:
        print("  No current-season data yet (offseason). Baseline-only run.")

    # ---- 2. Download everything ----
    print("\n[2/7] Downloading nflverse data...")
    games_path = fetch_games_file()
    games_all = pd.read_csv(games_path, low_memory=False)
    for s in all_seasons:
        print(f"  Fetching {s}...")
        fetch_season_files(s)
    roster_frames = []
    for s in all_seasons:
        rp = CACHE_DIR / f"roster_{s}.parquet"
        if rp.exists():
            roster_frames.append(pd.read_parquet(rp))
    roster_all = pd.concat(roster_frames) if roster_frames else pd.DataFrame()
    roster_map = (roster_all.sort_values('season').drop_duplicates('gsis_id', keep='last')
                  .set_index('gsis_id')['full_name']) if len(roster_all) else pd.Series(dtype=str)

    # Current-team lookup from roster data, NOT play-by-play. This matters specifically
    # around trades/free-agent signings: play-by-play only knows a player's team once
    # they've actually played a real game for it, so early in a season (or right after
    # an offseason move) it can show a player's OLD team. Roster data reflects real
    # roster moves as soon as they're official, independent of games played. Built
    # defensively since nflverse's exact column name isn't 100% guaranteed stable —
    # this prints what it actually found so a wrong assumption shows up immediately
    # rather than silently doing nothing.
    current_team_by_pid = pd.Series(dtype=str)
    if len(roster_all):
        team_col = next((c for c in ['team', 'team_abbr', 'recent_team'] if c in roster_all.columns), None)
        if team_col:
            current_team_by_pid = (roster_all.sort_values('season').drop_duplicates('gsis_id', keep='last')
                                    .set_index('gsis_id')[team_col])
            print(f"  Current-roster team lookup built from '{team_col}' column: {len(current_team_by_pid)} players")
        else:
            print(f"  [!] No team column found in roster data (columns: {list(roster_all.columns)[:15]}...) — falling back to play-by-play-derived team assignment")

    # ESPN's own roster pages, checked FIRST (higher priority than the nflverse roster
    # snapshot above) — see fetch_espn_current_rosters for why this exists.
    espn_current_teams = fetch_espn_current_rosters()

    # ---- 3. Build merged play-by-play for every season ----
    print("\n[3/7] Classifying plays (front/coverage/weather)...")
    merged_frames = []
    for s in all_seasons:
        m = build_merged(s, games_all)
        if m is not None:
            merged_frames.append(m)
            print(f"  {s}: {len(m)} plays")
    if not merged_frames:
        print("ERROR: No play-by-play data available at all. Aborting.")
        sys.exit(1)
    merged_all = pd.concat(merged_frames, ignore_index=True)

    # latest-team lookup (across all roles, most recent game)
    def latest_team_for_role(id_col):
        df = merged_all[merged_all[id_col].notna()].copy()
        df['week_num'] = df['game_id'].str.split('_').str[1].astype(int)
        df = df.sort_values(['season', 'week_num'])
        return df.groupby(id_col)['posteam'].last()

    latest_team_by_pid = {}
    for col in ['receiver_player_id', 'rusher_player_id', 'passer_player_id', 'kicker_player_id']:
        latest_team_by_pid.update(latest_team_for_role(col).to_dict())

    # team-change flag: does team differ between the two BASELINE seasons specifically
    def team_by_season(id_col):
        df = merged_all[merged_all[id_col].notna() & merged_all['season'].isin(BASELINE_SEASONS)]
        return df.groupby([id_col, 'season'])['posteam'].agg(lambda x: x.mode().iloc[0])

    team_change_map = {}
    for col in ['receiver_player_id', 'rusher_player_id', 'passer_player_id', 'kicker_player_id']:
        series = team_by_season(col)
        for pid in series.index.get_level_values(0).unique():
            sub = series.loc[pid]
            t24 = sub.get(BASELINE_SEASONS[0])
            t25 = sub.get(BASELINE_SEASONS[1])
            name = roster_map.get(pid)
            if name:
                team_change_map[name] = {
                    'team2024': t24, 'team2025': t25,
                    'changed': bool(t24 and t25 and t24 != t25)
                }

    # ---- 4. Build receiver / QB / kicker / sacks datasets with 2yr splits + current-season blend ----
    print("\n[4/7] Building player datasets with train/test splits and current-season blend...")
    baseline = merged_all[merged_all.season.isin(BASELINE_SEASONS)]
    current = merged_all[merged_all.season == current_season] if current_season else merged_all.iloc[0:0]

    redzone_tendencies = build_redzone_tendencies(baseline, current)
    print(f"  Red zone tendencies computed for {len(redzone_tendencies)} teams")

    def blend_stat(train_val, current_val, n_current_games):
        """Shrinkage-weighted blend of historical baseline vs current season-to-date."""
        if n_current_games == 0 or current_val is None:
            return {'value': train_val, 'weight_current': 0.0, 'games_this_season': 0}
        w = n_current_games / (n_current_games + SHRINKAGE_K)
        blended = w * current_val + (1 - w) * train_val
        return {'value': round(float(blended), 2), 'weight_current': round(float(w), 3), 'games_this_season': int(n_current_games)}

    def agg_receiving(g):
        n = len(g)
        if n == 0:
            return None
        catches = g['complete_pass'].fillna(0).sum()
        yards = g['yards_gained'].fillna(0).sum()
        tds = g['pass_touchdown'].fillna(0).sum()
        epa = g['epa'].fillna(0).sum()
        return {'targets': int(n), 'catches': int(catches), 'yards': float(yards), 'tds': int(tds),
                'catchRate': round(catches / n * 100, 1), 'yptTarget': round(yards / n, 2),
                'epaPerTarget': round(epa / n, 3)}

    receivers = []
    targets_baseline = baseline[baseline['receiver_player_id'].notna()].copy()
    targets_baseline['position'] = targets_baseline['receiver_player_id'].map(roster_map.index.to_series().map(lambda x: None)) if False else None
    # map position via roster
    pos_map = roster_all.sort_values('season').drop_duplicates('gsis_id', keep='last').set_index('gsis_id')['position'] if len(roster_all) else pd.Series(dtype=str)
    targets_baseline['position'] = targets_baseline['receiver_player_id'].map(pos_map)
    targets_baseline = targets_baseline[targets_baseline['position'].isin(['WR', 'TE', 'RB', 'FB'])]

    targets_current = current[current['receiver_player_id'].notna()].copy() if len(current) else current
    if len(targets_current):
        targets_current['position'] = targets_current['receiver_player_id'].map(pos_map)
        targets_current = targets_current[targets_current['position'].isin(['WR', 'TE', 'RB', 'FB'])]

    rush_baseline = baseline[baseline['rusher_player_id'].notna()]
    rush_current = current[current['rusher_player_id'].notna()] if len(current) else current

    for pid, g in targets_baseline.groupby('receiver_player_id'):
        if len(g) < 12:
            continue
        name = roster_map.get(pid, g['receiver_player_name'].iloc[0])
        pos = g['position'].iloc[0]
        team = espn_current_teams.get(name) or current_team_by_pid.get(pid) or latest_team_by_pid.get(pid, g['posteam'].mode().iloc[0])
        overall = agg_receiving(g)
        home = agg_receiving(g[g.is_home]) or {}
        away = agg_receiving(g[~g.is_home]) or {}
        fronts = {fb: agg_receiving(gg) for fb, gg in g.groupby('front_bucket')}
        covs = {cv: agg_receiving(gg) for cv, gg in g.groupby('coverage') if len(gg) >= 3}
        weathers = {w: agg_receiving(gg) for w, gg in g.groupby('weather')}
        gl = g.groupby(['season', 'game_id']).agg(
            targets=('week', 'count'), catches=('complete_pass', 'sum'), yards=('yards_gained', 'sum'), tds=('pass_touchdown', 'sum')
        ).reset_index()

        # merge this player's own rushing production (critical for RBs, and jet-sweep WRs)
        rb = rush_baseline[rush_baseline.rusher_player_id == pid]
        if len(rb):
            rush_gl = rb.groupby(['season', 'game_id']).agg(
                rush_att=('rush_attempt', 'sum'), rush_yards=('rushing_yards', 'sum'), rush_td=('rush_touchdown', 'sum')
            ).reset_index()
            if rb['rush_attempt'].sum() > 0:
                overall['rushAtt'] = int(rb['rush_attempt'].sum())
                overall['rushYards'] = float(rb['rushing_yards'].sum())
                overall['rushTD'] = int(rb['rush_touchdown'].sum())
                overall['ypc'] = round(overall['rushYards'] / overall['rushAtt'], 2) if overall['rushAtt'] else None
                overall['scrimmageYards'] = overall['yards'] + overall['rushYards']
            gl = gl.merge(rush_gl, on=['season', 'game_id'], how='outer').fillna(0)

        # current-season blend (targets/gm, receiving yds/gm, rushing yds/gm all shrinkage-weighted)
        cur_g = targets_current[targets_current.receiver_player_id == pid] if len(targets_current) else targets_current
        cur_games = cur_g['game_id'].nunique() if len(cur_g) else 0

        # Touchdowns panel reads 'tds' -- include real current-season TDs here too, same
        # reasoning as the gamelog/plays fixes above: an aggregate blend elsewhere doesn't
        # help if the actual list on the page never gets the new games added to it.
        td_plays_df = pd.concat([g, cur_g], ignore_index=True) if len(cur_g) else g
        td_plays = td_plays_df[td_plays_df.pass_touchdown == 1][['week', 'season', 'defteam', 'front', 'coverage', 'yards_gained']].to_dict('records')

        blend = None
        if cur_games > 0:
            cur_overall = agg_receiving(cur_g)
            cur_rush = rush_current[rush_current.rusher_player_id == pid] if len(rush_current) else rush_current
            cur_rush_att = float(cur_rush['rush_attempt'].sum()) if len(cur_rush) else 0.0
            cur_rush_yards = float(cur_rush['rushing_yards'].sum()) if len(cur_rush) else 0.0
            cur_scrimmage = cur_overall['yards'] + cur_rush_yards
            train_scrimmage = overall.get('scrimmageYards', overall['yards'])
            blend = {
                'targetsPerGame': blend_stat(overall['targets'] / max(len(gl), 1), cur_overall['targets'] / cur_games, cur_games),
                'yardsPerGame': blend_stat(overall['yards'] / max(len(gl), 1), cur_overall['yards'] / cur_games, cur_games),
                'rushAttPerGame': blend_stat(overall.get('rushAtt', 0) / max(len(gl), 1), cur_rush_att / cur_games, cur_games),
                'rushYardsPerGame': blend_stat(overall.get('rushYards', 0) / max(len(gl), 1), cur_rush_yards / cur_games, cur_games),
                'scrimmageYardsPerGame': blend_stat(train_scrimmage / max(len(gl), 1), cur_scrimmage / cur_games, cur_games),
                'currentSeasonGames': cur_games,
                'currentSeasonStats': cur_overall,
            }

            # Real per-game rows for the current season, appended to the SAME 'gamelog' the
            # Recent Games panel reads (which already mixes 2024 and 2025 games together,
            # tagged by their own season) -- so real current-season games actually show up
            # in that list next to 2024-25 ones instead of only ever appearing as an
            # aggregate blended average above it.
            cur_gl = cur_g.groupby(['season', 'game_id']).agg(
                targets=('week', 'count'), catches=('complete_pass', 'sum'), yards=('yards_gained', 'sum'), tds=('pass_touchdown', 'sum')
            ).reset_index()
            if len(cur_rush):
                cur_rush_gl = cur_rush.groupby(['season', 'game_id']).agg(
                    rush_att=('rush_attempt', 'sum'), rush_yards=('rushing_yards', 'sum'), rush_td=('rush_touchdown', 'sum')
                ).reset_index()
                cur_gl = cur_gl.merge(cur_rush_gl, on=['season', 'game_id'], how='outer').fillna(0)
            gl = pd.concat([gl, cur_gl], ignore_index=True).fillna(0).sort_values(['season', 'game_id']).reset_index(drop=True)

        receivers.append({
            'id': pid, 'shortName': g['receiver_player_name'].iloc[0], 'name': name, 'pos': pos, 'team': team,
            'overall': overall, 'home': home, 'away': away, 'fronts': fronts, 'coverages': covs, 'weather': weathers,
            'tds': [{'week': int(t['week']), 'season': int(t['season']), 'opp': t['defteam'], 'front': t['front'],
                     'coverage': t['coverage'], 'yards': float(t['yards_gained'])} for t in td_plays],
            'gamelog': gl.to_dict('records'),
            'currentSeasonBlend': blend,
            'isRookie': False,
        })

    # New-to-the-dataset players -- true rookies, practice-squad call-ups now starting,
    # anyone with zero 2024-25 targets -- are otherwise 100% invisible: the loop above
    # only ever iterates pids present in targets_baseline. A real target/catch/yard this
    # season is real regardless of whether the player has baseline history, so give them
    # their own path, built entirely from this season's own games. Flagged isRookie so
    # the ladder step below knows to use a single-season split instead of the normal
    # 2024-train/2025-test one (see pctile_ladder_rookie). ROOKIE_MIN_GAMES is a
    # module-level constant (see its definition up top) so build_atd_pool can honor the
    # same bar for a rookie's Anytime-TD eligibility.
    baseline_receiver_pids = set(targets_baseline['receiver_player_id'].unique()) if len(targets_baseline) else set()
    if len(targets_current):
        for pid, cg in targets_current.groupby('receiver_player_id'):
            if pid in baseline_receiver_pids:
                continue  # already covered above (has real baseline history too)
            cur_games = cg['game_id'].nunique()
            if cur_games < ROOKIE_MIN_GAMES:
                continue  # too early this season to say anything real yet
            name = roster_map.get(pid, cg['receiver_player_name'].iloc[0])
            pos = cg['position'].iloc[0]
            team = espn_current_teams.get(name) or current_team_by_pid.get(pid) or latest_team_by_pid.get(pid, cg['posteam'].mode().iloc[0])
            overall = agg_receiving(cg)
            home = agg_receiving(cg[cg.is_home]) or {}
            away = agg_receiving(cg[~cg.is_home]) or {}
            gl = cg.groupby(['season', 'game_id']).agg(
                targets=('week', 'count'), catches=('complete_pass', 'sum'), yards=('yards_gained', 'sum'), tds=('pass_touchdown', 'sum')
            ).reset_index()
            rb = rush_current[rush_current.rusher_player_id == pid] if len(rush_current) else rush_current
            if len(rb):
                rush_gl = rb.groupby(['season', 'game_id']).agg(
                    rush_att=('rush_attempt', 'sum'), rush_yards=('rushing_yards', 'sum'), rush_td=('rush_touchdown', 'sum')
                ).reset_index()
                if rb['rush_attempt'].sum() > 0:
                    overall['rushAtt'] = int(rb['rush_attempt'].sum())
                    overall['rushYards'] = float(rb['rushing_yards'].sum())
                    overall['rushTD'] = int(rb['rush_touchdown'].sum())
                    overall['ypc'] = round(overall['rushYards'] / overall['rushAtt'], 2) if overall['rushAtt'] else None
                    overall['scrimmageYards'] = overall['yards'] + overall['rushYards']
                gl = gl.merge(rush_gl, on=['season', 'game_id'], how='outer').fillna(0)
            td_plays = cg[cg.pass_touchdown == 1][['week', 'season', 'defteam', 'front', 'coverage', 'yards_gained']].to_dict('records')
            n_gl = max(len(gl), 1)
            receivers.append({
                'id': pid, 'shortName': cg['receiver_player_name'].iloc[0], 'name': name, 'pos': pos, 'team': team,
                'overall': overall, 'home': home, 'away': away, 'fronts': {}, 'coverages': {}, 'weather': {},
                'tds': [{'week': int(t['week']), 'season': int(t['season']), 'opp': t['defteam'], 'front': t['front'],
                         'coverage': t['coverage'], 'yards': float(t['yards_gained'])} for t in td_plays],
                'gamelog': gl.to_dict('records'),
                'currentSeasonBlend': {
                    'targetsPerGame': {'value': round(overall['targets'] / n_gl, 2), 'weight_current': 1.0, 'games_this_season': cur_games},
                    'yardsPerGame': {'value': round(overall['yards'] / n_gl, 2), 'weight_current': 1.0, 'games_this_season': cur_games},
                    'currentSeasonGames': cur_games, 'currentSeasonStats': overall,
                },
                'isRookie': True,
            })
    receivers.sort(key=lambda p: -p['overall']['targets'])
    print(f"  {len(receivers)} skill players ({sum(1 for r in receivers if r['isRookie'])} new-to-the-dataset this season)")

    # Target Share % — real metric (this player's targets ÷ their team's total targets over the same window)
    team_total_targets = targets_baseline.groupby('posteam').size().to_dict()
    for p in receivers:
        team_total = team_total_targets.get(p['team'])
        if team_total:
            p['overall']['targetShare'] = round(p['overall']['targets'] / team_total * 100, 1)
        else:
            p['overall']['targetShare'] = None

    # NOTE: QBs, kickers, sacks, FULL_POOL ladders, and team_defense follow the exact same
    # pattern established above (baseline train/test 2024->2025, unchanged; current-season
    # blend computed the same shrinkage-weighted way when current_season data exists).
    # For brevity in this script, reuse receivers' structure as the template — extend
    # analogously for QBS/KICKERS/SACKS/TOP10/FULL_POOL/TEAM_DEFENSE using passer_player_id /
    # kicker_player_id / sack_player_id and the corresponding stat columns, exactly as built
    # interactively during development. Placeholder empty structures below keep the pipeline
    # runnable end-to-end; fill in following the receivers pattern for full parity.
    # ---- QBs (passing + rushing merged, since QB rush yards/TDs matter) ----
    def agg_qb(g):
        n = len(g)
        if n == 0:
            return None
        comp = g['complete_pass'].fillna(0).sum()
        yards = g['passing_yards'].fillna(0).sum()
        tds = g['pass_touchdown'].fillna(0).sum()
        ints = g['interception'].fillna(0).sum()
        epa = g['epa'].fillna(0).sum()
        return {'attempts': int(n), 'completions': int(comp), 'yards': float(yards), 'tds': int(tds), 'ints': int(ints),
                'compPct': round(comp / n * 100, 1), 'yptAtt': round(yards / n, 2), 'epaPerAtt': round(epa / n, 3)}

    passes_baseline = baseline[baseline['passer_player_id'].notna()].copy()
    passes_baseline['position'] = passes_baseline['passer_player_id'].map(pos_map)
    passes_baseline = passes_baseline[passes_baseline['position'] == 'QB']
    passes_current = current[current['passer_player_id'].notna()].copy() if len(current) else current
    if len(passes_current):
        passes_current['position'] = passes_current['passer_player_id'].map(pos_map)
        passes_current = passes_current[passes_current['position'] == 'QB']

    qbs = []
    for pid, g in passes_baseline.groupby('passer_player_id'):
        if len(g) < 40:
            continue
        name = roster_map.get(pid, g['passer_player_name'].iloc[0])
        team = espn_current_teams.get(name) or current_team_by_pid.get(pid) or latest_team_by_pid.get(pid, g['posteam'].mode().iloc[0])
        overall = agg_qb(g)
        home = agg_qb(g[g.is_home]) or {}
        away = agg_qb(g[~g.is_home]) or {}
        fronts = {fb: agg_qb(gg) for fb, gg in g.groupby('front_bucket')}
        covs = {cv: agg_qb(gg) for cv, gg in g.groupby('coverage') if len(gg) >= 5}
        weathers = {w: agg_qb(gg) for w, gg in g.groupby('weather')}
        gl = g.groupby(['season', 'game_id']).agg(
            attempts=('week', 'count'), completions=('complete_pass', 'sum'), yards=('passing_yards', 'sum'),
            tds=('pass_touchdown', 'sum'), ints=('interception', 'sum')
        ).reset_index()

        # merge in this QB's own rushing (attempts/yards/tds) — the part you flagged as important
        rb = rush_baseline[rush_baseline.rusher_player_id == pid]
        if len(rb):
            rush_gl = rb.groupby(['season', 'game_id']).agg(
                rush_att=('rush_attempt', 'sum'), rush_yards=('rushing_yards', 'sum'), rush_td=('rush_touchdown', 'sum')
            ).reset_index()
            overall['rushAtt'] = int(rb['rush_attempt'].sum())
            overall['rushYards'] = float(rb['rushing_yards'].sum())
            overall['rushTD'] = int(rb['rush_touchdown'].sum())
            overall['totalYards'] = overall['yards'] + overall['rushYards']
            gl = gl.merge(rush_gl, on=['season', 'game_id'], how='left').fillna(0)
        else:
            gl['rush_att'] = 0; gl['rush_yards'] = 0.0; gl['rush_td'] = 0

        # current-season blend (passing yards + rush yards, weighted by games played this season)
        cur_g = passes_current[passes_current.passer_player_id == pid] if len(passes_current) else passes_current
        cur_games = cur_g['game_id'].nunique() if len(cur_g) else 0

        # Touchdowns panel reads 'tds' -- include real current-season TDs here too (same
        # reasoning as the receivers block above).
        td_plays_df = pd.concat([g, cur_g], ignore_index=True) if len(cur_g) else g
        td_plays = td_plays_df[td_plays_df.pass_touchdown == 1][['week', 'season', 'defteam', 'front', 'coverage']].to_dict('records')

        blend = None
        if cur_games > 0:
            cur_overall = agg_qb(cur_g)
            cur_rush = rush_current[rush_current.rusher_player_id == pid] if len(rush_current) else rush_current
            cur_rush_yards = float(cur_rush['rushing_yards'].sum()) if len(cur_rush) else 0.0
            w = cur_games / (cur_games + SHRINKAGE_K)
            blend = {
                'passYardsPerGame': blend_stat(overall['yards'] / max(len(gl), 1), cur_overall['yards'] / cur_games, cur_games),
                'rushYardsPerGame': blend_stat(overall.get('rushYards', 0) / max(len(gl), 1), cur_rush_yards / cur_games, cur_games),
                'currentSeasonGames': cur_games,
                'currentSeasonStats': cur_overall,
            }

            # Real current-season per-game rows appended to the same gamelog the Recent
            # Games panel reads -- see the identical note on the receivers block above.
            cur_gl = cur_g.groupby(['season', 'game_id']).agg(
                attempts=('week', 'count'), completions=('complete_pass', 'sum'), yards=('passing_yards', 'sum'),
                tds=('pass_touchdown', 'sum'), ints=('interception', 'sum')
            ).reset_index()
            if len(cur_rush):
                cur_rush_gl = cur_rush.groupby(['season', 'game_id']).agg(
                    rush_att=('rush_attempt', 'sum'), rush_yards=('rushing_yards', 'sum'), rush_td=('rush_touchdown', 'sum')
                ).reset_index()
                cur_gl = cur_gl.merge(cur_rush_gl, on=['season', 'game_id'], how='left').fillna(0)
            else:
                cur_gl['rush_att'] = 0; cur_gl['rush_yards'] = 0.0; cur_gl['rush_td'] = 0
            gl = pd.concat([gl, cur_gl], ignore_index=True).fillna(0).sort_values(['season', 'game_id']).reset_index(drop=True)

        qbs.append({
            'id': pid, 'shortName': g['passer_player_name'].iloc[0], 'name': name, 'pos': 'QB', 'team': team,
            'overall': overall, 'home': home, 'away': away, 'fronts': fronts, 'coverages': covs, 'weather': weathers,
            'tds': [{'week': int(t['week']), 'season': int(t['season']), 'opp': t['defteam'], 'front': t['front'], 'coverage': t['coverage']} for t in td_plays],
            'gamelog': gl.to_dict('records'),
            'currentSeasonBlend': blend,
            'isRookie': False,
        })

    # Same new-to-the-dataset path as receivers above -- a real rookie/new-starter QB
    # with zero 2024-25 baseline attempts is otherwise invisible no matter how many
    # real pass attempts he's thrown this season.
    baseline_qb_pids = set(passes_baseline['passer_player_id'].unique()) if len(passes_baseline) else set()
    if len(passes_current):
        for pid, cg in passes_current.groupby('passer_player_id'):
            if pid in baseline_qb_pids:
                continue
            cur_games = cg['game_id'].nunique()
            if cur_games < ROOKIE_MIN_GAMES:
                continue
            name = roster_map.get(pid, cg['passer_player_name'].iloc[0])
            team = espn_current_teams.get(name) or current_team_by_pid.get(pid) or latest_team_by_pid.get(pid, cg['posteam'].mode().iloc[0])
            overall = agg_qb(cg)
            home = agg_qb(cg[cg.is_home]) or {}
            away = agg_qb(cg[~cg.is_home]) or {}
            gl = cg.groupby(['season', 'game_id']).agg(
                attempts=('week', 'count'), completions=('complete_pass', 'sum'), yards=('passing_yards', 'sum'),
                tds=('pass_touchdown', 'sum'), ints=('interception', 'sum')
            ).reset_index()
            rb = rush_current[rush_current.rusher_player_id == pid] if len(rush_current) else rush_current
            if len(rb):
                rush_gl = rb.groupby(['season', 'game_id']).agg(
                    rush_att=('rush_attempt', 'sum'), rush_yards=('rushing_yards', 'sum'), rush_td=('rush_touchdown', 'sum')
                ).reset_index()
                overall['rushAtt'] = int(rb['rush_attempt'].sum())
                overall['rushYards'] = float(rb['rushing_yards'].sum())
                overall['rushTD'] = int(rb['rush_touchdown'].sum())
                overall['totalYards'] = overall['yards'] + overall['rushYards']
                gl = gl.merge(rush_gl, on=['season', 'game_id'], how='left').fillna(0)
            else:
                gl['rush_att'] = 0; gl['rush_yards'] = 0.0; gl['rush_td'] = 0
            td_plays = cg[cg.pass_touchdown == 1][['week', 'season', 'defteam', 'front', 'coverage']].to_dict('records')
            n_gl = max(len(gl), 1)
            qbs.append({
                'id': pid, 'shortName': cg['passer_player_name'].iloc[0], 'name': name, 'pos': 'QB', 'team': team,
                'overall': overall, 'home': home, 'away': away, 'fronts': {}, 'coverages': {}, 'weather': {},
                'tds': [{'week': int(t['week']), 'season': int(t['season']), 'opp': t['defteam'], 'front': t['front'], 'coverage': t['coverage']} for t in td_plays],
                'gamelog': gl.to_dict('records'),
                'currentSeasonBlend': {
                    'passYardsPerGame': {'value': round(overall['yards'] / n_gl, 2), 'weight_current': 1.0, 'games_this_season': cur_games},
                    'rushYardsPerGame': {'value': round(overall.get('rushYards', 0) / n_gl, 2), 'weight_current': 1.0, 'games_this_season': cur_games},
                    'currentSeasonGames': cur_games, 'currentSeasonStats': overall,
                },
                'isRookie': True,
            })
    qbs.sort(key=lambda p: -p['overall']['yards'])
    print(f"  {len(qbs)} QBs (with rushing merged in) ({sum(1 for q in qbs if q['isRookie'])} new-to-the-dataset this season)")

    atd_pool = build_atd_pool(baseline, current, receivers, qbs)
    print(f"  {len(atd_pool)} players with real Anytime TD rates computed (skill positions + QB rushing)")

    # ---- Kickers ----
    def agg_k(g):
        n = len(g)
        if n == 0:
            return None
        made = g['made'].sum()
        return {'attempts': int(n), 'made': int(made), 'pct': round(made / n * 100, 1),
                'avgDist': round(g['kick_distance'].mean(), 1) if g['kick_distance'].notna().any() else None}

    fgs_baseline = baseline[baseline['field_goal_attempt'] == 1].copy()
    fgs_baseline['made'] = (fgs_baseline['field_goal_result'] == 'made').astype(int)
    fgs_baseline['dist_bucket'] = fgs_baseline['kick_distance'].apply(
        lambda d: 'Unknown' if pd.isna(d) else ('<30' if d < 30 else '30-39' if d < 40 else '40-49' if d < 50 else '50+'))
    fgs_current = current[current['field_goal_attempt'] == 1].copy() if len(current) else current
    if len(fgs_current):
        fgs_current['made'] = (fgs_current['field_goal_result'] == 'made').astype(int)
    xps_baseline = baseline[baseline.get('extra_point_attempt', pd.Series(dtype=float)) == 1] if 'extra_point_attempt' in baseline.columns else baseline.iloc[0:0]

    kickers = []
    for pid, g in fgs_baseline.groupby('kicker_player_id'):
        if pd.isna(pid) or len(g) < 15:
            continue
        name = roster_map.get(pid, g['kicker_player_name'].iloc[0])
        team = espn_current_teams.get(name) or current_team_by_pid.get(pid) or latest_team_by_pid.get(pid, g['posteam'].mode().iloc[0])
        overall = agg_k(g)
        home = agg_k(g[g.is_home]) or {}
        away = agg_k(g[~g.is_home]) or {}
        dist = {db: agg_k(gg) for db, gg in g.groupby('dist_bucket')}
        weathers = {w: agg_k(gg) for w, gg in g.groupby('weather')}
        xp_g = xps_baseline[xps_baseline.kicker_player_id == pid] if len(xps_baseline) else xps_baseline
        xp_made = int((xp_g['extra_point_result'] == 'good').sum()) if len(xp_g) else 0
        xp_att = int(len(xp_g))
        fg_gl = g.groupby(['season', 'game_id']).agg(attempts=('made', 'count'), made=('made', 'sum')).reset_index()
        fg_gl['points'] = fg_gl['made'] * 3

        cur_g = fgs_current[fgs_current.kicker_player_id == pid] if len(fgs_current) else fgs_current
        cur_games = cur_g['game_id'].nunique() if len(cur_g) else 0
        blend = None
        if cur_games > 0:
            cur_overall = agg_k(cur_g)
            blend = {
                'fgMadePerGame': blend_stat(overall['made'] / max(len(fg_gl), 1), cur_overall['made'] / cur_games, cur_games),
                'currentSeasonGames': cur_games, 'currentSeasonStats': cur_overall,
            }

            # Real current-season per-game rows appended to the same gamelog the Recent
            # Games panel reads -- see the identical note on the receivers block above.
            cur_fg_gl = cur_g.groupby(['season', 'game_id']).agg(attempts=('made', 'count'), made=('made', 'sum')).reset_index()
            cur_fg_gl['points'] = cur_fg_gl['made'] * 3
            fg_gl = pd.concat([fg_gl, cur_fg_gl], ignore_index=True).fillna(0).sort_values(['season', 'game_id']).reset_index(drop=True)

        kickers.append({
            'id': pid, 'shortName': g['kicker_player_name'].iloc[0], 'name': name, 'pos': 'K', 'team': team,
            'overall': overall, 'home': home, 'away': away, 'distance': dist, 'weather': weathers,
            'xpMade': xp_made, 'xpAtt': xp_att, 'gamelog': fg_gl.to_dict('records'),
            'currentSeasonBlend': blend,
            'isRookie': False,
        })

    # Same new-to-the-dataset path as receivers/QBs above.
    baseline_kicker_pids = set(fgs_baseline['kicker_player_id'].dropna().unique()) if len(fgs_baseline) else set()
    if len(fgs_current):
        for pid, cg in fgs_current.groupby('kicker_player_id'):
            if pd.isna(pid) or pid in baseline_kicker_pids:
                continue
            cur_games = cg['game_id'].nunique()
            if cur_games < ROOKIE_MIN_GAMES:
                continue
            name = roster_map.get(pid, cg['kicker_player_name'].iloc[0])
            team = espn_current_teams.get(name) or current_team_by_pid.get(pid) or latest_team_by_pid.get(pid, cg['posteam'].mode().iloc[0])
            overall = agg_k(cg)
            home = agg_k(cg[cg.is_home]) or {}
            away = agg_k(cg[~cg.is_home]) or {}
            cg = cg.copy()
            cg['dist_bucket'] = cg['kick_distance'].apply(
                lambda d: 'Unknown' if pd.isna(d) else ('<30' if d < 30 else '30-39' if d < 40 else '40-49' if d < 50 else '50+'))
            dist = {db: agg_k(gg) for db, gg in cg.groupby('dist_bucket')}
            fg_gl = cg.groupby(['season', 'game_id']).agg(attempts=('made', 'count'), made=('made', 'sum')).reset_index()
            fg_gl['points'] = fg_gl['made'] * 3
            n_gl = max(len(fg_gl), 1)
            kickers.append({
                'id': pid, 'shortName': cg['kicker_player_name'].iloc[0], 'name': name, 'pos': 'K', 'team': team,
                'overall': overall, 'home': home, 'away': away, 'distance': dist, 'weather': {},
                'xpMade': 0, 'xpAtt': 0, 'gamelog': fg_gl.to_dict('records'),
                'currentSeasonBlend': {
                    'fgMadePerGame': {'value': round(overall['made'] / n_gl, 2), 'weight_current': 1.0, 'games_this_season': cur_games},
                    'currentSeasonGames': cur_games, 'currentSeasonStats': overall,
                },
                'isRookie': True,
            })
    kickers.sort(key=lambda p: -p['overall']['made'])
    print(f"  {len(kickers)} kickers ({sum(1 for k in kickers if k['isRookie'])} new-to-the-dataset this season)")

    # ---- Sacks (defenders) ----
    def build_sack_rows(df):
        rows = []
        if len(df) == 0:
            return pd.DataFrame(rows)
        for _, r in df[df['sack'] == 1].iterrows():
            entries = []
            if pd.notna(r.get('sack_player_id')):
                entries.append((r['sack_player_id'], 1.0))
            if pd.notna(r.get('half_sack_1_player_id')):
                entries.append((r['half_sack_1_player_id'], 0.5))
            if pd.notna(r.get('half_sack_2_player_id')):
                entries.append((r['half_sack_2_player_id'], 0.5))
            for pid, val in entries:
                rows.append({'pid': pid, 'val': val, 'week': r['week'], 'season': r['season'], 'posteam': r['posteam'],
                             'defteam': r['defteam'], 'is_home': r['defteam'] == r['home_team'], 'front': r['front'],
                             'coverage': r['coverage'], 'weather': r['weather'], 'qb': r.get('passer_player_name'),
                             'down': r.get('down'), 'ydsToGo': r.get('ydstogo'), 'game_id': r['game_id']})
        return pd.DataFrame(rows)

    sdf = build_sack_rows(baseline)
    sdf_current = build_sack_rows(current) if len(current) else pd.DataFrame()
    sacks = []
    if len(sdf):
        for pid, g in sdf.groupby('pid'):
            total = g['val'].sum()
            if total < 1.5:
                continue
            name = roster_map.get(pid, pid)
            pos = pos_map.get(pid, '?')
            team = espn_current_teams.get(name) or current_team_by_pid.get(pid) or latest_team_by_pid.get(pid, g['defteam'].mode().iloc[0])
            home_sacks = g[g.is_home]['val'].sum()
            away_sacks = g[~g.is_home]['val'].sum()
            front_breakdown = g.groupby('front')['val'].sum().sort_values(ascending=False).to_dict()
            weather_breakdown = g.groupby('weather')['val'].sum().to_dict()
            gl = g.groupby(['season', 'game_id'])['val'].sum().reset_index().rename(columns={'val': 'sacks'})

            # Real current-season blend, same shrinkage-weighted approach used for every
            # other position -- this was previously the one player type on the site with
            # zero current-season awareness at all.
            cur_g = sdf_current[sdf_current.pid == pid] if len(sdf_current) else sdf_current
            cur_games = cur_g['game_id'].nunique() if len(cur_g) else 0

            # "Every Sack" on DefenseDetail reads 'plays', NOT 'gamelog' -- current-season
            # sack plays need to land here too, or they'd pass through the gamelog/blend
            # fix above but still never actually show up in the one place a person would
            # look for them on this page.
            plays_all = pd.concat([g, cur_g], ignore_index=True) if len(cur_g) else g
            plays = plays_all[['week', 'season', 'posteam', 'front', 'coverage', 'qb', 'down', 'ydsToGo', 'val']].sort_values(['season', 'week']).to_dict('records')
            blend = None
            if cur_games > 0:
                cur_total = float(cur_g['val'].sum())
                blend = {
                    'sacksPerGame': blend_stat(float(total) / max(len(gl), 1), cur_total / cur_games, cur_games),
                    'currentSeasonGames': cur_games, 'currentSeasonStats': {'sacks': round(cur_total, 1), 'games': cur_games},
                }

                # Real current-season per-game rows appended to the same gamelog the Recent
                # Games panel reads -- see the identical note on the receivers block above.
                cur_gl = cur_g.groupby(['season', 'game_id'])['val'].sum().reset_index().rename(columns={'val': 'sacks'})
                gl = pd.concat([gl, cur_gl], ignore_index=True).fillna(0).sort_values(['season', 'game_id']).reset_index(drop=True)

            sacks.append({
                'id': pid, 'name': name, 'pos': pos, 'team': team, 'totalSacks': round(float(total), 1),
                'homeSacks': round(float(home_sacks), 1), 'awaySacks': round(float(away_sacks), 1),
                'avgPassRushers': None,
                'frontBreakdown': {k: round(float(v), 1) for k, v in front_breakdown.items()},
                'weatherBreakdown': {k: round(float(v), 1) for k, v in weather_breakdown.items()},
                'plays': [{'week': int(p['week']), 'season': int(p['season']), 'opp': p['posteam'], 'front': p['front'],
                           'coverage': p['coverage'], 'qb': p['qb'], 'down': (int(p['down']) if pd.notna(p['down']) else None),
                           'togo': (int(p['ydsToGo']) if pd.notna(p['ydsToGo']) else None), 'val': p['val']} for p in plays],
                'gamelog': gl.to_dict('records'),
                'currentSeasonBlend': blend,
                'isRookie': False,
            })

    # Same new-to-the-dataset path as receivers/QBs/kickers above -- a rookie or
    # newly-signed pass rusher with zero 2024-25 baseline sacks was otherwise invisible
    # on the Sacks page no matter how many real sacks he has this season.
    baseline_sack_pids = set(sdf['pid'].unique()) if len(sdf) else set()
    if len(sdf_current):
        for pid, cg in sdf_current.groupby('pid'):
            if pid in baseline_sack_pids:
                continue
            cur_games = cg['game_id'].nunique()
            total = cg['val'].sum()
            if cur_games < ROOKIE_MIN_GAMES or total < 1.5:
                continue
            name = roster_map.get(pid, pid)
            pos = pos_map.get(pid, '?')
            team = espn_current_teams.get(name) or current_team_by_pid.get(pid) or latest_team_by_pid.get(pid, cg['defteam'].mode().iloc[0])
            home_sacks = cg[cg.is_home]['val'].sum()
            away_sacks = cg[~cg.is_home]['val'].sum()
            front_breakdown = cg.groupby('front')['val'].sum().sort_values(ascending=False).to_dict()
            weather_breakdown = cg.groupby('weather')['val'].sum().to_dict()
            gl = cg.groupby(['season', 'game_id'])['val'].sum().reset_index().rename(columns={'val': 'sacks'})
            plays = cg[['week', 'season', 'posteam', 'front', 'coverage', 'qb', 'down', 'ydsToGo', 'val']].sort_values(['season', 'week']).to_dict('records')
            sacks.append({
                'id': pid, 'name': name, 'pos': pos, 'team': team, 'totalSacks': round(float(total), 1),
                'homeSacks': round(float(home_sacks), 1), 'awaySacks': round(float(away_sacks), 1),
                'avgPassRushers': None,
                'frontBreakdown': {k: round(float(v), 1) for k, v in front_breakdown.items()},
                'weatherBreakdown': {k: round(float(v), 1) for k, v in weather_breakdown.items()},
                'plays': [{'week': int(p['week']), 'season': int(p['season']), 'opp': p['posteam'], 'front': p['front'],
                           'coverage': p['coverage'], 'qb': p['qb'], 'down': (int(p['down']) if pd.notna(p['down']) else None),
                           'togo': (int(p['ydsToGo']) if pd.notna(p['ydsToGo']) else None), 'val': p['val']} for p in plays],
                'gamelog': gl.to_dict('records'),
                'currentSeasonBlend': {
                    'sacksPerGame': {'value': round(float(total) / max(len(gl), 1), 2), 'weight_current': 1.0, 'games_this_season': cur_games},
                    'currentSeasonGames': cur_games, 'currentSeasonStats': {'sacks': round(float(total), 1), 'games': cur_games},
                },
                'isRookie': True,
            })
    sacks.sort(key=lambda d: -d['totalSacks'])
    print(f"  {len(sacks)} pass rushers ({sum(1 for s in sacks if s['isRookie'])} new-to-the-dataset this season)")

    # ---- Prop pool (P25/P50/P75 ladders, train=baseline[0] test=baseline[1]) ----
    def pctile_ladder(train_vals, test_vals, min25, min50):
        if len(train_vals) < 8 or len(test_vals) < 6:
            return None
        p25 = np.floor(np.percentile(train_vals, 25))
        p50 = np.floor(np.percentile(train_vals, 50))
        p75 = np.floor(np.percentile(train_vals, 75))
        if p25 < min25 or p50 < min50 or p75 <= p50:
            return None
        def hit(line):
            return round(float((test_vals >= line).mean()) * 100, 1)
        return {'p25': {'line': float(p25), 'testHit': hit(p25)}, 'p50': {'line': float(p50), 'testHit': hit(p50)},
                'p75': {'line': float(p75), 'testHit': hit(p75)}, 'trainGames': int(len(train_vals)), 'testGames': int(len(test_vals))}

    def pctile_ladder_rookie(ordered_vals, min25, min50, min_games=ROOKIE_MIN_GAMES):
        """Same P25/P50/P75 math as pctile_ladder, but for a player with NO 2024-25
        baseline at all (isRookie=True) -- split WITHIN this season's own games instead
        of across two full seasons, so the line still comes from one slice of real games
        and the hit-rate is still checked against a different, held-out slice, never the
        same games used to set the line. Inherently a much smaller, noisier split than
        the normal 8-train/6-test one -- that's exactly why every entry built this way
        carries isRookie=True (the UI shows a ROOKIE badge) and why the existing
        ConfidenceBadge, which already reads real testGames, will show "Limited" rather
        than implying this is as solid as a full two-season read."""
        n = len(ordered_vals)
        if n < min_games:
            return None
        test_n = max(1, n // 3)
        train_vals = np.array(ordered_vals[:-test_n], dtype=float)
        test_vals = np.array(ordered_vals[-test_n:], dtype=float)
        if len(train_vals) == 0:
            return None
        p25 = np.floor(np.percentile(train_vals, 25))
        p50 = np.floor(np.percentile(train_vals, 50))
        p75 = np.floor(np.percentile(train_vals, 75))
        if p25 < min25 or p50 < min50 or p75 <= p50:
            return None
        def hit(line):
            return round(float((test_vals >= line).mean()) * 100, 1)
        return {'p25': {'line': float(p25), 'testHit': hit(p25)}, 'p50': {'line': float(p50), 'testHit': hit(p50)},
                'p75': {'line': float(p75), 'testHit': hit(p75)}, 'trainGames': int(len(train_vals)), 'testGames': int(len(test_vals))}

    def build_ladder(p, gl, key, min25, min50):
        """Dispatches to the right split depending on whether this player has a real
        2024-25 baseline (normal two-season train/test) or not (single-season rookie
        split) -- the one place that decides which math every stat/position uses."""
        if p.get('isRookie'):
            ordered = sorted(gl, key=lambda x: (x['season'], x['game_id']))
            vals = [x.get(key, 0) for x in ordered]
            return pctile_ladder_rookie(vals, min25, min50)
        train = np.array([x.get(key, 0) for x in gl if x['season'] == BASELINE_SEASONS[0]], dtype=float)
        test = np.array([x.get(key, 0) for x in gl if x['season'] == BASELINE_SEASONS[1]], dtype=float)
        return pctile_ladder(train, test, min25, min50)

    full_pool = []
    for p in receivers:
        gl = p['gamelog']
        change = team_change_map.get(p['name'], {})
        for key, label, min25, min50 in [('catches', 'Receptions', 1, 2), ('yards', 'Receiving Yards', 10, 20), ('targets', 'Targets', 2, 3)]:
            ladder = build_ladder(p, gl, key, min25, min50)
            if ladder:
                full_pool.append({'player': p['name'], 'pos': p['pos'], 'team': p['team'], 'stat': label, 'kind': 'ladder',
                                   **ladder, 'teamChanged': change.get('changed', False), 'team2024': change.get('team2024'),
                                   'team2025': change.get('team2025'), 'note': None, 'isRookie': p.get('isRookie', False),
                                   'id': f"{p['name']}|{label}".replace(' ', '_')})
        # rushing props (workhorse RBs primarily, but also jet-sweep WRs with real volume).
        # The "does this player rush enough to bother" check stays scoped to whichever
        # games actually feed the ladder below -- 2024 train games normally, or this
        # player's own current-season games for a rookie -- exactly like before, just no
        # longer assuming every player has 2024 rows to check.
        for key, label, min25, min50 in [('rush_att', 'Rush Attempts', 2, 4), ('rush_yards', 'Rush Yards', 10, 20)]:
            if p.get('isRookie'):
                check_vals = [x.get(key, 0) for x in gl]
            else:
                check_vals = [x.get(key, 0) for x in gl if x['season'] == BASELINE_SEASONS[0]]
            if len(check_vals) == 0 or np.mean(check_vals) < 1:
                continue
            ladder = build_ladder(p, gl, key, min25, min50)
            if ladder:
                full_pool.append({'player': p['name'], 'pos': p['pos'], 'team': p['team'], 'stat': label, 'kind': 'ladder',
                                   **ladder, 'teamChanged': change.get('changed', False), 'team2024': change.get('team2024'),
                                   'team2025': change.get('team2025'), 'note': None, 'isRookie': p.get('isRookie', False),
                                   'id': f"{p['name']}|{label}".replace(' ', '_')})
    for p in qbs:
        gl = p['gamelog']
        change = team_change_map.get(p['name'], {})
        for key, label, min25, min50 in [('yards', 'Passing Yards', 60, 120), ('completions', 'Completions', 6, 10),
                                          ('tds', 'Passing Touchdowns', 0, 1), ('rush_yards', 'QB Rush Yards', 0, 5)]:
            if key == 'rush_yards':
                if p.get('isRookie'):
                    check_vals = [x.get(key, 0) for x in gl]
                else:
                    check_vals = [x.get(key, 0) for x in gl if x['season'] == BASELINE_SEASONS[0]]
                if len(check_vals) == 0 or np.mean(check_vals) < 8:
                    continue
            ladder = build_ladder(p, gl, key, min25, min50)
            if ladder:
                full_pool.append({'player': p['name'], 'pos': 'QB', 'team': p['team'], 'stat': label, 'kind': 'ladder',
                                   **ladder, 'teamChanged': change.get('changed', False), 'team2024': change.get('team2024'),
                                   'team2025': change.get('team2025'), 'note': None, 'isRookie': p.get('isRookie', False),
                                   'id': f"{p['name']}|{label}".replace(' ', '_')})
    for p in kickers:
        gl = p['gamelog']
        change = team_change_map.get(p['name'], {})
        for key, label, min25, min50 in [('made', 'FG Made', 1, 1), ('points', 'Kicking Points', 1, 3)]:
            ladder = build_ladder(p, gl, key, min25, min50)
            if ladder:
                full_pool.append({'player': p['name'], 'pos': 'K', 'team': p['team'], 'stat': label, 'kind': 'ladder',
                                   **ladder, 'teamChanged': change.get('changed', False), 'team2024': change.get('team2024'),
                                   'team2025': change.get('team2025'), 'note': None, 'isRookie': p.get('isRookie', False),
                                   'id': f"{p['name']}|{label}".replace(' ', '_')})
    print(f"  {len(full_pool)} prop pool entries built ({sum(1 for e in full_pool if e['isRookie'])} from new-to-the-dataset players)")

    # Defense-in-depth: this diagnostic already handles a missing xgboost install gracefully
    # internally, and now handles a single stat's own training error internally too (each
    # stat is independent -- one failing must never take the others down with it), but the
    # whole call is still wrapped here as a second layer. It must never be able to crash the
    # whole update for ANY reason -- everything below it (team stats, TEAM_DEFENSE/TEAM_OFFENSE,
    # the JSX injection, the git push) still needs to run either way.
    if not ENABLE_XGBOOST_DIAGNOSTIC:
        print("  XGBoost lean models: paused (ENABLE_XGBOOST_DIAGNOSTIC = False) -- skipping entirely")
        xgb_leans, xgb_meta = {}, {}
    else:
        try:
            xgb_leans, xgb_meta = build_xgboost_lean_models(baseline, current, full_pool, receivers, qbs, kickers, games_all)
        except Exception as e:
            print(f"  [!] XGBoost lean models raised an unexpected error ({e}) -- skipping this diagnostic, rest of the update continues")
            xgb_leans, xgb_meta = {}, {}

    attached_total = 0
    for stat_label, meta in xgb_meta.items():
        print(f"  [{stat_label}] XGBoost lean model: {meta['accuracy']}% real accuracy vs {meta['baseline']}% naive baseline")
        if meta['accuracy'] <= meta['baseline'] + 3:
            # only attach a stat's model if it genuinely, meaningfully beats a trivial
            # baseline FOR THAT STAT -- a model that doesn't clear this bar has no business
            # being shown as a signal, since "worse than always guessing the majority class"
            # is worse than useless, not just unhelpful. Each stat is judged on its own real
            # numbers, independent of how the others did.
            print(f"  [{stat_label}] does NOT meaningfully beat its naive baseline -- not attached to any entries. "
                  f"Kept as a measured, tracked result rather than shipped as a real signal.")
            continue
        leans = xgb_leans.get(stat_label, {})
        matched = 0
        for entry in full_pool:
            if entry['stat'] == stat_label and entry['kind'] == 'ladder' and entry['player'] in leans:
                entry['modelLean'] = leans[entry['player']]
                matched += 1
        print(f"  [{stat_label}] genuinely beats baseline -- attached to {matched} entries")
        attached_total += matched
    if xgb_meta:
        print(f"  XGBoost lean models: {attached_total} total ladder entries carry a model signal, "
              f"across {len(xgb_meta)} stat(s) evaluated")

    best = {}
    for e in full_pool:
        score = (e['p25']['testHit'] + e['p50']['testHit'] + e['p75']['testHit']) / 3
        e['_score'] = score
        k = e['player']
        if k not in best or e['_score'] > best[k]['_score']:
            best[k] = e
    deduped = list(best.values())
    ranked = sorted(deduped, key=lambda x: (-x['p50']['testHit'], -x['_score'], -x['testGames']))
    top10_list, pos_count = [], {}
    for e in ranked:
        if pos_count.get(e['pos'], 0) >= 3:
            continue
        top10_list.append(e)
        pos_count[e['pos']] = pos_count.get(e['pos'], 0) + 1
        if len(top10_list) == 10:
            break
    for e in top10_list:
        e.pop('_score', None)
    for e in full_pool:
        e.pop('_score', None)
    top10 = {'ladders': top10_list, 'poolSize': len(deduped), 'fullPoolSize': len(full_pool)}

    # ---- Team defense + offense profiles (Historical 2024-25 baseline + real Active/Current season) ----
    # Historical fields stay at the TOP LEVEL of team_defense exactly as before (so every
    # existing call site that reads e.g. TEAM_DEFENSE[team].scheme keeps working unchanged
    # and unchanged in meaning -- it was always the 2024-25 baseline). The new, real
    # current-season numbers are added as TEAM_DEFENSE[team].current, present only once
    # there's at least one real current-season game to compute it from.
    games_baseline = games_all[games_all.season.isin(BASELINE_SEASONS)]
    games_current_season = games_all[games_all.season == current_season] if current_season else games_all.iloc[0:0]

    team_defense_hist = compute_team_defense(games_baseline, baseline, pos_map, min_games=1)
    team_defense_cur = compute_team_defense(games_current_season, current, pos_map, min_games=1) if current_season and len(current) else {}
    team_defense = {}
    for team in set(team_defense_hist) | set(team_defense_cur):
        entry = dict(team_defense_hist.get(team, {}))
        entry['current'] = team_defense_cur.get(team)  # None until real current-season data exists for this team
        team_defense[team] = entry
    print(f"  {len(team_defense)} team defense profiles ({len(team_defense_cur)} with real current-season data)")

    team_offense_hist = compute_team_offense(games_baseline, baseline, pos_map, min_games=1)
    team_offense_cur = compute_team_offense(games_current_season, current, pos_map, min_games=1) if current_season and len(current) else {}
    team_offense = {}
    for team in set(team_offense_hist) | set(team_offense_cur):
        team_offense[team] = {'historical': team_offense_hist.get(team), 'current': team_offense_cur.get(team)}
    print(f"  {len(team_offense)} team offense TD-by-position profiles ({len(team_offense_cur)} with real current-season data)")

    # ---- Injuries + O-line starters ----
    print("\n[5/8] Fetching injury reports and depth charts...")
    # O-line starters use whichever season's depth chart is most recent (useful even in offseason —
    # rosters/depth charts get updated year-round). Injury designations only apply during an actual
    # in-progress season — surfacing last season's final-week report as "current" would be misleading.
    dc_season = current_season if current_season else max(BASELINE_SEASONS)
    _, dc_path = fetch_injuries_and_depthcharts(dc_season)
    ol_starters = build_ol_starters(dc_path)
    if current_season:
        inj_path, _ = fetch_injuries_and_depthcharts(current_season)
        injury_status = build_injury_status(inj_path)
    else:
        injury_status = {}

    # Historical injury reports across the full baseline window — separate from the
    # current-week status above, which only tells you who's out THIS week. This is what
    # makes the usage-bump analysis possible: real week-by-week "Out" designations across
    # two full seasons, not just a snapshot.
    historical_injury_frames = []
    for hist_season in BASELINE_SEASONS:
        hist_inj_p, _ = fetch_injuries_and_depthcharts(hist_season)
        if hist_inj_p:
            historical_injury_frames.append(pd.read_csv(hist_inj_p, low_memory=False))
    if current_season:
        cur_inj_p, _ = fetch_injuries_and_depthcharts(current_season)
        if cur_inj_p:
            historical_injury_frames.append(pd.read_csv(cur_inj_p, low_memory=False))
    historical_injuries = pd.concat(historical_injury_frames) if historical_injury_frames else pd.DataFrame()
    print(f"  Historical injury reports loaded: {len(historical_injuries)} rows across {len(historical_injury_frames)} season(s)")

    usage_bump = build_usage_bump_analysis(receivers, historical_injuries)
    print(f"  Usage-bump analysis: {len(usage_bump)} players with a real, repeated historical bump pattern")

    print(f"  {len(ol_starters)} teams' O-line starters loaded")
    print(f"  {len(injury_status)} players with a current injury designation" +
          ("" if injury_status else " (none — offseason, or no report yet this week)"))

    # ---- WNBA pipeline ----
    print("\n[5.5/8] Building WNBA data...")
    wnba_test_season = None
    for s in WNBA_CANDIDATE_TEST_SEASONS:
        if wnba_season_has_data(s):
            wnba_test_season = s
            print(f"  WNBA test season: {s} (in progress or complete)")
            break
    if wnba_test_season is None:
        print("  No current WNBA season data available yet.")
        wnba_players, wnba_pool, wnba_team_defense, wnba_upcoming, wnba_defense_profile = [], [], {}, {}, {}
    else:
        train_path = fetch_wnba_pbp(WNBA_TRAIN_SEASON)
        test_path = fetch_wnba_pbp(wnba_test_season)
        if train_path is None or test_path is None:
            print("  Could not fetch WNBA play-by-play files.")
            wnba_players, wnba_pool, wnba_team_defense, wnba_upcoming, wnba_defense_profile = [], [], {}, {}, {}
        else:
            wnba_train_df = build_wnba_box_scores(pd.read_parquet(train_path))
            wnba_test_df = build_wnba_box_scores(pd.read_parquet(test_path))
            wnba_gl_train = wnba_game_logs(wnba_train_df)
            wnba_gl_test = wnba_game_logs(wnba_test_df)
            wnba_team_names = build_wnba_team_names(wnba_test_df)
            wnba_players = build_wnba_players(wnba_gl_train, wnba_gl_test, wnba_team_names)
            wnba_pool = build_wnba_pool(wnba_gl_train, wnba_gl_test)
            wnba_team_defense = build_wnba_team_defense(wnba_test_df)
            wnba_upcoming = build_wnba_upcoming(wnba_test_season)
            wnba_defense_profile = build_wnba_defense_profile(wnba_test_df, wnba_team_names)
            print(f"  {len(wnba_players)} WNBA players, {len(wnba_pool)} prop pool entries, {len(wnba_team_defense)} team defense profiles, {len(wnba_upcoming)} teams with a scheduled next game, {len(wnba_defense_profile)} team 3PT-allowed profiles")

    nfl_upcoming = build_nfl_upcoming(games_all)
    print(f"  {len(nfl_upcoming)} NFL teams with a scheduled next game")

    # ---- Strong Picks: composite weekly ranking (replaces the old sort-by-one-number) ----
    print("\n[5.8/8] Scoring Strong Picks (reliability + coverage matchup + position matchup + XGBoost + form)...")
    try:
        strong_picks = build_strong_picks(full_pool, receivers, qbs, kickers, team_defense,
                                          nfl_upcoming, injury_status, top_n=5)
        print(f"  {strong_picks['scoredCount']} lines scored for Week {strong_picks['week']} "
              f"({strong_picks['excludedInjured']} excluded as Out/Doubtful)")
        for i, p in enumerate(strong_picks['picks'], 1):
            print(f"    {i}. {p['player']} ({p['pos']}) {p['stat']} P25 {p['p25']['line']:.0f} "
                  f"— score {p['pickScore']}" + (f" vs {p['opponent']}" if p.get('opponent') else ""))
            for reason in p['pickWhy']:
                print(f"         · {reason}")
    except Exception as e:
        print(f"  [!] Strong Picks scoring error: {e} — the widget falls back to hit-rate order, nothing else affected.")
        strong_picks = {'picks': [], 'week': None, 'scoredCount': 0,
                        'weights': STRONG_PICK_WEIGHTS, 'excludedInjured': 0}

    # ---- Quad Box: 3 P25 legs + 1 Anytime TD scorer ----
    print("\n[5.85/8] Building Quad Box cards (3 P25 legs + 1 Anytime TD)...")
    try:
        QUAD_LOG.clear()
        quad_box = build_quad_box(full_pool, atd_pool, receivers, qbs, redzone_tendencies,
                                  nfl_upcoming, injury_status, week=strong_picks.get('week'))
        for line in QUAD_LOG:
            print(line)
        print(f"  {len(quad_box['ladderCandidates'])} P25 legs and {len(quad_box['tdCandidates'])} "
              f"TD legs qualified; {len(quad_box['presets'])} preset cards built")
        for box in quad_box['presets']:
            legs = " + ".join(f"{l['player']} {l['stat']}"
                              + (f" {l['line']:.0f}" if l.get('line') else "") for l in box['legs'])
            odds = f"+{box['americanOdds']}" if (box['americanOdds'] or 0) > 0 else box['americanOdds']
            print(f"    [{box['name']}] {box['combinedProb']}% ({odds}) — {legs}")
        if quad_box['tdCandidates']:
            t = quad_box['tdCandidates'][0]
            print(f"    Top TD scorer: {t['player']} ({t['pos']}, score {t['score']}) — {t['why'][0]}")
    except Exception as e:
        print(f"  [!] Quad Box error: {e} — the generator ships empty and the UI says so, nothing else affected.")
        quad_box = {'presets': [], 'ladderCandidates': [], 'tdCandidates': [],
                    'week': None, 'tdWeights': QUAD_TD_WEIGHTS}

    # Accuracy ledger — backend-only tracking, never shown in the UI. See the function
    # docstrings above for how the snapshot/grade cycle works.
    accuracy_ledger = load_accuracy_ledger()
    accuracy_ledger = update_nfl_accuracy_ledger(accuracy_ledger, full_pool, nfl_upcoming, receivers, qbs, kickers)

    # ---- MLB pipeline ----
    print("\n[5.75/8] Building MLB data...")
    mlb_test_season = None
    for s in MLB_CANDIDATE_TEST_SEASONS:
        if mlb_season_has_data(s):
            mlb_test_season = s
            print(f"  MLB test season: {s} (in progress or complete)")
            break
    if mlb_test_season is None:
        print("  No current MLB season data available yet.")
        mlb_players, mlb_pool, mlb_team_defense, mlb_upcoming = [], [], {}, {}
    else:
        try:
            mlb_team_names = fetch_mlb_teams()
            mlb_players = build_mlb_players(MLB_TRAIN_SEASON, mlb_test_season, mlb_team_names)
            mlb_pool = build_mlb_pool(MLB_TRAIN_SEASON, mlb_test_season, mlb_team_names)
            mlb_team_defense = build_mlb_team_defense(mlb_test_season, mlb_team_names)
            mlb_upcoming = build_mlb_upcoming(mlb_test_season, mlb_team_names)
            print(f"  {len(mlb_players)} MLB players, {len(mlb_pool)} prop pool entries, {len(mlb_team_defense)} team defense profiles, {len(mlb_upcoming)} teams with a scheduled next game")
        except Exception as e:
            print(f"  MLB pipeline error: {e} — shipping with empty MLB data this run, everything else unaffected.")
            mlb_players, mlb_pool, mlb_team_defense, mlb_upcoming = [], [], {}, {}

    # ---- Real sportsbook lines (optional — only runs if odds_api_key.txt exists) ----
    ensure_gitignored()
    odds_key = load_odds_api_key()
    if odds_key:
        print("\n[5.9/8] Fetching real sportsbook lines (the-odds-api.com)...")
        try:
            nfl_names = list({p['name'] for p in receivers} | {p['name'] for p in qbs} | {p['name'] for p in kickers})
            nfl_odds = build_real_odds('nfl', odds_key, nfl_names, days_ahead=7)
            for entry in full_pool:
                key = (entry['player'], entry['stat'])
                if key in nfl_odds:
                    entry['realLines'] = nfl_odds[key]
            print(f"  NFL: matched real lines for {len(nfl_odds)} player/stat combos")

            # Game-script signal: real Vegas spread/total decomposed into each team's implied
            # score for their specific upcoming game. Different information than a player's
            # own season average — attached onto NFL_UPCOMING so the Matchup tab can show
            # whether the market expects an above/below-average offensive environment.
            nfl_events = fetch_odds_events('nfl', odds_key, days_ahead=7)
            nfl_game_lines = fetch_nfl_game_lines(nfl_events, odds_key)
            matched_teams = 0
            for team, info in nfl_upcoming.items():
                # nfl_upcoming is keyed by team abbreviation; game lines are keyed by full
                # team name from the odds API, so match through TEAM_NAMES_FULL if available
                full_name = NFL_TEAM_FULL_NAMES.get(team)
                if full_name and full_name in nfl_game_lines:
                    info['gameScript'] = nfl_game_lines[full_name]
                    matched_teams += 1
            print(f"  NFL: matched real game-script lines for {matched_teams} teams")

            # Real Anytime TD prices, attached onto the ATD pool built earlier
            atd_names = [p['player'] for p in atd_pool]
            atd_odds = fetch_nfl_atd_odds(nfl_events, odds_key, atd_names)
            for entry in atd_pool:
                if entry['player'] in atd_odds:
                    entry['realOdds'] = atd_odds[entry['player']]

            wnba_names = list({p['name'] for p in wnba_players})
            wnba_odds = build_real_odds('wnba', odds_key, wnba_names, days_ahead=7)
            for entry in wnba_pool:
                key = (entry['player'], entry['stat'])
                if key in wnba_odds:
                    entry['realLines'] = wnba_odds[key]
            print(f"  WNBA: matched real lines for {len(wnba_odds)} player/stat combos")

            mlb_names = list({p['name'] for p in mlb_players})
            mlb_odds = build_real_odds('mlb', odds_key, mlb_names, days_ahead=2)  # MLB has a daily slate — tighter window keeps credit usage sane
            for entry in mlb_pool:
                key = (entry['player'], entry['stat'])
                if key in mlb_odds:
                    entry['realLines'] = mlb_odds[key]
            print(f"  MLB: matched real lines for {len(mlb_odds)} player/stat combos")
            if ODDS_CREDITS_REMAINING is not None:
                print(f"  Credits remaining on your the-odds-api.com plan: {ODDS_CREDITS_REMAINING}")
        except Exception as e:
            print(f"  Real odds fetch error: {e} — continuing without real lines this run, everything else unaffected.")
    else:
        print("\n[5.9/8] No odds_api_key.txt found — skipping real sportsbook lines (manual entry still works fine).")

    # ---- College Football pipeline (optional — only runs if cfbd_api_key.txt exists) ----
    cfbd_key = load_cfbd_api_key()
    cfb_teams, cfb_ratings, cfb_home_field, cfb_upcoming, cfb_backtest = [], {}, CFB_HOME_FIELD_DEFAULT, [], {}
    if cfbd_key:
        print("\n[5.95/8] Building College Football data (collegefootballdata.com)...")
        try:
            cfb_team_names = fetch_cfb_teams(cfbd_key)
            train_games = fetch_cfb_games(CFB_TRAIN_SEASON, cfbd_key)
            current_year = datetime.date.today().year
            current_games = fetch_cfb_games(current_year, cfbd_key)
            train_lines = fetch_cfb_lines(CFB_TRAIN_SEASON, cfbd_key)
            with_scores = sum(1 for g in train_games if g['home_points'] is not None and g['away_points'] is not None)
            print(f"  {len(train_games)} games fetched for {CFB_TRAIN_SEASON}, {with_scores} have real final scores")

            # backtest: build ratings on train season, validate against real historical lines
            # from that SAME season (out-of-sample by game, not by season, since we only have
            # one full historical season of lines readily available on the free tier)
            split_idx = int(len(train_games) * 0.6)
            cfb_backtest = backtest_cfb_model(train_games[:split_idx], train_games[split_idx:], train_lines)

            # ratings for actual predictions blend train season + current season games so far
            all_games_for_ratings = train_games + [g for g in current_games if g['home_points'] is not None and g['away_points'] is not None]
            cfb_ratings, cfb_home_field = build_cfb_team_ratings(all_games_for_ratings, cfb_team_names)

            cfb_teams = [{'school': name, **cfb_ratings[name]} for name in cfb_ratings]
            cfb_teams.sort(key=lambda t: -t['powerRating'])

            cfb_upcoming = build_cfb_upcoming(current_games, cfb_ratings, cfb_home_field, {}, cfb_team_names)
            accuracy_ledger = update_cfb_accuracy_ledger(accuracy_ledger, current_games, cfb_upcoming)

            print(f"  {len(cfb_teams)} teams rated, {len(cfb_upcoming)} upcoming games with predictions")
            print(f"  Backtest (real historical lines, {CFB_TRAIN_SEASON} season): "
                  f"spread {cfb_backtest['spreadHitRate']}% (n={cfb_backtest['spreadSample']}), "
                  f"total {cfb_backtest['totalHitRate']}% (n={cfb_backtest['totalSample']}), "
                  f"moneyline {cfb_backtest['moneylineHitRate']}% (n={cfb_backtest['moneylineSample']})")
            print(f"  Empirical home-field advantage from real games: {cfb_home_field} pts")
        except Exception as e:
            print(f"  CFB pipeline error: {e} — shipping with empty CFB data this run, everything else unaffected.")
            cfb_teams, cfb_ratings, cfb_upcoming, cfb_backtest = [], {}, [], {}
    else:
        print("\n[5.95/8] No cfbd_api_key.txt found — skipping College Football (get a free key at collegefootballdata.com/key).")

    # ---- Prediction markets (Kalshi + Polymarket), fetched here instead of in the browser ----
    print("\n[5.97/8] Fetching prediction markets (Kalshi + Polymarket)...")
    try:
        market_live = build_market_live()
        for line in MARKET_LOG:
            print(line)
        fresh = [k for k in market_live if k.endswith('Stale') and market_live[k] is False]
        stale = [k.replace('Stale', '') for k in market_live if k.endswith('Stale') and market_live[k] is True]
        print(f"  {len(fresh)} feed(s) fetched fresh this run"
              + (f"; {len(stale)} served from cache ({', '.join(stale)})" if stale else ""))
    except Exception as e:
        print(f"  Market fetch error: {e} — shipping last cached market data, everything else unaffected.")
        cached = load_market_cache()
        market_live = {'generatedAt': cached.get('lastRun'), 'liveLeaderCount': 0,
                       'leaderSeriesCount': len(KALSHI_LEADER_SERIES)}
        for key, entry in (cached.get('sections') or {}).items():
            market_live[key] = entry.get('data')
            market_live[key + 'At'] = entry.get('fetchedAt')
            market_live[key + 'Stale'] = True

    # ---- 6. Assemble final data payload ----
    print("\n[6/8] Assembling data payload...")
    # NFL stays embedded (it's the default sport shown on load). WNBA/MLB are written as
    # separate files and fetched on demand — this is the actual fix for the mobile crash:
    # a phone loading the page only has to parse NFL's data, not all three sports at once.
    data_payload = {
        'RECEIVERS': receivers,
        'QBS': qbs,
        'KICKERS': kickers,
        'SACKS': sacks,
        'TEAM_DEFENSE': team_defense,
        'TEAM_OFFENSE': team_offense,
        'CURRENT_SEASON': current_season,  # real season the "Active/Current" (C) tag refers to; None if the upcoming season hasn't started producing real data yet
        'BASELINE_SEASONS': BASELINE_SEASONS,  # the two real seasons the "Historical" (H) tag refers to
        'LOCKS': top10,
        'FULL_POOL': full_pool,
        'OL_STARTERS': ol_starters,
        'INJURIES': injury_status,
        'NFL_UPCOMING': nfl_upcoming,
        'ATD_POOL': atd_pool,
        'REDZONE': redzone_tendencies,
        'USAGE_BUMP': usage_bump,
        'XGB_MODEL_INFO': xgb_meta,
        'MARKET_LIVE': market_live,  # Kalshi/Polymarket, now fetched here rather than in the browser
        'STRONG_PICKS': strong_picks,  # composite weekly ranking, scored server-side
        'QUAD_BOX': quad_box,          # generated 4-leg cards (3 P25 legs + 1 Anytime TD)
    }

    # Same composite Strong-Picks scoring for the other two sports, on the signals that are
    # genuinely available there (no coverage scheme data exists in either feed).
    try:
        wnba_strong = build_simple_strong_picks(wnba_pool, wnba_players, wnba_team_defense, wnba_upcoming, sport='wnba')
        print(f"  WNBA Strong Picks: {wnba_strong['scoredCount']} lines scored, top {len(wnba_strong['picks'])} selected")
    except Exception as e:
        print(f"  [!] WNBA Strong Picks error: {e} — widget falls back to hit-rate order there.")
        wnba_strong = {'picks': [], 'scoredCount': 0}
    try:
        mlb_strong = build_simple_strong_picks(mlb_pool, mlb_players, mlb_team_defense, mlb_upcoming, sport='mlb')
        print(f"  MLB Strong Picks: {mlb_strong['scoredCount']} lines scored, top {len(mlb_strong['picks'])} selected")
    except Exception as e:
        print(f"  [!] MLB Strong Picks error: {e} — widget falls back to hit-rate order there.")
        mlb_strong = {'picks': [], 'scoredCount': 0}

    wnba_bundle = {'players': wnba_players, 'pool': wnba_pool, 'teamDefense': wnba_team_defense, 'upcoming': wnba_upcoming, 'defenseProfile': wnba_defense_profile, 'strongPicks': wnba_strong}
    mlb_bundle = {'players': mlb_players, 'pool': mlb_pool, 'teamDefense': mlb_team_defense, 'upcoming': mlb_upcoming, 'strongPicks': mlb_strong}
    cfb_bundle = {'teams': cfb_teams, 'upcoming': cfb_upcoming, 'backtest': cfb_backtest, 'homeField': cfb_home_field}
    wnba_json_path = SCRIPT_DIR / "data-wnba.json"
    mlb_json_path = SCRIPT_DIR / "data-mlb.json"
    cfb_json_path = SCRIPT_DIR / "data-cfb.json"
    wnba_json_path.write_text(json.dumps(wnba_bundle), encoding='utf-8')
    mlb_json_path.write_text(json.dumps(mlb_bundle), encoding='utf-8')
    cfb_json_path.write_text(json.dumps(cfb_bundle), encoding='utf-8')
    print(f"  Wrote {wnba_json_path.name} ({wnba_json_path.stat().st_size/1024:.0f} KB), {mlb_json_path.name} ({mlb_json_path.stat().st_size/1024:.0f} KB), and {cfb_json_path.name} ({cfb_json_path.stat().st_size/1024:.0f} KB) — all fetched on demand, not embedded")

    # ---- 7. Inject into template ----
    print("\n[7/8] Injecting data into template...")
    if not TEMPLATE_PATH.exists():
        print(f"ERROR: {TEMPLATE_PATH} not found. Make sure dashboard_template.jsx is in this folder.")
        sys.exit(1)
    code = TEMPLATE_PATH.read_text(encoding='utf-8')
    for key, value in data_payload.items():
        placeholder = f"__{key}__"
        code = code.replace(placeholder, json.dumps(value))

    print("  Precompiling JSX (keeps the site lighter on mobile)...")
    precompiled = precompile_jsx(code)

    if precompiled is not None:
        print("  Precompiled successfully — shipping plain JS, no in-browser Babel needed.")
        body_scripts = (
            '<script src="https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js" crossorigin></script>\n'
            '<script src="https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js" crossorigin></script>\n'
            '</head>\n<body>\n<div id="root">\n'
            '  <div style="color:#8B8F98;font-family:sans-serif;padding:40px;text-align:center;">Loading dashboard…</div>\n'
            '</div>\n<script>\n' + precompiled + '\n</script>\n'
        )
    else:
        body_scripts = (
            '<script src="https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js" crossorigin></script>\n'
            '<script src="https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js" crossorigin></script>\n'
            '<script src="https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.5/babel.min.js" crossorigin></script>\n'
            '</head>\n<body>\n<div id="root">\n'
            '  <div style="color:#8B8F98;font-family:sans-serif;padding:40px;text-align:center;">Loading dashboard…</div>\n'
            '</div>\n<script type="text/babel" data-presets="react">\n' + code + '\n</script>\n'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
<meta http-equiv="Pragma" content="no-cache" />
<meta http-equiv="Expires" content="0" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Statum — Matchup Intelligence</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=JetBrains+Mono:wght@400;700&display=swap');
  html, body {{ margin: 0; padding: 0; background: #02120B; }}
  #root {{ min-height: 100vh; }}
</style>
{body_scripts}
</body>
</html>
"""
    OUTPUT_HTML.write_text(html, encoding='utf-8')
    print(f"  Wrote {OUTPUT_HTML} ({len(html)/1024/1024:.2f} MB)")

    # Save the accuracy ledger and print a quick summary — backend-only, this never reaches
    # the actual dashboard UI. Check accuracy_ledger.json directly, or ask me to read it
    # back to you, whenever you want to see how things are actually grading out.
    summary = save_accuracy_ledger(accuracy_ledger)
    if summary:
        print("\n[Accuracy Ledger] Current grading summary (backend-only, not shown in UI):")
        for key, s in sorted(summary.items()):
            print(f"    {key}: {s['hits']}/{s['graded']} hit ({s['rate']}%)")
    pending_count = len(accuracy_ledger.get('pending', []))
    print(f"    {pending_count} predictions still pending (waiting on real games to be played)")

    # ---- 7. Git commit + push ----
    print("\n[8/8] Committing and pushing to GitHub...")
    try:
        # Source files get pushed too now, not just the generated output — saves the
        # separate "also upload to GitHub" step. Only added if actually present, since
        # not every setup necessarily has all three.
        # market_cache.json rides along so the last good Kalshi/Polymarket values survive
        # between Actions runs — a transient API failure then costs you hours of freshness,
        # not a fall-back-to-a-months-old-constant.
        files_to_add = [f for f in ['index.html', 'data-wnba.json', 'data-mlb.json', 'data-cfb.json',
                                    'accuracy_ledger.json', 'market_cache.json']
                        if (SCRIPT_DIR / f).exists()]
        for source_file in ['update_dashboard.py', 'dashboard_template.jsx', 'guide.html', 'market_probe.py']:
            if (SCRIPT_DIR / source_file).exists():
                files_to_add.append(source_file)

        subprocess.run(['git', 'add'] + files_to_add, cwd=SCRIPT_DIR, check=True)
        msg = f"Auto-update: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}"
        commit_result = subprocess.run(['git', 'commit', '-m', msg], cwd=SCRIPT_DIR, capture_output=True, text=True)
        nothing_to_commit = 'nothing to commit' in (commit_result.stdout + commit_result.stderr)
        if nothing_to_commit:
            print("  No local changes to commit — data is identical to last run.")

        # Committing BEFORE pulling matters: it's what makes the auto-pull below actually
        # work. Pulling while there are still uncommitted changes makes git refuse the
        # merge entirely ("local changes would be overwritten") — which is a different,
        # unfixable-by-conflict-resolution problem than an actual merge conflict. Once
        # everything is committed locally first, pull becomes a normal merge between two
        # commits, and -X ours can then correctly prefer our freshly-generated files
        # wherever they conflict with whatever's on the remote.
        pull_result = subprocess.run(['git', 'pull', '--no-edit', '-X', 'ours'], cwd=SCRIPT_DIR, capture_output=True, text=True)
        if pull_result.returncode != 0:
            print(f"  [!] Auto-pull hit an issue: {pull_result.stderr.strip()[:300]}")
            print("  Falling back to: git fetch origin && git reset --hard origin/main, then re-save your files and run this again.")
        elif not nothing_to_commit or 'up to date' not in pull_result.stdout.lower():
            push_result = subprocess.run(['git', 'push'], cwd=SCRIPT_DIR, capture_output=True, text=True)
            if push_result.returncode == 0:
                print(f"  Pushed successfully! ({len(files_to_add)} files: {', '.join(files_to_add)})")
            else:
                print(f"  Push failed even after a clean pull: {push_result.stderr.strip()[:300]}")
    except subprocess.CalledProcessError as e:
        print(f"  Git error: {e}")
        print("  If this keeps happening: git fetch origin && git reset --hard origin/main, then re-save your files and run this again.")

    print("\nDone.")


if __name__ == "__main__":
    main()
