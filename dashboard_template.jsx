
const { useState, useMemo, useEffect, useRef } = React;

// ---------------------------------------------------------------
// Real NFL data (nflverse play-by-play + NGS participation), 2024-2025
// Offense: WR/TE/RB (8+ tgt/season equiv), QB (40+ att), K (15+ FGA)
// Defense: any player with 1.5+ sacks across the 2-year window
// Market: live Kalshi snapshot (CFTC-regulated exchange)
// Locks: 10-per-tier prop floors, 1.5 std dev below 2yr mean
// ---------------------------------------------------------------
const RECEIVERS = __RECEIVERS__;
const NFL_UPCOMING = __NFL_UPCOMING__;

// WNBA and MLB data are NOT embedded here — they're fetched on demand the first time
// you switch to that sport, instead of every visitor's browser having to load and parse
// all three sports' data just to see the page. This is the fix for the mobile crash.
let SportDataCache = { wnba: null, mlb: null };
function wnbaPlayers() { return SportDataCache.wnba?.players || []; }
function wnbaPool() { return SportDataCache.wnba?.pool || []; }
function wnbaTeamDefense() { return SportDataCache.wnba?.teamDefense || {}; }
function wnbaUpcoming() { return SportDataCache.wnba?.upcoming || {}; }
function mlbPlayers() { return SportDataCache.mlb?.players || []; }
function mlbPool() { return SportDataCache.mlb?.pool || []; }
function mlbTeamDefense() { return SportDataCache.mlb?.teamDefense || {}; }
function mlbUpcoming() { return SportDataCache.mlb?.upcoming || {}; }

const QBS = __QBS__;
const KICKERS = __KICKERS__;
const SACKS = __SACKS__;
const MARKET_PULSE = {"fetchedAt": "2026-07-26", "leaders": [{"category": "Receiving Yards Leader", "totalMarkets": 26, "volume": 8192, "options": [{"name": "A.J. Brown", "pct": 20}, {"name": "Puka Nacua", "pct": 9}, {"name": "CeeDee Lamb", "pct": 6}]}, {"category": "Rushing Yards Leader", "totalMarkets": 25, "volume": 8877, "options": [{"name": "Derrick Henry", "pct": 12}, {"name": "Bijan Robinson", "pct": 10}, {"name": "Saquon Barkley", "pct": 10}]}, {"category": "Passing Yards Leader", "totalMarkets": 28, "volume": 7547, "options": [{"name": "Joe Burrow", "pct": 12}, {"name": "Jared Goff", "pct": 9}, {"name": "Trevor Lawrence", "pct": 5}]}, {"category": "Sacks Leader", "totalMarkets": 21, "volume": 8248, "options": [{"name": "Myles Garrett", "pct": 24}, {"name": "Aidan Hutchinson", "pct": 10}, {"name": "Will Anderson Jr.", "pct": 10}]}, {"category": "Interceptions Leader", "totalMarkets": 24, "volume": 1666, "options": [{"name": "Derek Stingley Jr.", "pct": 6}, {"name": "Jessie Bates III", "pct": 3}, {"name": "Deommodore Lenoir", "pct": 2}]}], "playerThresholds": [{"title": "75+ Receptions This Season", "totalMarkets": 79, "volume": 1884, "options": [{"name": "Wan'Dale Robinson", "pct": 55}, {"name": "Terry McLaurin", "pct": 52}, {"name": "Emeka Egbuka", "pct": 40}]}, {"title": "Aaron Donald to Play a Game This Season", "totalMarkets": 1, "volume": 206778, "options": [{"name": "Yes", "pct": 70}, {"name": "No", "pct": 30}]}], "winTotals": [{"team": "MIN", "options": [{"line": "9+ wins", "pct": 55}, {"line": "10+ wins", "pct": 43}, {"line": "8+ wins", "pct": 66}]}, {"team": "LA", "options": [{"line": "12+ wins", "pct": 54}, {"line": "13+ wins", "pct": 40}, {"line": "11+ wins", "pct": 66}]}, {"team": "SEA", "options": [{"line": "11+ wins", "pct": 52}, {"line": "12+ wins", "pct": 44}, {"line": "10+ wins", "pct": 63}]}, {"team": "DAL", "options": [{"line": "10+ wins", "pct": 52}, {"line": "11+ wins", "pct": 38}, {"line": "9+ wins", "pct": 63}]}, {"team": "DEN", "options": [{"line": "10+ wins", "pct": 56}, {"line": "11+ wins", "pct": 41}, {"line": "9+ wins", "pct": 67}]}, {"team": "CHI", "options": [{"line": "10+ wins", "pct": 50}, {"line": "9+ wins", "pct": 59}, {"line": "11+ wins", "pct": 36}]}, {"team": "NE", "options": [{"line": "11+ wins", "pct": 43}, {"line": "10+ wins", "pct": 53}, {"line": "12+ wins", "pct": 35}]}, {"team": "PHI", "options": [{"line": "10+ wins", "pct": 57}, {"line": "11+ wins", "pct": 45}, {"line": "12+ wins", "pct": 31}]}, {"team": "KC", "options": [{"line": "10+ wins", "pct": 54}, {"line": "11+ wins", "pct": 43}, {"line": "12+ wins", "pct": 30}]}, {"team": "BAL", "options": [{"line": "11+ wins", "pct": 59}, {"line": "12+ wins", "pct": 40}, {"line": "10+ wins", "pct": 68}]}, {"team": "SF", "options": [{"line": "11+ wins", "pct": 41}, {"line": "10+ wins", "pct": 56}, {"line": "12+ wins", "pct": 28}]}, {"team": "CIN", "options": [{"line": "11+ wins", "pct": 43}, {"line": "10+ wins", "pct": 58}, {"line": "9+ wins", "pct": 62}]}, {"team": "HOU", "options": [{"line": "10+ wins", "pct": 54}, {"line": "11+ wins", "pct": 37}, {"line": "9+ wins", "pct": 66}]}, {"team": "NYG", "options": [{"line": "8+ wins", "pct": 52}, {"line": "9+ wins", "pct": 40}, {"line": "7+ wins", "pct": 61}]}, {"team": "WAS", "options": [{"line": "8+ wins", "pct": 56}, {"line": "9+ wins", "pct": 38}, {"line": "7+ wins", "pct": 68}]}, {"team": "MIA", "options": [{"line": "5+ wins", "pct": 39}, {"line": "4+ wins", "pct": 65}, {"line": "6+ wins", "pct": 32}]}, {"team": "LV", "options": [{"line": "7+ wins", "pct": 48}, {"line": "6+ wins", "pct": 61}, {"line": "8+ wins", "pct": 43}]}, {"team": "NO", "options": [{"line": "9+ wins", "pct": 44}, {"line": "8+ wins", "pct": 55}, {"line": "10+ wins", "pct": 36}]}, {"team": "TEN", "options": [{"line": "7+ wins", "pct": 45}, {"line": "6+ wins", "pct": 61}, {"line": "8+ wins", "pct": 36}]}, {"team": "NYJ", "options": [{"line": "6+ wins", "pct": 46}, {"line": "5+ wins", "pct": 59}, {"line": "7+ wins", "pct": 34}]}, {"team": "CAR", "options": [{"line": "8+ wins", "pct": 45}, {"line": "7+ wins", "pct": 59}, {"line": "9+ wins", "pct": 36}]}, {"team": "CLE", "options": [{"line": "6+ wins", "pct": 50}, {"line": "7+ wins", "pct": 37}, {"line": "5+ wins", "pct": 64}]}, {"team": "ARI", "options": [{"line": "5+ wins", "pct": 42}, {"line": "4+ wins", "pct": 60}, {"line": "6+ wins", "pct": 30}]}], "transactions": [{"title": "Tyreek Hill's Next Team", "options": [{"name": "Kansas City", "pct": 40}, {"name": "Chicago", "pct": 8}, {"name": "Stays with Miami or Retires", "pct": 5}]}, {"title": "Stefon Diggs's Next Team", "options": [{"name": "Washington", "pct": 42}, {"name": "Baltimore", "pct": 12}, {"name": "Stays with New England or Retires", "pct": 10}]}, {"title": "Aaron Rodgers's Next Team", "options": [{"name": "Pittsburgh", "pct": 97}, {"name": "Retires / No Team", "pct": 9}, {"name": "Arizona", "pct": 1}]}, {"title": "Maxx Crosby's Next Team", "options": [{"name": "Stays with Las Vegas or Retires", "pct": 72}, {"name": "Cleveland", "pct": 2}, {"name": "Philadelphia", "pct": 1}]}]};
const TOP10 = __LOCKS__;
const FULL_POOL = __FULL_POOL__;


const TEAM_NAMES = {
  LAC:"Chargers",BAL:"Ravens",CAR:"Panthers",PIT:"Steelers",CLE:"Browns",DEN:"Broncos",NO:"Saints",
  MIA:"Dolphins",LA:"Rams",KC:"Chiefs",TEN:"Titans",CIN:"Bengals",GB:"Packers",MIN:"Vikings",NYJ:"Jets",
  HOU:"Texans",DAL:"Cowboys",JAX:"Jaguars",TB:"Buccaneers",SEA:"Seahawks",ATL:"Falcons",BUF:"Bills",
  IND:"Colts",NE:"Patriots",SF:"49ers",ARI:"Cardinals",DET:"Lions",PHI:"Eagles",WAS:"Commanders",
  NYG:"Giants",CHI:"Bears",LV:"Raiders"
};
const TEAMS = Object.keys(TEAM_NAMES).sort();

const COVERAGE_LABEL = {
  COVER_0:"Cover 0", COVER_1:"Cover 1", COVER_2:"Cover 2", COVER_3:"Cover 3", COVER_4:"Cover 4",
  COVER_6:"Cover 6", COVER_9:"Cover 9", "2_MAN":"2-Man", COMBO:"Combo", BLOWN:"Blown Coverage", Unknown:"Unlabeled"
};

const ACCENT = { teal:"#00E5FF", amber:"#FFB800", violet:"#C77DFF", rose:"#FF3D71", green:"#00E676" };
// P25/P50/P75 get their own dedicated palette — cyan / gold / magenta — instead of borrowing
// the generic green/teal/amber trio. Gold ties directly to the Statum brand; cyan and magenta
// give it real sci-fi contrast rather than a "traffic light" feel.
const TRANCHE_COLOR = { p25: "#00D9FF", p50: "#F0C674", p75: "#E838D4" };
const THEME = { primary:"#00E676", secondary:"#00C853", tertiary:"#B4FF39", quaternary:"#00E5C0" };

function fmt(n, d = 1) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Number(n).toFixed(d);
}

// ---------- ambient breathing background ----------
// Daily ambient theme — same look all day (stable, not jittery), rotates at midnight.
// Purely mood/atmosphere; functional colors (P25/P50/P75, badges, etc.) never change.
// Elegant jewel-tone palette family, each with a deeper "night" variant and a brighter,
// slightly lighter "day" variant of the same hue family — not a full light-mode flip
// (text/card colors stay dark-UI), just the ambient mood shifting with actual local time.
// Fixed Statum identity — true black at night, a lighter charcoal grey by day, gold accents
// throughout either way. Defaults to actual local time, but can be manually overridden.
const STATUM_THEME = {
  name: "Statum Gold", soft: false,
  night: { bg: "#080807", c1: "#D4A94A", c2: "#B8863A", c3: "#F0C674", c4: "#C9963F" },
  day:   { bg: "#FAF6EE", c1: "#B8860B", c2: "#96690D", c3: "#C9973D", c4: "#A67C1E" },
};

function getDailyTheme(override) {
  const hour = new Date().getHours();
  const autoIsDay = hour >= 6 && hour < 18;
  const isDay = override === null || override === undefined ? autoIsDay : override === "day";
  const variant = isDay ? STATUM_THEME.day : STATUM_THEME.night;
  return { name: STATUM_THEME.name, soft: STATUM_THEME.soft, isDay, ...variant };
}

// Gear + connected-nodes icon (matches the uploaded reference art), used as the toggle
// control for explanatory text throughout the app — click to reveal, click again to hide.
function GearNodeIcon({ size = 20, open }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" style={{ flexShrink: 0, transition: "transform 0.2s ease", transform: open ? "rotate(20deg)" : "rotate(0deg)" }}>
      <path d="M24 4 L27 4 L28 9 L32.5 10.5 L36.5 7.5 L39 10 L39 13.5 L36 16.5 L37.5 21 L43 22 L43 26 L37.5 27 L36 31.5 L39 34.5 L39 38 L36.5 40.5 L32.5 37.5 L28 39 L27 44 L21 44 L20 39 L15.5 37.5 L11.5 40.5 L9 38 L9 34.5 L12 31.5 L10.5 27 L5 26 L5 22 L10.5 21 L12 16.5 L9 13.5 L9 10 L11.5 7.5 L15.5 10.5 L20 9 L21 4 Z"
        fill="none" stroke={open ? "#F0C674" : "var(--text-secondary-a)"} strokeWidth="1.6" strokeLinejoin="round" />
      <circle cx="24" cy="18" r="3.4" fill="none" stroke={open ? "#F0C674" : "var(--text-secondary-a)"} strokeWidth="1.6" />
      <circle cx="17" cy="30" r="2.4" fill="none" stroke={open ? "#F0C674" : "var(--text-secondary-a)"} strokeWidth="1.6" />
      <circle cx="31" cy="30" r="2.4" fill="none" stroke={open ? "#F0C674" : "var(--text-secondary-a)"} strokeWidth="1.6" />
      <path d="M24 21.4 L24 25 M24 25 L17 25 L17 27.6 M24 25 L31 25 L31 27.6" fill="none" stroke={open ? "#F0C674" : "var(--text-secondary-a)"} strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

// Wraps any explanation block in a click-to-reveal toggle so the page defaults to lean,
// with the "why"/"how this works" text available on demand instead of always taking up space.
function InfoToggle({ label = "How this works", children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{ marginBottom: open ? 14 : 10 }}>
      <button onClick={()=>setOpen(o=>!o)} className="bubble-btn" style={{
        display: "inline-flex", alignItems: "center", gap: 7, padding: "6px 12px", borderRadius: 999,
        border: `1px solid ${open ? "#F0C67455" : "var(--overlay-6)"}`, cursor: "pointer",
        background: open ? "rgba(240,198,116,0.08)" : "var(--overlay-1)",
        color: open ? "#F0C674" : "var(--text-secondary-a)", fontSize: 11.5, fontWeight: 700
      }}>
        <GearNodeIcon size={16} open={open} /> {label}
      </button>
      {open && <div className="fade-in" style={{ marginTop: 8 }}>{children}</div>}
    </div>
  );
}

function Logo({ theme, size = 34 }) {
  return (
    <a href="./guide.html" title="Guide & Risk Info" style={{ display: "inline-flex", alignItems: "center", gap: 10, textDecoration: "none" }}>
      <svg width={size} height={size} viewBox="0 0 48 48" style={{ flexShrink: 0 }}>
        <defs>
          <linearGradient id="logoGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={theme.c1} />
            <stop offset="55%" stopColor={theme.c3} />
            <stop offset="100%" stopColor={theme.c4} />
          </linearGradient>
        </defs>
        <polygon points="24,2 44,13 44,35 24,46 4,35 4,13" fill="none" stroke="url(#logoGrad)" strokeWidth="2" opacity="0.55" />
        <path d="M 14 32 L 14 24 L 22 24 L 22 14" fill="none" stroke="url(#logoGrad)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M 34 32 L 34 20 L 26 20 L 26 14" fill="none" stroke="url(#logoGrad)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" opacity="0.6" />
        <circle cx="24" cy="14" r="3.2" fill={theme.c1} />
        <circle cx="14" cy="32" r="2.2" fill={theme.c3} />
        <circle cx="34" cy="32" r="2.2" fill={theme.c4} />
      </svg>
    </a>
  );
}

function Starfield({ count = 70 }) {
  const stars = useMemo(() => Array.from({ length: count }, () => ({
    x: Math.random() * 100, y: Math.random() * 100,
    r: Math.random() * 1.2 + 0.4, delay: Math.random() * 6, dur: 3 + Math.random() * 4,
    opacity: 0.25 + Math.random() * 0.5,
  })), [count]);
  return (
    <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} preserveAspectRatio="none" aria-hidden>
      {stars.map((s, i) => (
        <circle key={i} cx={`${s.x}%`} cy={`${s.y}%`} r={s.r} fill="var(--star-color)" opacity={s.opacity}>
          <animate attributeName="opacity" values={`${s.opacity};${s.opacity*0.15};${s.opacity}`} dur={`${s.dur}s`} begin={`${s.delay}s`} repeatCount="indefinite" />
        </circle>
      ))}
    </svg>
  );
}

function AmbientBackground({ theme }) {
  return (
    <div aria-hidden style={{ position: "fixed", inset: 0, zIndex: 0, overflow: "hidden", background: theme.bg }}>
      <div className="sweep" />
      <div className="blob blob-a" />
      <div className="blob blob-b" />
      <div className="blob blob-c" />
      <div className="blob blob-d" />
      <Starfield />
      <div style={{
        position: "absolute", inset: 0,
        backgroundImage: "radial-gradient(circle at 1px 1px, var(--overlay-3) 1px, transparent 0)",
        backgroundSize: "26px 26px"
      }} />
      <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at center, transparent 0%, ${theme.bg}8C 75%)` }} />
      <style>{`
        .blob { position:absolute; border-radius:50%; filter: blur(110px); }
        .blob-a { width:640px; height:640px; top:-200px; left:-160px; background:radial-gradient(circle,var(--theme-c1),transparent 70%); opacity:${theme.soft?0.35:0.5}; animation: float1 20s ease-in-out infinite; }
        .blob-b { width:560px; height:560px; bottom:-180px; right:-140px; background:radial-gradient(circle,var(--theme-c2),transparent 70%); opacity:${theme.soft?0.3:0.45}; animation: float2 24s ease-in-out infinite; }
        .blob-c { width:480px; height:480px; top:35%; left:55%; background:radial-gradient(circle,var(--theme-c3),transparent 70%); opacity:${theme.soft?0.22:0.32}; animation: float3 28s ease-in-out infinite; }
        .blob-d { width:420px; height:420px; top:5%; right:15%; background:radial-gradient(circle,var(--theme-c4),transparent 70%); opacity:${theme.soft?0.24:0.35}; animation: float2 32s ease-in-out infinite reverse; }
        .sweep { position:absolute; inset:-50%; background: conic-gradient(from 0deg, transparent 0deg, color-mix(in srgb, var(--theme-c1) 8%, transparent) 90deg, transparent 180deg, color-mix(in srgb, var(--theme-c4) 8%, transparent) 270deg, transparent 360deg); animation: spin ${theme.soft?55:40}s linear infinite; }
        @keyframes float1 { 0%,100%{ transform: translate(0,0) scale(1);} 50%{ transform: translate(70px,50px) scale(1.1);} }
        @keyframes float2 { 0%,100%{ transform: translate(0,0) scale(1);} 50%{ transform: translate(-60px,-40px) scale(1.06);} }
        @keyframes float3 { 0%,100%{ transform: translate(-50%,-50%) scale(1);} 50%{ transform: translate(-45%,-58%) scale(1.15);} }
        @keyframes spin { from { transform: rotate(0deg);} to { transform: rotate(360deg);} }
      `}</style>
    </div>
  );
}

// ---------- count-up number ----------
function CountUp({ value, decimals = 0, suffix = "" }) {
  const [display, setDisplay] = useState(0);
  const ref = useRef(null);
  useEffect(() => {
    if (value === null || value === undefined || Number.isNaN(value)) return;
    const start = performance.now();
    const dur = 650;
    function tick(now) {
      const t = Math.min(1, (now - start) / dur);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(value * eased);
      if (t < 1) ref.current = requestAnimationFrame(tick);
    }
    ref.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(ref.current);
  }, [value]);
  if (value === null || value === undefined || Number.isNaN(value)) return <>—</>;
  return <>{display.toFixed(decimals)}{suffix}</>;
}

function Glass({ children, style, hover = true, onClick }) {
  return <div onClick={onClick} className={hover ? "glass glass-hover gas-halo" : "glass"} style={style}>{children}</div>;
}

function GlobalStyle() {
  return (
    <style>{`
      * { box-sizing: border-box; }
      .gas-halo { position: relative; }
      .gas-halo::before {
        content: ""; position: absolute; inset: -10px; z-index: -1; border-radius: 12px;
        background: radial-gradient(ellipse at 30% 20%, color-mix(in srgb, var(--theme-c1) 14%, transparent), transparent 60%),
                    radial-gradient(ellipse at 75% 80%, color-mix(in srgb, var(--theme-c4) 10%, transparent), transparent 65%);
        filter: blur(14px); opacity: 0.6;
        animation: gasShimmer 9s ease-in-out infinite;
        pointer-events: none;
      }
      @keyframes gasShimmer { 0%,100% { opacity: 0.45;} 50% { opacity: 0.65;} }
      .glass {
        background: var(--card-bg); backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
        border: 1px solid var(--overlay-6); border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease, background 0.2s ease;
      }
      .glass-hover:hover {
        transform: translateY(-1px); border-color: color-mix(in srgb, var(--theme-c1) 32%, transparent);
        box-shadow: 0 10px 24px -10px rgba(0,0,0,0.4), 0 0 0 1px var(--overlay-3);
        background: var(--card-hover-bg); cursor: pointer;
      }
      .fade-in { animation: fadeIn 0.35s ease-out both; }
      @keyframes fadeIn { from { opacity:0; transform: translateY(4px);} to { opacity:1; transform: translateY(0);} }
      .pill { transition: all 0.2s ease; border-radius: 6px !important; }
      .pill:hover { transform: translateY(-1px); }
      .bar-fill { transition: width 0.6s ease-out; }
      .stamp-in { animation: stampDown 0.4s cubic-bezier(.2,1.4,.4,1) both; animation-delay: 0.15s; opacity: 0; }
      @keyframes stampDown { 0% { opacity: 0; transform: translateY(-50%) rotate(-9deg) scale(2.2);} 70% { opacity: 0.85; transform: translateY(-50%) rotate(-9deg) scale(0.92);} 100% { opacity: 0.85; transform: translateY(-50%) rotate(-9deg) scale(1);} }
      .win-in { animation: fadeIn 0.3s ease-out both; }
      .win-star { animation: starSpin 4s linear infinite; transform-origin: 12px 12px; }
      @keyframes starSpin { from { transform: rotate(0deg);} to { transform: rotate(360deg);} }
      ::-webkit-scrollbar { width: 8px; height: 8px; }
      ::-webkit-scrollbar-thumb { background: var(--overlay-7); border-radius: 4px; }
      ::-webkit-scrollbar-track { background: transparent; }
      input:focus, select:focus { outline: none; }
      @media (max-width: 520px) {
        .glass { border-radius: 8px !important; }
        input, select { font-size: 16px !important; } /* prevents iOS auto-zoom on focus */
        button { min-height: 38px; }
      }
      .bounce-in { animation: bounceIn 0.3s ease-out both; }
      @keyframes bounceIn { 0% { opacity:0; transform: translateY(6px);} 100% { opacity:1; transform: translateY(0);} }
      .bubble-btn { transition: transform 0.18s cubic-bezier(.34,1.56,.64,1), filter 0.18s ease, box-shadow 0.18s ease; }
      .bubble-btn:hover { transform: translateY(-2px) scale(1.04); filter: brightness(1.08); box-shadow: 0 8px 20px -6px rgba(0,0,0,0.5); }
      .bubble-btn:active { transform: translateY(0) scale(0.97); }
    `}</style>
  );
}

function InjuryBadge({ playerName, compact = false }) {
  const inj = INJURIES[playerName];
  if (!inj) return null;
  return (
    <span title={`${inj.status}${inj.injury ? " — " + inj.injury : ""} (Week ${inj.week} report)`} style={{
      fontSize: 9, color: ACCENT.rose, border: `1px solid ${ACCENT.rose}55`, borderRadius: 8, padding: "1px 6px", fontWeight: 700,
      whiteSpace: "nowrap"
    }}>
      {compact ? "+ INJ" : `+ ${inj.status.toUpperCase()}`}
    </span>
  );
}

// Only relevant for QB/RB — their own play depends most directly on the offensive line in front of them.
function findInjuredLineman(team) {
  const ol = OL_STARTERS[team];
  if (!ol) return null;
  for (const [posAbbr, name] of Object.entries(ol)) {
    if (INJURIES[name]) return { name, posAbbr, ...INJURIES[name] };
  }
  return null;
}
function OLInjuryBadge({ team, pos, compact = false }) {
  if (pos !== "QB" && pos !== "RB") return null;
  const hurt = findInjuredLineman(team);
  if (!hurt) return null;
  return (
    <span title={`${hurt.name} (${hurt.posAbbr}) is ${hurt.status}${hurt.injury ? " — " + hurt.injury : ""} — affects this player's protection/blocking`} style={{
      fontSize: 9, color: "#FFD54A", border: "1px solid #FFD54A55", borderRadius: 8, padding: "1px 6px", fontWeight: 700,
      whiteSpace: "nowrap"
    }}>
      {compact ? "+ OL" : `+ OL: ${hurt.posAbbr} ${hurt.status.toUpperCase()}`}
    </span>
  );
}

function Pill({ active, onClick, children, accent = ACCENT.amber }) {
  return (
    <button className="pill" onClick={onClick} style={{
      padding: "7px 14px", borderRadius: 20, fontSize: 12.5, fontWeight: 600,
      border: `1px solid ${active ? accent : "var(--overlay-6)"}`,
      background: active ? `${accent}22` : "rgba(255,255,255,0.02)",
      color: active ? accent : "var(--text-secondary-a)", cursor: "pointer", whiteSpace: "nowrap"
    }}>{children}</button>
  );
}

// Draws a real line from real data points only — never fabricated. Pass null/empty to skip.
function Sparkline({ data, color = ACCENT.teal, width = 90, height = 28 }) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / range) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const trendUp = data[data.length - 1] >= data[0];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: "block" }}>
      <polyline points={points} fill="none" stroke={trendUp ? ACCENT.green : ACCENT.rose} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" opacity="0.9" />
    </svg>
  );
}

function StatChip({ label, value, decimals = 0, accent, suffix = "" }) {
  return (
    <div style={{ textAlign: "center", minWidth: 64 }}>
      <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 22, fontWeight: 700, color: accent || "var(--text-primary)" }}>
        <CountUp value={value} decimals={decimals} suffix={suffix} />
      </div>
      <div style={{ fontSize: 9.5, letterSpacing: "0.1em", color: "var(--text-label)", textTransform: "uppercase", marginTop: 2 }}>{label}</div>
    </div>
  );
}

function SplitRow({ label, n, rate1Label, rate1, rate2Label, rate2, epa, maxAbs }) {
  if (!n) return null;
  const val = epa || 0;
  const pct = Math.min(100, (Math.abs(val) / (maxAbs || 0.5)) * 100);
  const good = val >= 0;
  return (
    <div style={{ marginBottom: 9 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 3 }}>
        <span style={{ color: "var(--text-body)", fontWeight: 600 }}>{label}</span>
        <span style={{ fontFamily: "'JetBrains Mono', monospace", color: "var(--text-secondary-b)" }}>
          {n}pl · {rate1Label} {fmt(rate1,0)}{typeof rate1==='number'&&rate1<=100&&rate1Label.includes('%')?'':''} · {rate2Label} {fmt(rate2)} · {val>=0?"+":""}{fmt(val,2)} EPA
        </span>
      </div>
      <div style={{ height: 6, background: "var(--overlay-3)", borderRadius: 3, overflow: "hidden" }}>
        <div className="bar-fill" style={{ height: "100%", width: `${Math.max(3,pct)}%`,
          background: good ? "linear-gradient(90deg,#2B6E8C,#4FC3F7)" : "linear-gradient(90deg,#8C3B2B,#F2745A)" }} />
      </div>
    </div>
  );
}

