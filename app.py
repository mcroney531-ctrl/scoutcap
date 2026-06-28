"""
Rookie Draft Scouting Agent — Streamlit frontend
"""

import os, sys, asyncio, json
sys.path.insert(0, os.path.dirname(__file__))

# Fall back to .env for local dev
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import pandas as pd

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Rookie Scout",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Secrets sync (must run after set_page_config so Streamlit runtime is ready) ──

def _init_secrets():
    _errors = []
    for _key in ["ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "SLEEPER_USERNAME", "SLEEPER_LEAGUE_ID"]:
        try:
            val = str(st.secrets[_key]).strip()
            if val:
                os.environ[_key] = val
            else:
                _errors.append(f"{_key} is empty in secrets")
        except Exception as e:
            _errors.append(f"{_key} not found: {e}")
    try:
        import litellm
        litellm.anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    except Exception:
        pass
    return _errors

_secret_errors = _init_secrets()

# ── Theme / custom CSS ────────────────────────────────────────────────────────

NAVY = "#212F52"  # brand primary

PALETTES = {
    "dark": {
        "app_bg": "#0d1322",
        "sidebar_bg": "#0a0f1c",
        "panel": NAVY,
        "panel_2": "#2c3b66",
        "text": "#e9edf5",
        "muted": "#9aa6bb",
        "accent": "#e8b84b",       # gold highlight line
        "border": "rgba(255,255,255,0.08)",
        "metric_value": "#e8b84b",
        "grade_c": "#e8b84b",
    },
    "light": {
        "app_bg": "#f4f6fa",
        "sidebar_bg": "#eaeef5",
        "panel": "#ffffff",
        "panel_2": "#eef1f6",
        "text": "#1b2233",
        "muted": "#5a6678",
        "accent": NAVY,            # navy becomes the accent in light mode
        "border": "rgba(33,47,82,0.15)",
        "metric_value": NAVY,
        "grade_c": "#b8902f",      # darker gold for contrast on white
    },
}

_light = st.session_state.get("ui_light_mode", False)
P = PALETTES["light"] if _light else PALETTES["dark"]

st.markdown(
    f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=SN+Pro:ital,wght@0,300;0,400;0,600;0,700;0,800;1,400&display=swap');

      /* Typeface — SN Pro everywhere */
      html, body, .stApp, button, input, textarea, select,
      [class*="st-"], [data-testid] {{
        font-family: 'SN Pro', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
      }}

      /* Base surfaces (override config.toml so the toggle can flip the theme) */
      .stApp, [data-testid="stAppViewContainer"] {{
        background-color: {P['app_bg']}; color: {P['text']};
      }}
      [data-testid="stHeader"] {{ background: transparent; }}
      section[data-testid="stSidebar"] {{ background-color: {P['sidebar_bg']}; }}
      .stApp p, .stApp label, .stApp li,
      .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp span,
      [data-testid="stMarkdownContainer"] {{ color: {P['text']}; }}
      .stApp [data-testid="stCaptionContainer"], .stApp small {{ color: {P['muted']} !important; }}

      /* Inputs */
      .stApp input, .stApp textarea,
      .stApp [data-baseweb="input"], .stApp [data-baseweb="select"] > div {{
        background-color: {P['panel']} !important; color: {P['text']} !important;
      }}

      .block-container {{ padding-top: 2.2rem; }}

      /* Brand bar — always navy gradient in both modes, light text inside */
      .brand-bar {{
        display: flex; align-items: center; gap: 0.75rem;
        padding: 0.9rem 1.25rem; margin-bottom: 1.2rem;
        background: linear-gradient(135deg, {NAVY} 0%, #16203b 100%);
        border: 1px solid rgba(232,184,75,0.25);
        border-left: 4px solid {P['accent']};
        border-radius: 10px;
      }}
      .brand-mark {{ font-size: 1.7rem; line-height: 1; }}
      .brand-title {{
        font-size: 1.35rem; font-weight: 800; letter-spacing: -0.01em;
        color: #f3f5fa !important; margin: 0;
      }}
      .brand-title .accent {{ color: #e8b84b !important; }}
      .brand-sub {{ font-size: 0.8rem; color: #aeb8cc !important; margin: 0.1rem 0 0 0; }}

      /* Grade badge pills */
      .grade-pill {{
        display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px;
        font-weight: 800; font-size: 0.95rem; letter-spacing: 0.02em;
      }}

      /* Sidebar draft-board buttons */
      section[data-testid="stSidebar"] .stButton > button {{
        text-align: left; justify-content: flex-start;
        font-size: 0.86rem; padding: 0.32rem 0.6rem;
        border: 1px solid {P['border']};
        background: {P['panel']}; color: {P['text']};
      }}
      section[data-testid="stSidebar"] .stButton > button:hover {{
        border-color: {P['accent']}; color: {P['accent']}; background: {P['panel_2']};
      }}

      /* Metric cards */
      div[data-testid="stMetric"] {{
        background: {P['panel']}; border: 1px solid {P['border']};
        border-radius: 10px; padding: 0.7rem 0.9rem;
      }}
      div[data-testid="stMetricValue"] {{ color: {P['metric_value']}; }}

      /* Expander */
      details summary {{ font-weight: 700; }}
      div[data-testid="stExpander"] {{ border-color: {P['border']}; }}
    </style>
    """,
    unsafe_allow_html=True,
)


def grade_color(grade: str) -> str:
    """Map a letter grade to a color for badge tinting."""
    if not grade or grade == "—":
        return P["muted"]
    g = grade[0].upper()
    return {
        "A": "#3fb950",   # green
        "B": "#3b82f6" if _light else "#58a6ff",  # blue
        "C": P["grade_c"],
        "D": "#e3873c",   # orange
        "F": "#f85149",   # red
    }.get(g, P["muted"])


def grade_pill(grade: str) -> str:
    """Return an HTML pill for a letter grade."""
    c = grade_color(grade)
    return (
        f'<span class="grade-pill" '
        f'style="background:{c}22; color:{c}; border:1px solid {c}66;">{grade}</span>'
    )


def brand_bar(subtitle: str):
    """Render the gold-accent brand bar with a contextual subtitle."""
    st.markdown(
        f"""
        <div class="brand-bar">
          <div class="brand-mark">🏈</div>
          <div>
            <p class="brand-title">Rookie <span class="accent">Scout</span></p>
            <p class="brand-sub">{subtitle}</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


SORT_FIELDS = {
    "Sleeper Rank": "search_rank",
    "Name": "full_name",
    "Position": "position",
    "Team": "team",
    "College": "college",
    "Depth Chart": "depth_chart_order",
}


def render_prospect_table(all_rows, key_prefix):
    """Sortable, filterable prospect table with a ★ favorite checkbox per row.

    Ticking ★ adds/removes the player from My Board (st.session_state.shortlist).
    A selectbox + Scout button runs the pipeline for a chosen prospect.
    """
    # Sort + filter controls
    sc1, sc2, sc3 = st.columns([3, 2, 3])
    sort_label = sc1.selectbox("Sort by", list(SORT_FIELDS.keys()), index=0, key=f"{key_prefix}_sortby")
    sort_dir = sc2.radio("Order", ["Asc", "Desc"], horizontal=True, key=f"{key_prefix}_order")
    pos_pick = sc3.multiselect(
        "Positions", ["QB", "RB", "WR", "TE"], default=["QB", "RB", "WR", "TE"], key=f"{key_prefix}_pos"
    )

    sort_key = SORT_FIELDS[sort_label]

    def _sv(r):
        v = r.get(sort_key)
        if v is None or v == "":
            return (1, "")  # push missing values last
        return (0, v.lower() if isinstance(v, str) else v)

    rows = [r for r in all_rows if r["position"] in pos_pick]
    rows = sorted(rows, key=_sv, reverse=(sort_dir == "Desc"))

    if not rows:
        st.info("No prospects match the current filter.")
        return

    df = pd.DataFrame(
        [
            {
                "★": r["player_id"] in st.session_state.shortlist,
                "Rank": r["search_rank"] if r["search_rank"] < 9999999 else None,
                "Name": r["full_name"],
                "Pos": r["position"],
                "Team": r["team"],
                "College": r["college"] or "—",
                "Depth": r["depth_chart_order"],
                "Status": r["status"] or "—",
            }
            for r in rows
        ]
    )

    st.caption("Tick ★ to track a prospect on My Board.")
    edited = st.data_editor(
        df,
        column_config={"★": st.column_config.CheckboxColumn("★", help="Track on My Board", width="small")},
        disabled=["Rank", "Name", "Pos", "Team", "College", "Depth", "Status"],
        hide_index=True,
        use_container_width=True,
        height=560,
        key=f"{key_prefix}_editor",
    )

    # Sync ★ column back to the shortlist
    display_ids = {r["player_id"] for r in rows}
    displayed_favs = [rows[i]["player_id"] for i in range(len(rows)) if bool(edited.iloc[i]["★"])]
    preserved = [pid for pid in st.session_state.shortlist if pid not in display_ids]
    new_shortlist = preserved + displayed_favs
    if set(new_shortlist) != set(st.session_state.shortlist):
        st.session_state.shortlist = new_shortlist
        st.rerun()

    # Scout a prospect from this table
    names = [r["full_name"] for r in rows]
    sa, sb = st.columns([5, 1])
    pick = sa.selectbox("Scout a prospect", names, key=f"{key_prefix}_scoutpick")
    if sb.button("🔍 Scout", key=f"{key_prefix}_scoutbtn", use_container_width=True):
        chosen = next(r for r in rows if r["full_name"] == pick)
        st.session_state.selected_player = chosen
        st.session_state.view = "home"
        st.rerun()


from tools.sleeper import get_nfl_players, get_user, get_rosters
from agents.synthesis_agent import run_synthesis_agent

# ── Session state defaults ────────────────────────────────────────────────────

if "shortlist" not in st.session_state:
    st.session_state.shortlist = []
if "selected_player" not in st.session_state:
    st.session_state.selected_player = None
if "analysis_cache" not in st.session_state:
    st.session_state.analysis_cache = {}
if "chat_history" not in st.session_state:
    st.session_state.chat_history = {}
if "view" not in st.session_state:
    st.session_state.view = "home"

# ── Data loading ──────────────────────────────────────────────────────────────


@st.cache_data(ttl=3600, show_spinner="Loading rookie draft board...")
def load_rookies():
    players = get_nfl_players()
    rookies = [
        {
            "player_id": pid,
            "full_name": p.get("full_name", "Unknown"),
            "position": p.get("position"),
            "team": p.get("team") or "FA",
            "search_rank": p.get("search_rank") or 9999999,
            "depth_chart_order": p.get("depth_chart_order"),
            "status": p.get("status", ""),
            "college": p.get("college", ""),
        }
        for pid, p in players.items()
        if p.get("years_exp") == 0
        and p.get("active")
        and p.get("position") in ("QB", "RB", "WR", "TE")
    ]
    rookies.sort(key=lambda p: p["search_rank"])
    return rookies

# ── Sidebar — draft board ─────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🏈 2026 Rookie Draft Board")

    st.toggle("☀️ Light mode", key="ui_light_mode", help="Switch between the navy dark theme and a light theme")

    # API key diagnostic — remove once confirmed working
    _api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if _api_key:
        st.caption(f"🔑 API key loaded ({_api_key[:4]}...{_api_key[-4:]})")
    else:
        st.error(f"❌ ANTHROPIC_API_KEY missing. Secrets errors: {_secret_errors}")

    rookies = load_rookies()

    # Position filter
    pos_filter = st.multiselect(
        "Position",
        ["QB", "RB", "WR", "TE"],
        default=["QB", "RB", "WR", "TE"],
        label_visibility="collapsed",
    )

    # Search
    search = st.text_input("Search players", placeholder="e.g. Jeremiyah Love", label_visibility="collapsed")

    filtered = [
        r for r in rookies
        if r["position"] in pos_filter
        and (not search or search.lower() in r["full_name"].lower())
    ]

    st.caption(f"{len(filtered)} prospects • click to scout")
    st.divider()

    # Shortlist section
    if st.session_state.shortlist:
        with st.expander(f"⭐ My Shortlist ({len(st.session_state.shortlist)})", expanded=False):
            for pid in list(st.session_state.shortlist):
                match = next((r for r in rookies if r["player_id"] == pid), None)
                if match:
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        if st.button(match["full_name"], key=f"sl_{pid}", use_container_width=True):
                            st.session_state.selected_player = match
                    with col2:
                        if st.button("✕", key=f"rm_{pid}"):
                            st.session_state.shortlist.remove(pid)
                            st.rerun()
        st.divider()

    # Draft board list
    for r in filtered[:75]:
        pos_colors = {"QB": "🟦", "RB": "🟩", "WR": "🟨", "TE": "🟧"}
        icon = pos_colors.get(r["position"], "⬜")
        label = f"{icon} {r['full_name']} · {r['position']} · {r['team']}"

        if st.button(label, key=f"board_{r['player_id']}", use_container_width=True):
            st.session_state.selected_player = r
            st.rerun()

# ── Main panel ────────────────────────────────────────────────────────────────

# ── All-prospects table view ──────────────────────────────────────────────────

if st.session_state.view == "all":
    brand_bar("Full 2026 rookie prospect list")

    top_l, top_r = st.columns([6, 1])
    with top_l:
        st.markdown(f"### 📊 All Prospects · {len(rookies)} players")
    with top_r:
        if st.button("← Back", use_container_width=True):
            st.session_state.view = "home"
            st.rerun()

    render_prospect_table(rookies, "all")
    st.stop()


# ── My Board table view ───────────────────────────────────────────────────────

if st.session_state.view == "board":
    brand_bar("Your tracked prospects")

    top_l, top_r = st.columns([6, 1])
    with top_l:
        st.markdown(f"### 📋 My Board · {len(st.session_state.shortlist)} tracked")
    with top_r:
        if st.button("← Back", use_container_width=True):
            st.session_state.view = "home"
            st.rerun()

    tracked = [r for r in rookies if r["player_id"] in st.session_state.shortlist]
    if not tracked:
        st.info("Your board is empty. Star players (★) from **All Prospects** or a scouting report to track them here.")
        if st.button("📊 Browse all prospects →"):
            st.session_state.view = "all"
            st.rerun()
    else:
        render_prospect_table(tracked, "board")
    st.stop()


if st.session_state.selected_player is None:
    brand_bar("Three-agent dynasty draft evaluation engine")

    # How it works — folded away so the landing page stays open
    with st.expander("❓ How it Works", expanded=False):
        st.markdown(
            "Select a prospect from the draft board to run a full scouting report. "
            "The three-agent pipeline evaluates **Talent**, **Opportunity**, and **Risk** "
            "independently, then combines them into a dynasty draft recommendation."
        )
        col1, col2, col3 = st.columns(3)
        with col1:
            st.info("**Situation Agent**\nDepth chart + draft capital → Opportunity Grade")
        with col2:
            st.info("**Production Agent**\nCollege stats + injury history → Talent Grade + Risk")
        with col3:
            st.info("**Synthesis Agent**\nOrchestrates both + roster need + sentiment → Pick recommendation")

    # ── My Board card (click to open the board table) ─────────────────────────
    with st.container(border=True):
        n = len(st.session_state.shortlist)
        st.markdown(
            f"### 📋 My Board &nbsp;<span class='grade-pill' "
            f"style='background:{P['accent']}22;color:{P['accent']};border:1px solid {P['accent']}66;'>{n}</span>",
            unsafe_allow_html=True,
        )

        if not st.session_state.shortlist:
            st.caption("Your board is empty. Star players (★) from All Prospects or a scouting report to track them here.")
        else:
            preview = [
                next((r["full_name"] for r in rookies if r["player_id"] == pid), None)
                for pid in st.session_state.shortlist
            ]
            preview = [p for p in preview if p]
            st.caption(", ".join(preview[:6]) + (" …" if len(preview) > 6 else ""))

        if st.button("Open My Board →", use_container_width=True, key="open_board"):
            st.session_state.view = "board"
            st.rerun()

    st.write("")
    if st.button("📊 View all prospects →", use_container_width=True):
        st.session_state.view = "all"
        st.rerun()

    st.stop()

player = st.session_state.selected_player
pid = player["player_id"]
name = player["full_name"]

# ── Player header ─────────────────────────────────────────────────────────────

brand_bar("Scouting report")

col_name, col_add = st.columns([5, 1])
with col_name:
    st.markdown(f"## {name}")
    st.caption(f"{player['position']} · {player['team']} · {player['college']}")
with col_add:
    if pid not in st.session_state.shortlist:
        if st.button("⭐ Favorite", use_container_width=True):
            st.session_state.shortlist.append(pid)
            st.rerun()
    else:
        if st.button("★ Favorited — remove", use_container_width=True):
            st.session_state.shortlist.remove(pid)
            st.rerun()

st.divider()

# ── Analysis card ─────────────────────────────────────────────────────────────

# Run analysis if not cached
if pid not in st.session_state.analysis_cache:
    progress = st.empty()
    steps = [
        "🔍 Situation Agent: evaluating landing spot and depth chart...",
        "📊 Production Agent: analyzing college stats and injury history...",
        "🧠 Synthesis Agent: combining signals and computing recommendation...",
    ]
    for step in steps:
        progress.info(step)
    try:
        result = asyncio.run(run_synthesis_agent(name))
        st.session_state.analysis_cache[pid] = result
        if pid not in st.session_state.chat_history:
            st.session_state.chat_history[pid] = []
        progress.empty()
    except Exception as e:
        progress.empty()
        st.error(f"Pipeline error: {e}")
        st.stop()

analysis = st.session_state.analysis_cache.get(pid, {})

if "raw_output" in analysis:
    st.warning("Agent returned unstructured output:")
    st.text(analysis["raw_output"])
else:
    # Collapsible analysis card
    headline = analysis.get("headline", "")
    talent_g = analysis.get("talent_grade", "—")
    opp_g = analysis.get("opportunity_grade", "—")
    rec = analysis.get("recommended_pick", "—")
    floor_p = analysis.get("floor_pick", "—")
    ceil_p = analysis.get("ceiling_pick", "—")
    composite = analysis.get("composite_score", "—")
    roster_need = analysis.get("roster_need", "—")

    with st.expander("📋 Scouting Report", expanded=True):
        # Grade badges
        st.markdown(
            f"Talent {grade_pill(talent_g)} &nbsp;&nbsp; Opportunity {grade_pill(opp_g)}",
            unsafe_allow_html=True,
        )
        st.write("")

        # Grade row
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Talent Grade", talent_g, f"Score: {analysis.get('talent_score', '—')}")
        c2.metric("Opportunity Grade", opp_g, f"Score: {analysis.get('opportunity_score', '—')}")
        c3.metric("Composite Score", composite)
        c4.metric("Roster Need", roster_need)

        st.divider()

        # Pick recommendation
        pc1, pc2, pc3 = st.columns(3)
        pc1.metric("🎯 Recommended Pick", rec)
        pc2.metric("📈 Ceiling", ceil_p)
        pc3.metric("📉 Floor", floor_p)

        st.divider()

        # Risk modifier
        risk = analysis.get("risk_modifier", {})
        dur = risk.get("durability_score", "—")
        inj_pct = risk.get("injury_chance_pct", "—")
        st.markdown(f"**Risk Modifier:** Durability {dur}/5 · Injury chance {inj_pct}%")
        if risk.get("injury_notes"):
            st.caption(risk["injury_notes"])

        st.divider()

        # Narrative
        st.markdown("**Analysis**")
        st.markdown(analysis.get("narrative", ""))

        # Sentiment
        sent = analysis.get("sentiment", {})
        rank = sent.get("rank_in_class")
        activity = sent.get("activity_level", "")
        if rank:
            st.caption(f"📊 Sentiment: #{rank} in rookie class trending adds ({activity} activity period)")
        else:
            st.caption(f"📊 Sentiment: Not in current trending ({activity} activity — treat as neutral)")

        st.divider()

        # Key upside / risks
        up_col, risk_col = st.columns(2)
        with up_col:
            st.markdown("**Key Upside**")
            for item in analysis.get("key_upside", []):
                st.markdown(f"✅ {item}")
        with risk_col:
            st.markdown("**Key Risks**")
            for item in analysis.get("key_risks", []):
                st.markdown(f"⚠️ {item}")

        st.divider()
        st.caption(f"**KTC Comparison:** {analysis.get('ktc_comparison', '—')}")
        st.caption(f"**Roster Note:** {analysis.get('roster_need_note', '—')}")

# ── Chat thread ───────────────────────────────────────────────────────────────

st.markdown("### 💬 Ask a follow-up")

chat_history = st.session_state.chat_history.get(pid, [])

# Display prior messages
for msg in chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Chat input
if prompt := st.chat_input(f"Ask anything about {name}..."):
    chat_history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            import anthropic
            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

            context = f"""You are a dynasty fantasy football analyst assistant.
You have just completed a scouting report for {name}. Here is the full analysis:

{json.dumps(analysis, indent=2)}

Answer the user's follow-up question concisely and specifically, referencing the data above where relevant.
Keep responses to 2-4 sentences unless a longer answer is clearly needed."""

            messages = [{"role": "user", "content": context + "\n\nUser question: " + prompt}]
            for prev in chat_history[:-1]:
                messages.append({"role": prev["role"], "content": prev["content"]})
            messages.append({"role": "user", "content": prompt})

            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=512,
                system=context,
                messages=[{"role": m["role"], "content": m["content"]} for m in chat_history],
            )
            reply = response.content[0].text

        st.markdown(reply)

    chat_history.append({"role": "assistant", "content": reply})
    st.session_state.chat_history[pid] = chat_history
