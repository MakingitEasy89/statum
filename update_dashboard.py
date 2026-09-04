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


def ensure_gitignored():
    """The odds API key must never reach the public repo. This makes that automatic
    rather than relying on remembering to edit .gitignore by hand."""
    entry = "odds_api_key.txt"
    if GITIGNORE_PATH.exists():
        content = GITIGNORE_PATH.read_text(encoding='utf-8')
        if entry in content:
            return
        GITIGNORE_PATH.write_text(content.rstrip('\n') + f'\n{entry}\n', encoding='utf-8')
    else:
        GITIGNORE_PATH.write_text(f'{entry}\n', encoding='utf-8')


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
    """Returns {(player_name, stat_label): {line, overPrice, underPrice, book}}"""
    market_map = ODDS_MARKET_MAP[sport]
    markets = list(market_map.values())
    reverse_map = {v: k for k, v in market_map.items()}
    events = fetch_odds_events(sport, api_key, days_ahead)
    out = {}
    for event in events[:8]:  # free-tier-safe default: 8 events x 6 markets x 1 region = 48 credits/sport,
                               # ~144 credits for a full run across all 3 sports — leaves room for several
                               # test runs within a 500/month free tier before hitting the ceiling. Widen
                               # this once you've upgraded and want fuller coverage — just ask.
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
                    if key in out:
                        continue  # first bookmaker found wins, keeps this simple
                    out[key] = {
                        'line': over.get('point'), 'overPrice': over.get('price'),
                        'underPrice': under.get('price') if under else None, 'book': bookmaker.get('title'),
                    }
        # bookmakers key present but no matching markets still counts against quota — nothing else to do here
    return out

TEMPLATE_PATH = SCRIPT_DIR / "dashboard_template.jsx"
OUTPUT_HTML = SCRIPT_DIR / "index.html"

BASELINE_SEASONS = [2024, 2025]   # the validated historical train/test backtest — never changes
CANDIDATE_CURRENT_SEASONS = [2026, 2027]  # script auto-detects whichever of these has real data

# Shrinkage constant for blending current-season-to-date with the historical baseline.
# weight_current = games_this_season / (games_this_season + SHRINKAGE_K)
# e.g. with K=4: 2 games in -> 33% current-season weight, 8 games in -> 67%, 16 games in -> 80%
SHRINKAGE_K = 4

NFLVERSE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"


# =====================================================================
# DOWNLOAD HELPERS
# =====================================================================
def download(url, dest_path):
    """Download url to dest_path if not already cached. Returns True on success."""
    if dest_path.exists():
        return True
    try:
        r = requests.get(url, timeout=180)
        if r.status_code != 200:
            return False
        dest_path.write_bytes(r.content)
        return True
    except requests.RequestException:
        return False