// =====================================================================
// SKILL POSITION (WR/TE/RB) DETAIL
// =====================================================================
function SkillDetail({ p, onClose }) {
  const frontEntries = Object.entries(p.fronts || {}).sort((a,b)=>b[1].targets-a[1].targets);
  const covEntries = Object.entries(p.coverages || {}).sort((a,b)=>b[1].targets-a[1].targets);
  const weatherEntries = Object.entries(p.weather || {}).sort((a,b)=>b[1].targets-a[1].targets);
  const allVals = [...frontEntries, ...covEntries].map(([,s]) => Math.abs(s.epaPerTarget || 0));
  const maxAbs = Math.max(0.3, ...allVals);
  const gamesPlayed = (p.gamelog || []).length;

  return (
    <div className="fade-in">
      <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--text-secondary-b)", fontSize: 12.5, cursor: "pointer", marginBottom: 14, padding: 0 }}>← Back to leaderboard</button>
      <div style={{ fontSize: 10.5, letterSpacing: "0.16em", color: ACCENT.amber, fontWeight: 700, marginBottom: 4 }}>{p.pos} · {TEAM_NAMES[p.team] || p.team}</div>
      <h2 style={{ fontSize: 26, fontWeight: 800, margin: 0, marginBottom: 16, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>{p.name}<InjuryBadge playerName={p.name} /><OLInjuryBadge team={p.team} pos={p.pos} /></h2>

      {NFL_UPCOMING[p.team] && (
        <div style={{ display: "inline-flex", alignItems: "center", gap: 8, background: "rgba(255,138,0,0.1)", border: "1px solid #FF8A0055", borderRadius: 10, padding: "8px 14px", marginBottom: 16, fontSize: 12.5, color: "#FFD8A8" }}>
          📅 <b>Next:</b> {NFL_UPCOMING[p.team].isHome ? "vs" : "@"} {TEAM_NAMES[NFL_UPCOMING[p.team].opp]||NFL_UPCOMING[p.team].opp} on {NFL_UPCOMING[p.team].date} (Week {NFL_UPCOMING[p.team].week})
        </div>
      )}

      <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 12, display: "flex", gap: 22, flexWrap: "wrap" }}>
        <StatChip label="Targets" value={p.overall.targets} />
        <StatChip label="Catches" value={p.overall.catches} />
        <StatChip label="Yards" value={p.overall.yards} />
        <StatChip label="TDs" value={p.overall.tds} accent={ACCENT.amber} />
        <StatChip label="Catch %" value={p.overall.catchRate} suffix="%" />
        <StatChip label="Target Share" value={p.overall.targetShare} suffix="%" accent={ACCENT.violet} />
        <StatChip label="EPA/Tgt" value={p.overall.epaPerTarget} decimals={2} accent={p.overall.epaPerTarget>=0?ACCENT.teal:ACCENT.rose} />
      </Glass>
      {p.overall.targetShare !== null && p.overall.targetShare !== undefined && (
        <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginBottom: 12, marginTop: -8 }}>
          Target Share = this player's targets ÷ their team's total targets over the same 2024–25 window — the real metric, not a simplified stand-in.
        </div>
      )}

      {p.overall.rushAtt > 0 && (
        <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 12, display: "flex", gap: 22, flexWrap: "wrap" }}>
          <div style={{ fontSize: 10, letterSpacing: "0.1em", color: ACCENT.green, textTransform: "uppercase", fontWeight: 700, width: "100%", marginBottom: 4 }}>Rushing</div>
          <StatChip label="Attempts" value={p.overall.rushAtt} accent={ACCENT.green} />
          <StatChip label="Rush Yards" value={p.overall.rushYards} accent={ACCENT.green} />
          <StatChip label="YPC" value={p.overall.ypc} decimals={1} accent={ACCENT.green} />
          <StatChip label="Rush TDs" value={p.overall.rushTD} accent={ACCENT.amber} />
          <StatChip label="Scrimmage Yds" value={p.overall.scrimmageYards} accent={ACCENT.teal} />
        </Glass>
      )}

      {gamesPlayed > 0 && (
        <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16, display: "flex", gap: 22, flexWrap: "wrap" }}>
          <div style={{ fontSize: 10, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", fontWeight: 700, width: "100%", marginBottom: 4 }}>Per Game ({gamesPlayed} games, 2024–25)</div>
          <StatChip label="Tgt/Gm" value={p.overall.targets/gamesPlayed} decimals={1} accent={ACCENT.teal} />
          <StatChip label="Rec/Gm" value={p.overall.catches/gamesPlayed} decimals={1} accent={ACCENT.teal} />
          <StatChip label="Rec Yds/Gm" value={p.overall.yards/gamesPlayed} decimals={1} accent={ACCENT.teal} />
          {p.overall.rushAtt > 0 && <StatChip label="Rush Yds/Gm" value={p.overall.rushYards/gamesPlayed} decimals={1} accent={ACCENT.green} />}
          {p.overall.rushAtt > 0 && <StatChip label="Scrim Yds/Gm" value={p.overall.scrimmageYards/gamesPlayed} decimals={1} accent={ACCENT.amber} />}
          <StatChip label="TD/Gm" value={p.overall.tds/gamesPlayed} decimals={2} accent={ACCENT.amber} />
        </Glass>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
        <Glass hover={false} style={{ padding: "12px 16px" }}><div style={{ fontSize: 10.5, color: "var(--text-secondary-b)", fontWeight: 700, marginBottom: 8 }}>HOME</div><div style={{ fontSize: 13, color: "var(--text-body)" }}>{fmt(p.home.yards)} yds · {p.home.targets} tgt</div></Glass>
        <Glass hover={false} style={{ padding: "12px 16px" }}><div style={{ fontSize: 10.5, color: "var(--text-secondary-b)", fontWeight: 700, marginBottom: 8 }}>AWAY</div><div style={{ fontSize: 13, color: "var(--text-body)" }}>{fmt(p.away.yards)} yds · {p.away.targets} tgt</div></Glass>
      </div>

      <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16 }}>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>vs. Front</div>
        {frontEntries.map(([f,s]) => <SplitRow key={f} label={f} n={s.targets} rate1Label="catch" rate1={s.catchRate} rate2Label="ypt" rate2={s.yptTarget} epa={s.epaPerTarget} maxAbs={maxAbs} />)}
      </Glass>
      <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16 }}>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>vs. Coverage</div>
        {covEntries.length ? covEntries.map(([c,s]) => <SplitRow key={c} label={COVERAGE_LABEL[c]||c} n={s.targets} rate1Label="catch" rate1={s.catchRate} rate2Label="ypt" rate2={s.yptTarget} epa={s.epaPerTarget} maxAbs={maxAbs} />) : <div style={{color:"var(--text-tertiary)",fontSize:12}}>Not enough volume for a reliable split.</div>}
      </Glass>
      <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16 }}>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>Weather</div>
        {weatherEntries.map(([w,s]) => <SplitRow key={w} label={w} n={s.targets} rate1Label="catch" rate1={s.catchRate} rate2Label="ypt" rate2={s.yptTarget} epa={s.epaPerTarget} maxAbs={maxAbs} />)}
      </Glass>
      {p.tds && p.tds.length > 0 && (
        <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16 }}>
          <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>Touchdowns ({p.tds.length})</div>
          {p.tds.map((t,i) => (
            <div key={i} style={{ display:"grid", gridTemplateColumns:"36px 46px 1fr 1fr 50px", gap:8, fontSize:12, padding:"7px 0", borderTop: i? "1px solid var(--overlay-3)":"none" }}>
              <span style={{ color:"var(--text-tertiary)", fontFamily:"'JetBrains Mono', monospace" }}>'{String(t.season).slice(2)}</span>
              <span style={{ color:"var(--text-tertiary)", fontFamily:"'JetBrains Mono', monospace" }}>Wk{t.week}</span>
              <span style={{ fontWeight:600 }}>{TEAM_NAMES[t.opp]||t.opp}</span>
              <span style={{ color: (t.coverage==="COVER_0"||t.coverage==="COVER_1") ? ACCENT.amber : "var(--text-body)" }}>{COVERAGE_LABEL[t.coverage]||t.coverage}</span>
              <span style={{ fontFamily:"'JetBrains Mono', monospace", color: ACCENT.teal, textAlign:"right" }}>{t.yards}yd</span>
            </div>
          ))}
        </Glass>
      )}
      <Glass hover={false} style={{ padding: "16px 18px" }}>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>Recent Games</div>
        <div style={{ maxHeight: 320, overflowY: "auto" }}>
          {[...(p.gamelog||[])].reverse().slice(0,15).map((g,i) => {
            const { week, opp } = parseGameId(g.game_id, p.team);
            return (
              <div key={i} style={{ display:"grid", gridTemplateColumns:"36px 46px 1fr 1fr 1fr", gap:8, fontSize:11.5, padding:"7px 0", borderTop: i? "1px solid var(--overlay-3)":"none" }}>
                <span style={{ color:"var(--text-tertiary)", fontFamily:"'JetBrains Mono', monospace" }}>'{String(g.season).slice(2)}</span>
                <span style={{ color:"var(--text-tertiary)", fontFamily:"'JetBrains Mono', monospace" }}>Wk{week}</span>
                <span style={{ fontWeight:600 }}>vs {TEAM_NAMES[opp]||opp||"?"}</span>
                <span style={{ color:"var(--text-body)" }}>{g.targets} tgt, {g.catches} rec</span>
                <span style={{ fontFamily:"'JetBrains Mono', monospace", color: ACCENT.teal, textAlign:"right" }}>{g.yards}yd</span>
              </div>
            );
          })}
        </div>
      </Glass>
    </div>
  );
}

// =====================================================================
// QB DETAIL
// =====================================================================
function QBDetail({ p, onClose }) {
  const frontEntries = Object.entries(p.fronts || {}).sort((a,b)=>b[1].attempts-a[1].attempts);
  const covEntries = Object.entries(p.coverages || {}).sort((a,b)=>b[1].attempts-a[1].attempts);
  const weatherEntries = Object.entries(p.weather || {}).sort((a,b)=>b[1].attempts-a[1].attempts);
  const allVals = [...frontEntries, ...covEntries].map(([,s]) => Math.abs(s.epaPerAtt || 0));
  const maxAbs = Math.max(0.3, ...allVals);
  const gamesPlayed = (p.gamelog || []).length;
  const olLine = OL_STARTERS[p.team];
  const olPositions = [["LT","Left Tackle"],["LG","Left Guard"],["C","Center"],["RG","Right Guard"],["RT","Right Tackle"]];

  return (
    <div className="fade-in">
      <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--text-secondary-b)", fontSize: 12.5, cursor: "pointer", marginBottom: 14, padding: 0 }}>← Back to leaderboard</button>
      <div style={{ fontSize: 10.5, letterSpacing: "0.16em", color: ACCENT.green, fontWeight: 700, marginBottom: 4 }}>QB · {TEAM_NAMES[p.team] || p.team}</div>
      <h2 style={{ fontSize: 26, fontWeight: 800, margin: 0, marginBottom: 16, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>{p.name}<InjuryBadge playerName={p.name} /><OLInjuryBadge team={p.team} pos="QB" /></h2>

      {NFL_UPCOMING[p.team] && (
        <div style={{ display: "inline-flex", alignItems: "center", gap: 8, background: "rgba(255,138,0,0.1)", border: "1px solid #FF8A0055", borderRadius: 10, padding: "8px 14px", marginBottom: 16, fontSize: 12.5, color: "#FFD8A8" }}>
          📅 <b>Next:</b> {NFL_UPCOMING[p.team].isHome ? "vs" : "@"} {TEAM_NAMES[NFL_UPCOMING[p.team].opp]||NFL_UPCOMING[p.team].opp} on {NFL_UPCOMING[p.team].date} (Week {NFL_UPCOMING[p.team].week})
        </div>
      )}

      <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 12, display: "flex", gap: 22, flexWrap: "wrap" }}>
        <StatChip label="Attempts" value={p.overall.attempts} />
        <StatChip label="Completions" value={p.overall.completions} />
        <StatChip label="Pass Yards" value={p.overall.yards} />
        <StatChip label="TDs" value={p.overall.tds} accent={ACCENT.amber} />
        <StatChip label="INTs" value={p.overall.ints} accent={ACCENT.rose} />
        <StatChip label="Comp %" value={p.overall.compPct} suffix="%" />
        <StatChip label="EPA/Att" value={p.overall.epaPerAtt} decimals={2} accent={p.overall.epaPerAtt>=0?ACCENT.teal:ACCENT.rose} />
      </Glass>

      {p.overall.rushAtt > 0 && (
        <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 12, display: "flex", gap: 22, flexWrap: "wrap" }}>
          <div style={{ fontSize: 10, letterSpacing: "0.1em", color: ACCENT.green, textTransform: "uppercase", fontWeight: 700, width: "100%", marginBottom: 4 }}>Rushing</div>
          <StatChip label="Attempts" value={p.overall.rushAtt} accent={ACCENT.green} />
          <StatChip label="Rush Yards" value={p.overall.rushYards} accent={ACCENT.green} />
          <StatChip label="Rush TDs" value={p.overall.rushTD} accent={ACCENT.amber} />
          <StatChip label="Total Yards" value={p.overall.totalYards} accent={ACCENT.teal} />
        </Glass>
      )}

      {olLine && (
        <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16 }}>
          <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 4, fontWeight: 700 }}>Offensive Line — Current Starters</div>
          <div style={{ fontSize: 10.5, color: "var(--text-tertiary)", marginBottom: 10 }}>From the most recent depth chart — who's protecting him right now.</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 8 }}>
            {olPositions.map(([abbr, label]) => {
              const name = olLine[abbr];
              return (
                <div key={abbr} style={{ background: "var(--overlay-1)", border: "1px solid var(--overlay-4)", borderRadius: 8, padding: "8px 10px" }}>
                  <div style={{ fontSize: 9.5, color: "var(--text-label)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
                  <div style={{ fontSize: 12.5, fontWeight: 700, display: "flex", alignItems: "center", gap: 6 }}>
                    {name || "—"}{name && <InjuryBadge playerName={name} compact />}
                  </div>
                </div>
              );
            })}
          </div>
        </Glass>
      )}

      {gamesPlayed > 0 && (
        <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16, display: "flex", gap: 22, flexWrap: "wrap" }}>
          <div style={{ fontSize: 10, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", fontWeight: 700, width: "100%", marginBottom: 4 }}>Per Game ({gamesPlayed} games, 2024–25)</div>
          <StatChip label="Att/Gm" value={p.overall.attempts/gamesPlayed} decimals={1} accent={ACCENT.teal} />
          <StatChip label="Cmp/Gm" value={p.overall.completions/gamesPlayed} decimals={1} accent={ACCENT.teal} />
          <StatChip label="Pass Yds/Gm" value={p.overall.yards/gamesPlayed} decimals={1} accent={ACCENT.teal} />
          {p.overall.rushAtt > 0 && <StatChip label="Rush Yds/Gm" value={p.overall.rushYards/gamesPlayed} decimals={1} accent={ACCENT.green} />}
          <StatChip label="TD/Gm" value={p.overall.tds/gamesPlayed} decimals={2} accent={ACCENT.amber} />
        </Glass>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
        <Glass hover={false} style={{ padding: "12px 16px" }}><div style={{ fontSize: 10.5, color: "var(--text-secondary-b)", fontWeight: 700, marginBottom: 8 }}>HOME</div><div style={{ fontSize: 13, color: "var(--text-body)" }}>{fmt(p.home.yards)} yds · {p.home.attempts} att</div></Glass>
        <Glass hover={false} style={{ padding: "12px 16px" }}><div style={{ fontSize: 10.5, color: "var(--text-secondary-b)", fontWeight: 700, marginBottom: 8 }}>AWAY</div><div style={{ fontSize: 13, color: "var(--text-body)" }}>{fmt(p.away.yards)} yds · {p.away.attempts} att</div></Glass>
      </div>

      <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16 }}>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>vs. Front</div>
        {frontEntries.map(([f,s]) => <SplitRow key={f} label={f} n={s.attempts} rate1Label="comp%" rate1={s.compPct} rate2Label="ypa" rate2={s.yptAtt} epa={s.epaPerAtt} maxAbs={maxAbs} />)}
      </Glass>
      <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16 }}>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>vs. Coverage</div>
        {covEntries.length ? covEntries.map(([c,s]) => <SplitRow key={c} label={COVERAGE_LABEL[c]||c} n={s.attempts} rate1Label="comp%" rate1={s.compPct} rate2Label="ypa" rate2={s.yptAtt} epa={s.epaPerAtt} maxAbs={maxAbs} />) : <div style={{color:"var(--text-tertiary)",fontSize:12}}>Not enough volume.</div>}
      </Glass>
      <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16 }}>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>Weather</div>
        {weatherEntries.map(([w,s]) => <SplitRow key={w} label={w} n={s.attempts} rate1Label="comp%" rate1={s.compPct} rate2Label="ypa" rate2={s.yptAtt} epa={s.epaPerAtt} maxAbs={maxAbs} />)}
      </Glass>
      <Glass hover={false} style={{ padding: "16px 18px" }}>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>Recent Games</div>
        <div style={{ maxHeight: 320, overflowY: "auto" }}>
          {[...(p.gamelog||[])].reverse().slice(0,15).map((g,i) => {
            const { week, opp } = parseGameId(g.game_id, p.team);
            return (
              <div key={i} style={{ display:"grid", gridTemplateColumns:"36px 46px 1fr 1fr 1fr", gap:8, fontSize:11.5, padding:"7px 0", borderTop: i? "1px solid var(--overlay-3)":"none" }}>
                <span style={{ color:"var(--text-tertiary)", fontFamily:"'JetBrains Mono', monospace" }}>'{String(g.season).slice(2)}</span>
                <span style={{ color:"var(--text-tertiary)", fontFamily:"'JetBrains Mono', monospace" }}>Wk{week}</span>
                <span style={{ fontWeight:600 }}>vs {TEAM_NAMES[opp]||opp||"?"}</span>
                <span style={{ color:"var(--text-body)" }}>{g.completions}/{g.attempts}, {g.tds} td</span>
                <span style={{ fontFamily:"'JetBrains Mono', monospace", color: ACCENT.teal, textAlign:"right" }}>{g.yards}yd</span>
              </div>
            );
          })}
        </div>
      </Glass>
    </div>
  );
}

// =====================================================================
// KICKER DETAIL
// =====================================================================
function KickerDetail({ p, onClose }) {
  const distEntries = Object.entries(p.distance || {}).sort((a,b)=>b[1].attempts-a[1].attempts);
  const weatherEntries = Object.entries(p.weather || {}).sort((a,b)=>b[1].attempts-a[1].attempts);
  const gamesPlayed = (p.gamelog || []).length;
  return (
    <div className="fade-in">
      <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--text-secondary-b)", fontSize: 12.5, cursor: "pointer", marginBottom: 14, padding: 0 }}>← Back to leaderboard</button>
      <div style={{ fontSize: 10.5, letterSpacing: "0.16em", color: ACCENT.rose, fontWeight: 700, marginBottom: 4 }}>K · {TEAM_NAMES[p.team] || p.team}</div>
      <h2 style={{ fontSize: 26, fontWeight: 800, margin: 0, marginBottom: 16, display: "flex", alignItems: "center", gap: 10 }}>{p.name}<InjuryBadge playerName={p.name} /></h2>

      <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 12, display: "flex", gap: 22, flexWrap: "wrap" }}>
        <StatChip label="FG Att" value={p.overall.attempts} />
        <StatChip label="FG Made" value={p.overall.made} accent={ACCENT.teal} />
        <StatChip label="FG %" value={p.overall.pct} suffix="%" />
        <StatChip label="Avg Dist" value={p.overall.avgDist} suffix=" yd" />
        <StatChip label="XP Made" value={p.xpMade} />
        <StatChip label="XP Att" value={p.xpAtt} />
      </Glass>

      {gamesPlayed > 0 && (
        <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16, display: "flex", gap: 22, flexWrap: "wrap" }}>
          <div style={{ fontSize: 10, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", fontWeight: 700, width: "100%", marginBottom: 4 }}>Per Game ({gamesPlayed} games, 2024–25)</div>
          <StatChip label="FGA/Gm" value={p.overall.attempts/gamesPlayed} decimals={1} accent={ACCENT.teal} />
          <StatChip label="FGM/Gm" value={p.overall.made/gamesPlayed} decimals={1} accent={ACCENT.teal} />
        </Glass>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
        <Glass hover={false} style={{ padding: "12px 16px" }}><div style={{ fontSize: 10.5, color: "var(--text-secondary-b)", fontWeight: 700, marginBottom: 8 }}>HOME</div><div style={{ fontSize: 13, color: "var(--text-body)" }}>{p.home.made}/{p.home.attempts} ({fmt(p.home.pct,0)}%)</div></Glass>
        <Glass hover={false} style={{ padding: "12px 16px" }}><div style={{ fontSize: 10.5, color: "var(--text-secondary-b)", fontWeight: 700, marginBottom: 8 }}>AWAY</div><div style={{ fontSize: 13, color: "var(--text-body)" }}>{p.away.made}/{p.away.attempts} ({fmt(p.away.pct,0)}%)</div></Glass>
      </div>

      <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16 }}>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>By Distance</div>
        {distEntries.map(([d,s]) => (
          <div key={d} style={{ marginBottom: 9 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 3 }}>
              <span style={{ color: "var(--text-body)", fontWeight: 600 }}>{d} yd</span>
              <span style={{ fontFamily: "'JetBrains Mono', monospace", color: "var(--text-secondary-b)" }}>{s.made}/{s.attempts} ({fmt(s.pct,0)}%)</span>
            </div>
            <div style={{ height: 6, background: "var(--overlay-3)", borderRadius: 3, overflow: "hidden" }}>
              <div className="bar-fill" style={{ height: "100%", width: `${Math.max(3,s.pct||0)}%`, background: "linear-gradient(90deg,#8C3B2B,#F2745A)" }} />
            </div>
          </div>
        ))}
      </Glass>
      <Glass hover={false} style={{ padding: "16px 18px" }}>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>Weather</div>
        {weatherEntries.map(([w,s]) => (
          <div key={w} style={{ marginBottom: 9 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 3 }}>
              <span style={{ color: "var(--text-body)", fontWeight: 600 }}>{w}</span>
              <span style={{ fontFamily: "'JetBrains Mono', monospace", color: "var(--text-secondary-b)" }}>{s.made}/{s.attempts} ({fmt(s.pct,0)}%)</span>
            </div>
            <div style={{ height: 6, background: "var(--overlay-3)", borderRadius: 3, overflow: "hidden" }}>
              <div className="bar-fill" style={{ height: "100%", width: `${Math.max(3,s.pct||0)}%`, background: "linear-gradient(90deg,#2B6E8C,#4FC3F7)" }} />
            </div>
          </div>
        ))}
      </Glass>
    </div>
  );
}

// =====================================================================
// DEFENSE DETAIL
// =====================================================================
function DefenseDetail({ d, onClose }) {
  const fronts = Object.entries(d.frontBreakdown || {}).sort((a,b)=>b[1]-a[1]);
  const maxFront = Math.max(...fronts.map(([,v])=>v), 1);
  const weathers = Object.entries(d.weatherBreakdown || {}).sort((a,b)=>b[1]-a[1]);
  const maxWeather = Math.max(...weathers.map(([,v])=>v), 1);
  return (
    <div className="fade-in">
      <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--text-secondary-b)", fontSize: 12.5, cursor: "pointer", marginBottom: 14, padding: 0 }}>← Back to leaderboard</button>
      <div style={{ fontSize: 10.5, letterSpacing: "0.16em", color: ACCENT.violet, fontWeight: 700, marginBottom: 4 }}>{d.pos} · {TEAM_NAMES[d.team] || d.team}</div>
      <h2 style={{ fontSize: 26, fontWeight: 800, margin: 0, marginBottom: 16 }}>{d.name}</h2>

      <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16, display: "flex", gap: 26, flexWrap: "wrap" }}>
        <StatChip label="Sacks" value={d.totalSacks} decimals={d.totalSacks % 1 ? 1 : 0} accent={ACCENT.violet} />
        <StatChip label="Home" value={d.homeSacks} decimals={d.homeSacks % 1 ? 1 : 0} />
        <StatChip label="Away" value={d.awaySacks} decimals={d.awaySacks % 1 ? 1 : 0} />
        <StatChip label="Avg Rushers" value={d.avgPassRushers} decimals={1} />
      </Glass>

      <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16 }}>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>Sacks by Offensive Front Faced</div>
        {fronts.map(([f,v]) => (
          <div key={f} style={{ marginBottom: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 3 }}><span style={{ color: "var(--text-body)", fontWeight: 600 }}>{f}</span><span style={{ fontFamily: "'JetBrains Mono', monospace", color: "var(--text-secondary-b)" }}>{v} sk</span></div>
            <div style={{ height: 6, background: "var(--overlay-3)", borderRadius: 3, overflow: "hidden" }}><div className="bar-fill" style={{ height: "100%", width: `${Math.max(4,(v/maxFront)*100)}%`, background: "linear-gradient(90deg,#5A3C82,#B98CF2)" }} /></div>
          </div>
        ))}
      </Glass>
      <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16 }}>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>Weather</div>
        {weathers.map(([w,v]) => (
          <div key={w} style={{ marginBottom: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 3 }}><span style={{ color: "var(--text-body)", fontWeight: 600 }}>{w}</span><span style={{ fontFamily: "'JetBrains Mono', monospace", color: "var(--text-secondary-b)" }}>{v} sk</span></div>
            <div style={{ height: 6, background: "var(--overlay-3)", borderRadius: 3, overflow: "hidden" }}><div className="bar-fill" style={{ height: "100%", width: `${Math.max(4,(v/maxWeather)*100)}%`, background: "linear-gradient(90deg,#8C5B2B,#F2A900)" }} /></div>
          </div>
        ))}
      </Glass>
      <Glass hover={false} style={{ padding: "16px 18px" }}>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>Every Sack ({d.plays.length} plays)</div>
        <div style={{ maxHeight: 320, overflowY: "auto" }}>
          {d.plays.map((pl,i) => (
            <div key={i} style={{ display:"grid", gridTemplateColumns:"32px 44px 46px 1fr 1fr 90px", gap:6, fontSize:11.5, padding:"7px 0", borderTop: i? "1px solid var(--overlay-3)":"none" }}>
              <span style={{ color:"var(--text-tertiary)", fontFamily:"'JetBrains Mono', monospace" }}>'{String(pl.season).slice(2)}</span>
              <span style={{ color:"var(--text-tertiary)", fontFamily:"'JetBrains Mono', monospace" }}>Wk{pl.week}</span>
              <span style={{ fontWeight:600 }}>{TEAM_NAMES[pl.opp]||pl.opp}</span>
              <span style={{ color:"var(--text-body)" }}>{pl.front}</span>
              <span style={{ color:"var(--text-body)" }}>{COVERAGE_LABEL[pl.coverage]||pl.coverage}</span>
              <span style={{ color:"var(--text-label)", textAlign:"right" }}>{pl.down ? `${pl.down}&${pl.togo}` : ""} vs {pl.qb || "?"}</span>
            </div>
          ))}
        </div>
      </Glass>
    </div>
  );
}

// =====================================================================
// LEADERBOARD CARDS
// =====================================================================
// =====================================================================
// WNBA CARDS + DETAIL
// =====================================================================
function WNBACard({ p, onSelect, idx, mode }) {
  const primary = mode === "defense" ? (p.overall.stl + p.overall.blk).toFixed(1) : p.overall.pts;
  const primaryLabel = mode === "defense" ? "stl+blk/gm" : "pts/gm";
  return (
    <Glass onClick={() => onSelect(p)} style={{ padding: "14px 16px", animationDelay: `${Math.min(idx,20)*18}ms` }}>
      <div className="fade-in" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, display: "flex", alignItems: "center", gap: 6 }}>{p.name}<InjuryBadge playerName={p.name} compact /></div>
          <div style={{ fontSize: 11, color: "var(--text-secondary-b)", marginTop: 2 }}>{p.team} · {p.overall.games} games</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 16, fontWeight: 700, color: ACCENT.teal }}>{primary}</div>
          <div style={{ fontSize: 9.5, color: "var(--text-label)" }}>{primaryLabel}</div>
        </div>
      </div>
      <div style={{ marginTop: 10, fontSize: 11.5, color: "var(--text-secondary-a)", fontFamily: "'JetBrains Mono', monospace" }}>
        {p.overall.pts} pts · {p.overall.reb} reb · {p.overall.ast} ast · {p.overall.stl} stl · {p.overall.blk} blk
      </div>
    </Glass>
  );
}

// =====================================================================
// MLB CARDS + DETAIL (batters and pitchers, distinct stat shapes)
// =====================================================================
function MLBCard({ p, onSelect, idx }) {
  const isPitcher = p.group === "pitching";
  const primary = isPitcher ? fmt(p.overall.era, 2) : p.overall.totalHR;
  const primaryLabel = isPitcher ? "ERA" : "HR";
  return (
    <Glass onClick={() => onSelect(p)} style={{ padding: "14px 16px", animationDelay: `${Math.min(idx,20)*18}ms` }}>
      <div className="fade-in" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, display: "flex", alignItems: "center", gap: 6 }}>{p.name}<InjuryBadge playerName={p.name} compact /></div>
          <div style={{ fontSize: 11, color: "var(--text-secondary-b)", marginTop: 2 }}>{p.team} · {p.overall.games} games</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 16, fontWeight: 700, color: isPitcher?"#6EC9F2":ACCENT.teal }}>{primary}</div>
          <div style={{ fontSize: 9.5, color: "var(--text-label)" }}>{primaryLabel}</div>
        </div>
      </div>
      <div style={{ marginTop: 10, fontSize: 11.5, color: "var(--text-secondary-a)", fontFamily: "'JetBrains Mono', monospace" }}>
        {isPitcher
          ? `${p.overall.avg_so} K/gm · ${p.overall.avg_ip} IP/gm · ${p.overall.totalWins} W · ${p.overall.totalSaves} SV`
          : `.${String(Math.round((p.overall.battingAvg||0)*1000)).padStart(3,'0')} AVG · ${p.overall.avg_hits} H/gm · ${p.overall.totalRBI} RBI`}
      </div>
    </Glass>
  );
}

function MLBDetail({ p, onClose }) {
  const isPitcher = p.group === "pitching";
  const next = mlbUpcoming()[p.team];
  return (
    <div className="fade-in">
      <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--text-secondary-b)", fontSize: 12.5, cursor: "pointer", marginBottom: 14, padding: 0 }}>← Back to leaderboard</button>
      <div style={{ fontSize: 10.5, letterSpacing: "0.16em", color: ACCENT.amber, fontWeight: 700, marginBottom: 4 }}>{p.team} · {isPitcher?"Pitcher":"Batter"} · {p.overall.games} games</div>
      <h2 style={{ fontSize: 26, fontWeight: 800, margin: 0, marginBottom: 16, display: "flex", alignItems: "center", gap: 10 }}>{p.name}<InjuryBadge playerName={p.name} /></h2>

      {next && (
        <div style={{ display: "inline-flex", alignItems: "center", gap: 8, background: "rgba(255,138,0,0.1)", border: "1px solid #FF8A0055", borderRadius: 10, padding: "8px 14px", marginBottom: 16, fontSize: 12.5, color: "#FFD8A8" }}>
          📅 <b>Next:</b> {next.isHome ? "vs" : "@"} {next.opp} on {next.date}
        </div>
      )}

      {isPitcher ? (
        <>
        <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16, display: "flex", gap: 22, flexWrap: "wrap" }}>
          <StatChip label="ERA" value={p.overall.era} decimals={2} accent="#6EC9F2" />
          <StatChip label="K/Gm" value={p.overall.avg_so} decimals={1} />
          <StatChip label="IP/Gm" value={p.overall.avg_ip} decimals={1} />
          <StatChip label="Wins" value={p.overall.totalWins} accent={ACCENT.amber} />
          <StatChip label="Saves" value={p.overall.totalSaves} accent={ACCENT.amber} />
        </Glass>
        <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16, display: "flex", gap: 22, flexWrap: "wrap" }}>
          <StatChip label="WHIP" value={p.overall.whip} decimals={2} accent="#6EC9F2" />
          <StatChip label="K/9" value={p.overall.k9} decimals={2} accent="#6EC9F2" />
        </Glass>
        </>
      ) : (
        <>
        <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16, display: "flex", gap: 22, flexWrap: "wrap" }}>
          <StatChip label="AVG" value={p.overall.battingAvg} decimals={3} accent={ACCENT.teal} />
          <StatChip label="H/Gm" value={p.overall.avg_hits} decimals={1} />
          <StatChip label="HR" value={p.overall.totalHR} accent={ACCENT.amber} />
          <StatChip label="RBI" value={p.overall.totalRBI} accent={ACCENT.amber} />
          <StatChip label="Runs/Gm" value={p.overall.avg_runs} decimals={1} />
          <StatChip label="SB" value={p.overall.totalSB} accent={ACCENT.violet} />
        </Glass>
        <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16, display: "flex", gap: 22, flexWrap: "wrap" }}>
          <StatChip label="OBP" value={p.overall.obp} decimals={3} accent={ACCENT.teal} />
          <StatChip label="SLG" value={p.overall.slg} decimals={3} accent={ACCENT.teal} />
          <StatChip label="OPS" value={p.overall.ops} decimals={3} accent={ACCENT.amber} />
        </Glass>
        </>
      )}

      <Glass hover={false} style={{ padding: "16px 18px" }}>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>Recent Games</div>
        <div style={{ maxHeight: 320, overflowY: "auto" }}>
          {(p.gamelog||[]).slice(-15).reverse().map((g,i) => (
            <div key={i} style={{ display:"grid", gridTemplateColumns:"70px 1fr 1fr 1fr", gap:6, fontSize:11.5, padding:"7px 0", borderTop: i? "1px solid var(--overlay-3)":"none" }}>
              <span style={{ color:"var(--text-tertiary)", fontFamily:"'JetBrains Mono', monospace" }}>{g.date}</span>
              <span style={{ color:"var(--text-secondary-a)" }}>{g.isHome ? "vs" : "@"} {g.opp}</span>
              {isPitcher
                ? <><span style={{ color:"var(--text-body)" }}>{g.ip} IP, {g.er} ER</span><span style={{ fontFamily:"'JetBrains Mono', monospace", color:"#6EC9F2" }}>{g.so} K</span></>
                : <><span style={{ color:"var(--text-body)" }}>{g.hits} H, {g.rbi} RBI</span><span style={{ fontFamily:"'JetBrains Mono', monospace", color: ACCENT.teal }}>{g.hr} HR</span></>}
            </div>
          ))}
        </div>
      </Glass>
    </div>
  );
}

function WNBADetail({ p, onClose }) {
  const next = wnbaUpcoming()[p.team];
  return (
    <div className="fade-in">
      <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--text-secondary-b)", fontSize: 12.5, cursor: "pointer", marginBottom: 14, padding: 0 }}>← Back to leaderboard</button>
      <div style={{ fontSize: 10.5, letterSpacing: "0.16em", color: ACCENT.amber, fontWeight: 700, marginBottom: 4 }}>{p.team} · {p.overall.games} games (2025–26)</div>
      <h2 style={{ fontSize: 26, fontWeight: 800, margin: 0, marginBottom: 16, display: "flex", alignItems: "center", gap: 10 }}>{p.name}<InjuryBadge playerName={p.name} /></h2>

      {next && (
        <div style={{ display: "inline-flex", alignItems: "center", gap: 8, background: "rgba(255,138,0,0.1)", border: "1px solid #FF8A0055", borderRadius: 10, padding: "8px 14px", marginBottom: 16, fontSize: 12.5, color: "#FFD8A8" }}>
          📅 <b>Next:</b> vs {next.opp} on {next.date}
        </div>
      )}

      <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16, display: "flex", gap: 22, flexWrap: "wrap" }}>
        <StatChip label="Pts/Gm" value={p.overall.pts} decimals={1} accent={ACCENT.teal} />
        <StatChip label="Reb/Gm" value={p.overall.reb} decimals={1} />
        <StatChip label="Ast/Gm" value={p.overall.ast} decimals={1} />
        <StatChip label="Stl/Gm" value={p.overall.stl} decimals={1} />
        <StatChip label="Blk/Gm" value={p.overall.blk} decimals={1} accent={ACCENT.amber} />
        <StatChip label="TOV/Gm" value={p.overall.tov} decimals={1} accent={ACCENT.rose} />
      </Glass>

      <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 16, display: "flex", gap: 22, flexWrap: "wrap" }}>
        <StatChip label="FG%" value={p.overall.fgPct} decimals={1} suffix="%" accent={ACCENT.teal} />
        <StatChip label="3PT%" value={p.overall.tpPct} decimals={1} suffix="%" accent={ACCENT.teal} />
        <StatChip label="Shot Share %" value={p.overall.usage} decimals={1} suffix="%" accent={ACCENT.violet} />
      </Glass>
      <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginBottom: 16, marginTop: -8 }}>
        Shot Share = this player's shot attempts + 0.44×FTA + turnovers, as a share of their team's total — a real
        possession-involvement number, but deliberately not labeled "Usage %" here, since the official NBA/WNBA usage
        stat also adjusts for on-court minutes, which we don't have.
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20 }}>
        <Glass hover={false} style={{ padding: "12px 16px" }}><div style={{ fontSize: 10.5, color: "var(--text-secondary-b)", fontWeight: 700, marginBottom: 8 }}>HOME ({p.home.games}gm)</div><div style={{ fontSize: 13, color: "var(--text-body)" }}>{fmt(p.home.pts,1)} pts/gm</div></Glass>
        <Glass hover={false} style={{ padding: "12px 16px" }}><div style={{ fontSize: 10.5, color: "var(--text-secondary-b)", fontWeight: 700, marginBottom: 8 }}>AWAY ({p.away.games}gm)</div><div style={{ fontSize: 13, color: "var(--text-body)" }}>{fmt(p.away.pts,1)} pts/gm</div></Glass>
      </div>

      <Glass hover={false} style={{ padding: "16px 18px" }}>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>Recent Games (2026 season)</div>
        <div style={{ maxHeight: 320, overflowY: "auto" }}>
          {(p.gamelog||[]).slice(-15).reverse().map((g,i) => (
            <div key={i} style={{ display:"grid", gridTemplateColumns:"90px 70px 1fr 1fr 1fr 1fr 1fr", gap:6, fontSize:11.5, padding:"7px 0", borderTop: i? "1px solid var(--overlay-3)":"none", alignItems:"center" }}>
              <span style={{ color:"var(--text-tertiary)", fontFamily:"'JetBrains Mono', monospace" }}>{g.game_date}</span>
              <span style={{ color:"var(--text-secondary-a)" }}>{g.is_home ? "vs" : "@"} {g.opp_team_name}</span>
              <span style={{ fontFamily:"'JetBrains Mono', monospace", color: ACCENT.teal }}>{g.pts} pts</span>
              <span style={{ color:"var(--text-body)" }}>{g.reb} reb</span>
              <span style={{ color:"var(--text-body)" }}>{g.ast} ast</span>
              <span style={{ color:"var(--text-body)" }}>{g.stl} stl</span>
              <span style={{ color:"var(--text-body)" }}>{g.blk} blk</span>
            </div>
          ))}
        </div>
      </Glass>
    </div>
  );
}

function OffenseCard({ p, onSelect, idx }) {
  let primary, primaryLabel, secondary, accent;
  const hasRush = p.overall.rushAtt > 0;
  if (p.kind === "skill") {
    if (hasRush) {
      primary = fmt(p.overall.scrimmageYards,0); primaryLabel = "scrim yds";
      secondary = `${p.overall.rushAtt} rush (${fmt(p.overall.ypc,1)} ypc, ${p.overall.rushTD} td) · ${p.overall.catches} rec, ${fmt(p.overall.yards,0)} rec yds`;
    } else {
      primary = fmt(p.overall.yards,0); primaryLabel = "yds";
      secondary = `${p.overall.targets} tgt · ${p.overall.catches} rec · ${p.overall.tds} td`;
    }
    accent = ACCENT.teal;
  } else if (p.kind === "qb") {
    primary = fmt(p.overall.yards,0); primaryLabel = "pass yds";
    secondary = hasRush
      ? `${fmt(p.overall.compPct,0)}% · ${p.overall.tds} td · ${p.overall.ints} int · ${p.overall.rushAtt} rush, ${fmt(p.overall.rushYards,0)} rush yds`
      : `${p.overall.attempts} att · ${fmt(p.overall.compPct,0)}% · ${p.overall.tds} td · ${p.overall.ints} int`;
    accent = ACCENT.green;
  } else {
    primary = p.overall.made; primaryLabel = "fg made";
    secondary = `${p.overall.attempts} att · ${fmt(p.overall.pct,0)}% · ${fmt(p.overall.avgDist,0)}yd avg`;
    accent = ACCENT.rose;
  }
  return (
    <Glass onClick={() => onSelect(p)} style={{ padding: "14px 16px", animationDelay: `${Math.min(idx,20)*18}ms` }}>
      <div className="fade-in" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>{p.name}<InjuryBadge playerName={p.name} compact /><OLInjuryBadge team={p.team} pos={p.pos} compact /></div>
          <div style={{ fontSize: 11, color: "var(--text-secondary-b)", marginTop: 2 }}>{p.pos} · {TEAM_NAMES[p.team]||p.team}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 16, fontWeight: 700, color: accent }}>{primary}</div>
          <div style={{ fontSize: 9.5, color: "var(--text-label)" }}>{primaryLabel}</div>
        </div>
      </div>
      <div style={{ marginTop: 10, fontSize: 11.5, color: "var(--text-secondary-a)", fontFamily: "'JetBrains Mono', monospace" }}>{secondary}</div>
    </Glass>
  );
}

function DefenseCard({ d, onSelect, idx }) {
  return (
    <Glass onClick={() => onSelect(d)} style={{ padding: "14px 16px", animationDelay: `${Math.min(idx,20)*18}ms` }}>
      <div className="fade-in" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700 }}>{d.name}</div>
          <div style={{ fontSize: 11, color: "var(--text-secondary-b)", marginTop: 2 }}>{d.pos} · {TEAM_NAMES[d.team]||d.team}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 16, fontWeight: 700, color: ACCENT.violet }}>{d.totalSacks}</div>
          <div style={{ fontSize: 9.5, color: "var(--text-label)" }}>sacks</div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 12, marginTop: 10, fontSize: 11.5, color: "var(--text-secondary-a)", fontFamily: "'JetBrains Mono', monospace" }}>
        <span>{d.homeSacks} home</span><span>{d.awaySacks} away</span><span>{fmt(d.avgPassRushers,1)} avg rushers</span>
      </div>
    </Glass>
  );
}

// =====================================================================
// MARKET PULSE
// =====================================================================
function MarketBar({ name, pct, accent }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, marginBottom: 3 }}><span style={{ color: "var(--text-body)", fontWeight: 600 }}>{name}</span><span style={{ fontFamily: "'JetBrains Mono', monospace", color: accent || "var(--text-secondary-a)", fontWeight: 700 }}>{pct}%</span></div>
      <div style={{ height: 7, background: "var(--overlay-3)", borderRadius: 3, overflow: "hidden" }}><div className="bar-fill" style={{ height: "100%", width: `${pct}%`, background: accent ? `linear-gradient(90deg,${accent}55,${accent})` : "linear-gradient(90deg,#2B6E8C,#4FC3F7)" }} /></div>
    </div>
  );
}
function DepthFlowPanel({ data, accent, status }) {
  if (status === "loading") {
    return <div style={{ fontSize: 11.5, color: "var(--text-tertiary)", marginBottom: 22 }}>Checking order book depth & flow…</div>;
  }
  if (!data || data.length === 0) {
    return (
      <Glass hover={false} style={{ padding: "14px 16px", marginBottom: 22, fontSize: 11.5, color: "var(--text-tertiary)" }}>
        🌊 Depth & Flow data unavailable right now — Kalshi's order book/candlestick endpoints didn't return usable data
        for this market (rate limit, ticker mismatch, or a market with too little activity). The rest of the page is unaffected.
      </Glass>
    );
  }
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 10, marginBottom: 22 }}>
      {data.map((m) => {
        const totalDepth = (m.depth?.yesTotal || 0) + (m.depth?.noTotal || 0);
        const yesPct = totalDepth ? (m.depth.yesTotal / totalDepth) * 100 : 50;
        const oiUp = m.flow && m.flow.oiChange > 0;
        return (
          <Glass key={m.ticker} hover={false} style={{ padding: "14px 16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 10 }}>
              <div style={{ fontSize: 14, fontWeight: 700 }}>{m.name}</div>
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, color: accent }}>{fmt(m.price,1)}%</div>
            </div>
            {m.depth && (
              <>
                <div style={{ fontSize: 9.5, color: "var(--text-label)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>Order Book Depth (resting size)</div>
                <div style={{ height: 10, borderRadius: 5, overflow: "hidden", display: "flex", marginBottom: 6 }}>
                  <div style={{ width: `${yesPct}%`, background: "linear-gradient(90deg,#00C853,#00E676)" }} />
                  <div style={{ width: `${100-yesPct}%`, background: "linear-gradient(90deg,#FF3D71,#8C3B2B)" }} />
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10.5, color: "var(--text-secondary-a)", marginBottom: 10 }}>
                  <span>YES wall: {m.depth.yesTopSize ?? "—"} @ {m.depth.yesTopPrice ?? "—"}¢</span>
                  <span>NO wall: {m.depth.noTopSize ?? "—"} @ {m.depth.noTopPrice ?? "—"}¢</span>
                </div>
              </>
            )}
            {m.flow && (
              <div style={{ fontSize: 11, color: "var(--text-secondary-a)" }}>
                7d volume: <span style={{ color: "var(--text-primary)", fontWeight: 700 }}>{fmt(m.flow.totalVolume,0)}</span> ·
                {" "}Open interest: <span style={{ color: "var(--text-primary)", fontWeight: 700 }}>{fmt(m.flow.latestOI,0)}</span>
                {" "}<span style={{ color: oiUp ? "#00E676" : "#FF3D71" }}>{oiUp ? "▲" : "▼"} {fmt(Math.abs(m.flow.oiChange),0)} this week</span>
              </div>
            )}
          </Glass>
        );
      })}
    </div>
  );
}

function MarketCard({ title, options, meta, accent, live }) {
  return (
    <Glass hover={false} style={{ padding: "14px 16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
        <div style={{ fontSize: 13, fontWeight: 700 }}>{title}</div>
        {live !== undefined && (
          <span style={{
            fontSize: 8.5, fontWeight: 800, letterSpacing: "0.05em", borderRadius: 6, padding: "2px 6px", flexShrink: 0, marginLeft: 8,
            color: live ? "#08090B" : "var(--text-secondary-b)", background: live ? ACCENT.green : "var(--overlay-4)",
            border: live ? "none" : "1px solid var(--overlay-7)"
          }}>{live ? "● LIVE" : "SNAPSHOT"}</span>
        )}
      </div>
      {options.map((o,i) => <MarketBar key={i} name={o.name} pct={o.pct} accent={accent} />)}
      {meta && <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginTop: 6 }}>{meta}</div>}
    </Glass>
  );
}

const CHAMPIONSHIP_SNAPSHOT = {"fetchedAt": "2026-06-25", "teams": [{"team": "LAR", "kalshiPct": 17, "polyPct": 10}, {"team": "SEA", "kalshiPct": 8, "polyPct": 11}, {"team": "KC", "kalshiPct": 7, "polyPct": 5.8}, {"team": "BUF", "kalshiPct": 6, "polyPct": 8}, {"team": "BAL", "kalshiPct": 6, "polyPct": 6}, {"team": "DEN", "kalshiPct": 6, "polyPct": 4}, {"team": "SF", "kalshiPct": 5, "polyPct": 5}]};
const WNBA_CHAMPIONSHIP_SNAPSHOT = {"fetchedAt": "2026-08-04","teams": [{"team": "Minnesota", "kalshiPct": 29, "polyPct": 22},{"team": "New York", "kalshiPct": 19, "polyPct": 23},{"team": "Las Vegas", "kalshiPct": 18, "polyPct": 15}]};
const MLB_CHAMPIONSHIP_SNAPSHOT = {"fetchedAt": "2026-08-05","teams": [{"team": "Los Angeles Dodgers", "kalshiPct": 32.9, "polyPct": 35.0},{"team": "New York Yankees", "kalshiPct": 15.0, "polyPct": 14.0},{"team": "Boston Red Sox", "kalshiPct": 3.3, "polyPct": 4.5}]};
const OL_STARTERS = __OL_STARTERS__;
const INJURIES = __INJURIES__;
const KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2";
// Series tickers confirmed against kalshi.com; unconfirmed guesses are attempted but fail silently to snapshot.
const KALSHI_LEADER_SERIES = [
  { key: "Receiving Yards Leader", ticker: "KXLEADERNFLRYDS" },
  { key: "Passing Yards Leader", ticker: "KXLEADERNFLPYDS" },
  { key: "Rushing Yards Leader", ticker: "KXLEADERNFLRSHYDS" },
  { key: "Sacks Leader", ticker: "KXLEADERNFLSACK" },
  { key: "Interceptions Leader", ticker: "KXLEADERNFLINT" },
];

async function fetchKalshiSeries(ticker) {
  const res = await fetch(`${KALSHI_API}/markets?series_ticker=${ticker}&status=open&limit=10`);
  if (!res.ok) throw new Error(`status ${res.status}`);
  const data = await res.json();
  const markets = (data.markets || [])
    .map(m => ({ name: m.yes_sub_title || m.title, pct: Math.round(parseFloat(m.last_price_dollars || m.yes_bid_dollars || 0) * 100) }))
    .filter(o => o.name && !isNaN(o.pct))
    .sort((a,b) => b.pct - a.pct)
    .slice(0, 3);
  if (markets.length === 0) throw new Error("no open markets");
  return markets;
}

const POLY_TEAM_TO_CODE = {
  "Seattle Seahawks":"SEA","Los Angeles Rams":"LAR","Buffalo Bills":"BUF","Kansas City Chiefs":"KC",
  "Baltimore Ravens":"BAL","San Francisco 49ers":"SF","Los Angeles Chargers":"LAC","Cincinnati Bengals":"CIN",
  "Denver Broncos":"DEN","Detroit Lions":"DET","Philadelphia Eagles":"PHI","Houston Texans":"HOU",
  "Green Bay Packers":"GB","Chicago Bears":"CHI","New England Patriots":"NE","Dallas Cowboys":"DAL",
  "Jacksonville Jaguars":"JAX","Minnesota Vikings":"MIN","Tampa Bay Buccaneers":"TB","Cleveland Browns":"CLE",
};

async function fetchPolymarketChampionship() {
  const res = await fetch(`https://gamma-api.polymarket.com/events?slug=big-game-champion-2027`);
  if (!res.ok) throw new Error(`status ${res.status}`);
  const data = await res.json();
  const event = Array.isArray(data) ? data[0] : data;
  if (!event || !event.markets) throw new Error("no markets in response");
  const out = {};
  event.markets.forEach(m => {
    const code = POLY_TEAM_TO_CODE[m.groupItemTitle || m.question] || null;
    let price = null;
    try {
      const prices = JSON.parse(m.outcomePrices || "[]");
      price = prices && prices[0] ? parseFloat(prices[0]) * 100 : null;
    } catch (e) {}
    if (code && price !== null && !isNaN(price)) out[code] = Math.round(price * 10) / 10;
  });
  if (Object.keys(out).length === 0) throw new Error("no teams parsed");
  return out;
}

// =====================================================================
// GEX-STYLE MARKET DEPTH & FLOW
// Order book depth = where real resting size is stacked (the "gravity" walls).
// Open interest trend = where positions are actively building, not just where price sits.
// =====================================================================
async function fetchTopMarketTickers(seriesTicker, limit = 3) {
  const res = await fetch(`${KALSHI_API}/markets?series_ticker=${seriesTicker}&status=open&limit=20`);
  if (!res.ok) throw new Error(`status ${res.status}`);
  const data = await res.json();
  if (!data.markets || data.markets.length === 0) throw new Error("no markets");
  return data.markets
    .map(m => ({
      ticker: m.ticker,
      name: m.yes_sub_title || m.title,
      price: Math.round(parseFloat(m.last_price_dollars || m.yes_bid_dollars || 0) * 1000) / 10,
    }))
    .filter(m => m.ticker && m.name)
    .sort((a, b) => b.price - a.price)
    .slice(0, limit);
}

async function fetchMarketDepth(ticker) {
  const res = await fetch(`${KALSHI_API}/markets/${ticker}/orderbook`);
  if (!res.ok) throw new Error(`status ${res.status}`);
  const data = await res.json();
  const ob = data.orderbook || data;
  const yesLevels = ob.yes || [];
  const noLevels = ob.no || [];
  if (yesLevels.length === 0 && noLevels.length === 0) throw new Error("empty orderbook");
  const sum = (levels) => levels.reduce((s, lvl) => s + (Array.isArray(lvl) ? lvl[1] : (lvl.count || lvl.size || 0)), 0);
  const topLevel = (levels) => {
    if (!levels.length) return null;
    return levels.reduce((a, b) => {
      const aSize = Array.isArray(a) ? a[1] : (a.count || a.size || 0);
      const bSize = Array.isArray(b) ? b[1] : (b.count || b.size || 0);
      return bSize > aSize ? b : a;
    });
  };
  const yesTop = topLevel(yesLevels);
  const noTop = topLevel(noLevels);
  return {
    yesTotal: sum(yesLevels), noTotal: sum(noLevels),
    yesTopPrice: yesTop ? (Array.isArray(yesTop) ? yesTop[0] : yesTop.price) : null,
    yesTopSize: yesTop ? (Array.isArray(yesTop) ? yesTop[1] : (yesTop.count || yesTop.size)) : null,
    noTopPrice: noTop ? (Array.isArray(noTop) ? noTop[0] : noTop.price) : null,
    noTopSize: noTop ? (Array.isArray(noTop) ? noTop[1] : (noTop.count || noTop.size)) : null,
  };
}

async function fetchMarketFlow(ticker) {
  const end = Math.floor(Date.now() / 1000);
  const start = end - 7 * 24 * 3600;
  const res = await fetch(`${KALSHI_API}/markets/${ticker}/candlesticks?start_ts=${start}&end_ts=${end}&period_interval=1440`);
  if (!res.ok) throw new Error(`status ${res.status}`);
  const data = await res.json();
  const candles = data.candlesticks || [];
  if (candles.length === 0) throw new Error("no candles");
  const vol = (c) => parseFloat(c.volume_fp ?? c.volume ?? 0);
  const oi = (c) => parseFloat(c.open_interest_fp ?? c.open_interest ?? 0);
  const totalVolume = candles.reduce((s, c) => s + vol(c), 0);
  const latestOI = oi(candles[candles.length - 1]);
  const firstOI = oi(candles[0]);
  const oiSeries = candles.map(oi); // real daily points — only sparkline data we actually have
  return { totalVolume, latestOI, oiChange: latestOI - firstOI, oiSeries };
}

async function fetchDepthAndFlowPanel(seriesTicker, limit = 3) {
  const markets = await fetchTopMarketTickers(seriesTicker, limit);
  const results = await Promise.all(markets.map(async (m) => {
    let depth = null, flow = null;
    try { depth = await fetchMarketDepth(m.ticker); } catch (e) {}
    try { flow = await fetchMarketFlow(m.ticker); } catch (e) {}
    return { ...m, depth, flow };
  }));
  return results.filter(r => r.depth || r.flow);
}

async function fetchKalshiChampionship() {
  // best-effort ticker guess, matching Kalshi's other multi-outcome naming conventions
  const attempts = ["KXNFLCHAMP", "KXSBCHAMP", "KXNFLGAME-CHAMP"];
  for (const ticker of attempts) {
    try {
      const res = await fetch(`${KALSHI_API}/markets?series_ticker=${ticker}&status=open&limit=40`);
      if (!res.ok) continue;
      const data = await res.json();
      if (!data.markets || data.markets.length === 0) continue;
      const out = {};
      data.markets.forEach(m => {
        const code = Object.values(TEAM_NAMES).includes(m.yes_sub_title) ?
          Object.keys(TEAM_NAMES).find(k => TEAM_NAMES[k] === m.yes_sub_title) : null;
        const pct = Math.round(parseFloat(m.last_price_dollars || m.yes_bid_dollars || 0) * 1000) / 10;
        if (code && !isNaN(pct)) out[code] = pct;
      });
      if (Object.keys(out).length > 0) return out;
    } catch (e) { /* try next ticker */ }
  }
  throw new Error("no working championship ticker found");
}

// WNBA championship — confirmed tickers (not guessed): Kalshi series KXWNBA, Polymarket event wnba-2026-champion-464
async function fetchWnbaPolymarketChampionship() {
  const res = await fetch(`https://gamma-api.polymarket.com/events?slug=wnba-2026-champion-464`);
  if (!res.ok) throw new Error(`status ${res.status}`);
  const data = await res.json();
  const event = Array.isArray(data) ? data[0] : data;
  if (!event || !event.markets) throw new Error("no markets in response");
  const out = {};
  event.markets.forEach(m => {
    const title = m.groupItemTitle || m.question || "";
    // poly titles are full team names ("Minnesota Lynx") — key on the city/first-word to match our team naming
    const city = title.replace(/\s+(Lynx|Liberty|Aces|Dream|Fever|Wings|Valkyries|Sparks|Mercury|Tempo|Mystics|Fire|Storm|Sky|Sun)$/i, "").trim();
    let price = null;
    try {
      const prices = JSON.parse(m.outcomePrices || "[]");
      price = prices && prices[0] ? parseFloat(prices[0]) * 100 : null;
    } catch (e) {}
    if (city && price !== null && !isNaN(price)) out[city] = Math.round(price * 10) / 10;
  });
  if (Object.keys(out).length === 0) throw new Error("no teams parsed");
  return out;
}

async function fetchWnbaKalshiChampionship() {
  const res = await fetch(`${KALSHI_API}/markets?series_ticker=KXWNBA&status=open&limit=40`);
  if (!res.ok) throw new Error(`status ${res.status}`);
  const data = await res.json();
  if (!data.markets || data.markets.length === 0) throw new Error("no open markets");
  const out = {};
  data.markets.forEach(m => {
    const city = m.yes_sub_title;
    const pct = Math.round(parseFloat(m.last_price_dollars || m.yes_bid_dollars || 0) * 1000) / 10;
    if (city && !isNaN(pct)) out[city] = pct;
  });
  if (Object.keys(out).length === 0) throw new Error("no teams parsed");
  return out;
}

// MLB World Series champion — Polymarket slug confirmed real (mlb-world-series-champion-2026, $38.3M
// traded as of Aug 2026). Kalshi's exact ticker isn't confirmed, so try candidates defensively.
async function fetchMlbPolymarketChampionship() {
  const res = await fetch(`https://gamma-api.polymarket.com/events?slug=mlb-world-series-champion-2026`);
  if (!res.ok) throw new Error(`status ${res.status}`);
  const data = await res.json();
  const event = Array.isArray(data) ? data[0] : data;
  if (!event || !event.markets) throw new Error("no markets in response");
  const out = {};
  event.markets.forEach(m => {
    const title = m.groupItemTitle || m.question || "";
    let price = null;
    try {
      const prices = JSON.parse(m.outcomePrices || "[]");
      price = prices && prices[0] ? parseFloat(prices[0]) * 100 : null;
    } catch (e) {}
    if (title && price !== null && !isNaN(price)) out[title] = Math.round(price * 10) / 10;
  });
  if (Object.keys(out).length === 0) throw new Error("no teams parsed");
  return out;
}

async function fetchMlbKalshiChampionship() {
  const attempts = ["KXMLBWS", "KXMLBWORLDSERIES", "KXWORLDSERIES"];
  for (const ticker of attempts) {
    try {
      const res = await fetch(`${KALSHI_API}/markets?series_ticker=${ticker}&status=open&limit=40`);
      if (!res.ok) continue;
      const data = await res.json();
      if (!data.markets || data.markets.length === 0) continue;
      const out = {};
      data.markets.forEach(m => {
        const team = m.yes_sub_title;
        const pct = Math.round(parseFloat(m.last_price_dollars || m.yes_bid_dollars || 0) * 1000) / 10;
        if (team && !isNaN(pct)) out[team] = pct;
      });
      if (Object.keys(out).length > 0) return out;
    } catch (e) { /* try next */ }
  }
  throw new Error("no working World Series ticker found");
}