def season_has_data(season):
    """Quick check whether a season's play-by-play file exists on nflverse yet."""
    url = f"{NFLVERSE_BASE}/pbp/play_by_play_{season}.parquet"
    try:
        r = requests.head(url, timeout=30, allow_redirects=True)
        return r.status_code == 200
    except requests.RequestException:
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
    try:
        r = requests.head(f"{WNBA_BASE}/play_by_play_{season}.parquet", timeout=30, allow_redirects=True)
        if r.status_code != 200:
            return False
        test_path = CACHE_DIR / f"_wnba_probe_{season}.parquet"
        ok = download(f"{WNBA_BASE}/play_by_play_{season}.parquet", test_path)
        if not ok:
            return False
        df = pd.read_parquet(test_path, columns=['game_id'])
        return df['game_id'].nunique() >= 5
    except Exception:
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
        players.append({
            'name': player, 'team': team_name, 'overall': overall,
            'home': {'pts': round(home_g.pts.mean(), 1) if len(home_g) else None, 'games': int(len(home_g))},
            'away': {'pts': round(away_g.pts.mean(), 1) if len(away_g) else None, 'games': int(len(away_g))},
            'gamelog': test_g[['game_id', 'pts', 'reb', 'ast', 'stl', 'blk', 'fga', 'fgm', 'tpa', 'tpm', 'opp_team_name', 'game_date', 'is_home']].to_dict('records'),
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

    stat_map = [('pts', 'Points'), ('reb', 'Rebounds'), ('ast', 'Assists'), ('stl', 'Steals'), ('blk', 'Blocks'), ('tpm', 'Three-Pointers Made')]
    pool = []
    for player in gl_train.player.unique():
        train_g = gl_train[gl_train.player == player]
        test_g = gl_test[gl_test.player == player]
        if len(train_g) < 8 or len(test_g) < 6:
            continue
        for key, label in stat_map:
            l = ladder(train_g[key].values, test_g[key].values, label)
            if l:
                pool.append({'player': player, 'stat': label, 'kind': 'ladder', **l, 'id': f"{player}|{label}".replace(' ', '_')})
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

    pool = []
    hit_stat_map = [('hits','Hits'), ('hr','HR'), ('rbi','RBI'), ('runs','Runs'), ('tb','Total Bases')]
    pitch_stat_map = [('so','Strikeouts')]
    qualified_hit = fetch_mlb_qualified_players(train_season, 'hitting')
    qualified_pitch = fetch_mlb_qualified_players(train_season, 'pitching')

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
                pool.append({'player': p['name'], 'stat': label, 'kind': 'ladder', **l,
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
                pool.append({'player': p['name'], 'stat': label, 'kind': 'ladder', **l,
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
        status_map[row['full_name']] = {
            'status': row['report_status'],
            'injury': row.get('report_primary_injury'),
            'week': int(latest_week),
        }
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
    pbp_path = CACHE_DIR / f"pbp_{season}.parquet"
    part_path = CACHE_DIR / f"participation_{season}.parquet"
    if not pbp_path.exists() or not part_path.exists():
        return None
    pbp = pd.read_parquet(pbp_path)
    part = pd.read_parquet(part_path)
    pbp['play_id'] = pbp['play_id'].astype(float)
    part['play_id'] = part['play_id'].astype(float)
    merged = pbp.merge(part, left_on=['game_id', 'play_id'], right_on=['nflverse_game_id', 'play_id'],
                        how='left', suffixes=('', '_part'))
    merged['front'] = merged['defense_personnel'].apply(classify_front)
    merged['front_bucket'] = merged['front'].apply(bucket_front)
    merged['coverage'] = merged['defense_coverage_type'].fillna('Unknown')
    merged['is_home'] = merged['posteam'] == merged['home_team']
    gctx = games_all[games_all.season == season].set_index('game_id')[['weekday', 'gametime', 'location', 'roof', 'temp', 'wind']]
    merged = merged.join(gctx, on='game_id', rsuffix='_g')
    merged['primetime'] = merged.apply(primetime, axis=1)
    merged['weather'] = merged.apply(weather_bucket, axis=1)
    merged['season'] = season
    return merged


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
        team = latest_team_by_pid.get(pid, g['posteam'].mode().iloc[0])
        overall = agg_receiving(g)
        home = agg_receiving(g[g.is_home]) or {}
        away = agg_receiving(g[~g.is_home]) or {}
        fronts = {fb: agg_receiving(gg) for fb, gg in g.groupby('front_bucket')}
        covs = {cv: agg_receiving(gg) for cv, gg in g.groupby('coverage') if len(gg) >= 3}
        weathers = {w: agg_receiving(gg) for w, gg in g.groupby('weather')}
        td_plays = g[g.pass_touchdown == 1][['week', 'season', 'defteam', 'front', 'coverage', 'yards_gained']].to_dict('records')
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

        receivers.append({
            'id': pid, 'shortName': g['receiver_player_name'].iloc[0], 'name': name, 'pos': pos, 'team': team,
            'overall': overall, 'home': home, 'away': away, 'fronts': fronts, 'coverages': covs, 'weather': weathers,
            'tds': [{'week': int(t['week']), 'season': int(t['season']), 'opp': t['defteam'], 'front': t['front'],
                     'coverage': t['coverage'], 'yards': float(t['yards_gained'])} for t in td_plays],
            'gamelog': gl.to_dict('records'),
            'currentSeasonBlend': blend,
        })
    receivers.sort(key=lambda p: -p['overall']['targets'])
    print(f"  {len(receivers)} skill players")

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
        team = latest_team_by_pid.get(pid, g['posteam'].mode().iloc[0])
        overall = agg_qb(g)
        home = agg_qb(g[g.is_home]) or {}
        away = agg_qb(g[~g.is_home]) or {}
        fronts = {fb: agg_qb(gg) for fb, gg in g.groupby('front_bucket')}
        covs = {cv: agg_qb(gg) for cv, gg in g.groupby('coverage') if len(gg) >= 5}
        weathers = {w: agg_qb(gg) for w, gg in g.groupby('weather')}
        td_plays = g[g.pass_touchdown == 1][['week', 'season', 'defteam', 'front', 'coverage']].to_dict('records')
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

        qbs.append({
            'id': pid, 'shortName': g['passer_player_name'].iloc[0], 'name': name, 'pos': 'QB', 'team': team,
            'overall': overall, 'home': home, 'away': away, 'fronts': fronts, 'coverages': covs, 'weather': weathers,
            'tds': [{'week': int(t['week']), 'season': int(t['season']), 'opp': t['defteam'], 'front': t['front'], 'coverage': t['coverage']} for t in td_plays],
            'gamelog': gl.to_dict('records'),
            'currentSeasonBlend': blend,
        })
    qbs.sort(key=lambda p: -p['overall']['yards'])
    print(f"  {len(qbs)} QBs (with rushing merged in)")

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
        team = latest_team_by_pid.get(pid, g['posteam'].mode().iloc[0])
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

        kickers.append({
            'id': pid, 'shortName': g['kicker_player_name'].iloc[0], 'name': name, 'pos': 'K', 'team': team,
            'overall': overall, 'home': home, 'away': away, 'distance': dist, 'weather': weathers,
            'xpMade': xp_made, 'xpAtt': xp_att, 'gamelog': fg_gl.to_dict('records'),
            'currentSeasonBlend': blend,
        })
    kickers.sort(key=lambda p: -p['overall']['made'])
    print(f"  {len(kickers)} kickers")

    # ---- Sacks (defenders) ----
    sack_rows = []
    for _, r in baseline[baseline['sack'] == 1].iterrows():
        entries = []
        if pd.notna(r.get('sack_player_id')):
            entries.append((r['sack_player_id'], 1.0))
        if pd.notna(r.get('half_sack_1_player_id')):
            entries.append((r['half_sack_1_player_id'], 0.5))
        if pd.notna(r.get('half_sack_2_player_id')):
            entries.append((r['half_sack_2_player_id'], 0.5))
        for pid, val in entries:
            sack_rows.append({'pid': pid, 'val': val, 'week': r['week'], 'season': r['season'], 'posteam': r['posteam'],
                               'defteam': r['defteam'], 'is_home': r['defteam'] == r['home_team'], 'front': r['front'],
                               'coverage': r['coverage'], 'weather': r['weather'], 'qb': r.get('passer_player_name'),
                               'down': r.get('down'), 'ydsToGo': r.get('ydstogo'), 'game_id': r['game_id']})
    sdf = pd.DataFrame(sack_rows)
    sacks = []
    if len(sdf):
        for pid, g in sdf.groupby('pid'):
            total = g['val'].sum()
            if total < 1.5:
                continue
            name = roster_map.get(pid, pid)
            pos = pos_map.get(pid, '?')
            team = latest_team_by_pid.get(pid, g['defteam'].mode().iloc[0])
            home_sacks = g[g.is_home]['val'].sum()
            away_sacks = g[~g.is_home]['val'].sum()
            front_breakdown = g.groupby('front')['val'].sum().sort_values(ascending=False).to_dict()
            weather_breakdown = g.groupby('weather')['val'].sum().to_dict()
            plays = g[['week', 'season', 'posteam', 'front', 'coverage', 'qb', 'down', 'ydsToGo', 'val']].sort_values(['season', 'week']).to_dict('records')
            gl = g.groupby(['season', 'game_id'])['val'].sum().reset_index().rename(columns={'val': 'sacks'})
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
            })
        sacks.sort(key=lambda d: -d['totalSacks'])
    print(f"  {len(sacks)} pass rushers")

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

    full_pool = []
    for p in receivers:
        gl = p['gamelog']
        change = team_change_map.get(p['name'], {})
        for key, label, min25, min50 in [('catches', 'Receptions', 1, 2), ('yards', 'Receiving Yards', 10, 20), ('targets', 'Targets', 2, 3)]:
            train = np.array([x[key] for x in gl if x['season'] == BASELINE_SEASONS[0]], dtype=float)
            test = np.array([x[key] for x in gl if x['season'] == BASELINE_SEASONS[1]], dtype=float)
            ladder = pctile_ladder(train, test, min25, min50)
            if ladder:
                full_pool.append({'player': p['name'], 'pos': p['pos'], 'team': p['team'], 'stat': label, 'kind': 'ladder',
                                   **ladder, 'teamChanged': change.get('changed', False), 'team2024': change.get('team2024'),
                                   'team2025': change.get('team2025'), 'note': None, 'isRookie': False,
                                   'id': f"{p['name']}|{label}".replace(' ', '_')})
        # rushing props (workhorse RBs primarily, but also jet-sweep WRs with real volume)
        for key, label, min25, min50 in [('rush_att', 'Rush Attempts', 2, 4), ('rush_yards', 'Rush Yards', 10, 20)]:
            train = np.array([x.get(key, 0) for x in gl if x['season'] == BASELINE_SEASONS[0]], dtype=float)
            test = np.array([x.get(key, 0) for x in gl if x['season'] == BASELINE_SEASONS[1]], dtype=float)
            if len(train) == 0 or train.mean() < 1:
                continue
            ladder = pctile_ladder(train, test, min25, min50)
            if ladder:
                full_pool.append({'player': p['name'], 'pos': p['pos'], 'team': p['team'], 'stat': label, 'kind': 'ladder',
                                   **ladder, 'teamChanged': change.get('changed', False), 'team2024': change.get('team2024'),
                                   'team2025': change.get('team2025'), 'note': None, 'isRookie': False,
                                   'id': f"{p['name']}|{label}".replace(' ', '_')})
    for p in qbs:
        gl = p['gamelog']
        change = team_change_map.get(p['name'], {})
        for key, label, min25, min50 in [('yards', 'Passing Yards', 60, 120), ('completions', 'Completions', 6, 10),
                                          ('rush_yards', 'QB Rush Yards', 0, 5)]:
            train = np.array([x.get(key, 0) for x in gl if x['season'] == BASELINE_SEASONS[0]], dtype=float)
            test = np.array([x.get(key, 0) for x in gl if x['season'] == BASELINE_SEASONS[1]], dtype=float)
            if key == 'rush_yards' and train.mean() < 8:
                continue
            ladder = pctile_ladder(train, test, min25, min50)
            if ladder:
                full_pool.append({'player': p['name'], 'pos': 'QB', 'team': p['team'], 'stat': label, 'kind': 'ladder',
                                   **ladder, 'teamChanged': change.get('changed', False), 'team2024': change.get('team2024'),
                                   'team2025': change.get('team2025'), 'note': None, 'isRookie': False,
                                   'id': f"{p['name']}|{label}".replace(' ', '_')})
    for p in kickers:
        gl = p['gamelog']
        change = team_change_map.get(p['name'], {})
        for key, label, min25, min50 in [('made', 'FG Made', 1, 1), ('points', 'Kicking Points', 1, 3)]:
            train = np.array([x.get(key, 0) for x in gl if x['season'] == BASELINE_SEASONS[0]], dtype=float)
            test = np.array([x.get(key, 0) for x in gl if x['season'] == BASELINE_SEASONS[1]], dtype=float)
            ladder = pctile_ladder(train, test, min25, min50)
            if ladder:
                full_pool.append({'player': p['name'], 'pos': 'K', 'team': p['team'], 'stat': label, 'kind': 'ladder',
                                   **ladder, 'teamChanged': change.get('changed', False), 'team2024': change.get('team2024'),
                                   'team2025': change.get('team2025'), 'note': None, 'isRookie': False,
                                   'id': f"{p['name']}|{label}".replace(' ', '_')})
    print(f"  {len(full_pool)} prop pool entries built")

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

    # ---- Team defense profiles ----
    team_defense = {}
    games_baseline = games_all[games_all.season.isin(BASELINE_SEASONS)]
    pa_rows = []
    for _, g in games_baseline.iterrows():
        if pd.isna(g.home_score) or pd.isna(g.away_score):
            continue
        pa_rows.append({'team': g.home_team, 'allowed': g.away_score, 'scored': g.home_score})
        pa_rows.append({'team': g.away_team, 'allowed': g.home_score, 'scored': g.away_score})
    pa = pd.DataFrame(pa_rows)
    points_allowed = pa.groupby('team').agg(gamesPlayed=('allowed', 'count'), totalAllowed=('allowed', 'sum'), totalScored=('scored', 'sum')).reset_index()
    points_allowed['ppgAllowed'] = points_allowed['totalAllowed'] / points_allowed['gamesPlayed']
    points_allowed['ppgScored'] = points_allowed['totalScored'] / points_allowed['gamesPlayed']
    points_allowed['rank'] = points_allowed['ppgAllowed'].rank(ascending=False).astype(int)
    points_allowed['scoredRank'] = points_allowed['ppgScored'].rank(ascending=False).astype(int)
    points_allowed = points_allowed.set_index('team')

    targets_all = baseline[baseline['receiver_player_id'].notna()].copy()
    targets_all['recv_pos'] = targets_all['receiver_player_id'].map(pos_map).replace('FB', 'RB')
    targets_all = targets_all[targets_all['recv_pos'].isin(['WR', 'TE', 'RB'])]
    games_played_by_def = baseline.groupby('defteam')['game_id'].nunique()
    pos_allowed = targets_all.groupby(['defteam', 'recv_pos']).agg(
        targets=('week', 'count'), catches=('complete_pass', 'sum'), yards=('yards_gained', 'sum'),
        tds=('pass_touchdown', 'sum'), epaAllowed=('epa', 'sum')
    ).reset_index()
    pos_allowed = pos_allowed.join(games_played_by_def.rename('gp'), on='defteam')
    pos_allowed['ypg'] = pos_allowed['yards'] / pos_allowed['gp']
    pos_allowed['epaPerTgt'] = pos_allowed['epaAllowed'] / pos_allowed['targets']
    pos_allowed['rank'] = pos_allowed.groupby('recv_pos')['ypg'].rank(ascending=False).astype(int)

    def_plays = baseline[baseline['defteam'].notna() & (baseline['pass'] == 1)]
    for team, g in def_plays.groupby('defteam'):
        front_counts = g['front_bucket'].value_counts(normalize=True) * 100
        cov_counts = g['coverage'].value_counts(normalize=True) * 100
        top_front_bucket = front_counts.idxmax()
        sub = g[g['front_bucket'] == top_front_bucket]
        top_front_exact = sub['front'].value_counts().idxmax() if len(sub) else None
        top_cov = cov_counts.idxmax()
        pa_row = points_allowed.loc[team] if team in points_allowed.index else None
        pos_rows = pos_allowed[pos_allowed.defteam == team]
        pos_by_group = {r['recv_pos']: {'ypg': round(r['ypg'], 1), 'rank': int(r['rank']), 'tds': int(r['tds']),
                                          'targets': int(r['targets']), 'catches': int(r['catches']),
                                          'epaPerTgt': round(r['epaPerTgt'], 3)} for _, r in pos_rows.iterrows()}
        weakest = max(pos_by_group.items(), key=lambda kv: -kv[1]['rank']) if pos_by_group else None
        team_defense[team] = {
            'pointsAllowedPerGame': round(float(pa_row['ppgAllowed']), 1) if pa_row is not None else None,
            'pointsAllowedRank': int(pa_row['rank']) if pa_row is not None else None,
            'pointsScoredPerGame': round(float(pa_row['ppgScored']), 1) if pa_row is not None else None,
            'pointsScoredRank': int(pa_row['scoredRank']) if pa_row is not None else None,
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
    print(f"  {len(team_defense)} team defense profiles")

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
        wnba_players, wnba_pool, wnba_team_defense, wnba_upcoming = [], [], {}, {}
    else:
        train_path = fetch_wnba_pbp(WNBA_TRAIN_SEASON)
        test_path = fetch_wnba_pbp(wnba_test_season)
        if train_path is None or test_path is None:
            print("  Could not fetch WNBA play-by-play files.")
            wnba_players, wnba_pool, wnba_team_defense, wnba_upcoming = [], [], {}, {}
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
            print(f"  {len(wnba_players)} WNBA players, {len(wnba_pool)} prop pool entries, {len(wnba_team_defense)} team defense profiles, {len(wnba_upcoming)} teams with a scheduled next game")

    nfl_upcoming = build_nfl_upcoming(games_all)
    print(f"  {len(nfl_upcoming)} NFL teams with a scheduled next game")

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
                    entry['realLine'] = nfl_odds[key]
            print(f"  NFL: matched real lines for {len(nfl_odds)} player/stat combos")

            wnba_names = list({p['name'] for p in wnba_players})
            wnba_odds = build_real_odds('wnba', odds_key, wnba_names, days_ahead=7)
            for entry in wnba_pool:
                key = (entry['player'], entry['stat'])
                if key in wnba_odds:
                    entry['realLine'] = wnba_odds[key]
            print(f"  WNBA: matched real lines for {len(wnba_odds)} player/stat combos")

            mlb_names = list({p['name'] for p in mlb_players})
            mlb_odds = build_real_odds('mlb', odds_key, mlb_names, days_ahead=2)  # MLB has a daily slate — tighter window keeps credit usage sane
            for entry in mlb_pool:
                key = (entry['player'], entry['stat'])
                if key in mlb_odds:
                    entry['realLine'] = mlb_odds[key]
            print(f"  MLB: matched real lines for {len(mlb_odds)} player/stat combos")
            if ODDS_CREDITS_REMAINING is not None:
                print(f"  Credits remaining on your the-odds-api.com plan: {ODDS_CREDITS_REMAINING}")
        except Exception as e:
            print(f"  Real odds fetch error: {e} — continuing without real lines this run, everything else unaffected.")
    else:
        print("\n[5.9/8] No odds_api_key.txt found — skipping real sportsbook lines (manual entry still works fine).")

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
        'LOCKS': top10,
        'FULL_POOL': full_pool,
        'OL_STARTERS': ol_starters,
        'INJURIES': injury_status,
        'NFL_UPCOMING': nfl_upcoming,
    }

    wnba_bundle = {'players': wnba_players, 'pool': wnba_pool, 'teamDefense': wnba_team_defense, 'upcoming': wnba_upcoming}
    mlb_bundle = {'players': mlb_players, 'pool': mlb_pool, 'teamDefense': mlb_team_defense, 'upcoming': mlb_upcoming}
    wnba_json_path = SCRIPT_DIR / "data-wnba.json"
    mlb_json_path = SCRIPT_DIR / "data-mlb.json"
    wnba_json_path.write_text(json.dumps(wnba_bundle), encoding='utf-8')
    mlb_json_path.write_text(json.dumps(mlb_bundle), encoding='utf-8')
    print(f"  Wrote {wnba_json_path.name} ({wnba_json_path.stat().st_size/1024:.0f} KB) and {mlb_json_path.name} ({mlb_json_path.stat().st_size/1024:.0f} KB) — fetched on demand, not embedded")

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

    # ---- 7. Git commit + push ----
    print("\n[8/8] Committing and pushing to GitHub...")
    try:
        subprocess.run(['git', 'add', 'index.html', 'data-wnba.json', 'data-mlb.json'], cwd=SCRIPT_DIR, check=True)
        msg = f"Auto-update: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}"
        result = subprocess.run(['git', 'commit', '-m', msg], cwd=SCRIPT_DIR, capture_output=True, text=True)
        if 'nothing to commit' in (result.stdout + result.stderr):
            print("  No changes to commit — data is identical to last run.")
        else:
            subprocess.run(['git', 'push'], cwd=SCRIPT_DIR, check=True)
            print("  Pushed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"  Git error: {e}")
        print("  You may need to push manually: git add index.html data-wnba.json data-mlb.json && git commit -m 'update' && git push")

    print("\nDone.")


if __name__ == "__main__":
    main()