function MarketPulseView({ sport }) {
  const [liveLeaders, setLiveLeaders] = useState({});
  const [liveStatus, setLiveStatus] = useState("loading"); // loading | done
  const [lastChecked, setLastChecked] = useState(null);
  const [liveChampKalshi, setLiveChampKalshi] = useState(null);
  const [liveChampPoly, setLiveChampPoly] = useState(null);
  const [wnbaChampKalshi, setWnbaChampKalshi] = useState(null);
  const [wnbaChampPoly, setWnbaChampPoly] = useState(null);
  const [wnbaStatus, setWnbaStatus] = useState("loading");
  const [wnbaLastChecked, setWnbaLastChecked] = useState(null);

  async function loadLive() {
    setLiveStatus("loading");
    const results = {};
    await Promise.all(KALSHI_LEADER_SERIES.map(async ({ key, ticker }) => {
      try {
        results[key] = await fetchKalshiSeries(ticker);
      } catch (e) {
        // leave undefined -> falls back to snapshot for this card only
      }
    }));
    setLiveLeaders(results);

    try { setLiveChampPoly(await fetchPolymarketChampionship()); } catch (e) { setLiveChampPoly(null); }
    try { setLiveChampKalshi(await fetchKalshiChampionship()); } catch (e) { setLiveChampKalshi(null); }

    setLiveStatus("done");
    setLastChecked(new Date());
  }

  async function loadWnbaLive() {
    setWnbaStatus("loading");
    try { setWnbaChampPoly(await fetchWnbaPolymarketChampionship()); } catch (e) { setWnbaChampPoly(null); }
    try { setWnbaChampKalshi(await fetchWnbaKalshiChampionship()); } catch (e) { setWnbaChampKalshi(null); }
    setWnbaStatus("done");
    setWnbaLastChecked(new Date());
  }

  const [mlbChampKalshi, setMlbChampKalshi] = useState(null);
  const [mlbChampPoly, setMlbChampPoly] = useState(null);
  const [mlbStatus, setMlbStatus] = useState("loading");
  const [mlbLastChecked, setMlbLastChecked] = useState(null);

  async function loadMlbLive() {
    setMlbStatus("loading");
    try { setMlbChampPoly(await fetchMlbPolymarketChampionship()); } catch (e) { setMlbChampPoly(null); }
    try { setMlbChampKalshi(await fetchMlbKalshiChampionship()); } catch (e) { setMlbChampKalshi(null); }
    setMlbStatus("done");
    setMlbLastChecked(new Date());
  }

  const [nflDepthFlow, setNflDepthFlow] = useState(null);
  const [wnbaDepthFlow, setWnbaDepthFlow] = useState(null);
  const [depthFlowStatus, setDepthFlowStatus] = useState("loading");

  async function loadDepthFlow(currentSport) {
    setDepthFlowStatus("loading");
    try {
      if (currentSport === "nfl") {
        // NFL championship ticker is a best-effort guess elsewhere; try the same candidates here
        for (const ticker of ["KXNFLCHAMP", "KXSBCHAMP"]) {
          try {
            const res = await fetchDepthAndFlowPanel(ticker, 3);
            if (res.length > 0) { setNflDepthFlow(res); break; }
          } catch (e) { /* try next */ }
        }
      } else {
        const res = await fetchDepthAndFlowPanel("KXWNBA", 3);
        if (res.length > 0) setWnbaDepthFlow(res);
      }
    } catch (e) { /* leave null -> panel shows "unavailable" */ }
    setDepthFlowStatus("done");
  }

  useEffect(() => {
    if (sport==="nfl") { loadLive(); loadDepthFlow("nfl"); }
    else if (sport==="wnba") { loadWnbaLive(); loadDepthFlow("wnba"); }
    else { loadMlbLive(); }
  }, [sport]);

  const wnbaChampionshipRows = useMemo(() => {
    return WNBA_CHAMPIONSHIP_SNAPSHOT.teams.map(snap => {
      const kalshi = wnbaChampKalshi && wnbaChampKalshi[snap.team] !== undefined ? wnbaChampKalshi[snap.team] : snap.kalshiPct;
      const poly = wnbaChampPoly && wnbaChampPoly[snap.team] !== undefined ? wnbaChampPoly[snap.team] : snap.polyPct;
      const kalshiLive = !!(wnbaChampKalshi && wnbaChampKalshi[snap.team] !== undefined);
      const polyLive = !!(wnbaChampPoly && wnbaChampPoly[snap.team] !== undefined);
      const blend = (kalshi + poly) / 2;
      return { team: snap.team, kalshi, poly, kalshiLive, polyLive, blend, divergence: Math.abs(kalshi - poly) };
    }).sort((a,b) => b.blend - a.blend);
  }, [wnbaChampKalshi, wnbaChampPoly]);

  const mlbChampionshipRows = useMemo(() => {
    return MLB_CHAMPIONSHIP_SNAPSHOT.teams.map(snap => {
      const kalshi = mlbChampKalshi && mlbChampKalshi[snap.team] !== undefined ? mlbChampKalshi[snap.team] : snap.kalshiPct;
      const poly = mlbChampPoly && mlbChampPoly[snap.team] !== undefined ? mlbChampPoly[snap.team] : snap.polyPct;
      const kalshiLive = !!(mlbChampKalshi && mlbChampKalshi[snap.team] !== undefined);
      const polyLive = !!(mlbChampPoly && mlbChampPoly[snap.team] !== undefined);
      const blend = (kalshi + poly) / 2;
      return { team: snap.team, kalshi, poly, kalshiLive, polyLive, blend, divergence: Math.abs(kalshi - poly) };
    }).sort((a,b) => b.blend - a.blend);
  }, [mlbChampKalshi, mlbChampPoly]);

  if (sport === "mlb") {
    return (
      <div className="fade-in">
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
          <span style={{ fontSize: 11, fontWeight: 800, color: "#6EC9F2", border: "1px solid #6EC9F255", borderRadius: 999, padding: "4px 12px" }}>⚾ MLB MARKET PULSE</span>
          <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>{mlbStatus==="loading" ? "checking for live prices…" : `checked ${mlbLastChecked ? mlbLastChecked.toLocaleTimeString() : ""}`}</span>
        </div>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 10, fontWeight: 700 }}>🏆 World Series Odds — Kalshi × Polymarket Blend</div>
        <Glass hover={false} style={{ padding: "14px 16px", marginBottom: 22 }}>
          <div style={{ display: "flex", gap: 16, fontSize: 10, color: "var(--text-secondary-b)", marginBottom: 10, paddingBottom: 8, borderBottom: "1px solid var(--overlay-5)" }}>
            <div style={{ width: 170 }}>TEAM</div>
            <div style={{ width: 70 }}>KALSHI</div>
            <div style={{ width: 70 }}>POLYMARKET</div>
            <div style={{ width: 70 }}>BLEND</div>
            <div>NOTE</div>
          </div>
          {mlbChampionshipRows.map(r => (
            <div key={r.team} style={{ display: "flex", gap: 16, alignItems: "center", fontSize: 12.5, padding: "6px 0" }}>
              <div style={{ width: 170, fontWeight: 700 }}>{r.team}</div>
              <div style={{ width: 70, fontFamily: "'JetBrains Mono', monospace", color: r.kalshiLive ? "#00E676" : "var(--text-secondary-a)" }}>{fmt(r.kalshi,1)}% {r.kalshiLive && "●"}</div>
              <div style={{ width: 70, fontFamily: "'JetBrains Mono', monospace", color: r.polyLive ? "#00E676" : "var(--text-secondary-a)" }}>{fmt(r.poly,1)}% {r.polyLive && "●"}</div>
              <div style={{ width: 70, fontFamily: "'JetBrains Mono', monospace", fontWeight: 800, color: "#6EC9F2" }}>{fmt(r.blend,1)}%</div>
              <div style={{ fontSize: 11, color: r.divergence >= 4 ? "#FF3D71" : "var(--text-tertiary)" }}>{r.divergence >= 4 ? `⚡ ${fmt(r.divergence,1)}pt disagreement` : ""}</div>
            </div>
          ))}
          <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginTop: 10 }}>
            <span style={{color:"#00E676"}}>●</span> = fetched live this page load. Un-marked values are the last confirmed
            snapshot ({MLB_CHAMPIONSHIP_SNAPSHOT.fetchedAt}). Polymarket's ticker is confirmed real (mlb-world-series-champion-2026,
            $38.3M traded); Kalshi's exact World Series ticker isn't publicly confirmed, so it tries a few known naming
            patterns and falls back honestly if none work. Blend is a simple average, not a weighted model.
          </div>
        </Glass>
        <Glass hover={false} style={{ padding: "16px 20px", color: "var(--text-secondary-b)", fontSize: 12.5 }}>
          Player prop markets (HR leader, batting title, Cy Young) aren't wired up for MLB yet — only the World Series
          blend above. Ask to have those added if useful.
        </Glass>
      </div>
    );
  }

  if (sport === "wnba") {
    return (
      <div className="fade-in">
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
          <span style={{ fontSize: 11, fontWeight: 800, color: "#FF8A00", border: "1px solid #FF8A0055", borderRadius: 999, padding: "4px 12px" }}>🏀 WNBA MARKET PULSE</span>
          <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>{wnbaStatus==="loading" ? "checking for live prices…" : `checked ${wnbaLastChecked ? wnbaLastChecked.toLocaleTimeString() : ""}`}</span>
        </div>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 10, fontWeight: 700 }}>🏆 Championship Odds — Kalshi × Polymarket Blend</div>
        <Glass hover={false} style={{ padding: "14px 16px", marginBottom: 22 }}>
          <div style={{ display: "flex", gap: 16, fontSize: 10, color: "var(--text-secondary-b)", marginBottom: 10, paddingBottom: 8, borderBottom: "1px solid var(--overlay-5)" }}>
            <div style={{ width: 90 }}>TEAM</div>
            <div style={{ width: 70 }}>KALSHI</div>
            <div style={{ width: 70 }}>POLYMARKET</div>
            <div style={{ width: 70 }}>BLEND</div>
            <div>NOTE</div>
          </div>
          {wnbaChampionshipRows.map(r => (
            <div key={r.team} style={{ display: "flex", gap: 16, alignItems: "center", fontSize: 12.5, padding: "6px 0" }}>
              <div style={{ width: 90, fontWeight: 700 }}>{r.team}</div>
              <div style={{ width: 70, fontFamily: "'JetBrains Mono', monospace", color: r.kalshiLive ? "#00E676" : "var(--text-secondary-a)" }}>{fmt(r.kalshi,1)}% {r.kalshiLive && "●"}</div>
              <div style={{ width: 70, fontFamily: "'JetBrains Mono', monospace", color: r.polyLive ? "#00E676" : "var(--text-secondary-a)" }}>{fmt(r.poly,1)}% {r.polyLive && "●"}</div>
              <div style={{ width: 70, fontFamily: "'JetBrains Mono', monospace", fontWeight: 800, color: "#FF8A00" }}>{fmt(r.blend,1)}%</div>
              <div style={{ fontSize: 11, color: r.divergence >= 4 ? "#FF3D71" : "var(--text-tertiary)" }}>{r.divergence >= 4 ? `⚡ ${fmt(r.divergence,1)}pt disagreement` : ""}</div>
            </div>
          ))}
          <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginTop: 10 }}>
            <span style={{color:"#00E676"}}>●</span> = fetched live this page load. Un-marked values are the last confirmed
            snapshot ({WNBA_CHAMPIONSHIP_SNAPSHOT.fetchedAt}). Tickers confirmed directly against Kalshi (KXWNBA) and
            Polymarket (wnba-2026-champion-464) — not guessed. Blend is a simple average, not a weighted model.
          </div>
        </Glass>

        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 10, fontWeight: 700 }}>🌊 Market Depth & Flow (GEX-style)</div>
        <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 10 }}>Order book depth shows where real resting size is stacked — the "gravity" walls. Open interest trend shows where positions are actively building, not just where price sits.</div>
        <DepthFlowPanel data={wnbaDepthFlow} accent="#FF8A00" status={depthFlowStatus} />

        <Glass hover={false} style={{ padding: "16px 20px", color: "var(--text-secondary-b)", fontSize: 12.5 }}>
          Season-long leader races (points/rebounds/assists leader, MVP) aren't wired up for WNBA yet — only the
          championship blend above. Ask to have those added if useful.
        </Glass>
      </div>
    );
  }


  const liveCount = Object.keys(liveLeaders).length;

  const championshipRows = useMemo(() => {
    const teams = CHAMPIONSHIP_SNAPSHOT.teams.map(t => t.team);
    return teams.map(team => {
      const snap = CHAMPIONSHIP_SNAPSHOT.teams.find(t => t.team === team);
      const kalshi = liveChampKalshi && liveChampKalshi[team] !== undefined ? liveChampKalshi[team] : snap.kalshiPct;
      const poly = liveChampPoly && liveChampPoly[team] !== undefined ? liveChampPoly[team] : snap.polyPct;
      const kalshiLive = !!(liveChampKalshi && liveChampKalshi[team] !== undefined);
      const polyLive = !!(liveChampPoly && liveChampPoly[team] !== undefined);
      const blend = (kalshi + poly) / 2;
      const divergence = Math.abs(kalshi - poly);
      return { team, kalshi, poly, kalshiLive, polyLive, blend, divergence };
    }).sort((a,b) => b.blend - a.blend);
  }, [liveChampKalshi, liveChampPoly]);

  return (

    <div className="fade-in">
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 11, fontWeight: 800, color: ACCENT.teal, border: `1px solid ${ACCENT.teal}55`, borderRadius: 999, padding: "4px 12px" }}>🏈 NFL MARKET PULSE</span>
      </div>
      <Glass hover={false} style={{ padding: "12px 16px", marginBottom: 18, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <div style={{ fontSize: 12.5, color: "var(--text-body)" }}>
          <b style={{ color: ACCENT.amber }}>Kalshi</b> (CFTC-regulated exchange) — contract price = market-implied probability, no vig.
          {liveStatus === "loading" && <span style={{ color: "var(--text-tertiary)" }}> · checking for live prices…</span>}
          {liveStatus === "done" && <span style={{ color: liveCount > 0 ? ACCENT.green : "var(--text-tertiary)" }}> · {liveCount} of {KALSHI_LEADER_SERIES.length} leader markets live{lastChecked ? ` as of ${lastChecked.toLocaleTimeString()}` : ""}</span>}
        </div>
        <button onClick={loadLive} className="bubble-btn" style={{ padding: "6px 14px", borderRadius: 999, border: "none", cursor: "pointer", background: "var(--overlay-5)", color: "var(--text-body)", fontSize: 11, fontWeight: 700 }}>
          {liveStatus === "loading" ? "Checking…" : "🔄 Refresh Live"}
        </button>
      </Glass>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", fontWeight: 700 }}>🏆 Championship Odds — Kalshi × Polymarket Blend</div>
      </div>
      <Glass hover={false} style={{ padding: "14px 16px", marginBottom: 22 }}>
        <div style={{ display: "flex", gap: 16, fontSize: 10, color: "var(--text-secondary-b)", marginBottom: 10, paddingBottom: 8, borderBottom: "1px solid var(--overlay-5)" }}>
          <div style={{ width: 60 }}>TEAM</div>
          <div style={{ width: 70 }}>KALSHI</div>
          <div style={{ width: 70 }}>POLYMARKET</div>
          <div style={{ width: 70 }}>BLEND</div>
          <div>NOTE</div>
        </div>
        {championshipRows.map(r => (
          <div key={r.team} style={{ display: "flex", gap: 16, alignItems: "center", fontSize: 12.5, padding: "6px 0" }}>
            <div style={{ width: 60, fontWeight: 700 }}>{TEAM_NAMES[r.team] || r.team}</div>
            <div style={{ width: 70, fontFamily: "'JetBrains Mono', monospace", color: r.kalshiLive ? ACCENT.green : "var(--text-secondary-a)" }}>{fmt(r.kalshi,1)}% {r.kalshiLive && "●"}</div>
            <div style={{ width: 70, fontFamily: "'JetBrains Mono', monospace", color: r.polyLive ? ACCENT.green : "var(--text-secondary-a)" }}>{fmt(r.poly,1)}% {r.polyLive && "●"}</div>
            <div style={{ width: 70, fontFamily: "'JetBrains Mono', monospace", fontWeight: 800, color: ACCENT.amber }}>{fmt(r.blend,1)}%</div>
            <div style={{ fontSize: 11, color: r.divergence >= 4 ? ACCENT.rose : "var(--text-tertiary)" }}>{r.divergence >= 4 ? `⚡ ${fmt(r.divergence,1)}pt disagreement` : ""}</div>
          </div>
        ))}
        <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginTop: 10 }}>
          <span style={{color:ACCENT.green}}>●</span> = fetched live this page load. Un-marked values are the last confirmed snapshot ({CHAMPIONSHIP_SNAPSHOT.fetchedAt}) — Kalshi's exact championship market ticker isn't publicly confirmed, so that side attempts a few known naming patterns and falls back honestly if none work. Blend is a simple average of whichever two numbers are showing, not a weighted model.
        </div>
      </Glass>

      <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 10, fontWeight: 700 }}>🌊 Market Depth & Flow (GEX-style)</div>
      <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginBottom: 10 }}>Order book depth shows where real resting size is stacked — the "gravity" walls. Open interest trend shows where positions are actively building, not just where price sits.</div>
      <DepthFlowPanel data={nflDepthFlow} accent={ACCENT.teal} status={depthFlowStatus} />

      <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 10, fontWeight: 700 }}>Season Leader Races</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, marginBottom: 22 }}>
        {MARKET_PULSE.leaders.map((l,i) => {
          const live = liveLeaders[l.category];
          const isLive = !!live;
          const options = isLive ? live : l.options;
          return <MarketCard key={i} title={l.category} options={options} accent={ACCENT.teal} live={isLive}
            meta={isLive ? "fetched live from Kalshi's API just now" : `snapshot from ${MARKET_PULSE.fetchedAt} · ${l.totalMarkets} players tracked`} />;
        })}
      </div>

      <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 10, fontWeight: 700 }}>Player Thresholds <span style={{color:"var(--text-tertiary)",fontWeight:400,textTransform:"none",letterSpacing:0}}>(snapshot)</span></div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, marginBottom: 22 }}>
        {MARKET_PULSE.playerThresholds.map((l,i) => <MarketCard key={i} title={l.title} options={l.options} accent={ACCENT.amber} live={false} meta={`snapshot from ${MARKET_PULSE.fetchedAt} · ${l.totalMarkets} market${l.totalMarkets>1?"s":""}`} />)}
      </div>
      <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 10, fontWeight: 700 }}>Team Win Totals <span style={{color:"var(--text-tertiary)",fontWeight:400,textTransform:"none",letterSpacing:0}}>(snapshot)</span></div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10, marginBottom: 22 }}>
        {MARKET_PULSE.winTotals.map((w,i) => <MarketCard key={i} title={TEAM_NAMES[w.team]||w.team} options={w.options.map(o=>({name:o.line,pct:o.pct}))} accent={ACCENT.violet} live={false} />)}
      </div>
      <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 10, fontWeight: 700 }}>Offseason Movement <span style={{color:"var(--text-tertiary)",fontWeight:400,textTransform:"none",letterSpacing:0}}>(snapshot)</span></div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10 }}>
        {MARKET_PULSE.transactions.map((t,i) => <MarketCard key={i} title={t.title} options={t.options} accent={ACCENT.rose} live={false} />)}
      </div>
      <div style={{ borderTop: "1px solid var(--overlay-4)", marginTop: 26, paddingTop: 14, fontSize: 11, color: "var(--text-tertiary)", lineHeight: 1.6 }}>
        <b style={{color:ACCENT.green}}>● LIVE</b> cards fetch directly from Kalshi's public API when this page loads — real-time, not stored anywhere.
        <b> SNAPSHOT</b> cards (thresholds, win totals, offseason movement) are a manual pull, since not every market has a confirmed public ticker to fetch by. If your browser or network blocks the live call, every card safely falls back to its snapshot value — nothing breaks.
      </div>
    </div>
  );
}

// =====================================================================
// LOCKS
// =====================================================================

// =====================================================================
// PARLAY MATH
// =====================================================================
function probToAmerican(p) {
  if (p <= 0 || p >= 1) return null;
  if (p >= 0.5) return Math.round(-100 * p / (1 - p));
  return Math.round(100 * (1 - p) / p);
}
function getGamelogSourceForLeg(leg) {
  let source = null, field = null, group = null;
  if (STAT_FIELD_MAP.skill[leg.stat]) { source = RECEIVERS.find(p => p.name === leg.player); field = STAT_FIELD_MAP.skill[leg.stat]; group = 'skill'; }
  else if (STAT_FIELD_MAP.qb[leg.stat]) { source = QBS.find(p => p.name === leg.player); field = STAT_FIELD_MAP.qb[leg.stat]; group = 'qb'; }
  else if (STAT_FIELD_MAP.k[leg.stat]) { source = KICKERS.find(p => p.name === leg.player); field = STAT_FIELD_MAP.k[leg.stat]; group = 'k'; }
  else if (STAT_FIELD_MAP.wnba[leg.stat]) { source = wnbaPlayers().find(p => p.name === leg.player); field = STAT_FIELD_MAP.wnba[leg.stat]; group = 'wnba'; }
  else if (STAT_FIELD_MAP.mlb_hit[leg.stat]) { source = mlbPlayers().find(p => p.name === leg.player && p.group === "hitting"); field = STAT_FIELD_MAP.mlb_hit[leg.stat]; group = 'mlb_hit'; }
  else if (STAT_FIELD_MAP.mlb_pitch[leg.stat]) { source = mlbPlayers().find(p => p.name === leg.player && p.group === "pitching"); field = STAT_FIELD_MAP.mlb_pitch[leg.stat]; group = 'mlb_pitch'; }
  if (!source || !source.gamelog) return null;
  return { source, field, group };
}
function gameKeyFor(group, g) {
  return (group === 'mlb_hit' || group === 'mlb_pitch') ? g.gamePk : g.game_id;
}
function legLineValue(l) {
  if (l.kind !== 'ladder') return null;
  return l.tranche === "p25" ? l.p25.line : l.tranche === "p75" ? l.p75.line : l.p50.line;
}
// The real fix for the independence bug: instead of a guessed "same-team boost," this finds
// actual overlapping games between two same-team players and computes how often BOTH really
// cleared their lines together, vs. how often that'd happen if the legs were truly independent.
// Requires 6+ shared real games before it trusts the estimate — otherwise leaves that pair
// as independent, same as before, rather than adjusting off too small a sample.
function empiricalJointHitRate(legA, lineA, legB, lineB) {
  if (!legA.team || legA.team !== legB.team) return null;
  const srcA = getGamelogSourceForLeg(legA);
  const srcB = getGamelogSourceForLeg(legB);
  if (!srcA || !srcB) return null;
  const mapB = new Map();
  srcB.source.gamelog.forEach(g => { const k = gameKeyFor(srcB.group, g); if (k != null) mapB.set(k, g); });
  let both = 0, overlap = 0;
  srcA.source.gamelog.forEach(gA => {
    const k = gameKeyFor(srcA.group, gA);
    const gB = mapB.get(k);
    if (!gB || gA[srcA.field] === undefined || gB[srcB.field] === undefined) return;
    overlap++;
    if (gA[srcA.field] >= lineA && gB[srcB.field] >= lineB) both++;
  });
  if (overlap < 6) return null;
  return { jointRate: both / overlap, overlap };
}

// Full breakdown: naive (independence-assumed) probability, correlation-adjusted probability,
// and which specific pairs got a real adjustment applied. Used where this needs to be shown
// to the user (the slip itself); comboProb() below stays a plain number for every other caller.
function comboProbDetailed(legs) {
  const naive = legs.reduce((acc, l) => acc * (legProb(l) / 100), 1);
  if (legs.length < 2) return { prob: naive, naive, adjustments: [] };
  let adjusted = naive;
  const adjustments = [];
  for (let i = 0; i < legs.length; i++) {
    for (let j = i + 1; j < legs.length; j++) {
      const a = legs[i], b = legs[j];
      const lineA = legLineValue(a), lineB = legLineValue(b);
      if (lineA == null || lineB == null) continue;
      const result = empiricalJointHitRate(a, lineA, b, lineB);
      if (!result) continue;
      const naivePair = (legProb(a) / 100) * (legProb(b) / 100);
      if (naivePair < 0.001) continue;
      const factor = result.jointRate / naivePair;
      adjusted *= factor;
      adjustments.push({ playerA: a.player, playerB: b.player, factor, overlap: result.overlap, jointRate: result.jointRate });
    }
  }
  return { prob: Math.max(0.001, Math.min(0.999, adjusted)), naive, adjustments };
}
function comboProb(legs) {
  return comboProbDetailed(legs).prob;
}
function legProb(l) {
  if (l.kind === "under") return l.testHit;
  if (l.kind === "binary") return l.testRate;
  if (l.kind === "future") return l.prob;
  return l.tranche === "p25" ? l.p25.testHit : l.tranche === "p75" ? l.p75.testHit : l.p50.testHit;
}
function legLineLabel(l) {
  if (l.kind === "under") return `Under ${l.line}`;
  if (l.kind === "binary") return "Anytime";
  if (l.kind === "future") return l.selection;
  const t = l.tranche === "p25" ? l.p25 : l.tranche === "p75" ? l.p75 : l.p50;
  return `Over ${t.line}`;
}

// Build a flat, parlay-eligible pool from the Kalshi market snapshot
const FUTURES_POOL = (() => {
  const out = [];
  MARKET_PULSE.leaders.forEach(l => l.options.forEach(o => out.push({
    id: `future_${l.category}_${o.name}`.replace(/\s+/g,'_'), kind: "future",
    market: l.category, selection: o.name, prob: o.pct, player: o.name, stat: l.category, pos: "FUT", team: null
  })));
  MARKET_PULSE.playerThresholds.forEach(l => l.options.forEach(o => out.push({
    id: `future_${l.title}_${o.name}`.replace(/\s+/g,'_'), kind: "future",
    market: l.title, selection: o.name, prob: o.pct, player: o.name, stat: l.title, pos: "FUT", team: null
  })));
  MARKET_PULSE.winTotals.forEach(w => w.options.forEach(o => out.push({
    id: `future_${w.team}_${o.line}`.replace(/\s+/g,'_'), kind: "future",
    market: `${TEAM_NAMES[w.team]||w.team} Win Total`, selection: o.line, prob: o.pct,
    player: TEAM_NAMES[w.team]||w.team, stat: "Win Total", pos: "FUT", team: w.team
  })));
  MARKET_PULSE.transactions.forEach(t => t.options.forEach(o => out.push({
    id: `future_${t.title}_${o.name}`.replace(/\s+/g,'_'), kind: "future",
    market: t.title, selection: o.name, prob: o.pct, player: o.name, stat: t.title, pos: "FUT", team: null
  })));
  return out;
})();

// =====================================================================
// SLIP LEG ROW
// =====================================================================
function TrancheStep({ label, line, hit, accent, width }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
      <div style={{ width: 34, fontSize: 10.5, color: accent, fontWeight: 700 }}>{label}</div>
      <div style={{ flex: 1, height: 20, background: "var(--overlay-3)", borderRadius: 6, overflow: "hidden" }}>
        <div className="bar-fill" style={{ height: "100%", width: `${width}%`, background: `linear-gradient(90deg,${accent}40,${accent})`, display: "flex", alignItems: "center", paddingLeft: 8 }}>
          <span style={{ fontSize: 11, fontWeight: 800, color: "#0B0C0E", fontFamily: "'JetBrains Mono', monospace" }}>{line}+</span>
        </div>
      </div>
      <div style={{ width: 46, fontFamily: "'JetBrains Mono', monospace", fontSize: 11.5, color: "var(--text-secondary-a)", textAlign: "right" }}>{fmt(hit,0)}%</div>
    </div>
  );
}

const TEAM_DEFENSE = __TEAM_DEFENSE__;
const TRANCHE_ACCENT = { p25: TRANCHE_COLOR.p25, p50: TRANCHE_COLOR.p50, p75: TRANCHE_COLOR.p75 };
function AddButton({ inSlip, onClick, tranche }) {
  const accent = TRANCHE_ACCENT[tranche] || TRANCHE_COLOR.p50;
  return (
    <button onClick={onClick} className="bubble-btn" style={{
      padding: "8px 16px", borderRadius: 999, fontSize: 12.5, fontWeight: 800, border: "none", cursor: "pointer",
      background: inSlip ? "linear-gradient(135deg,#F2745A,#F2A900)" : `linear-gradient(135deg,${accent},${accent}CC)`,
      color: "#08090B", whiteSpace: "nowrap",
      boxShadow: inSlip ? "none" : `0 0 12px ${accent}66, 0 0 2px ${accent}AA inset`,
    }}>
      {inSlip ? "✓ In Slip" : `+ Add ${tranche ? tranche.toUpperCase() : ""}`}
    </button>
  );
}

// Honest confidence signal — the same testHit% means something very different backed by
// 8 out-of-sample games vs. 30. This surfaces that difference instead of hiding it.
function confidenceTier(testGames) {
  if (testGames == null) return null;
  if (testGames >= 20) return { label: "Strong", color: ACCENT.green, note: `${testGames} out-of-sample games` };
  if (testGames >= 10) return { label: "Moderate", color: ACCENT.amber, note: `${testGames} out-of-sample games` };
  return { label: "Limited", color: ACCENT.rose, note: `only ${testGames} out-of-sample games — treat with real caution` };
}
function ConfidenceBadge({ testGames }) {
  const tier = confidenceTier(testGames);
  if (!tier) return null;
  return (
    <span title={tier.note} style={{
      fontSize: 8.5, fontWeight: 800, color: tier.color, border: `1px solid ${tier.color}55`, borderRadius: 8,
      padding: "1px 6px", whiteSpace: "nowrap"
    }}>📊 {tier.label}</span>
  );
}

// =====================================================================
// MARKET LINE COMPARATOR — "where does the sportsbook line sit inside
// the modeled distribution?" Not auto-fetched (no paid odds API); you
// type in what you see on your own sportsbook, math runs instantly.
// =====================================================================
function classifyMarketLine(line, p25, p50, p75) {
  const spread = (p75 - p25) || 1;
  const neutralBand = spread * 0.08;
  let zone, direction, edgeScore, refTestHit, refLabel;
  if (line < p25) {
    zone = "Strong Over"; direction = "over"; edgeScore = (p25 - line) / spread;
  } else if (line < p50 - neutralBand) {
    zone = "Moderate Over"; direction = "over"; edgeScore = (p25 - line) / spread;
  } else if (line <= p50 + neutralBand) {
    zone = "Neutral / Pass"; direction = "neutral"; edgeScore = 0;
  } else if (line <= p75) {
    zone = "Moderate Under"; direction = "under"; edgeScore = (line - p75) / spread;
  } else {
    zone = "Strong Under"; direction = "under"; edgeScore = (line - p75) / spread;
  }
  return { zone, direction, edgeScore, spread };
}

function breakEvenProb(oddsStr) {
  const n = parseFloat(String(oddsStr).replace(/\+/g, ""));
  if (isNaN(n) || n === 0) return null;
  if (n < 0) return (Math.abs(n) / (Math.abs(n) + 100)) * 100;
  return (100 / (n + 100)) * 100;
}

const ZONE_COLOR = { "Strong Over": ACCENT.green, "Moderate Over": "#7FD98A", "Neutral / Pass": "var(--text-secondary-a)", "Moderate Under": "#F2A65A", "Strong Under": ACCENT.rose };

function MarketLineComparator({ e }) {
  const hasReal = !!e.realLine;
  const [open, setOpen] = useState(hasReal);
  const [line, setLine] = useState(hasReal ? String(e.realLine.line) : "");
  const [odds, setOdds] = useState(hasReal ? String(e.realLine.overPrice) : "-115");

  const lineNum = parseFloat(line);
  const valid = !isNaN(lineNum);
  const result = valid ? classifyMarketLine(lineNum, e.p25.line, e.p50.line, e.p75.line) : null;
  const beProb = breakEvenProb(odds);

  // calibration check — does this tranche's historical hit rate actually match its theoretical target?
  const calibration = useMemo(() => {
    const checks = [
      { label: "P25", actual: e.p25.testHit, target: 75 },
      { label: "P50", actual: e.p50.testHit, target: 50 },
      { label: "P75", actual: e.p75.testHit, target: 25 },
    ];
    return checks.map(c => ({ ...c, diff: c.actual - c.target, off: Math.abs(c.actual - c.target) > 12 }));
  }, [e]);
  const miscalibrated = calibration.some(c => c.off);

  const refHit = result?.direction === "under" ? e.p75.testHit : e.p25.testHit;

  return (
    <div style={{ marginTop: 6 }}>
      <button onClick={()=>setOpen(o=>!o)} style={{ background: "none", border: "none", color: hasReal ? ACCENT.green : "var(--text-secondary-b)", fontSize: 10.5, cursor: "pointer", padding: 0, textDecoration: "underline dotted", fontWeight: hasReal ? 700 : 400 }}>
        {hasReal ? `${open?"Hide":"Show"} · ✓ Real line found (${e.realLine.book})` : (open ? "Hide" : "📏 Compare to your sportsbook line")}
      </button>
      {open && (
        <div className="fade-in" style={{ marginTop: 8, padding: "10px 12px", background: "var(--overlay-1)", border: "1px solid var(--overlay-5)", borderRadius: 8 }}>
          {hasReal && (
            <div style={{ fontSize: 10, color: ACCENT.green, marginBottom: 8 }}>
              Auto-filled from {e.realLine.book} — edit below if you're checking a different book.
            </div>
          )}
          <div style={{ display: "flex", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
            <input placeholder="Line (e.g. 22.5)" value={line} onChange={ev=>setLine(ev.target.value)} style={{ width: 110, background: "var(--overlay-3)", border: "1px solid var(--overlay-6)", borderRadius: 6, padding: "5px 8px", color: "var(--text-primary)", fontSize: 12 }} />
            <input placeholder="Odds (e.g. -115)" value={odds} onChange={ev=>setOdds(ev.target.value)} style={{ width: 100, background: "var(--overlay-3)", border: "1px solid var(--overlay-6)", borderRadius: 6, padding: "5px 8px", color: "var(--text-primary)", fontSize: 12 }} />
          </div>
          {valid && result && (
            <div style={{ fontSize: 11.5, lineHeight: 1.7 }}>
              <div style={{ marginBottom: 4 }}>
                <span style={{ fontWeight: 800, color: ZONE_COLOR[result.zone] }}>{result.zone}</span>
                <span style={{ color: "var(--text-secondary-b)" }}> — line sits {fmt(Math.abs(result.edgeScore)*100,0)}% of the P25–P75 width {result.edgeScore>=0?"beyond":"short of"} the relevant quartile</span>
              </div>
              <div style={{ color: "var(--text-secondary-a)" }}>
                Historical hit rate near this zone: <b style={{color:"var(--text-body)"}}>{fmt(refHit,0)}%</b>
                {beProb !== null && <> · Break-even at {odds}: <b style={{color:"var(--text-body)"}}>{fmt(beProb,1)}%</b></>}
              </div>
              {beProb !== null && refHit != null && (
                <div style={{ marginTop: 4, color: refHit > beProb ? ACCENT.green : ACCENT.rose, fontWeight: 700 }}>
                  {refHit > beProb ? `✓ Historical rate clears break-even by ${fmt(refHit-beProb,1)}pt` : `⚠ Historical rate is below break-even by ${fmt(beProb-refHit,1)}pt`}
                </div>
              )}
              {miscalibrated && (
                <div style={{ marginTop: 6, fontSize: 10.5, color: "#F2A65A" }}>
                  ⚠ Calibration check: {calibration.filter(c=>c.off).map(c=>`${c.label} hit ${fmt(c.actual,0)}% historically vs a ~${c.target}% target`).join("; ")} — this zone hasn't tracked its theoretical rate closely, treat with extra caution.
                </div>
              )}
              <div style={{ marginTop: 6, fontSize: 9.5, color: "var(--text-tertiary)" }}>
                Reference hit rate is the nearest computed tranche (P25 or P75), not an exact rate at your typed line — treat as an approximation, not a precise probability.
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function LadderCard({ e, onAdd, inSlipTranches }) {
  return (
    <Glass hover={false} style={{ padding: "14px 16px" }} className="glass bounce-in">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 2 }}>
        <div>
          <div style={{ fontSize: 14.5, fontWeight: 800, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            {e.player}
            {e.teamChanged && <span title={`${e.team2024} → ${e.team2025}`} style={{ fontSize: 9, color: ACCENT.rose, border: `1px solid ${ACCENT.rose}55`, borderRadius: 8, padding: "1px 6px", fontWeight: 700 }}>TEAM CHANGE</span>}
            {e.isRookie && <span title="Single-season 2025 sample — no 2024 baseline to validate against" style={{ fontSize: 9, color: "#B4FF39", border: "1px solid #B4FF3955", borderRadius: 8, padding: "1px 6px", fontWeight: 700 }}>ROOKIE</span>}
          </div>
        </div>
        <ConfidenceBadge testGames={e.testGames} />
      </div>
      <div style={{ fontSize: 10.5, color: "var(--text-secondary-b)", marginBottom: 10 }}>{[e.pos, TEAM_NAMES[e.team]||e.team, e.stat].filter(Boolean).join(" · ")}</div>

      <div style={{ display: "flex", gap: 14, fontSize: 11, marginBottom: 8, flexWrap: "wrap" }}>
        <span style={{ color: TRANCHE_COLOR.p25 }}>P25: {fmt(e.p25.line,0)} <span style={{color:"var(--text-secondary-b)"}}>({fmt(e.p25.testHit,0)}%)</span></span>
        <span style={{ color: TRANCHE_COLOR.p50 }}>P50: {fmt(e.p50.line,0)} <span style={{color:"var(--text-secondary-b)"}}>({fmt(e.p50.testHit,0)}%)</span></span>
        <span style={{ color: TRANCHE_COLOR.p75 }}>P75: {fmt(e.p75.line,0)} <span style={{color:"var(--text-secondary-b)"}}>({fmt(e.p75.testHit,0)}%)</span></span>
      </div>
      {e.note && <div style={{ fontSize: 10.5, color: "var(--text-label)", marginBottom: 10, fontStyle: "italic" }}>📋 {e.note}</div>}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {["p25","p50","p75"].map(tr => (
          <AddButton key={tr} inSlip={inSlipTranches.includes(tr)} onClick={()=>onAdd(e, tr)} tranche={tr} />
        ))}
      </div>
      <MarketLineComparator e={e} />
    </Glass>
  );
}

// One card per PLAYER, not per stat — consolidates all of a player's bettable lines
// under a single header instead of repeating their name/team for every stat.
function PlayerPoolGroup({ player, entries, onAdd, inSlipTranchesFor }) {
  const first = entries[0];
  const hasRookie = entries.some(e => e.isRookie);
  const hasTeamChange = entries.some(e => e.teamChanged);
  const subtitle = [first.pos, TEAM_NAMES[first.team]||first.team].filter(Boolean).join(" · ");

  return (
    <Glass hover={false} style={{ padding: "14px 16px" }} className="glass bounce-in">
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", marginBottom: 2 }}>
        <div style={{ fontSize: 14.5, fontWeight: 800 }}>{player}</div>
        {hasTeamChange && <span title={`${first.team2024} → ${first.team2025}`} style={{ fontSize: 9, color: ACCENT.rose, border: `1px solid ${ACCENT.rose}55`, borderRadius: 8, padding: "1px 6px", fontWeight: 700 }}>TEAM CHANGE</span>}
        {hasRookie && <span style={{ fontSize: 9, color: "#B4FF39", border: "1px solid #B4FF3955", borderRadius: 8, padding: "1px 6px", fontWeight: 700 }}>ROOKIE</span>}
      </div>
      {subtitle && <div style={{ fontSize: 10.5, color: "var(--text-secondary-b)", marginBottom: 10 }}>{subtitle}</div>}

      {entries.map((e, i) => {
        const inSlip = inSlipTranchesFor(e);
        return (
          <div key={e.id} style={{ paddingTop: i > 0 ? 10 : 0, marginTop: i > 0 ? 10 : 0, borderTop: i > 0 ? "1px solid var(--overlay-4)" : "none" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-body)" }}>
                {e.kind === "future" ? e.market : e.stat}
              </div>
              <ConfidenceBadge testGames={e.testGames} />
            </div>
            {e.kind === "ladder" ? (
              <>
                <div style={{ display: "flex", gap: 14, fontSize: 11, marginBottom: 6 }}>
                  <span style={{ color: TRANCHE_COLOR.p25 }}>P25: {fmt(e.p25.line,0)} <span style={{color:"var(--text-secondary-b)"}}>({fmt(e.p25.testHit,0)}%)</span></span>
                  <span style={{ color: TRANCHE_COLOR.p50 }}>P50: {fmt(e.p50.line,0)} <span style={{color:"var(--text-secondary-b)"}}>({fmt(e.p50.testHit,0)}%)</span></span>
                  <span style={{ color: TRANCHE_COLOR.p75 }}>P75: {fmt(e.p75.line,0)} <span style={{color:"var(--text-secondary-b)"}}>({fmt(e.p75.testHit,0)}%)</span></span>
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {["p25","p50","p75"].map(tr => (
                    <AddButton key={tr} inSlip={inSlip.includes(tr)} onClick={()=>onAdd(e, tr)} tranche={tr} />
                  ))}
                </div>
                <MarketLineComparator e={e} />
              </>
            ) : (
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 11.5, color: "var(--text-secondary-a)" }}>
                  {e.kind === "under" ? `Under ${e.line}` : e.kind === "binary" ? "Anytime" : e.selection}
                  {" · "}{fmt(e.kind === "under" ? e.testHit : e.kind === "binary" ? e.testRate : e.prob, 0)}%
                </span>
                <AddButton inSlip={inSlip.length>0} onClick={()=>onAdd(e, "p50")} tranche={null} />
              </div>
            )}
          </div>
        );
      })}
    </Glass>
  );
}

// simple binary / under card for the pool browser
function PoolCard({ e, onAdd, inSlipTranches }) {
  const subtitle = e.kind === "future" ? e.market : [e.pos, TEAM_NAMES[e.team]||e.team, e.stat].filter(Boolean).join(" · ");

  if (e.kind === "ladder") {
    const maxLine = e.p75.line || 1;
    return (
      <Glass hover={false} style={{ padding: "12px 14px" }} className="glass bounce-in">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
          <div>
            <div style={{ fontSize: 13.5, fontWeight: 700, display:"flex", alignItems:"center", gap:6 }}>
              {e.player}
              {e.isRookie && <span style={{ fontSize: 9, color: "#B4FF39", border: "1px solid #B4FF3955", borderRadius: 8, padding: "1px 6px", fontWeight: 700 }}>ROOKIE</span>}
            </div>
            <div style={{ fontSize: 10.5, color: "var(--text-secondary-b)" }}>{subtitle}</div>
          </div>
        </div>
        <TrancheStep label="P25" line={e.p25.line} hit={e.p25.testHit} accent={ACCENT.green} width={(e.p25.line/maxLine)*100} />
        <TrancheStep label="P50" line={e.p50.line} hit={e.p50.testHit} accent={ACCENT.teal} width={(e.p50.line/maxLine)*100} />
        <TrancheStep label="P75" line={e.p75.line} hit={e.p75.testHit} accent={ACCENT.amber} width={100} />
        <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
          {["p25","p50","p75"].map(tr => (
            <AddButton key={tr} inSlip={inSlipTranches.includes(tr)} onClick={()=>onAdd(e, tr)} tranche={tr} />
          ))}
        </div>
      </Glass>
    );
  }

  const accent = e.kind === "binary" ? ACCENT.violet : e.kind === "under" ? ACCENT.rose : "#FFD54A";
  const hit = e.kind === "under" ? e.testHit : e.kind === "binary" ? e.testRate : e.prob;
  const lineTxt = e.kind === "under" ? `Under ${e.line}` : e.kind === "binary" ? "Anytime" : e.selection;
  return (
    <Glass hover={false} style={{ padding: "12px 14px" }} className="glass bounce-in">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 13.5, fontWeight: 700, display:"flex", alignItems:"center", gap:6 }}>
            {e.player}
            {e.kind==="future" && <span style={{ fontSize: 9, color: "#FFD54A", border: "1px solid #FFD54A55", borderRadius: 8, padding: "1px 6px", fontWeight: 700 }}>FUTURE</span>}
            {e.isRookie && <span style={{ fontSize: 9, color: "#B4FF39", border: "1px solid #B4FF3955", borderRadius: 8, padding: "1px 6px", fontWeight: 700 }}>ROOKIE</span>}
          </div>
          <div style={{ fontSize: 10.5, color: "var(--text-secondary-b)" }}>{subtitle} · {lineTxt}</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 800, color: accent, fontSize: 15 }}>{fmt(hit,0)}%</div>
          </div>
          <AddButton inSlip={inSlipTranches.length>0} onClick={()=>onAdd(e, "p50")} tranche={null} />
        </div>
      </div>
    </Glass>
  );
}

// =====================================================================
// PARLAY SLIP
// =====================================================================
// =====================================================================
// RESOLUTION ENGINE (for Submit + Tracking)
// =====================================================================
const STAT_FIELD_MAP = {
  skill: { 'Receptions':'catches', 'Receiving Yards':'yards', 'Targets':'targets', 'Rush Attempts':'rush_att', 'Rush Yards':'rush_yards' },
  qb: { 'Passing Yards':'yards', 'Completions':'completions', 'Passing TDs':'tds', 'QB Rush Yards':'rush_yards' },
  k: { 'FG Made':'made', 'Kicking Points':'points', 'FG Attempts':'attempts' },
  wnba: { 'Points':'pts', 'Rebounds':'reb', 'Assists':'ast', 'Steals':'stl', 'Blocks':'blk', 'Three-Pointers Made':'tpm' },
  mlb_hit: { 'Hits':'hits', 'HR':'hr', 'RBI':'rbi', 'Runs':'runs', 'Total Bases':'tb' },
  mlb_pitch: { 'Strikeouts':'so' },
};
// Real-data verification for Tracking specifically — extends beyond what submitBet's resolveLeg
// checks, so a leg that resolved via simulation at submission (no exact NFL data, or any WNBA/MLB
// leg) can still get an honest independent cross-check against actual embedded game logs where
// that data exists now. Not tied to a specific real calendar date — same "no live 2026 slate"
// honesty as everywhere else — just: does a real game in the dataset confirm this outcome.
function findRealGameForLeg(leg) {
  let source = null, field = null, opp = null;
  if (STAT_FIELD_MAP.skill[leg.stat]) { source = RECEIVERS.find(p => p.name === leg.player); field = STAT_FIELD_MAP.skill[leg.stat]; }
  else if (STAT_FIELD_MAP.qb[leg.stat]) { source = QBS.find(p => p.name === leg.player); field = STAT_FIELD_MAP.qb[leg.stat]; }
  else if (STAT_FIELD_MAP.k[leg.stat]) { source = KICKERS.find(p => p.name === leg.player); field = STAT_FIELD_MAP.k[leg.stat]; }
  else if (STAT_FIELD_MAP.wnba[leg.stat]) { source = wnbaPlayers().find(p => p.name === leg.player); field = STAT_FIELD_MAP.wnba[leg.stat]; }
  else if (STAT_FIELD_MAP.mlb_hit[leg.stat]) { source = mlbPlayers().find(p => p.name === leg.player && p.group === "hitting"); field = STAT_FIELD_MAP.mlb_hit[leg.stat]; }
  else if (STAT_FIELD_MAP.mlb_pitch[leg.stat]) { source = mlbPlayers().find(p => p.name === leg.player && p.group === "pitching"); field = STAT_FIELD_MAP.mlb_pitch[leg.stat]; }
  if (!source || !source.gamelog || source.gamelog.length === 0) return null;
  const games = source.gamelog.filter(g => g[field] !== undefined && g[field] !== null);
  if (!games.length) return null;
  const g = games[Math.floor(Math.random() * games.length)];
  const line = leg.tranche === "p25" ? null : null; // line resolved by caller against the leg's own tranche
  return { actual: g[field], game: g };
}
function parseGameId(gameId, team) {
  const parts = gameId.split('_'); // [season, week, away, home]
  const week = parseInt(parts[1], 10);
  const away = parts[2], home = parts[3];
  const opp = team === home ? away : team === away ? home : null;
  return { week, opp };
}
function findExactGame(entry) {
  let source = null, field = null;
  if (STAT_FIELD_MAP.skill[entry.stat]) { source = RECEIVERS.find(p => p.name === entry.player); field = STAT_FIELD_MAP.skill[entry.stat]; }
  else if (STAT_FIELD_MAP.qb[entry.stat]) { source = QBS.find(p => p.name === entry.player); field = STAT_FIELD_MAP.qb[entry.stat]; }
  else if (STAT_FIELD_MAP.k[entry.stat]) { source = KICKERS.find(p => p.name === entry.player); field = STAT_FIELD_MAP.k[entry.stat]; }
  if (!source) return null;
  const testGames = (source.gamelog || []).filter(g => g.season === 2025);
  if (!testGames.length) return null;
  const g = testGames[Math.floor(Math.random() * testGames.length)];
  const { week, opp } = parseGameId(g.game_id, entry.team);
  return { week, opp, actual: g[field] };
}
function resolveLeg(entry, tranche) {
  if (entry.kind === "future") return { status: "pending" };
  const gameInfo = findExactGame(entry);
  if (gameInfo && entry.kind === "ladder") {
    const tr = tranche === "p25" ? entry.p25 : tranche === "p75" ? entry.p75 : entry.p50;
    const hit = gameInfo.actual >= tr.line;
    return {
      status: hit ? "win" : "loss", exact: true, actual: gameInfo.actual, line: tr.line,
      week: gameInfo.week, opp: gameInfo.opp,
      p25hit: gameInfo.actual >= entry.p25.line, p50hit: gameInfo.actual >= entry.p50.line, p75hit: gameInfo.actual >= entry.p75.line,
    };
  }
  if (gameInfo && entry.kind === "under") {
    const hit = gameInfo.actual <= entry.line;
    return { status: hit ? "win" : "loss", exact: true, actual: gameInfo.actual, line: entry.line, week: gameInfo.week, opp: gameInfo.opp };
  }
  // fallback: no exact per-game data embedded for this stat (e.g. rush stats, anytime TD) — simulate from its own out-of-sample hit rate
  const prob = legProb({ ...entry, tranche, kind: entry.kind || "ladder" });
  const hit = Math.random() * 100 < prob;
  return { status: hit ? "win" : "loss", exact: false, simulatedProb: prob };
}
function adviceFor(leg) {
  if (leg.status === "pending") return "Resolves when the 2026 season concludes — futures can't be checked yet.";
  if (!leg.exact) return `No exact 2025 game log for this stat — resolved as a weighted simulation off its ${fmt(leg.simulatedProb,0)}% historical hit rate, not a specific box score.`;
  const oppTxt = leg.opp ? ` (Week ${leg.week} vs ${TEAM_NAMES[leg.opp]||leg.opp})` : (leg.week ? ` (Week ${leg.week})` : "");
  if (leg.status === "win") {
    const margin = leg.actual - leg.line;
    return `Cleared${oppTxt}: actual ${leg.actual} vs line ${leg.line}${margin<=1 ? " — close one." : "."}`;
  }
  if (leg.p25hit === false) return `Missed even at the safest P25 tranche${oppTxt}: actual ${leg.actual} vs P25 line. Tough matchup that week — check the Matchup tab for that opponent's profile.`;
  if (leg.p50hit) return `Would have hit at P50 or P25${oppTxt} — actual ${leg.actual} cleared those, just not your P75 line.`;
  if (leg.p25hit) return `Only the P25 tranche would have cleared${oppTxt} — actual ${leg.actual}.`;
  return `Missed${oppTxt}: actual ${leg.actual} vs line ${leg.line}.`;
}

// Formats the slip as clean text for pasting into DraftKings/FanDuel yourself — Statum never
// touches your sportsbook account or credentials, this just saves re-typing everything.
function copySlipToClipboard(legs, stake, payout) {
  const lines = [
    "STATUM PARLAY SLIP",
    "-------------------",
    ...legs.map(l => {
      const desc = l.kind === "future" ? l.market : `${l.stat} ${legLineLabel({...l, kind: l.kind})}`;
      return `${l.player} — ${desc}`;
    }),
    "-------------------",
    `Stake: $${fmt(stake,2)}  ·  Est. Payout: $${fmt(payout,2)}`,
  ];
  const text = lines.join("\n");
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).catch(() => {});
  }
  return text;
}

function ParlaySlip({ slip, onRemove, onClear, stake, setStake, aiSuggestion, onRunAI, onSubmit, minimized, setMinimized }) {
  const [justCopied, setJustCopied] = useState(false);
  if (slip.length === 0) return null;
  const legs = slip.map(s => ({ ...s.entry, tranche: s.tranche, kind: s.entry.kind || "ladder" }));
  const probDetail = comboProbDetailed(legs);
  const prob = probDetail.prob;
  const american = probToAmerican(prob);
  const decimal = 1 / prob;
  const payout = stake * decimal;

  if (minimized) {
    return (
      <div style={{
        position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 40,
        background: "rgba(12,13,16,0.94)", backdropFilter: "blur(20px)", borderTop: "1px solid var(--overlay-6)",
        boxShadow: "0 -6px 24px rgba(0,0,0,0.5)"
      }} className="fade-in">
        <div onClick={()=>setMinimized(false)} style={{
          width: "90%", maxWidth: 1600, margin: "0 auto", padding: "10px 20px", display: "flex", alignItems: "center",
          justifyContent: "space-between", cursor: "pointer", gap: 12, flexWrap: "wrap"
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 13, fontWeight: 800 }}>🎟️ Slip</span>
            <span style={{ background: ACCENT.amber, color: "#0B0C0E", borderRadius: 999, padding: "1px 8px", fontSize: 11, fontWeight: 800 }}>{slip.length}</span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12.5, color: ACCENT.teal }}>{fmt(prob*100,1)}%</span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12.5, color: ACCENT.amber }}>${fmt(payout,2)}</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ fontSize: 11.5, color: "var(--text-secondary-b)" }}>Tap to expand ▲</span>
            <button onClick={(e)=>{e.stopPropagation(); onClear();}} style={{ background: "none", border: "none", color: "var(--text-secondary-b)", fontSize: 11.5, cursor: "pointer" }}>Clear</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{
      position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 40,
      background: "rgba(12,13,16,0.92)", backdropFilter: "blur(20px)", borderTop: "1px solid var(--overlay-6)",
      boxShadow: "0 -10px 40px rgba(0,0,0,0.5)", maxHeight: "58vh", overflowY: "auto"
    }} className="fade-in">
      <div style={{ width: "90%", maxWidth: 1600, margin: "0 auto", padding: "14px 20px 20px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
          <div style={{ fontSize: 13, fontWeight: 800, display: "flex", alignItems: "center", gap: 8 }}>
            🎟️ PARLAY SLIP <span style={{ background: ACCENT.amber, color: "#0B0C0E", borderRadius: 999, padding: "1px 8px", fontSize: 11 }}>{slip.length}</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <button onClick={()=>setMinimized(true)} style={{ background: "none", border: "none", color: "var(--text-secondary-b)", fontSize: 11.5, cursor: "pointer" }}>Minimize ▼</button>
            <button onClick={onClear} style={{ background: "none", border: "none", color: "var(--text-secondary-b)", fontSize: 11.5, cursor: "pointer" }}>Clear all</button>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 12 }}>
          {slip.map((s,i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "var(--overlay-2)", borderRadius: 10, padding: "8px 12px" }}>
              <div style={{ fontSize: 12.5 }}>
                <b>{s.entry.player}</b> <span style={{ color: "var(--text-secondary-b)" }}>{s.entry.stat} · {legLineLabel({...s.entry, tranche:s.tranche, kind:s.entry.kind||"ladder"})}</span> <InjuryBadge playerName={s.entry.player} compact /> <OLInjuryBadge team={s.entry.team} pos={s.entry.pos} compact />
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: ACCENT.teal }}>{fmt(legProb({...s.entry, tranche:s.tranche, kind:s.entry.kind||"ladder"}),0)}%</span>
                <button onClick={()=>onRemove(i)} style={{ background: "none", border: "none", color: ACCENT.rose, fontSize: 15, cursor: "pointer", lineHeight: 1 }}>×</button>
              </div>
            </div>
          ))}
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "center", marginBottom: 10 }}>
          <div>
            <div style={{ fontSize: 9.5, color: "var(--text-label)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Combined Hit Prob.</div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 20, fontWeight: 800, color: ACCENT.teal }}>{fmt(prob*100,1)}%</div>
            {probDetail.adjustments.length > 0 && (
              <div title={probDetail.adjustments.map(a => `${a.playerA} + ${a.playerB}: hit together ${fmt(a.jointRate*100,0)}% of ${a.overlap} shared real games`).join(" · ")}
                style={{ fontSize: 9, color: prob > probDetail.naive ? ACCENT.green : ACCENT.amber, marginTop: 2 }}>
                {prob > probDetail.naive ? "▲" : "▼"} correlation-adjusted from {fmt(probDetail.naive*100,1)}% (independent)
              </div>
            )}
          </div>
          <div>
            <div style={{ fontSize: 9.5, color: "var(--text-label)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Fair Odds</div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 20, fontWeight: 800 }}>{american>0?`+${american}`:american} <span style={{fontSize:12,color:"var(--text-secondary-b)"}}>({decimal.toFixed(2)}x)</span></div>
          </div>
          <div>
            <div style={{ fontSize: 9.5, color: "var(--text-label)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Stake</div>
            <input type="number" value={stake} onChange={e=>setStake(Number(e.target.value)||0)} style={{
              width: 80, background: "var(--overlay-4)", border: "1px solid var(--overlay-6)", borderRadius: 8,
              color: "var(--text-primary)", padding: "5px 8px", fontFamily: "'JetBrains Mono', monospace", fontSize: 14
            }} />
          </div>
          <div>
            <div style={{ fontSize: 9.5, color: "var(--text-label)", textTransform: "uppercase", letterSpacing: "0.08em" }}>Payout</div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 20, fontWeight: 800, color: ACCENT.amber }}>${fmt(payout,2)}</div>
          </div>
          <button onClick={onRunAI} className="bubble-btn" style={{
            marginLeft: "auto", padding: "10px 18px", borderRadius: 999, border: "none", cursor: "pointer",
            background: "linear-gradient(135deg,#B98CF2,#4FC3F7)", color: "#0B0C0E", fontWeight: 800, fontSize: 12.5
          }}>✨ AI Assist: Boost This Slip</button>
          <button onClick={() => { copySlipToClipboard(legs, stake, payout); setJustCopied(true); setTimeout(()=>setJustCopied(false), 2000); }} className="bubble-btn" style={{
            padding: "10px 18px", borderRadius: 999, border: "1px solid rgba(255,255,255,0.15)", cursor: "pointer",
            background: justCopied ? "rgba(0,230,118,0.15)" : "var(--overlay-3)", color: justCopied ? ACCENT.green : "var(--text-body)", fontWeight: 700, fontSize: 12.5
          }}>{justCopied ? "✓ Copied!" : "📋 Copy Slip"}</button>
          <button onClick={onSubmit} className="bubble-btn" style={{
            padding: "10px 18px", borderRadius: 999, border: "none", cursor: "pointer",
            background: "linear-gradient(135deg,#00E676,#B4FF39)", color: "#08090B", fontWeight: 800, fontSize: 12.5
          }}>🎯 Submit Bet</button>
        </div>

        {aiSuggestion && (
          <div style={{ background: "rgba(185,140,242,0.08)", border: "1px solid rgba(185,140,242,0.3)", borderRadius: 10, padding: "10px 14px", fontSize: 12.5, color: "#D8C4F5", lineHeight: 1.5 }} className="fade-in">
            {aiSuggestion}
          </div>
        )}

        <div style={{ fontSize: 9.5, color: "var(--text-tertiary)", marginTop: 10 }}>
          "Fair odds" = 1 ÷ combined historical hit rate, no sportsbook vig applied. Rules-based heuristic suggestion, not a live model call. Not betting advice.
        </div>
      </div>
    </div>

  );
}

// =====================================================================
// PROP FLOORS VIEW (parlay + AI assist + search)
// =====================================================================
function PropFloorsView({ sport, slip, setSlip, stake, setStake, aiSuggestion, setAiSuggestion, dataTick, sportDataStatus, matchupFilter, setMatchupFilter }) {
  const [minimized, setMinimized] = useState(false);
  const [poolSearch, setPoolSearch] = useState("");
  const [poolPos, setPoolPos] = useState("all");
  const [showTopPicks, setShowTopPicks] = useState(false);
  useEffect(() => { setPoolPos("all"); setPoolSearch(""); }, [sport]);

  const inSlipTranchesFor = (entry) => slip.filter(s => s.entry.id === entry.id).map(s => s.tranche);
  const isInSlip = (entry) => slip.some(s => s.entry.id === entry.id);

  function addLeg(entry, tranche) {
    setAiSuggestion(null);
    setSlip(prev => {
      const exists = prev.find(s => s.entry.id === entry.id && s.tranche === tranche);
      if (exists) return prev.filter(s => !(s.entry.id === entry.id && s.tranche === tranche));
      // only one tranche per player-stat at a time
      const withoutSameEntry = prev.filter(s => s.entry.id !== entry.id);
      return [...withoutSameEntry, { entry, tranche }];
    });
  }
  function removeLeg(i) { setAiSuggestion(null); setSlip(prev => prev.filter((_,idx) => idx!==i)); }
  function clearSlip() { setSlip([]); setAiSuggestion(null); setMinimized(false); }

  function submitBet() {
    if (slip.length === 0) return;
    const legs = slip.map(s => {
      const res = resolveLeg(s.entry, s.tranche);
      return {
        player: s.entry.player, stat: s.entry.stat, pos: s.entry.pos, team: s.entry.team,
        tranche: s.tranche, kind: s.entry.kind || "ladder",
        lineLabel: legLineLabel({ ...s.entry, tranche: s.tranche, kind: s.entry.kind || "ladder" }),
        prob: legProb({ ...s.entry, tranche: s.tranche, kind: s.entry.kind || "ladder" }),
        note: s.entry.note || null,
        ...res,
      };
    });
    const combinedProb = comboProb(slip.map(s => ({ ...s.entry, tranche: s.tranche, kind: s.entry.kind || "ladder" })));
    const overallStatus = legs.some(l => l.status === "pending") ? "pending" : (legs.every(l => l.status === "win") ? "win" : "loss");
    const bet = {
      id: Date.now(), timestamp: new Date().toISOString(), legs, stake,
      combinedProb, payout: stake * (1 / combinedProb), overallStatus,
    };
    try {
      const existing = JSON.parse(localStorage.getItem("nfl_dashboard_bets") || "[]");
      existing.unshift(bet);
      localStorage.setItem("nfl_dashboard_bets", JSON.stringify(existing));
    } catch (e) { /* storage unavailable — bet just won't persist */ }
    setSlip([]);
    setAiSuggestion(`✅ Bet submitted and resolved — head to the 🏆 Tracking tab to see how it played out.`);
  }


  function runAIAssist() {
    if (slip.length === 0) return;
    const withProb = slip.map((s,i) => ({ i, prob: legProb({...s.entry, tranche:s.tranche, kind:s.entry.kind||"ladder"}) }));
    withProb.sort((a,b) => a.prob - b.prob);
    const weakest = withProb[0];
    const weakEntry = slip[weakest.i];
    // heuristic 1: if on p75/p50, suggest dropping to a safer tranche of the SAME player-stat
    if (weakEntry.entry.kind === "ladder" && weakEntry.tranche !== "p25") {
      const saferTranche = weakEntry.tranche === "p75" ? "p50" : "p25";
      const saferHit = weakEntry.entry[saferTranche].testHit;
      const newLegs = slip.map((s,idx) => idx===weakest.i ? {...s, tranche: saferTranche} : s);
      const newProb = comboProb(newLegs.map(s => ({...s.entry, tranche:s.tranche, kind:s.entry.kind||"ladder"})));
      setAiSuggestion(
        `Weakest leg: ${weakEntry.entry.player} ${weakEntry.entry.stat} (${weakEntry.tranche.toUpperCase()}, ${fmt(weakest.prob,0)}%). ` +
        `Dropping it to ${saferTranche.toUpperCase()} (${fmt(saferHit,0)}%) would move combined probability from ${fmt(comboProb(slip.map(s=>({...s.entry,tranche:s.tranche,kind:s.entry.kind||"ladder"})))*100,1)}% ` +
        `to ${fmt(newProb*100,1)}% — lower payout, meaningfully safer slip.`
      );
      return;
    }
    // heuristic 2: suggest swapping to the highest-hit-rate alternative from the SAME sport as the weak leg
    // (a mixed NFL+WNBA slip's weakest leg might belong to either sport, regardless of which tab you're browsing)
    const usedIds = new Set(slip.map(s=>s.entry.id));
    const legIsWnba = wnbaPool().some(e => e.id === weakEntry.entry.id);
    const legIsMlb = mlbPool().some(e => e.id === weakEntry.entry.id);
    const searchPool = legIsWnba ? wnbaPool() : legIsMlb ? mlbPool() : [...FULL_POOL, ...FUTURES_POOL];
    const alt = searchPool.filter(e => e.kind==="ladder" && !usedIds.has(e.id) && ((legIsWnba || legIsMlb) || e.pos===weakEntry.entry.pos))
      .sort((a,b) => b.p25.testHit - a.p25.testHit)[0];
    if (alt) {
      const newLegs = slip.map((s,idx) => idx===weakest.i ? {entry: alt, tranche:"p25"} : s);
      const newProb = comboProb(newLegs.map(s => ({...s.entry, tranche:s.tranche, kind:s.entry.kind||"ladder"})));
      setAiSuggestion(
        `Weakest leg: ${weakEntry.entry.player} ${weakEntry.entry.stat} (${fmt(weakest.prob,0)}%), already at its safest tranche. ` +
        `Swapping for ${alt.player} ${alt.stat} at P25 (${fmt(alt.p25.testHit,0)}%) would move combined probability to ~${fmt(newProb*100,1)}%.`
      );
    } else {
      setAiSuggestion(`Weakest leg: ${weakEntry.entry.player} ${weakEntry.entry.stat} (${fmt(weakest.prob,0)}%) — already at its safest available tranche with no stronger same-position alternative outside your slip.`);
    }
  }

  const COMBINED_POOL = useMemo(() => {
    if (sport === "wnba") return wnbaPool();
    if (sport === "mlb") return mlbPool();
    return [...FULL_POOL, ...FUTURES_POOL];
  }, [sport, dataTick]);

  const activeTop10 = useMemo(() => {
    if (sport === "nfl") return TOP10.ladders;
    // same selection logic as the NFL pre-baked TOP10 — ranked by P50 reliability, position-diversified
    const sourcePool = sport === "wnba" ? wnbaPool() : mlbPool();
    const ladderEntries = sourcePool.filter(e => e.kind === "ladder");
    const best = {};
    ladderEntries.forEach(e => {
      const score = (e.p25.testHit + e.p50.testHit + e.p75.testHit) / 3;
      if (!best[e.player] || score > best[e.player]._score) best[e.player] = { ...e, _score: score };
    });
    return Object.values(best).sort((a,b) => b.p50.testHit - a.p50.testHit || b._score - a._score).slice(0, 10);
  }, [sport, dataTick]);

  const filteredPool = useMemo(() => {
    return COMBINED_POOL.filter(e => {
      if (poolPos !== "all" && e.pos !== poolPos) return false;
      if (poolSearch && !e.player.toLowerCase().includes(poolSearch.toLowerCase()) && !e.stat.toLowerCase().includes(poolSearch.toLowerCase()) && !(e.market||"").toLowerCase().includes(poolSearch.toLowerCase())) return false;
      if (matchupFilter && e.team !== matchupFilter.teamA && e.team !== matchupFilter.teamB) return false;
      return true;
    }).slice(0, 60);
  }, [poolSearch, poolPos, COMBINED_POOL, matchupFilter]);

  const groupedPool = useMemo(() => {
    const order = [];
    const byPlayer = {};
    filteredPool.forEach(e => {
      if (!byPlayer[e.player]) { byPlayer[e.player] = []; order.push(e.player); }
      byPlayer[e.player].push(e);
    });
    return order.map(player => ({ player, entries: byPlayer[player] }));
  }, [filteredPool]);

  return (
    <div className="fade-in" style={{ paddingBottom: slip.length ? (minimized ? 60 : 280) : 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, fontWeight: 800, color: sport==="nfl"?ACCENT.teal:sport==="wnba"?"#FF8A00":"#6EC9F2", border: `1px solid ${sport==="nfl"?ACCENT.teal:sport==="wnba"?"#FF8A00":"#6EC9F2"}55`, borderRadius: 999, padding: "4px 12px" }}>
          {sport==="nfl" ? "🏈 NFL" : sport==="wnba" ? "🏀 WNBA" : "⚾ MLB"} PROP FLOORS
        </span>
        {matchupFilter ? (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, fontWeight: 700, color: TRANCHE_COLOR.p50, border: `1px solid ${TRANCHE_COLOR.p50}55`, borderRadius: 999, padding: "4px 10px", background: `${TRANCHE_COLOR.p50}14` }}>
            🎯 Showing: {matchupFilter.label}
            <button onClick={()=>setMatchupFilter(null)} style={{ background: "none", border: "none", color: TRANCHE_COLOR.p50, cursor: "pointer", fontSize: 13, padding: 0, lineHeight: 1 }}>✕</button>
          </span>
        ) : (
          <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>— switch the sport toggle up top to browse the other leagues. Your slip below can mix all three.</span>
        )}
      </div>
      {sport !== "nfl" && sportDataStatus?.[sport] === "loading" && (
        <Glass hover={false} style={{ padding: "20px 16px", marginBottom: 20, textAlign: "center", color: "var(--text-secondary-a)", fontSize: 13 }}>
          Loading {sport==="wnba"?"WNBA":"MLB"} data…
        </Glass>
      )}
      {sport !== "nfl" && sportDataStatus?.[sport] === "error" && (
        <Glass hover={false} style={{ padding: "20px 16px", marginBottom: 20, textAlign: "center", color: ACCENT.rose, fontSize: 13 }}>
          Couldn't load {sport==="wnba"?"WNBA":"MLB"} data — try switching sports again, or refresh the page.
        </Glass>
      )}
      <InfoToggle label="How this works">
        <Glass hover={false} style={{ padding: "12px 16px", fontSize: 12.5, color: "var(--text-body)", lineHeight: 1.6 }}>
          {sport==="nfl" ? (
            <><b>Offer-curve model.</b> Each ladder is set from 2024 games only — <b style={{color:TRANCHE_COLOR.p25}}>P25</b> (conservative,
            ~75% historical clear), <b style={{color:TRANCHE_COLOR.p50}}>P50</b> (median), <b style={{color:TRANCHE_COLOR.p75}}>P75</b> (stretch,
            ~25% clear, bigger number). Hit rates shown are out-of-sample against 2025. Tap a tranche to add it to your slip below
            and build a parlay across players. 📋 notes are usage/tendency call-outs pulled from real front & coverage splits — not
            tied to a scheduled opponent, since there's no 2026 slate yet.</>
          ) : sport==="wnba" ? (
            <><b>Offer-curve model.</b> Each ladder is set from 2025 games only — <b style={{color:TRANCHE_COLOR.p25}}>P25</b> (conservative,
            ~75% historical clear), <b style={{color:TRANCHE_COLOR.p50}}>P50</b> (median), <b style={{color:TRANCHE_COLOR.p75}}>P75</b> (stretch,
            ~25% clear, bigger number). Hit rates shown are out-of-sample against real 2026 season games. Tap a tranche to add it to
            your slip below and build a parlay.</>
          ) : (
            <><b>Offer-curve model.</b> Each ladder is set from 2025 games only — <b style={{color:TRANCHE_COLOR.p25}}>P25</b> (conservative,
            ~75% historical clear), <b style={{color:TRANCHE_COLOR.p50}}>P50</b> (median), <b style={{color:TRANCHE_COLOR.p75}}>P75</b> (stretch,
            ~25% clear, bigger number). Hit rates shown are out-of-sample against real 2026 season games, pulled from MLB's own
            Stats API. Tap a tranche to add it to your slip below and build a parlay.</>
          )}
        </Glass>
      </InfoToggle>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", fontWeight: 700 }}>🏆 Today's Top Picks</div>
        <button onClick={()=>setShowTopPicks(s=>!s)} className="bubble-btn" style={{ padding: "6px 14px", borderRadius: 999, border: "none", cursor: "pointer", background: "var(--overlay-5)", color: "var(--text-body)", fontSize: 11.5, fontWeight: 700 }}>
          {showTopPicks ? "Hide" : "Show"}
        </button>
      </div>
      {showTopPicks && (
        <div className="fade-in" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 10, marginBottom: 24 }}>
          {activeTop10.map((e,i) => <LadderCard key={i} e={e} onAdd={addLeg} inSlipTranches={inSlipTranchesFor(e)} />)}
        </div>
      )}

      <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", fontWeight: 700, marginBottom: 10 }}>
        Browse & Search ({COMBINED_POOL.length} bettable lines{sport==="nfl" ? ", all positions" : ""})
      </div>

      <div className="fade-in">
        <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
          <input placeholder="Search player or stat…" value={poolSearch} onChange={e=>setPoolSearch(e.target.value)} style={{
            flex: 1, minWidth: 200, background: "var(--overlay-2)", border: "1px solid var(--overlay-5)", borderRadius: 8, padding: "8px 12px", color: "var(--text-primary)", fontSize: 13
          }} />
          {(sport==="nfl" ? ["all","WR","TE","RB","QB","K","FUT"] : ["all"]).map(pos => (
            <Pill key={pos} active={poolPos===pos} onClick={()=>setPoolPos(pos)}>{pos==="all"?"All":pos==="FUT"?"🔮 Futures":pos}</Pill>
          ))}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 10 }}>
          {groupedPool.map(g => <PlayerPoolGroup key={g.player} player={g.player} entries={g.entries} onAdd={addLeg} inSlipTranchesFor={inSlipTranchesFor} />)}
        </div>
        {filteredPool.length===60 && <div style={{ fontSize: 10.5, color: "var(--text-tertiary)", marginTop: 10 }}>Showing first 60 matches — narrow your search for more.</div>}
      </div>

      <ParlaySlip slip={slip} onRemove={removeLeg} onClear={clearSlip} stake={stake} setStake={setStake} aiSuggestion={aiSuggestion} onRunAI={runAIAssist} onSubmit={submitBet} minimized={minimized} setMinimized={setMinimized} />
    </div>
  );
}

// =====================================================================
// MATCHUP VIEW
// =====================================================================
function getWnbaTeams() { return [...new Set(wnbaPlayers().map(p => p.team))].sort(); }
function getMlbTeamsList() { return [...new Set(mlbPlayers().map(p => p.team))].sort(); }
function isWnbaPlayer(name) {
  return wnbaPlayers().some(p => p.name === name);
}
function isMlbPlayer(name) {
  return mlbPlayers().some(p => p.name === name);
}

function schemeLabel(s) {
  if (!s) return "—";
  return `${s.primaryFrontExact || s.primaryFrontBucket} front (${s.primaryFrontBucketPct}% of snaps) · ${COVERAGE_LABEL[s.primaryCoverage]||s.primaryCoverage} heavy (${s.primaryCoveragePct}%)`;
}
function posGroupFor(pos) {
  if (["WR","TE","RB"].includes(pos)) return pos;
  return null; // QB/K don't map to a receiving position-group weakness
}
function MatchupCard({ player, pos, team, opp, setOpp }) {
  const isWnba = isWnbaPlayer(player);
  const isMlb = isMlbPlayer(player);

  if (isMlb) {
    const def = mlbTeamDefense()[opp];
    return (
      <Glass hover={false} style={{ padding: "16px 18px" }} className="bounce-in">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 800 }}>{player}</div>
            <div style={{ fontSize: 11, color: "var(--text-secondary-b)" }}>{team}</div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 11, color: "var(--text-secondary-b)" }}>vs.</span>
            <select value={opp} onChange={e=>setOpp(e.target.value)} style={{
              background: "var(--overlay-4)", border: "1px solid var(--overlay-7)", borderRadius: 20,
              color: "var(--text-primary)", fontSize: 12.5, fontWeight: 700, padding: "6px 12px"
            }}>
              {getMlbTeamsList().map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
        </div>
        {def ? (
          <>
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 9.5, color: "var(--text-label)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Runs Allowed/Gm</div>
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 17, fontWeight: 800 }}>{fmt(def.runsAllowedPerGame,2)} <span style={{fontSize:10,color:"var(--text-secondary-b)"}}>(#{def.rank} of {getMlbTeamsList().length} most, {def.games} gm sample)</span></div>
            </div>
            <div style={{ fontSize: 11.5, color: "var(--text-tertiary)" }}>
              No batter/pitcher-specific matchup splits yet (e.g. vs LHP/RHP) — runs allowed is the real team-level signal available right now.
            </div>
          </>
        ) : <div style={{ color: "var(--text-tertiary)", fontSize: 12 }}>No defense data for this team yet.</div>}
      </Glass>
    );
  }

  if (isWnba) {
    const def = wnbaTeamDefense()[opp];
    return (
      <Glass hover={false} style={{ padding: "16px 18px" }} className="bounce-in">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 800 }}>{player}</div>
            <div style={{ fontSize: 11, color: "var(--text-secondary-b)" }}>{team}</div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 11, color: "var(--text-secondary-b)" }}>vs.</span>
            <select value={opp} onChange={e=>setOpp(e.target.value)} style={{
              background: "var(--overlay-4)", border: "1px solid var(--overlay-7)", borderRadius: 20,
              color: "var(--text-primary)", fontSize: 12.5, fontWeight: 700, padding: "6px 12px"
            }}>
              {getWnbaTeams().map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
        </div>
        {def ? (
          <>
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 9.5, color: "var(--text-label)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Pts Allowed/Gm</div>
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 17, fontWeight: 800 }}>{fmt(def.ppgAllowed,1)} <span style={{fontSize:10,color:"var(--text-secondary-b)"}}>(#{def.rank} of {getWnbaTeams().length} most, {def.games} gm sample)</span></div>
            </div>
            <div style={{ fontSize: 11.5, color: "var(--text-tertiary)" }}>
              No per-position-group or scheme data for WNBA yet (no public man/zone tracking) — points allowed is the real signal available right now.
            </div>
          </>
        ) : <div style={{ color: "var(--text-tertiary)", fontSize: 12 }}>No defense data for this team (too few games, likely an All-Star roster).</div>}
      </Glass>
    );
  }

  const def = TEAM_DEFENSE[opp];
  const group = posGroupFor(pos);
  const allowed = def && group ? def.allowedByPosition[group] : null;
  const isWeakness = def && group && def.weakestPosition === group;
  const closeToWeakness = def && group && allowed && allowed.rank <= 8; // top-8 worst = meaningful exposure

  return (
    <Glass hover={false} style={{ padding: "16px 18px" }} className="bounce-in">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 800 }}>{player}</div>
          <div style={{ fontSize: 11, color: "var(--text-secondary-b)" }}>{pos} · {TEAM_NAMES[team]||team}</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, color: "var(--text-secondary-b)" }}>vs.</span>
          <select value={opp} onChange={e=>setOpp(e.target.value)} style={{
            background: "var(--overlay-4)", border: "1px solid var(--overlay-7)", borderRadius: 20,
            color: "var(--text-primary)", fontSize: 12.5, fontWeight: 700, padding: "6px 12px"
          }}>
            {TEAMS.map(t => <option key={t} value={t}>{TEAM_NAMES[t]}</option>)}
          </select>
        </div>
      </div>

      {def ? (
        <>
          <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginBottom: 12 }}>
            <div>
              <div style={{ fontSize: 9.5, color: "var(--text-label)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Pts Allowed/Gm</div>
              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 17, fontWeight: 800 }}>{fmt(def.pointsAllowedPerGame,1)} <span style={{fontSize:10,color:"var(--text-secondary-b)"}}>(#{def.pointsAllowedRank} most)</span></div>
            </div>
            {allowed && (
              <div>
                <div style={{ fontSize: 9.5, color: "var(--text-label)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Yds/Gm Allowed to {group}s</div>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 17, fontWeight: 800, color: closeToWeakness ? ACCENT.rose : "var(--text-primary)" }}>
                  {fmt(allowed.ypg,1)} <span style={{fontSize:10,color:"var(--text-secondary-b)"}}>(#{allowed.rank} of 32 most)</span>
                </div>
              </div>
            )}
          </div>

          <div style={{ fontSize: 11.5, color: "var(--text-secondary-a)", marginBottom: 10 }}>
            <b style={{color:"var(--text-body)"}}>Scheme:</b> {schemeLabel(def.scheme)}
          </div>

          {group ? (
            isWeakness ? (
              <div style={{ background: "rgba(242,116,90,0.1)", border: `1px solid ${ACCENT.rose}55`, borderRadius: 10, padding: "10px 14px", fontSize: 12.5, color: "#F5B8AC" }}>
                🎯 <b>Matchup Edge:</b> {TEAM_NAMES[opp]} allow the most in the league to {group}s — {fmt(allowed.ypg,1)} yds/gm,
                {" "}{allowed.tds} TDs allowed to the position over the 2-year sample. {player} ({pos}) sits right in that exposure.
              </div>
            ) : closeToWeakness ? (
              <div style={{ background: "rgba(242,169,0,0.08)", border: `1px solid ${ACCENT.amber}55`, borderRadius: 10, padding: "10px 14px", fontSize: 12.5, color: "#D9BE7C" }}>
                ⚡ <b>Worth a look:</b> {TEAM_NAMES[opp]} rank #{allowed.rank} of 32 vs {group}s (top-8 worst) — not their single biggest hole, but real exposure for a {pos}.
              </div>
            ) : (
              <div style={{ background: "var(--overlay-1)", border: "1px solid var(--overlay-5)", borderRadius: 10, padding: "10px 14px", fontSize: 12.5, color: "var(--text-secondary-b)" }}>
                No standout edge — {TEAM_NAMES[opp]} rank #{allowed?allowed.rank:"?"} of 32 vs {group}s. Their real weakness is {def.weakestPosition}s (#{def.weakestPositionRank}).
              </div>
            )
          ) : (
            <div style={{ fontSize: 11.5, color: "var(--text-tertiary)" }}>Position-group weakness matching applies to WR/TE/RB — {pos} isn't mapped to a receiving group here.</div>
          )}
        </>
      ) : <div style={{ color: "var(--text-tertiary)", fontSize: 12 }}>No defense data.</div>}
    </Glass>
  );
}

// =====================================================================
// DASHBOARD / OVERVIEW — real-data summary widgets, no fabricated numbers
// =====================================================================
function DashboardView({ sport, slip, sportDataStatus, onSelectGame }) {
  const pool = sport==="nfl" ? [...FULL_POOL, ...FUTURES_POOL] : sport==="wnba" ? wnbaPool() : mlbPool();
  const upcoming = sport==="nfl" ? NFL_UPCOMING : sport==="wnba" ? wnbaUpcoming() : mlbUpcoming();
  const sportLabel = sport==="nfl" ? "NFL" : sport==="wnba" ? "WNBA" : "MLB";
  const sportAccent = sport==="nfl" ? ACCENT.teal : sport==="wnba" ? "#FF8A00" : "#6EC9F2";
  const isLoadingSportData = sport !== "nfl" && sportDataStatus?.[sport] === "loading";

  const [bets, setBets] = useState([]);
  useEffect(() => {
    try { const raw = localStorage.getItem("nfl_dashboard_bets"); setBets(raw ? JSON.parse(raw) : []); }
    catch (e) { setBets([]); }
  }, []);
  const pendingCount = bets.filter(b => b.overallStatus === "pending").length;
  const resolved = bets.filter(b => b.overallStatus !== "pending");
  const staked = resolved.reduce((s,b) => s + b.stake, 0);
  const returned = resolved.reduce((s,b) => s + (b.overallStatus === "win" ? b.payout : 0), 0);
  const roi = staked > 0 ? ((returned - staked) / staked) * 100 : null;
  const wins = resolved.filter(b => b.overallStatus === "win").length;
  const winRate = resolved.length ? (wins / resolved.length) * 100 : null;

  const strongCount = useMemo(() => pool.filter(e => e.kind === "ladder" && confidenceTier(e.testGames)?.label === "Strong").length, [pool]);

  const topPicks = useMemo(() => {
    const candidates = pool.filter(e => e.kind === "ladder" && confidenceTier(e.testGames)?.label !== "Limited");
    const byPlayer = {};
    candidates.forEach(e => {
      if (!byPlayer[e.player] || e.p50.testHit > byPlayer[e.player].p50.testHit) byPlayer[e.player] = e;
    });
    return Object.values(byPlayer).sort((a,b) => b.p50.testHit - a.p50.testHit).slice(0, 5);
  }, [pool]);

  const slateGroups = useMemo(() => {
    const seen = new Set();
    const rows = [];
    Object.entries(upcoming).forEach(([team, g]) => {
      const key = [team, g.opp].sort().join("|");
      if (seen.has(key)) return;
      seen.add(key);
      rows.push({ team, ...g });
    });
    rows.sort((a,b) => a.date.localeCompare(b.date));

    const todayStr = new Date().toISOString().slice(0,10);
    const tomorrowStr = new Date(Date.now() + 86400000).toISOString().slice(0,10);
    const dateLabel = (d) => d === todayStr ? "Today" : d === tomorrowStr ? "Tomorrow" : new Date(d + "T00:00:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });

    const groups = [];
    let currentDate = null, currentGroup = null;
    for (const g of rows) {
      if (g.date !== currentDate) {
        currentDate = g.date;
        currentGroup = { date: g.date, label: dateLabel(g.date), games: [] };
        groups.push(currentGroup);
      }
      currentGroup.games.push(g);
      if (groups.length > 4) break; // cap how many distinct DAYS we show, not how many total games
    }
    return groups.slice(0, 4);
  }, [upcoming]);

  return (
    <div className="fade-in">
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: 26, fontWeight: 800, margin: "0 0 4px" }}>Know the game.</h2>
        <div style={{ fontSize: 13, color: "var(--text-secondary-b)" }}>Real backtested data. Live market odds. No fabricated numbers — anything shown here is either directly computed or clearly marked as unavailable.</div>
      </div>

      {isLoadingSportData && (
        <Glass hover={false} style={{ padding: "16px", marginBottom: 20, textAlign: "center", color: "var(--text-secondary-a)", fontSize: 13 }}>
          Loading {sportLabel} data — numbers below will fill in shortly…
        </Glass>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10, marginBottom: 24 }}>
        <Glass hover={false} style={{ padding: "14px 16px" }}>
          <div style={{ fontSize: 9.5, color: "var(--text-label)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>🎯 Strong-Confidence Props</div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 24, fontWeight: 800, color: ACCENT.green }}>{strongCount}</div>
          <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>{sportLabel} · 20+ game sample</div>
        </Glass>
        <Glass hover={false} style={{ padding: "14px 16px" }}>
          <div style={{ fontSize: 9.5, color: "var(--text-label)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>📋 Open Bets</div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 24, fontWeight: 800, color: "#FFD54A" }}>{pendingCount}</div>
          <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>pending resolution</div>
        </Glass>
        <Glass hover={false} style={{ padding: "14px 16px" }}>
          <div style={{ fontSize: 9.5, color: "var(--text-label)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>📈 Portfolio ROI</div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 24, fontWeight: 800, color: roi===null?"var(--text-tertiary)":roi>=0?ACCENT.green:ACCENT.rose }}>{roi===null?"—":`${roi>=0?"+":""}${fmt(roi,1)}%`}</div>
          <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>{resolved.length} resolved bets</div>
        </Glass>
        <Glass hover={false} style={{ padding: "14px 16px" }}>
          <div style={{ fontSize: 9.5, color: "var(--text-label)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>🎟️ Current Slip</div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 24, fontWeight: 800 }}>{slip.length}</div>
          <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>{slip.length>0 ? "legs in your draft" : "empty — build one on Prop Floors"}</div>
        </Glass>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 12 }}>
        <Glass hover={false} style={{ padding: "16px 18px" }}>
          <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>📅 Upcoming Slate — {sportLabel}</div>
          {slateGroups.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--text-tertiary)" }}>No scheduled games loaded for {sportLabel} right now.</div>
          ) : slateGroups.map((group, gi) => (
            <div key={group.date} style={{ marginTop: gi>0 ? 14 : 0 }}>
              <div style={{ fontSize: 10, fontWeight: 800, color: group.label==="Today" ? TRANCHE_COLOR.p50 : "var(--text-secondary-b)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
                {group.label==="Today" && "● "}{group.label}
              </div>
              {group.games.map((g,i) => {
                const home = g.isHome ? g.team : g.opp;
                const away = g.isHome ? g.opp : g.team;
                return (
                  <div key={i} onClick={()=>onSelectGame(g.team, g.opp, `${away} @ ${home}`)}
                    style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 4px", borderTop: i?"1px solid var(--overlay-4)":"none", fontSize: 12.5, cursor: "pointer", borderRadius: 6, transition: "background 0.15s" }}
                    className="glass-hover">
                    <div>
                      <b>{away}</b> <span style={{color:"var(--text-tertiary)"}}>@</span> <b>{home}</b>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, color: "var(--text-secondary-a)" }}>
                      {g.spread != null && <span title="Spread (home team perspective)">{g.spread>0?"+":""}{fmt(g.spread,1)}</span>}
                      {g.total != null && <span title="Total">O/U {fmt(g.total,1)}</span>}
                      <span style={{ color: TRANCHE_COLOR.p25, fontSize: 11 }}>Props →</span>
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
          {sport === "nfl" && slateGroups.length > 0 && slateGroups.some(gr=>gr.games.some(g=>g.spread==null)) && (
            <div style={{ fontSize: 9.5, color: "var(--text-tertiary)", marginTop: 8 }}>Spread/total not yet posted for some games this far out.</div>
          )}
          <div style={{ fontSize: 9.5, color: "var(--text-tertiary)", marginTop: 10 }}>Click a game to see props for those two teams.</div>
        </Glass>

        <Glass hover={false} style={{ padding: "16px 18px" }}>
          <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>🏆 Top 5 Strong Picks — {sportLabel}</div>
          {topPicks.length > 0 ? (
            <>
              {topPicks.map((p, i) => (
                <div key={p.id || `${p.player}-${p.stat}`} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "7px 0", borderTop: i>0 ? "1px solid var(--overlay-3)" : "none" }}>
                  <div>
                    <span style={{ fontSize: 10.5, color: "var(--text-tertiary)", marginRight: 8 }}>#{i+1}</span>
                    <span style={{ fontSize: 13, fontWeight: 700 }}>{p.player}</span>
                    <div style={{ fontSize: 10.5, color: "var(--text-secondary-b)", marginLeft: 20 }}>{p.stat}</div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 11.5, color: TRANCHE_COLOR.p50, fontWeight: 700 }}>{fmt(p.p50.line,0)} ({fmt(p.p50.testHit,0)}%)</span>
                    <ConfidenceBadge testGames={p.testGames} />
                  </div>
                </div>
              ))}
              <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginTop: 8 }}>Ranked by P50 hit rate among Strong/Moderate-confidence {sportLabel} lines right now.</div>
            </>
          ) : <div style={{ fontSize: 12, color: "var(--text-tertiary)" }}>No qualifying picks for {sportLabel} yet.</div>}
        </Glass>

        <Glass hover={false} style={{ padding: "16px 18px" }}>
          <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>🧾 Recent Bet Log</div>
          {resolved.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--text-tertiary)" }}>No resolved bets yet — submit a slip on Prop Floors to start building history.</div>
          ) : [...resolved].reverse().slice(0,4).map((b,i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderTop: i?"1px solid var(--overlay-4)":"none", fontSize: 12 }}>
              <span>{b.legs.length}-leg parlay · {new Date(b.timestamp).toLocaleDateString()}</span>
              <span style={{ fontWeight: 800, color: b.overallStatus==="win"?ACCENT.green:ACCENT.rose }}>{b.overallStatus==="win"?"WON":"LOST"}</span>
            </div>
          ))}
        </Glass>

        <Glass hover={false} style={{ padding: "16px 18px" }}>
          <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 12, fontWeight: 700 }}>💼 Portfolio Summary</div>
          <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
            <StatChip label="ROI" value={roi} decimals={1} suffix="%" accent={roi===null?"var(--text-tertiary)":roi>=0?ACCENT.green:ACCENT.rose} />
            <StatChip label="Win Rate" value={winRate} decimals={1} suffix="%" accent={sportAccent} />
            <StatChip label="Record" value={wins} suffix={`-${resolved.length-wins}`} />
          </div>
        </Glass>
      </div>
    </div>
  );
}

// =====================================================================
// TEAMS — same browse-then-detail pattern as players: a grid of team
// cards showing combined offense+defense, click one for the full picture
// plus that team's top players.
// =====================================================================
function TeamCard({ team, sport, onSelect }) {
  let scored=null, scoredRank=null, allowed=null, allowedRank=null, label="";
  if (sport === "nfl") {
    const d = TEAM_DEFENSE[team];
    scored = d?.pointsScoredPerGame; scoredRank = d?.pointsScoredRank;
    allowed = d?.pointsAllowedPerGame; allowedRank = d?.pointsAllowedRank;
    label = "Pts";
  } else if (sport === "wnba") {
    const d = wnbaTeamDefense()[team];
    scored = d?.ppgScored; scoredRank = d?.scoredRank;
    allowed = d?.ppgAllowed; allowedRank = d?.rank;
    label = "Pts";
  } else {
    const d = mlbTeamDefense()[team];
    scored = d?.runsScoredPerGame; scoredRank = d?.scoredRank;
    allowed = d?.runsAllowedPerGame; allowedRank = d?.rank;
    label = "Runs";
  }
  const teamLabel = sport === "nfl" ? (TEAM_NAMES[team] || team) : team;
  return (
    <Glass onClick={()=>onSelect(team)} style={{ padding: "14px 16px" }} className="bounce-in">
      <div style={{ fontSize: 14.5, fontWeight: 800, marginBottom: 10 }}>{teamLabel}</div>
      <div style={{ display: "flex", gap: 18 }}>
        <div>
          <div style={{ fontSize: 9, color: "var(--text-label)", textTransform: "uppercase" }}>{label} Scored/Gm</div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 15, fontWeight: 700, color: ACCENT.teal }}>
            {scored!=null ? fmt(scored,1) : "—"} {scoredRank && <span style={{fontSize:9,color:"var(--text-secondary-b)"}}>#{scoredRank}</span>}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 9, color: "var(--text-label)", textTransform: "uppercase" }}>{label} Allowed/Gm</div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 15, fontWeight: 700 }}>
            {allowed!=null ? fmt(allowed,1) : "—"} {allowedRank && <span style={{fontSize:9,color:"var(--text-secondary-b)"}}>#{allowedRank}</span>}
          </div>
        </div>
      </div>
    </Glass>
  );
}

function TeamDetail({ team, sport, onClose, onSelectPlayer }) {
  const teamLabel = sport === "nfl" ? (TEAM_NAMES[team] || team) : team;
  let def = null, label = "";
  if (sport === "nfl") { def = TEAM_DEFENSE[team]; label = "Pts"; }
  else if (sport === "wnba") { def = wnbaTeamDefense()[team]; label = "Pts"; }
  else { def = mlbTeamDefense()[team]; label = "Runs"; }

  const scored = sport==="mlb" ? def?.runsScoredPerGame : def?.pointsScoredPerGame ?? def?.ppgScored;
  const scoredRank = sport==="mlb" ? def?.scoredRank : def?.pointsScoredRank ?? def?.scoredRank;
  const allowed = sport==="mlb" ? def?.runsAllowedPerGame : def?.pointsAllowedPerGame ?? def?.ppgAllowed;
  const allowedRank = sport==="mlb" ? def?.rank : def?.pointsAllowedRank ?? def?.rank;

  const teamPlayers = useMemo(() => {
    if (sport === "nfl") {
      return [...RECEIVERS.map(p=>({...p,kind:"skill"})), ...QBS.map(p=>({...p,kind:"qb"})), ...KICKERS.map(p=>({...p,kind:"k"})), ...SACKS.map(p=>({...p,kind:"sack"}))]
        .filter(p => p.team === team);
    }
    if (sport === "wnba") return wnbaPlayers().filter(p => p.team === team);
    return mlbPlayers().filter(p => p.team === team);
  }, [team, sport]);

  return (
    <div className="fade-in">
      <button onClick={onClose} style={{ background: "none", border: "none", color: "var(--text-secondary-b)", fontSize: 12.5, cursor: "pointer", marginBottom: 14, padding: 0 }}>← Back to teams</button>
      <h2 style={{ fontSize: 26, fontWeight: 800, margin: 0, marginBottom: 16 }}>{teamLabel}</h2>

      <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 20, display: "flex", gap: 24, flexWrap: "wrap" }}>
        <StatChip label={`${label} Scored/Gm`} value={scored} decimals={1} accent={ACCENT.teal} />
        {scoredRank && <StatChip label="Offense Rank" value={scoredRank} accent={ACCENT.green} />}
        <StatChip label={`${label} Allowed/Gm`} value={allowed} decimals={1} />
        {allowedRank && <StatChip label="Defense Rank" value={allowedRank} accent={ACCENT.rose} />}
      </Glass>

      {sport === "nfl" && def?.scheme && (
        <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 20, fontSize: 12.5, color: "var(--text-secondary-a)" }}>
          <b style={{color:"var(--text-body)"}}>Scheme:</b> {schemeLabel(def.scheme)}
          {def.weakestPosition && <> · weakest vs <b style={{color:ACCENT.rose}}>{def.weakestPosition}s</b> (#{def.weakestPositionRank})</>}
        </Glass>
      )}

      <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 10, fontWeight: 700 }}>
        Players ({teamPlayers.length})
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 8 }}>
        {teamPlayers.slice(0, 30).map((p,i) => (
          <Glass key={p.id || p.name || i} onClick={()=>onSelectPlayer(p)} style={{ padding: "10px 12px" }}>
            <div style={{ fontSize: 12.5, fontWeight: 700 }}>{p.name}</div>
            <div style={{ fontSize: 10, color: "var(--text-secondary-b)" }}>{p.pos || p.group || ""}</div>
          </Glass>
        ))}
      </div>
    </div>
  );
}

function MatchupView({ slip, setSlip }) {
  const players = useMemo(() => {
    const seen = new Map();
    for (const s of slip) {
      const p = s.entry;
      if (!seen.has(p.player)) seen.set(p.player, { player: p.player, pos: p.pos, team: p.team });
    }
    return [...seen.values()];
  }, [slip]);

  function resetDraft() {
    if (window.confirm("Clear your entire parlay slip? This can't be undone.")) {
      setSlip([]);
    }
  }

  const [opponents, setOpponents] = useState({});
  useEffect(() => {
    setOpponents(prev => {
      const next = { ...prev };
      players.forEach(p => {
        if (!next[p.player]) {
          if (isMlbPlayer(p.player)) {
            next[p.player] = getMlbTeamsList().find(t => t !== p.team) || getMlbTeamsList()[0];
          } else if (isWnbaPlayer(p.player)) {
            next[p.player] = getWnbaTeams().find(t => t !== p.team) || getWnbaTeams()[0];
          } else {
            next[p.player] = TEAMS.find(t => t !== p.team) || TEAMS[0];
          }
        }
      });
      return next;
    });
  }, [players]);

  if (players.length === 0) {
    return (
      <div className="fade-in">
        <Glass hover={false} style={{ padding: "30px 20px", textAlign: "center", color: "var(--text-secondary-b)", fontSize: 13.5 }}>
          Your parlay slip is empty. Add a few legs on the <b style={{color:ACCENT.green}}>Prop Floors + Parlay</b> tab,
          then come back here to check each player against a chosen opponent's defense.
        </Glass>
      </div>
    );
  }

  return (
    <div className="fade-in">
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 10 }}>
        <button onClick={resetDraft} className="bubble-btn" style={{ padding: "8px 16px", borderRadius: 999, border: "1px solid rgba(255,61,113,0.3)", cursor: "pointer", background: "rgba(255,61,113,0.1)", color: ACCENT.rose, fontWeight: 700, fontSize: 11.5 }}>↺ Reset Draft</button>
      </div>
      <InfoToggle label="How this works">
        <Glass hover={false} style={{ padding: "12px 16px", fontSize: 12.5, color: "var(--text-body)", lineHeight: 1.6 }}>
          Pick an opponent for each player in your slip — this works across all three sports at once if your slip is mixed.
          NFL cards show real front/coverage scheme signatures; WNBA and MLB cards show points/runs allowed only, since
          there's no public tracking data to build a scheme signature from in either. None of this is tied to an actual
          scheduled game (no 2026 NFL slate, and WNBA/MLB opponent picks aren't locked to the real calendar either) — treat
          the opponent picker as a "what if they played X" tool across all three.
        </Glass>
      </InfoToggle>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 12 }}>
        {players.map(p => (
          <MatchupCard key={p.player} player={p.player} pos={p.pos} team={p.team}
            opp={opponents[p.player] || (isMlbPlayer(p.player) ? getMlbTeamsList()[0] : isWnbaPlayer(p.player) ? getWnbaTeams()[0] : TEAMS[0])}
            setOpp={(t) => setOpponents(prev => ({ ...prev, [p.player]: t }))} />
        ))}
      </div>
    </div>
  );
}

// =====================================================================
// TRACKING VIEW
// =====================================================================
function extractLineNumber(lineLabel) {
  const m = String(lineLabel||"").match(/(\d+\.?\d*)/);
  return m ? parseFloat(m[1]) : null;
}

// Independent real-data cross-check, separate from whatever the leg originally resolved
// against at submission — click to pull a real embedded game and see if it agrees.
function RealGameCheck({ leg }) {
  const [checked, setChecked] = useState(null);
  if (leg.kind === "future" || leg.kind === "binary") return null; // no clean numeric line to check

  function runCheck() {
    const result = findRealGameForLeg(leg);
    if (!result) { setChecked({ found: false }); return; }
    const lineNum = extractLineNumber(leg.lineLabel);
    const isUnder = (leg.lineLabel||"").toLowerCase().includes("under");
    const hit = lineNum == null ? null : (isUnder ? result.actual <= lineNum : result.actual >= lineNum);
    setChecked({ found: true, actual: result.actual, hit, agrees: hit !== null && (hit === (leg.status === "win")) });
  }

  if (leg.exact) {
    return <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginTop: 4 }}>✓ Already resolved against a real embedded game log at submission.</div>;
  }

  return (
    <div style={{ marginTop: 4 }}>
      {!checked ? (
        <button onClick={runCheck} style={{ background: "none", border: "none", color: "var(--text-secondary-b)", fontSize: 10, cursor: "pointer", padding: 0, textDecoration: "underline dotted" }}>
          🔍 Check vs a real game
        </button>
      ) : checked.found === false ? (
        <div style={{ fontSize: 10, color: "var(--text-tertiary)" }}>No real embedded game log for this stat yet — still simulation-only.</div>
      ) : (
        <div style={{ fontSize: 10.5, color: checked.agrees ? ACCENT.green : ACCENT.amber }}>
          {checked.agrees ? "✓" : "⚠"} Real game check: actual {fmt(checked.actual,0)} — {checked.agrees ? "agrees with the simulated result" : "differs from the simulated result"}.
        </div>
      )}
    </div>
  );
}

function LegRow({ leg }) {
  const color = leg.status === "win" ? ACCENT.green : leg.status === "loss" ? ACCENT.rose : "var(--text-secondary-b)";
  const icon = leg.status === "win" ? "✅" : leg.status === "loss" ? "❌" : "⏳";
  return (
    <div style={{ borderTop: "1px solid var(--overlay-4)", padding: "10px 0" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
        <div style={{ fontSize: 12.5 }}>
          <b>{leg.player}</b> <span style={{ color: "var(--text-secondary-b)" }}>{leg.stat} · {leg.lineLabel}</span>
        </div>
        <div style={{ fontSize: 14 }}>{icon}</div>
      </div>
      <div style={{ fontSize: 11, color: "var(--text-secondary-a)", lineHeight: 1.5 }}>{adviceFor(leg)}</div>
      {leg.note && <div style={{ fontSize: 10.5, color: "var(--text-tertiary)", marginTop: 3, fontStyle: "italic" }}>📋 {leg.note}</div>}
      <RealGameCheck leg={leg} />
    </div>
  );
}
function LossStamp() {
  return (
    <div style={{ position: "absolute", top: "50%", right: 20, transform: "translateY(-50%) rotate(-9deg)", pointerEvents: "none", zIndex: 2 }} className="stamp-in">
      <div style={{
        border: "3px solid #FF3D71", borderRadius: 6, padding: "4px 14px", position: "relative",
        color: "#FF3D71", fontWeight: 900, fontSize: 20, letterSpacing: "0.12em", fontFamily: "'Courier New', monospace",
        opacity: 0.85, mixBlendMode: "screen",
      }}>
        <div style={{ position: "absolute", inset: 3, border: "1px solid #FF3D71", borderRadius: 3, opacity: 0.6 }} />
        LOST
      </div>
    </div>
  );
}

function WinBanner() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, background: "linear-gradient(90deg,#00C853,#00A843)", borderRadius: 6, padding: "5px 12px", boxShadow: "0 4px 14px -4px rgba(0,200,83,0.5)" }} className="win-in">
      <svg width="16" height="16" viewBox="0 0 24 24" className="win-star" style={{ flexShrink: 0 }}>
        <polygon points="12,1 15,9 23,9 16.5,14 19,22 12,17 5,22 7.5,14 1,9 9,9"
          fill="#FFD54A" stroke="#B8890A" strokeWidth="0.5" />
      </svg>
      <span style={{ color: "#08090B", fontWeight: 900, fontSize: 12.5, letterSpacing: "0.06em" }}>WON</span>
    </div>
  );
}

function BetCard({ bet }) {
  const [open, setOpen] = useState(false);
  const statusColor = bet.overallStatus === "win" ? ACCENT.green : bet.overallStatus === "loss" ? ACCENT.rose : "#FFD54A";
  const statusLabel = bet.overallStatus === "win" ? "WON" : bet.overallStatus === "loss" ? "LOST" : "PENDING";
  return (
    <Glass hover={false} style={{ padding: "14px 16px", position: "relative", overflow: "hidden" }} className="bounce-in">
      {bet.overallStatus === "loss" && <LossStamp />}
      <div onClick={()=>setOpen(o=>!o)} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer" }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700 }}>{bet.legs.length}-leg parlay <span style={{ color: "var(--text-tertiary)", fontWeight: 400 }}>· {new Date(bet.timestamp).toLocaleDateString()}</span></div>
          <div style={{ fontSize: 11, color: "var(--text-secondary-b)" }}>Stake ${fmt(bet.stake,0)} · Combined {fmt(bet.combinedProb*100,1)}% · Payout ${fmt(bet.payout,2)}</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {bet.overallStatus === "win" ? <WinBanner /> : (
            <span style={{ background: `${statusColor}22`, color: statusColor, border: `1px solid ${statusColor}55`, borderRadius: 999, padding: "3px 12px", fontSize: 11, fontWeight: 800 }}>{statusLabel}</span>
          )}
          <span style={{ color: "var(--text-tertiary)", fontSize: 12 }}>{open ? "▲" : "▼"}</span>
        </div>
      </div>
      {open && <div style={{ marginTop: 8 }}>{bet.legs.map((l,i) => <LegRow key={i} leg={l} />)}</div>}
    </Glass>
  );
}
// =====================================================================
// STD-DEV ANALYSIS (how each resolved leg compares to the player's own history)
// =====================================================================
const STAT_FIELD_FOR_Z = { ...STAT_FIELD_MAP.skill, ...STAT_FIELD_MAP.qb, ...STAT_FIELD_MAP.k };
function zScoreFor(leg) {
  if (!leg.exact || leg.status === "pending") return null;
  const field = STAT_FIELD_FOR_Z[leg.stat];
  if (!field) return null;
  let source = null;
  if (STAT_FIELD_MAP.skill[leg.stat]) source = RECEIVERS.find(p => p.name === leg.player);
  else if (STAT_FIELD_MAP.qb[leg.stat]) source = QBS.find(p => p.name === leg.player);
  else if (STAT_FIELD_MAP.k[leg.stat]) source = KICKERS.find(p => p.name === leg.player);
  if (!source || !source.gamelog || source.gamelog.length < 4) return null;
  const vals = source.gamelog.map(g => g[field]).filter(v => typeof v === "number");
  const mean = vals.reduce((a,b)=>a+b,0) / vals.length;
  const variance = vals.reduce((a,b)=>a+(b-mean)**2,0) / vals.length;
  const std = Math.sqrt(variance);
  if (std === 0) return null;
  return (leg.actual - mean) / std;
}
function zBucketLabel(z) {
  if (z < -2) return "< -2σ";
  if (z < -1) return "-2σ to -1σ";
  if (z < 0) return "-1σ to 0";
  if (z < 1) return "0 to +1σ";
  if (z < 2) return "+1σ to +2σ";
  return "> +2σ";
}
function ZScoreChart({ points }) {
  if (points.length === 0) return null;
  const buckets = ["< -2σ", "-2σ to -1σ", "-1σ to 0", "0 to +1σ", "+1σ to +2σ", "> +2σ"];
  const grouped = buckets.map(b => ({
    label: b,
    win: points.filter(p => zBucketLabel(p.z) === b && p.status === "win").length,
    loss: points.filter(p => zBucketLabel(p.z) === b && p.status === "loss").length,
  }));
  const maxCount = Math.max(...grouped.map(g => g.win + g.loss), 1);
  const avgZ = points.reduce((s,p)=>s+p.z,0) / points.length;
  const avgZWin = points.filter(p=>p.status==="win").length ? points.filter(p=>p.status==="win").reduce((s,p)=>s+p.z,0) / points.filter(p=>p.status==="win").length : null;
  const avgZLoss = points.filter(p=>p.status==="loss").length ? points.filter(p=>p.status==="loss").reduce((s,p)=>s+p.z,0) / points.filter(p=>p.status==="loss").length : null;

  return (
    <Glass hover={false} style={{ padding: "18px 20px" }}>
      <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 4, fontWeight: 700 }}>
        Performance vs. Expectation
      </div>
      <div style={{ fontSize: 11.5, color: "var(--text-tertiary)", marginBottom: 16, lineHeight: 1.5 }}>
        For each resolved pick, how many standard deviations the actual game result was from that player's own historical average — not from your line, from their real distribution. 0 = a totally typical game for them.
      </div>

      <div style={{ display: "flex", gap: 24, marginBottom: 18, flexWrap: "wrap" }}>
        <StatChip label="Avg Z (all)" value={avgZ} decimals={2} accent={avgZ>=0?ACCENT.teal:ACCENT.rose} />
        {avgZWin !== null && <StatChip label="Avg Z (wins)" value={avgZWin} decimals={2} accent={ACCENT.green} />}
        {avgZLoss !== null && <StatChip label="Avg Z (losses)" value={avgZLoss} decimals={2} accent={ACCENT.rose} />}
      </div>

      <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height: 140, marginBottom: 8 }}>
        {grouped.map(g => {
          const total = g.win + g.loss;
          const h = (total / maxCount) * 120;
          const winH = total ? (g.win / total) * h : 0;
          const lossH = total ? (g.loss / total) * h : 0;
          return (
            <div key={g.label} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end", height: "100%" }}>
              <div style={{ fontSize: 10, color: "var(--text-secondary-a)", marginBottom: 4 }}>{total || ""}</div>
              <div style={{ width: "100%", display: "flex", flexDirection: "column-reverse", borderRadius: "4px 4px 0 0", overflow: "hidden" }}>
                {g.loss > 0 && <div className="bar-fill" style={{ height: lossH, background: ACCENT.rose }} />}
                {g.win > 0 && <div className="bar-fill" style={{ height: winH, background: ACCENT.green }} />}
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        {buckets.map(b => <div key={b} style={{ flex: 1, fontSize: 9, color: "var(--text-tertiary)", textAlign: "center" }}>{b}</div>)}
      </div>
      <div style={{ display: "flex", gap: 14, marginTop: 14, fontSize: 11, color: "var(--text-secondary-a)" }}>
        <span><span style={{display:"inline-block",width:9,height:9,background:ACCENT.green,borderRadius:2,marginRight:5}}></span>Win</span>
        <span><span style={{display:"inline-block",width:9,height:9,background:ACCENT.rose,borderRadius:2,marginRight:5}}></span>Loss</span>
      </div>
      <div style={{ fontSize: 10, color: "var(--text-tertiary)", marginTop: 12 }}>
        Only legs with an exact real-game resolution are included ({points.length} of them) — simulated legs (no embedded game log for that stat) don't have a meaningful z-score to compute.
      </div>
    </Glass>
  );
}

// =====================================================================
// BET HISTORY IMPORT — best-effort text parser for pasted sportsbook history.
// Neither DraftKings nor FanDuel offer a documented export-as-text format, so
// this can't target one exact structure. Instead: flexible fuzzy matching,
// then an editable preview before anything is saved — the parser only needs
// to get you close, not perfect.
// =====================================================================
const IMPORT_STAT_KEYWORDS = [
  [/rec(?:eiving)?\s*yds?|receiving\s*yards|rec\s+yards?/i, "Receiving Yards"],
  [/rush(?:ing)?\s*yds?|rushing\s*yards/i, "Rush Yards"],
  [/pass(?:ing)?\s*yds?|passing\s*yards/i, "Passing Yards"],
  [/receptions?|catches/i, "Receptions"],
  [/completions?/i, "Completions"],
  [/rush(?:ing)?\s*att(?:empts)?/i, "Rush Attempts"],
  [/targets?/i, "Targets"],
  [/rebounds?/i, "Rebounds"],
  [/assists?/i, "Assists"],
  [/steals?/i, "Steals"],
  [/blocks?/i, "Blocks"],
  [/three.?point(?:ers)?\s*made|\b3pm\b|threes?\s*made/i, "Three-Pointers Made"],
  [/strikeouts?|\bk'?s\b/i, "Strikeouts"],
  [/home\s*runs?|\bhrs?\b/i, "HR"],
  [/\brbis?\b/i, "RBI"],
  [/total\s*bases?/i, "Total Bases"],
  [/\bhits\b/i, "Hits"],
  [/\bruns\b/i, "Runs"],
  [/points?/i, "Points"],
];

function importPlayerPool() {
  const nfl = [...RECEIVERS, ...QBS, ...KICKERS, ...SACKS].map(p => ({ name: p.name, team: p.team, pos: p.pos, sport: "nfl" }));
  const wnba = wnbaPlayers().map(p => ({ name: p.name, team: p.team, pos: null, sport: "wnba" }));
  const mlb = mlbPlayers().map(p => ({ name: p.name, team: p.team, pos: null, sport: "mlb" }));
  return [...nfl, ...wnba, ...mlb];
}

function findPlayerInText(text, pool) {
  // longest-name-first so "Ja'Marr Chase" matches before a shorter partial collision
  const sorted = [...pool].sort((a,b) => b.name.length - a.name.length);
  const lower = text.toLowerCase();
  for (const p of sorted) {
    if (lower.includes(p.name.toLowerCase())) return p;
  }
  return null;
}

function parseImportedText(rawText) {
  const pool = importPlayerPool();
  const lines = rawText.split(/\n/).map(l => l.trim()).filter(Boolean);

  // Only a line that itself contains a player's name starts a new leg — prevents an
  // earlier unrelated line (like "2-Leg Parlay") from spuriously grabbing a later match.
  const playerLines = [];
  lines.forEach((line, idx) => {
    const p = findPlayerInText(line, pool);
    if (p) playerLines.push({ idx, player: p });
  });

  const results = [];
  for (let k = 0; k < playerLines.length; k++) {
    const { idx, player } = playerLines[k];
    // context is bounded by the NEXT player's line, so one leg's details can never
    // bleed into another leg's entry — this was the real bug in the first version
    const nextIdx = k + 1 < playerLines.length ? playerLines[k+1].idx : lines.length;
    const contextEnd = Math.min(idx + 5, nextIdx);
    const windowText = lines.slice(idx, contextEnd).join(" \n ");

    let stat = null;
    for (const [re, label] of IMPORT_STAT_KEYWORDS) {
      if (re.test(windowText)) { stat = label; break; }
    }
    const lineMatch = windowText.match(/(\d+\.?\d*)/);
    const dirMatch = windowText.match(/\b(over|under|o|u)\b/i);
    const oddsMatch = windowText.match(/([+-]\d{2,4})/);
    const resultMatch = windowText.match(/\b(won|win|lost|loss|lose|push|pending)\b/i);
    let status = "pending";
    if (resultMatch) {
      const r = resultMatch[1].toLowerCase();
      status = (r === "won" || r === "win") ? "win" : (r === "lost" || r === "loss" || r === "lose") ? "loss" : "pending";
    }
    results.push({
      id: `imp_${Date.now()}_${idx}`, raw: lines[idx], player: player.name, team: player.team, pos: player.pos, sport: player.sport,
      stat: stat || "", line: lineMatch ? lineMatch[1] : "", direction: dirMatch ? (dirMatch[1].toLowerCase()[0]==="o"?"Over":"Under") : "Over",
      odds: oddsMatch ? oddsMatch[1] : "-110", status, confident: !!(stat && lineMatch),
    });
  }
  return results;
}

function ImportBetHistory({ onImport }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [rows, setRows] = useState(null);

  function handleParse() {
    setRows(parseImportedText(text));
  }
  function updateRow(id, field, value) {
    setRows(prev => prev.map(r => r.id === id ? { ...r, [field]: value } : r));
  }
  function removeRow(id) {
    setRows(prev => prev.filter(r => r.id !== id));
  }
  function handleImport() {
    const bets = rows.filter(r => r.player && r.stat).map(r => ({
      id: r.id, timestamp: new Date().toISOString(), stake: 1, payout: r.status==="win" ? 1.91 : 0,
      overallStatus: r.status, imported: true,
      legs: [{
        player: r.player, team: r.team, pos: r.pos, stat: r.stat, kind: "ladder", tranche: "p50",
        lineLabel: `${r.direction} ${r.line}`, status: r.status, exact: false,
      }],
    }));
    onImport(bets);
    setText(""); setRows(null); setOpen(false);
  }

  return (
    <div style={{ marginBottom: 20 }}>
      <button onClick={()=>setOpen(o=>!o)} className="bubble-btn" style={{ padding: "9px 16px", borderRadius: 10, border: "1px solid var(--overlay-7)", background: "var(--overlay-2)", color: "var(--text-body)", fontWeight: 700, fontSize: 12.5, cursor: "pointer" }}>
        📥 {open ? "Hide Import" : "Import Bet History"}
      </button>
      {open && (
        <Glass hover={false} style={{ padding: "16px 18px", marginTop: 10 }} className="fade-in">
          <div style={{ fontSize: 11.5, color: "var(--text-secondary-a)", marginBottom: 10, lineHeight: 1.6 }}>
            Paste bet history text from DraftKings/FanDuel (or anywhere). <b style={{color:"var(--text-body)"}}>Neither book has an official export-as-text
            feature</b>, so this is a best-effort parser — it looks for known player names, a stat, a line, and a result. Review and fix the
            parsed rows below before importing; nothing saves until you click Import.
          </div>
          <textarea value={text} onChange={e=>setText(e.target.value)} rows={5} placeholder="Paste your bet history here…"
            style={{ width: "100%", background: "var(--overlay-2)", border: "1px solid var(--overlay-6)", borderRadius: 8, padding: "10px 12px", color: "var(--text-primary)", fontSize: 13, fontFamily: "inherit", resize: "vertical" }} />
          <button onClick={handleParse} disabled={!text.trim()} className="bubble-btn" style={{ marginTop: 8, padding: "8px 16px", borderRadius: 8, border: "none", background: text.trim()?ACCENT.teal:"var(--overlay-5)", color: text.trim()?"#08090B":"var(--text-tertiary)", fontWeight: 700, fontSize: 12.5, cursor: text.trim()?"pointer":"default" }}>Parse Text</button>

          {rows && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: 11, color: "var(--text-secondary-b)", marginBottom: 8 }}>
                Found {rows.length} possible leg{rows.length!==1?"s":""} — check each row, fix anything wrong, remove any that aren't real.
              </div>
              {rows.length === 0 && <div style={{ fontSize: 12.5, color: "var(--text-tertiary)" }}>No recognizable players found. Try pasting more context, or the player might not be in this dashboard's dataset yet.</div>}
              {rows.map(r => (
                <div key={r.id} style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr 0.7fr 0.8fr 0.9fr auto", gap: 6, alignItems: "center", padding: "6px 0", borderTop: "1px solid var(--overlay-4)", fontSize: 12 }}>
                  <div>
                    <div style={{ fontWeight: 700 }}>{r.player}{!r.confident && <span title="Low confidence — double check this row" style={{color:ACCENT.amber, marginLeft: 4}}>⚠</span>}</div>
                    <div style={{ fontSize: 9.5, color: "var(--text-tertiary)" }}>{r.team}</div>
                  </div>
                  <input value={r.stat} onChange={e=>updateRow(r.id,"stat",e.target.value)} placeholder="Stat" style={{ background: "var(--overlay-3)", border: "1px solid var(--overlay-6)", borderRadius: 6, padding: "5px 8px", color: "var(--text-primary)", fontSize: 11.5 }} />
                  <select value={r.direction} onChange={e=>updateRow(r.id,"direction",e.target.value)} style={{ background: "var(--overlay-3)", border: "1px solid var(--overlay-6)", borderRadius: 6, padding: "5px 6px", color: "var(--text-primary)", fontSize: 11.5 }}>
                    <option>Over</option><option>Under</option>
                  </select>
                  <input value={r.line} onChange={e=>updateRow(r.id,"line",e.target.value)} placeholder="Line" style={{ background: "var(--overlay-3)", border: "1px solid var(--overlay-6)", borderRadius: 6, padding: "5px 8px", color: "var(--text-primary)", fontSize: 11.5 }} />
                  <select value={r.status} onChange={e=>updateRow(r.id,"status",e.target.value)} style={{ background: "var(--overlay-3)", border: "1px solid var(--overlay-6)", borderRadius: 6, padding: "5px 6px", color: r.status==="win"?ACCENT.green:r.status==="loss"?ACCENT.rose:"#FFD54A", fontSize: 11.5, fontWeight: 700 }}>
                    <option value="win">Won</option><option value="loss">Lost</option><option value="pending">Pending</option>
                  </select>
                  <button onClick={()=>removeRow(r.id)} style={{ background: "none", border: "none", color: "var(--text-secondary-b)", cursor: "pointer", fontSize: 14 }}>✕</button>
                </div>
              ))}
              {rows.length > 0 && (
                <button onClick={handleImport} className="bubble-btn" style={{ marginTop: 12, padding: "9px 18px", borderRadius: 999, border: "none", background: "linear-gradient(135deg,#00E676,#B4FF39)", color: "#08090B", fontWeight: 800, fontSize: 12.5, cursor: "pointer" }}>
                  Import {rows.filter(r=>r.player&&r.stat).length} Bet{rows.filter(r=>r.player&&r.stat).length!==1?"s":""}
                </button>
              )}
            </div>
          )}
        </Glass>
      )}
    </div>
  );
}

function TrackingView({ slip, setSlip }) {
  const [bets, setBets] = useState([]);
  useEffect(() => {
    try { setBets(JSON.parse(localStorage.getItem("nfl_dashboard_bets") || "[]")); } catch(e) { setBets([]); }
  }, []);

  function clearHistory() {
    if (window.confirm("Clear your entire bet history? This can't be undone.")) {
      try { localStorage.removeItem("nfl_dashboard_bets"); } catch(e) {}
      setBets([]);
    }
  }

  function handleImportedBets(newBets) {
    setBets(prev => {
      const merged = [...prev, ...newBets];
      try { localStorage.setItem("nfl_dashboard_bets", JSON.stringify(merged)); } catch(e) {}
      return merged;
    });
  }

  const resolved = bets.filter(b => b.overallStatus !== "pending");
  const wins = resolved.filter(b => b.overallStatus === "win").length;
  const losses = resolved.filter(b => b.overallStatus === "loss").length;
  const pending = bets.length - resolved.length;
  const winRate = resolved.length ? (wins / resolved.length) * 100 : null;
  const totalStaked = resolved.reduce((sum,b) => sum + b.stake, 0);
  const totalReturned = resolved.reduce((sum,b) => sum + (b.overallStatus === "win" ? b.payout : 0), 0);
  const netUnits = totalReturned - totalStaked;

  // per-tranche accuracy across all resolved legs
  const trancheStats = { p25: {hit:0,total:0}, p50: {hit:0,total:0}, p75: {hit:0,total:0} };
  resolved.forEach(b => b.legs.forEach(l => {
    if (l.kind === "ladder" && l.status !== "pending") {
      trancheStats[l.tranche].total++;
      if (l.status === "win") trancheStats[l.tranche].hit++;
    }
  }));

  // team success — which teams your bets tend to hit on (from every resolved leg, regardless of parlay size)
  const teamStats = {};
  resolved.forEach(b => b.legs.forEach(l => {
    if (!l.team || l.status === "pending") return;
    if (!teamStats[l.team]) teamStats[l.team] = { hit: 0, total: 0 };
    teamStats[l.team].total++;
    if (l.status === "win") teamStats[l.team].hit++;
  }));
  const teamRows = Object.entries(teamStats)
    .map(([team, s]) => ({ team, ...s, rate: (s.hit/s.total)*100 }))
    .filter(r => r.total >= 2)
    .sort((a,b) => b.rate - a.rate || b.total - a.total);

  // value by stat category — which prop types are actually working for you
  const statStats = {};
  resolved.forEach(b => b.legs.forEach(l => {
    if (l.status === "pending") return;
    if (!statStats[l.stat]) statStats[l.stat] = { hit: 0, total: 0 };
    statStats[l.stat].total++;
    if (l.status === "win") statStats[l.stat].hit++;
  }));
  const statRows = Object.entries(statStats)
    .map(([stat, s]) => ({ stat, ...s, rate: (s.hit/s.total)*100 }))
    .filter(r => r.total >= 2)
    .sort((a,b) => b.rate - a.rate || b.total - a.total);

  const zPoints = [];
  resolved.forEach(b => b.legs.forEach(l => {
    const z = zScoreFor(l);
    if (z !== null && isFinite(z)) zPoints.push({ z, status: l.status });
  }));

  if (bets.length === 0) {
    return (
      <div className="fade-in">
        {slip.length > 0 && (
          <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 10 }}>
            <button onClick={()=>{ if (window.confirm("Clear your current parlay slip draft? This can't be undone.")) setSlip([]); }} className="bubble-btn" style={{ padding: "8px 16px", borderRadius: 999, border: "1px solid rgba(255,61,113,0.3)", cursor: "pointer", background: "rgba(255,61,113,0.1)", color: ACCENT.rose, fontWeight: 700, fontSize: 11.5 }}>↺ Reset Draft ({slip.length})</button>
          </div>
        )}
        <ImportBetHistory onImport={handleImportedBets} />
        <Glass hover={false} style={{ padding: "30px 20px", textAlign: "center", color: "var(--text-secondary-b)", fontSize: 13.5 }}>
          No submitted bets yet. Build a slip on <b style={{color:ACCENT.green}}>Prop Floors + Parlay</b> and hit
          <b> 🎯 Submit Bet</b> — it resolves instantly against real 2025 data (or a weighted simulation where exact
          game logs aren't embedded) and shows up here. Or import your real history from another sportsbook above.
        </Glass>
      </div>
    );
  }

  return (
    <div className="fade-in">
      <ImportBetHistory onImport={handleImportedBets} />
      <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 14, display: "flex", gap: 28, flexWrap: "wrap", alignItems: "center" }}>
        <StatChip label="Money In" value={totalStaked} decimals={2} accent="var(--text-secondary-a)" suffix="$" />
        <StatChip label="Money Out" value={totalReturned} decimals={2} accent={ACCENT.teal} suffix="$" />
        <StatChip label="Net P&L" value={netUnits} decimals={2} accent={netUnits>=0?ACCENT.green:ACCENT.rose} suffix="$" />
      </Glass>

      <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 20, display: "flex", gap: 28, flexWrap: "wrap", alignItems: "center" }}>
        <StatChip label="Record" value={wins} decimals={0} accent={ACCENT.green} suffix={`-${losses}`} />
        <StatChip label="Win Rate" value={winRate} decimals={1} suffix="%" accent={ACCENT.teal} />
        <StatChip label="Pending" value={pending} decimals={0} accent="#FFD54A" />
        <button onClick={clearHistory} className="bubble-btn" style={{ marginLeft: "auto", padding: "8px 16px", borderRadius: 999, border: "none", cursor: "pointer", background: "rgba(255,61,113,0.15)", color: ACCENT.rose, fontWeight: 700, fontSize: 11.5 }}>Clear History</button>
        {slip.length > 0 && (
          <button onClick={()=>{ if (window.confirm("Clear your current parlay slip draft? This can't be undone.")) setSlip([]); }} className="bubble-btn" style={{ padding: "8px 16px", borderRadius: 999, border: "1px solid rgba(255,61,113,0.3)", cursor: "pointer", background: "rgba(255,61,113,0.1)", color: ACCENT.rose, fontWeight: 700, fontSize: 11.5 }}>↺ Reset Draft ({slip.length})</button>
        )}
      </Glass>

      {resolved.length > 0 && (
        <Glass hover={false} style={{ padding: "14px 16px", marginBottom: 20 }}>
          <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 10, fontWeight: 700 }}>Tranche Accuracy (your picks, resolved)</div>
          <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
            {["p25","p50","p75"].map(tr => {
              const t = trancheStats[tr];
              const rate = t.total ? (t.hit/t.total)*100 : null;
              const accent = tr==="p25"?ACCENT.green:tr==="p50"?ACCENT.teal:ACCENT.amber;
              return (
                <div key={tr}>
                  <div style={{ fontSize: 10, color: accent, fontWeight: 700 }}>{tr.toUpperCase()}</div>
                  <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 16, fontWeight: 800 }}>{rate===null?"—":`${fmt(rate,0)}%`} <span style={{fontSize:10,color:"var(--text-tertiary)"}}>({t.hit}/{t.total})</span></div>
                </div>
              );
            })}
          </div>
        </Glass>
      )}

      {statRows.length > 0 && (
        <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 20 }}>
          <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 4, fontWeight: 700 }}>Where You're Finding Value</div>
          <div style={{ fontSize: 10.5, color: "var(--text-tertiary)", marginBottom: 12 }}>Win rate by prop type, across every resolved leg (2+ picks minimum to show).</div>
          {statRows.map(r => (
            <div key={r.stat} style={{ marginBottom: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, marginBottom: 3 }}>
                <span style={{ color: "var(--text-body)", fontWeight: 600 }}>{r.stat}</span>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", color: "var(--text-secondary-b)" }}>{r.hit}/{r.total} · {fmt(r.rate,0)}%</span>
              </div>
              <div style={{ height: 6, background: "var(--overlay-3)", borderRadius: 3, overflow: "hidden" }}>
                <div className="bar-fill" style={{ height: "100%", width: `${Math.max(3,r.rate)}%`, background: r.rate>=50 ? "linear-gradient(90deg,#00C853,#00E676)" : "linear-gradient(90deg,#8C3B2B,#FF3D71)" }} />
              </div>
            </div>
          ))}
        </Glass>
      )}

      {teamRows.length > 0 && (
        <Glass hover={false} style={{ padding: "16px 18px", marginBottom: 20 }}>
          <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 4, fontWeight: 700 }}>Your Money-Making Teams</div>
          <div style={{ fontSize: 10.5, color: "var(--text-tertiary)", marginBottom: 12 }}>Win rate by team, across every resolved leg (2+ picks minimum to show).</div>
          {teamRows.map(r => (
            <div key={r.team} style={{ marginBottom: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, marginBottom: 3 }}>
                <span style={{ color: "var(--text-body)", fontWeight: 600 }}>{TEAM_NAMES[r.team] || r.team}</span>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", color: "var(--text-secondary-b)" }}>{r.hit}/{r.total} · {fmt(r.rate,0)}%</span>
              </div>
              <div style={{ height: 6, background: "var(--overlay-3)", borderRadius: 3, overflow: "hidden" }}>
                <div className="bar-fill" style={{ height: "100%", width: `${Math.max(3,r.rate)}%`, background: r.rate>=50 ? "linear-gradient(90deg,#5A3C82,#C77DFF)" : "linear-gradient(90deg,#8C3B2B,#FF3D71)" }} />
              </div>
            </div>
          ))}
        </Glass>
      )}

      {zPoints.length > 0 && <div style={{ marginBottom: 20 }}><ZScoreChart points={zPoints} /></div>}

      <div style={{ fontSize: 11, letterSpacing: "0.1em", color: "var(--text-secondary-b)", textTransform: "uppercase", marginBottom: 10, fontWeight: 700 }}>Bet History</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {bets.map(b => <BetCard key={b.id} bet={b} />)}
      </div>

      <div style={{ fontSize: 10.5, color: "var(--text-tertiary)", marginTop: 16, lineHeight: 1.5 }}>
        Resolutions use a real, randomly-drawn 2025 game for that player where an exact game log is embedded
        (receiving, passing, kicking stats); rushing/anytime-TD/futures fall back to a probability-weighted
        simulation since exact per-game values for those aren't embedded yet. This is retrospective — it shows how
        your selection engine would have performed, not a live bet with real money. History is stored in this
        browser only (localStorage) — it won't follow you to another device or browser.
      </div>
    </div>
  );
}

// =====================================================================
// APP
// =====================================================================
function App() {
  const [sport, setSport] = useState("nfl");
  const [tab, setTab] = useState("dashboard");
  const [search, setSearch] = useState("");
  const [team, setTeam] = useState("all");
  const [posFilter, setPosFilter] = useState("all");
  const [sortKey, setSortKey] = useState("yards");
  const [selected, setSelected] = useState(null);
  const [selectedTeam, setSelectedTeam] = useState(null);
  const [matchupFilter, setMatchupFilter] = useState(null); // { teamA, teamB, label } — set when a Dashboard slate game is clicked
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [slip, setSlip] = useState([]);
  const [stake, setStake] = useState(20);
  const [aiSuggestion, setAiSuggestion] = useState(null);

  // Lazy-load state for WNBA/MLB data — declared early since several useMemo hooks below
  // depend on dataTick to know when to recompute after a fetch completes.
  const [dataTick, setDataTick] = useState(0); // bumped after a lazy-load completes, to force a re-render
  const [sportDataStatus, setSportDataStatus] = useState({ wnba: "idle", mlb: "idle" });

  async function loadSportData(key) {
    if (SportDataCache[key] || sportDataStatus[key] === "loading") return;
    setSportDataStatus(s => ({ ...s, [key]: "loading" }));
    try {
      const res = await fetch(`./data-${key}.json`);
      if (!res.ok) throw new Error(`status ${res.status}`);
      const data = await res.json();
      SportDataCache[key] = data;
      setSportDataStatus(s => ({ ...s, [key]: "loaded" }));
      setDataTick(t => t + 1);
    } catch (e) {
      setSportDataStatus(s => ({ ...s, [key]: "error" }));
    }
  }

  useEffect(() => {
    if (sport === "wnba") loadSportData("wnba");
    if (sport === "mlb") loadSportData("mlb");
  }, [sport]);

  const offensePositions = ["WR","TE","RB","QB","K"];
  const defensePositions = ["DL","LB","DB"];

  const ALL_OFFENSE = useMemo(() => [
    ...RECEIVERS.map(p => ({ ...p, kind: "skill" })),
    ...QBS.map(p => ({ ...p, kind: "qb" })),
    ...KICKERS.map(p => ({ ...p, kind: "k" })),
  ], []);

  const filteredOffense = useMemo(() => {
    let list = ALL_OFFENSE.filter(p => {
      if (team !== "all" && p.team !== team) return false;
      if (posFilter !== "all" && p.pos !== posFilter) return false;
      if (search && !p.name.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
    const val = p => {
      if (sortKey === "yards") return p.kind==="k" ? p.overall.made*3 : p.kind==="skill" ? (p.overall.scrimmageYards||p.overall.yards) : (p.overall.totalYards||p.overall.yards);
      if (sortKey === "volume") return p.kind==="skill" ? p.overall.targets : p.kind==="qb" ? p.overall.attempts : p.overall.attempts;
      if (sortKey === "tds") return p.kind==="k" ? p.overall.made : (p.overall.tds||0);
      if (sortKey === "epa") return p.kind==="k" ? (p.overall.pct||0) : (p.kind==="skill" ? p.overall.epaPerTarget : p.overall.epaPerAtt) ?? -99;
      return 0;
    };
    return list.sort((a,b) => val(b)-val(a));
  }, [ALL_OFFENSE, team, posFilter, search, sortKey]);

  const filteredDefense = useMemo(() => {
    let list = SACKS.filter(d => {
      if (team !== "all" && d.team !== team) return false;
      if (posFilter !== "all" && d.pos !== posFilter) return false;
      if (search && !d.name.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
    return list.sort((a,b) => b.totalSacks - a.totalSacks);
  }, [team, posFilter, search]);

  const filteredWNBA = useMemo(() => {
    let list = wnbaPlayers().filter(p => {
      if (team !== "all" && p.team !== team) return false;
      if (search && !p.name.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
    if (tab === "defense") return list.sort((a,b) => (b.overall.stl+b.overall.blk) - (a.overall.stl+a.overall.blk));
    const key = { yards: p=>p.overall.pts, volume: p=>p.overall.games, tds: p=>p.overall.reb, epa: p=>p.overall.usage||0 }[sortKey] || (p=>p.overall.pts);
    return list.sort((a,b) => key(b)-key(a));
  }, [team, search, sortKey, tab, dataTick]);

  const WNBA_TEAMS = useMemo(() => getWnbaTeams(), [dataTick]);

  const filteredMLB = useMemo(() => {
    const wantGroup = tab === "offense" ? "hitting" : "pitching";
    let list = mlbPlayers().filter(p => {
      if (p.group !== wantGroup) return false;
      if (team !== "all" && p.team !== team) return false;
      if (search && !p.name.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
    if (wantGroup === "pitching") return list.sort((a,b) => (b.overall.avg_so||0) - (a.overall.avg_so||0));
    return list.sort((a,b) => (b.overall.totalHR||0) - (a.overall.totalHR||0));
  }, [team, search, tab, dataTick]);

  const MLB_TEAMS = useMemo(() => getMlbTeamsList(), [dataTick]);

  useEffect(() => { setSelected(null); setSelectedTeam(null); setPosFilter("all"); }, [tab]);
  useEffect(() => { setSelected(null); setSelectedTeam(null); setSearch(""); setPosFilter("all"); setTeam("all"); setMatchupFilter(null); }, [sport]);

  const [themeOverride, setThemeOverride] = useState(null); // null = auto (local time), "day", or "night"

  const dailyTheme = useMemo(() => getDailyTheme(themeOverride), [themeOverride]);
  const isDay = dailyTheme.isDay;
  const themeVars = {
    "--theme-bg": dailyTheme.bg, "--theme-c1": dailyTheme.c1, "--theme-c2": dailyTheme.c2,
    "--theme-c3": dailyTheme.c3, "--theme-c4": dailyTheme.c4,
    // text tiers — swap between light-on-dark and dark-on-light
    "--text-primary": isDay ? "#14151A" : "#EDEEF0",
    "--text-body": isDay ? "#2B2E33" : "#C7CAD1",
    "--text-secondary-a": isDay ? "#5A5F68" : "#8B8F98",
    "--text-secondary-b": isDay ? "#666B73" : "#7C828D",
    "--text-tertiary": isDay ? "#8A8F98" : "#54585F",
    "--text-label": isDay ? "#8B9099" : "#6B7078",
    // surface overlays — white-based washes at night, black-based washes by day
    "--overlay-1": isDay ? "rgba(0,0,0,0.04)" : "rgba(255,255,255,0.03)",
    "--overlay-2": isDay ? "rgba(0,0,0,0.05)" : "rgba(255,255,255,0.04)",
    "--overlay-3": isDay ? "rgba(0,0,0,0.06)" : "rgba(255,255,255,0.05)",
    "--overlay-4": isDay ? "rgba(0,0,0,0.07)" : "rgba(255,255,255,0.06)",
    "--overlay-5": isDay ? "rgba(0,0,0,0.09)" : "rgba(255,255,255,0.08)",
    "--overlay-6": isDay ? "rgba(0,0,0,0.11)" : "rgba(255,255,255,0.1)",
    "--overlay-7": isDay ? "rgba(0,0,0,0.14)" : "rgba(255,255,255,0.12)",
    "--card-bg": isDay ? "rgba(255,255,255,0.72)" : "rgba(14,16,20,0.68)",
    "--card-border": isDay ? "rgba(0,0,0,0.10)" : "rgba(255,255,255,0.10)",
    "--card-hover-bg": isDay ? "rgba(255,255,255,0.88)" : "rgba(18,20,25,0.78)",
    "--star-color": isDay ? "#1A1B1E" : "#FFFFFF",
    "--dot-grid": isDay ? "rgba(0,0,0,0.05)" : "rgba(255,255,255,0.05)",
  };

  return (
    <div style={{ position: "relative", minHeight: "100vh", fontFamily: "'Inter', -apple-system, sans-serif", color: "var(--text-primary)", ...themeVars }}>
      <GlobalStyle />
      <AmbientBackground theme={dailyTheme} />
      <div style={{ position: "relative", zIndex: 1, width: "90%", maxWidth: 1600, margin: "0 auto", padding: "28px 20px 70px" }}>

        <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 16 }}>
          <Logo theme={dailyTheme} />
          <button onClick={()=>setSport("nfl")} className="bubble-btn" style={{
            padding: "9px 20px", borderRadius: 10, border: `1px solid ${sport==="nfl"?ACCENT.teal:"var(--overlay-6)"}`,
            background: sport==="nfl" ? `${ACCENT.teal}18` : "var(--overlay-1)",
            color: sport==="nfl" ? ACCENT.teal : "var(--text-secondary-a)", fontWeight: 800, fontSize: 13, cursor: "pointer"
          }}>🏈 NFL</button>
          <button onClick={()=>setSport("wnba")} className="bubble-btn" style={{
            padding: "9px 20px", borderRadius: 10, border: `1px solid ${sport==="wnba"?"#FF8A00":"var(--overlay-6)"}`,
            background: sport==="wnba" ? "#FF8A0018" : "var(--overlay-1)",
            color: sport==="wnba" ? "#FF8A00" : "var(--text-secondary-a)", fontWeight: 800, fontSize: 13, cursor: "pointer"
          }}>🏀 WNBA</button>
          <button onClick={()=>setSport("mlb")} className="bubble-btn" style={{
            padding: "9px 20px", borderRadius: 10, border: `1px solid ${sport==="mlb"?"#6EC9F2":"var(--overlay-6)"}`,
            background: sport==="mlb" ? "#6EC9F218" : "var(--overlay-1)",
            color: sport==="mlb" ? "#6EC9F2" : "var(--text-secondary-a)", fontWeight: 800, fontSize: 13, cursor: "pointer"
          }}>⚾ MLB</button>
          <button
            onClick={()=>setThemeOverride(o => o === null ? (dailyTheme.isDay ? "night" : "day") : (o === "day" ? "night" : "day"))}
            title={themeOverride === null ? "Auto (following local time) — click to override" : `Manual ${themeOverride} mode — click to switch, or refresh to reset to auto`}
            className="bubble-btn" style={{
              marginLeft: "auto", padding: "9px 14px", borderRadius: 10, border: "1px solid var(--overlay-6)",
              background: "var(--overlay-1)", color: "var(--text-body)", fontWeight: 700, fontSize: 13, cursor: "pointer"
            }}>{dailyTheme.isDay ? "☀️" : "🌙"} {themeOverride === null ? "Auto" : dailyTheme.isDay ? "Day" : "Night"}</button>
        </div>

        <div style={{ marginBottom: 22, display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 10 }}>
          <div>
            <div style={{ fontSize: 11, letterSpacing: "0.18em", color: ACCENT.amber, fontWeight: 700, marginBottom: 6 }}>
              {sport==="nfl" ? "NFL 2024–25 · MATCHUP INTELLIGENCE" : sport==="wnba" ? "WNBA 2025–26 · MATCHUP INTELLIGENCE" : "MLB 2025–26 · MATCHUP INTELLIGENCE"}
            </div>
            <h1 style={{ fontSize: 32, fontWeight: 800, margin: 0, letterSpacing: "-0.02em", background: `linear-gradient(90deg,${dailyTheme.c1},${dailyTheme.c3} 45%,${dailyTheme.c4})`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>Statum</h1>
            <div style={{ fontSize: 12.5, color: "var(--text-label)", marginTop: 4 }}>
              {sport==="nfl"
                ? `${RECEIVERS.length} skill players · ${QBS.length} QBs · ${KICKERS.length} kickers · ${SACKS.length} pass rushers · two full seasons, every play tagged by real front & coverage`
                : sport==="wnba"
                ? `${wnbaPlayers().length} players · real box scores parsed from play-by-play · train/test validated prop lines`
                : `${mlbPlayers().length} batters & pitchers · official MLB Stats API · train/test validated prop lines`}
            </div>
          </div>
          <a href="./guide.html" style={{
            fontSize: 12, fontWeight: 700, color: "#B4FF39", border: "1px solid #B4FF3955", borderRadius: 999,
            padding: "7px 14px", textDecoration: "none", whiteSpace: "nowrap"
          }}>📖 Guide & Risk Info</a>
        </div>

        <div style={{ display: "flex", gap: 8, marginBottom: 18, flexWrap: "wrap" }}>
          <Pill active={tab==="dashboard"} onClick={()=>setTab("dashboard")} accent="#FFD54A">🏠 Dashboard</Pill>
          <Pill active={tab==="offense"} onClick={()=>setTab("offense")} accent={ACCENT.teal}>{sport==="nfl" ? "NFL Offense" : sport==="wnba" ? "WNBA Players" : "MLB Batters"}</Pill>
          <Pill active={tab==="defense"} onClick={()=>setTab("defense")} accent={ACCENT.violet}>{sport==="nfl" ? "NFL Defense · Sacks" : sport==="wnba" ? "WNBA Defense · Stl+Blk" : "MLB Pitchers"}</Pill>
          <Pill active={tab==="market"} onClick={()=>setTab("market")} accent={ACCENT.amber}>Market Pulse · Kalshi</Pill>
          <Pill active={tab==="locks"} onClick={()=>setTab("locks")} accent={ACCENT.green}>🎯 Prop Floors + Parlay</Pill>
          <Pill active={tab==="matchup"} onClick={()=>setTab("matchup")} accent={ACCENT.rose}>🏟️ Matchup</Pill>
          <Pill active={tab==="teams"} onClick={()=>setTab("teams")} accent="#6EC9F2">🏛️ Teams</Pill>
          <Pill active={tab==="tracking"} onClick={()=>setTab("tracking")} accent="#FFD54A">🏆 Tracking</Pill>
        </div>

        {tab==="dashboard" && <DashboardView sport={sport} slip={slip} sportDataStatus={sportDataStatus} onSelectGame={(teamA, teamB, label)=>{ setMatchupFilter({teamA, teamB, label}); setTab("locks"); }} />}
        {tab==="market" && <MarketPulseView sport={sport} />}
        {tab==="locks" && <PropFloorsView sport={sport} slip={slip} setSlip={setSlip} stake={stake} setStake={setStake} aiSuggestion={aiSuggestion} setAiSuggestion={setAiSuggestion} dataTick={dataTick} sportDataStatus={sportDataStatus} matchupFilter={matchupFilter} setMatchupFilter={setMatchupFilter} />}
        {tab==="matchup" && <MatchupView slip={slip} setSlip={setSlip} />}
        {tab==="teams" && !selectedTeam && (
          <div className="fade-in">
            {sport !== "nfl" && sportDataStatus[sport] === "loading" && (
              <Glass hover={false} style={{ padding: "30px 20px", textAlign: "center", color: "var(--text-secondary-a)", fontSize: 13 }}>Loading {sport==="wnba"?"WNBA":"MLB"} data…</Glass>
            )}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 10 }}>
              {(sport==="nfl" ? TEAMS : sport==="wnba" ? getWnbaTeams() : getMlbTeamsList()).map(t => (
                <TeamCard key={t} team={t} sport={sport} onSelect={setSelectedTeam} />
              ))}
            </div>
          </div>
        )}
        {tab==="teams" && selectedTeam && (
          <TeamDetail team={selectedTeam} sport={sport} onClose={()=>setSelectedTeam(null)}
            onSelectPlayer={(p) => {
              setSelected(p);
              setSelectedTeam(null);
              setTab(sport==="nfl" && p.kind==="sack" ? "defense" : "offense");
            }} />
        )}
        {tab==="tracking" && <TrackingView slip={slip} setSlip={setSlip} />}

        {sport==="nfl" && (tab==="offense" || tab==="defense") && !selected && (
          <>
            <Glass hover={false} style={{ padding: "14px 16px", marginBottom: 18 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: filtersOpen ? 12 : 0 }}>
                <input
                  placeholder={tab==="offense" ? "Search offense…" : "Search pass rushers…"}
                  value={search} onChange={e=>setSearch(e.target.value)}
                  style={{ flex: 1, background: "var(--overlay-2)", border: "1px solid var(--overlay-5)", borderRadius: 8, padding: "11px 12px", color: "var(--text-primary)", fontSize: 15 }}
                />
                <button onClick={()=>setFiltersOpen(o=>!o)} className="bubble-btn" style={{
                  flexShrink: 0, padding: "10px 14px", borderRadius: 8, border: "1px solid var(--overlay-6)",
                  background: (posFilter!=="all"||team!=="all") ? `${ACCENT.teal}22` : "var(--overlay-2)",
                  color: (posFilter!=="all"||team!=="all") ? ACCENT.teal : "var(--text-body)", fontSize: 13, fontWeight: 700, cursor: "pointer"
                }}>⚙ {filtersOpen ? "Hide" : "Filters"}</button>
              </div>
              {filtersOpen && (
                <div className="fade-in">
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
                    <Pill active={posFilter==="all"} onClick={()=>setPosFilter("all")}>All Positions</Pill>
                    {(tab==="offense"?offensePositions:defensePositions).map(pos => (
                      <Pill key={pos} active={posFilter===pos} onClick={()=>setPosFilter(posFilter===pos?"all":pos)}>{pos}</Pill>
                    ))}
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                    <select value={team} onChange={e=>setTeam(e.target.value)} style={{ background: "var(--overlay-2)", border: "1px solid var(--overlay-5)", borderRadius: 20, color: team==="all" ? "var(--text-secondary-a)" : "var(--text-primary)", fontSize: 13, fontWeight: 600, padding: "8px 12px" }}>
                      <option value="all">Any Team</option>
                      {TEAMS.map(t => <option key={t} value={t}>{TEAM_NAMES[t]}</option>)}
                    </select>
                    {tab==="offense" && (<>
                      <span style={{ color: "#3D4147", fontSize: 12 }}>sort:</span>
                      {[["yards","Prod."],["volume","Volume"],["tds","TD/FG"],["epa","Efficiency"]].map(([k,l]) => (
                        <Pill key={k} active={sortKey===k} onClick={()=>setSortKey(k)} accent={ACCENT.teal}>{l}</Pill>
                      ))}
                    </>)}
                  </div>
                </div>
              )}
            </Glass>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10 }}>
              {tab==="offense"
                ? filteredOffense.slice(0,60).map((p,i) => <OffenseCard key={p.id} p={p} idx={i} onSelect={setSelected} />)
                : filteredDefense.slice(0,60).map((d,i) => <DefenseCard key={d.id} d={d} idx={i} onSelect={setSelected} />)}
            </div>
            {(tab==="offense" ? filteredOffense.length : filteredDefense.length) === 0 && (
              <div style={{ color: "var(--text-tertiary)", fontSize: 13, padding: 30, textAlign: "center" }}>No matches. Try a different search or filter.</div>
            )}
            {(tab==="offense" ? filteredOffense.length : filteredDefense.length) > 60 && (
              <div style={{ color: "var(--text-tertiary)", fontSize: 11.5, marginTop: 14, textAlign: "center" }}>Showing top 60 — narrow with search or filters to see more.</div>
            )}
          </>
        )}

        {sport==="wnba" && (tab==="offense" || tab==="defense") && !selected && (
          <>
            {sportDataStatus.wnba === "loading" && (
              <Glass hover={false} style={{ padding: "30px 20px", textAlign: "center", color: "var(--text-secondary-a)", fontSize: 13 }}>Loading WNBA data…</Glass>
            )}
            {sportDataStatus.wnba === "error" && (
              <Glass hover={false} style={{ padding: "30px 20px", textAlign: "center", color: ACCENT.rose, fontSize: 13 }}>Couldn't load WNBA data — switch sports and back, or refresh.</Glass>
            )}
            <Glass hover={false} style={{ padding: "14px 16px", marginBottom: 18 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <input
                  placeholder="Search WNBA players…"
                  value={search} onChange={e=>setSearch(e.target.value)}
                  style={{ flex: 1, minWidth: 180, background: "var(--overlay-2)", border: "1px solid var(--overlay-5)", borderRadius: 8, padding: "11px 12px", color: "var(--text-primary)", fontSize: 15 }}
                />
                <select value={team} onChange={e=>setTeam(e.target.value)} style={{ background: "var(--overlay-2)", border: "1px solid var(--overlay-5)", borderRadius: 20, color: team==="all" ? "var(--text-secondary-a)" : "var(--text-primary)", fontSize: 13, fontWeight: 600, padding: "10px 14px" }}>
                  <option value="all">Any Team</option>
                  {WNBA_TEAMS.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
                {tab==="offense" && (
                  <select value={sortKey} onChange={e=>setSortKey(e.target.value)} style={{ background: "var(--overlay-2)", border: "1px solid var(--overlay-5)", borderRadius: 20, color: "var(--text-primary)", fontSize: 13, fontWeight: 600, padding: "10px 14px" }}>
                    <option value="yards">Sort: Points</option>
                    <option value="tds">Sort: Rebounds</option>
                    <option value="volume">Sort: Games</option>
                    <option value="epa">Sort: Usage %</option>
                  </select>
                )}
              </div>
            </Glass>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10 }}>
              {filteredWNBA.slice(0,60).map((p,i) => <WNBACard key={p.name} p={p} idx={i} onSelect={setSelected} mode={tab} />)}
            </div>
            {filteredWNBA.length === 0 && <div style={{ color: "var(--text-tertiary)", fontSize: 13, padding: 30, textAlign: "center" }}>No matches. Try a different search or filter.</div>}
            {filteredWNBA.length > 60 && <div style={{ color: "var(--text-tertiary)", fontSize: 11.5, marginTop: 14, textAlign: "center" }}>Showing top 60 — narrow with search to see more.</div>}
          </>
        )}

        {sport==="mlb" && (tab==="offense" || tab==="defense") && !selected && (
          <>
            {sportDataStatus.mlb === "loading" && (
              <Glass hover={false} style={{ padding: "30px 20px", textAlign: "center", color: "var(--text-secondary-a)", fontSize: 13 }}>Loading MLB data…</Glass>
            )}
            {sportDataStatus.mlb === "error" && (
              <Glass hover={false} style={{ padding: "30px 20px", textAlign: "center", color: ACCENT.rose, fontSize: 13 }}>Couldn't load MLB data — switch sports and back, or refresh.</Glass>
            )}
            <Glass hover={false} style={{ padding: "14px 16px", marginBottom: 18 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <input
                  placeholder={tab==="offense" ? "Search MLB batters…" : "Search MLB pitchers…"}
                  value={search} onChange={e=>setSearch(e.target.value)}
                  style={{ flex: 1, minWidth: 180, background: "var(--overlay-2)", border: "1px solid var(--overlay-5)", borderRadius: 8, padding: "11px 12px", color: "var(--text-primary)", fontSize: 15 }}
                />
                <select value={team} onChange={e=>setTeam(e.target.value)} style={{ background: "var(--overlay-2)", border: "1px solid var(--overlay-5)", borderRadius: 20, color: team==="all" ? "var(--text-secondary-a)" : "var(--text-primary)", fontSize: 13, fontWeight: 600, padding: "10px 14px" }}>
                  <option value="all">Any Team</option>
                  {MLB_TEAMS.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
            </Glass>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10 }}>
              {filteredMLB.slice(0,60).map((p,i) => <MLBCard key={p.name} p={p} idx={i} onSelect={setSelected} />)}
            </div>
            {filteredMLB.length === 0 && <div style={{ color: "var(--text-tertiary)", fontSize: 13, padding: 30, textAlign: "center" }}>No matches. Try a different search or filter — or the MLB pipeline may not have run successfully yet.</div>}
            {filteredMLB.length > 60 && <div style={{ color: "var(--text-tertiary)", fontSize: 11.5, marginTop: 14, textAlign: "center" }}>Showing top 60 — narrow with search to see more.</div>}
          </>
        )}

        {selected && sport==="mlb" && <MLBDetail p={selected} onClose={()=>setSelected(null)} />}
        {selected && sport==="wnba" && <WNBADetail p={selected} onClose={()=>setSelected(null)} />}
        {selected && sport==="nfl" && tab==="offense" && selected.kind==="skill" && <SkillDetail p={selected} onClose={()=>setSelected(null)} />}
        {selected && sport==="nfl" && tab==="offense" && selected.kind==="qb" && <QBDetail p={selected} onClose={()=>setSelected(null)} />}
        {selected && tab==="offense" && selected.kind==="k" && <KickerDetail p={selected} onClose={()=>setSelected(null)} />}
        {selected && sport==="nfl" && tab==="defense" && <DefenseDetail d={selected} onClose={()=>setSelected(null)} />}

        <div style={{ borderTop: "1px solid var(--overlay-4)", marginTop: 34, paddingTop: 16, fontSize: 11, color: "var(--text-tertiary)", lineHeight: 1.6 }}>
          Data: 2024 + 2025 NFL play-by-play + Next Gen Stats participation (nflverse), joined per-play. Front and
          coverage are derived from actual on-field personnel/tracking for that snap. Locks methodology and Kalshi
          snapshot detailed in their respective tabs.
        </div>
      </div>
    </div>
  );
}


const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
