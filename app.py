"""
Rookie Draft Scouting Agent — Streamlit frontend
"""

import os, sys, asyncio, json, random, time
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
        "app_bg": "#f7faff",
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

_light = st.session_state.get("ui_light_mode", True)
P = PALETTES["light"] if _light else PALETTES["dark"]

st.markdown(
    f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=SN+Pro:ital,wght@0,300;0,400;0,600;0,700;0,800;1,400&display=swap');

      /* Typeface — SN Pro on text content; intentionally excludes
         [class*="st-"] and bare [data-testid] to avoid clobbering
         Streamlit's internal Material Symbols icon font. */
      html, body, .stApp, button, input, textarea, select,
      [data-testid="stMarkdownContainer"],
      [data-testid="stText"],
      [data-testid="stWidgetLabel"] {{
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

      /* Info / alert boxes — navy background, white text in both modes */
      div[data-testid="stAlert"] {{
        background-color: {NAVY} !important;
        border-color: {NAVY} !important;
        border-radius: 8px;
      }}
      div[data-testid="stAlert"] p,
      div[data-testid="stAlert"] span,
      div[data-testid="stAlert"] [data-testid="stMarkdownContainer"],
      div[data-testid="stAlert"] [data-testid="stMarkdownContainer"] * {{
        color: #ffffff !important;
      }}
      div[data-testid="stAlert"] svg {{ fill: #ffffff !important; }}

      /* Multiselect tag pills — navy bg from primaryColor needs white text */
      [data-baseweb="tag"] {{ background-color: {NAVY} !important; }}
      [data-baseweb="tag"] span {{ color: #ffffff !important; }}
      [data-baseweb="tag"] svg {{ fill: #ffffff !important; color: #ffffff !important; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# Neumorphic layer — light mode only.
# Shadow pair calibrated to #f7faff:  dark → #cdd1e0  |  light → #ffffff
# Sidebar shadow pair for #eaeef5:     dark → #c4c8d3  |  light → #ffffff
if _light:
    st.markdown(
        """<style>
        /* ── Buttons ── */
        .stButton > button {
          background: #f7faff !important;
          border: none !important;
          border-radius: 12px !important;
          color: #212F52 !important;
          font-weight: 600 !important;
          box-shadow: 5px 5px 12px #cdd1e0, -5px -5px 12px #ffffff !important;
          transition: box-shadow 0.15s ease, transform 0.12s ease !important;
        }
        .stButton > button:hover {
          box-shadow: 3px 3px 8px #cdd1e0, -3px -3px 8px #ffffff !important;
          transform: translateY(-1px);
        }
        .stButton > button:active {
          box-shadow: inset 3px 3px 7px #cdd1e0, inset -3px -3px 7px #ffffff !important;
          transform: translateY(0);
        }

        /* ── Sidebar draft-board buttons (base = sidebar_bg #eaeef5) ── */
        section[data-testid="stSidebar"] .stButton > button {
          background: #eaeef5 !important;
          border: none !important;
          box-shadow: 3px 3px 8px #c4c8d3, -3px -3px 8px #ffffff !important;
        }
        section[data-testid="stSidebar"] .stButton > button:hover {
          background: #eaeef5 !important;
          box-shadow: 2px 2px 5px #c4c8d3, -2px -2px 5px #ffffff !important;
        }
        section[data-testid="stSidebar"] .stButton > button:active {
          box-shadow: inset 2px 2px 5px #c4c8d3, inset -2px -2px 5px #ffffff !important;
        }

        /* ── Inputs and textareas — inset / recessed ── */
        .stApp input, .stApp textarea,
        .stApp [data-baseweb="input"],
        .stApp [data-baseweb="textarea"] {
          background: #f7faff !important;
          border: none !important;
          border-radius: 10px !important;
          box-shadow: inset 3px 3px 7px #cdd1e0, inset -3px -3px 7px #ffffff !important;
        }

        /* ── Select / dropdowns — inset ── */
        .stApp [data-baseweb="select"] > div {
          background: #f7faff !important;
          border: none !important;
          border-radius: 10px !important;
          box-shadow: inset 3px 3px 7px #cdd1e0, inset -3px -3px 7px #ffffff !important;
        }

        /* ── Metric cards — outset / raised ── */
        div[data-testid="stMetric"] {
          background: #f7faff !important;
          border: none !important;
          border-radius: 14px !important;
          box-shadow: 6px 6px 14px #cdd1e0, -6px -6px 14px #ffffff !important;
        }

        /* ── Expanders — outset / raised ── */
        div[data-testid="stExpander"] {
          background: #f7faff !important;
          border: none !important;
          border-radius: 12px !important;
          box-shadow: 5px 5px 12px #cdd1e0, -5px -5px 12px #ffffff !important;
          overflow: hidden;
        }

        /* ── Toggle widget ── */
        div[data-testid="stToggle"] > label {
          gap: 0.5rem;
        }
        </style>""",
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


# ── Mock Draft Simulator helpers ──────────────────────────────────────────────

def _get_adp_ranking(rookies: list) -> list:
    """Rank prospects by estimated ADP. Sleeper search_rank primary; FC dynasty
    value fallback for players without a Sleeper rank."""
    from tools.fantasycalc import _load as _fc_load
    fc = _fc_load()
    out = []
    for r in rookies:
        sr = r.get("search_rank") or 9999999
        fc_rec = fc.get(str(r["player_id"]))
        if sr < 9999999:
            score = float(sr)
        elif fc_rec:
            # Offset so FC players sort after all Sleeper-ranked prospects.
            score = 10000.0 - fc_rec.get("dynasty_value", 0)
        else:
            score = 999999.0
        out.append({**r, "_adp_score": score})
    return sorted(out, key=lambda x: x["_adp_score"])


def _pick_label(overall: int, teams: int = 12) -> str:
    r = (overall - 1) // teams + 1
    p = (overall - 1) % teams + 1
    return f"{r}.{p:02d}"


def _user_picks_for_slot(slot: int, rounds: int = 4, teams: int = 12) -> list:
    """Overall pick numbers for a given draft slot (snake draft)."""
    picks = []
    for r in range(rounds):
        picks.append(r * teams + slot if r % 2 == 0 else r * teams + (teams - slot + 1))
    return picks


def _start_draft(slot: int, pins: dict, variance: int, rookies: list):
    """Initialize interactive draft state. Called once when user clicks Start Draft."""
    adp = _get_adp_ranking(rookies)
    user_picks_set = set(_user_picks_for_slot(slot))
    pinned_ids = {str(v) for v in pins.values()}

    # Resolve pins to player dicts
    pin_map = {}
    for pick_num, pid in pins.items():
        match = next((r for r in adp if str(r["player_id"]) == str(pid)), None)
        if match:
            pin_map[int(pick_num)] = match

    # Build available pool with variance noise applied upfront (excludes pinned players)
    pool = []
    for i, p in enumerate(adp):
        if str(p["player_id"]) not in pinned_ids:
            noise = random.gauss(0, variance) if variance > 0 else 0
            pool.append((i + noise, p))
    pool.sort(key=lambda x: x[0])

    st.session_state.mock_active = True
    st.session_state.mock_draft_picks = []
    st.session_state.mock_draft_available = [p for _, p in pool]
    st.session_state.mock_draft_current_pick = 1
    st.session_state.mock_draft_pin_map = pin_map
    st.session_state.mock_draft_user_picks_set = user_picks_set


def _render_draft_board(completed_map: dict, current_pick: int, user_picks_set: set, draft_done: bool):
    """Render the HTML draft board grid (4 rounds × 12 picks)."""
    POS_COLOR = {"QB": "#3b82f6", "RB": "#3fb950", "WR": "#e8b84b", "TE": "#e3873c"}
    rows_html = ""
    for round_idx in range(4):
        cells = ""
        for pick_n in range(round_idx * 12 + 1, round_idx * 12 + 13):
            lbl = _pick_label(pick_n)
            pp = completed_map.get(pick_n)
            is_on_clock = (pick_n == current_pick and not draft_done)

            if is_on_clock:
                cell = (
                    f'<td style="padding:8px 9px;border-radius:8px;border:2px solid {P["accent"]};'
                    f'background:{P["accent"]}30;vertical-align:top;min-width:80px;">'
                    f'<div style="font-size:0.62rem;color:{P["accent"]};font-weight:700;margin-bottom:2px;">{lbl} 🟡</div>'
                    f'<div style="font-weight:800;font-size:0.8rem;color:{P["accent"]};">YOU</div>'
                    f'<div style="font-size:0.68rem;color:{P["accent"]};">ON THE CLOCK</div></td>'
                )
            elif pp:
                player = pp.get("player")
                is_user = pp["is_user"]
                is_pin = pp.get("pinned", False)
                bw = "2px" if is_user else "1px"
                bs = "dashed" if is_pin else "solid"
                bc = P["accent"] if is_user else P["border"]
                bg = f"{P['accent']}18" if is_user else P["panel"]
                nc = P["accent"] if is_user else P["text"]
                pin_ico = " 📌" if is_pin else ""
                if player:
                    pos = player.get("position", "")
                    team = player.get("team") or "FA"
                    pc = POS_COLOR.get(pos, P["muted"])
                    cell = (
                        f'<td style="padding:8px 9px;border-radius:8px;border:{bw} {bs} {bc};'
                        f'background:{bg};vertical-align:top;min-width:80px;">'
                        f'<div style="font-size:0.62rem;color:{P["muted"]};margin-bottom:2px;">{lbl}{pin_ico}</div>'
                        f'<div style="font-weight:700;font-size:0.78rem;color:{nc};line-height:1.25;">{player["full_name"]}</div>'
                        f'<div style="font-size:0.68rem;margin-top:2px;">'
                        f'<span style="color:{pc};font-weight:600;">{pos}</span>'
                        f'<span style="color:{P["muted"]};"> · {team}</span></div></td>'
                    )
                else:
                    cell = (
                        f'<td style="padding:8px 9px;border-radius:8px;border:{bw} {bs} {bc};'
                        f'background:{bg};vertical-align:top;">'
                        f'<div style="font-size:0.62rem;color:{P["muted"]};">{lbl}</div>'
                        f'<div style="font-size:0.78rem;color:{P["muted"]};">—</div></td>'
                    )
            else:
                # Future/empty pick
                is_future_user = pick_n in user_picks_set
                bc = P["accent"] if is_future_user else P["border"]
                opacity = "0.5" if is_future_user else "0.25"
                cell = (
                    f'<td style="padding:8px 9px;border-radius:8px;border:1px dashed {bc};'
                    f'background:{P["panel"]}10;vertical-align:top;min-width:80px;opacity:{opacity};">'
                    f'<div style="font-size:0.62rem;color:{P["muted"]};">{lbl}</div>'
                    f'<div style="font-size:0.78rem;color:{P["muted"]};">·</div></td>'
                )
            cells += cell

        rnd_hdr = (
            f'<td style="padding:4px 6px;font-size:0.7rem;font-weight:700;'
            f'color:{P["muted"]};vertical-align:middle;white-space:nowrap;">R{round_idx+1}</td>'
        )
        rows_html += f"<tr>{rnd_hdr}{cells}</tr>"

    st.markdown(
        f'<div style="overflow-x:auto;margin:0.8rem 0;">'
        f'<table style="border-collapse:separate;border-spacing:5px;width:100%;">'
        f'<tbody>{rows_html}</tbody></table></div>',
        unsafe_allow_html=True,
    )


def render_mock_draft(rookies: list):
    """Interactive turn-by-turn mock draft view."""
    brand_bar("2026 Mock Draft Simulator")

    top_l, top_r = st.columns([6, 1])
    with top_l:
        st.markdown("### 🎯 Mock Draft")
    with top_r:
        if st.button("🏠", use_container_width=True, key="mock_back"):
            st.session_state.mock_active = False
            st.session_state.view = "home"
            st.rerun()

    # ── Setup screen (draft not yet started) ─────────────────────────────────
    if not st.session_state.mock_active:
        s1, s2, s3 = st.columns([2, 3, 3])
        with s1:
            slot = st.selectbox(
                "Your draft slot", list(range(1, 13)),
                index=st.session_state.mock_slot - 1, key="mock_slot_sel",
                help="Your position in the 12-team league",
            )
            st.session_state.mock_slot = slot
        with s2:
            variance = st.slider(
                "Variance", 0, 5, st.session_state.mock_variance, key="mock_var_slider",
                help="0 = pure ADP order · 5 = heavy randomness",
            )
            st.session_state.mock_variance = variance
        with s3:
            labels = "  ·  ".join(_pick_label(p) for p in _user_picks_for_slot(slot))
            st.metric("Your picks", labels)

        pin_count = len(st.session_state.mock_pins)
        with st.expander(f"📌 Pre-set picks  ({pin_count} pinned)", expanded=bool(pin_count)):
            if st.session_state.mock_pins:
                for pick_num, pid in list(st.session_state.mock_pins.items()):
                    match = next((r for r in rookies if r["player_id"] == pid), None)
                    name_str = match["full_name"] if match else str(pid)
                    ca, cb = st.columns([6, 1])
                    ca.markdown(f"**{_pick_label(int(pick_num))}** → {name_str}")
                    if cb.button("✕", key=f"rm_pin_{pick_num}"):
                        del st.session_state.mock_pins[pick_num]
                        st.rerun()
                st.divider()
            rookie_names = ["(select player)"] + [r["full_name"] for r in rookies]
            pa, pb, pc = st.columns([4, 2, 1])
            pin_player = pa.selectbox("Player", rookie_names, key="mock_pin_player_sel")
            pin_pick_num = pb.number_input("To pick #", 1, 48, 1, step=1, key="mock_pin_pick_num")
            if pc.button("+ Pin", key="add_pin_btn"):
                if pin_player != "(select player)":
                    match = next((r for r in rookies if r["full_name"] == pin_player), None)
                    if match:
                        st.session_state.mock_pins[int(pin_pick_num)] = match["player_id"]
                        st.rerun()

        if st.button("▶ Start Draft", type="primary", use_container_width=True, key="start_draft_btn"):
            _start_draft(st.session_state.mock_slot, st.session_state.mock_pins,
                         st.session_state.mock_variance, rookies)
            st.rerun()
        return

    # ── Active draft ──────────────────────────────────────────────────────────
    completed   = st.session_state.mock_draft_picks
    available   = st.session_state.mock_draft_available
    current     = st.session_state.mock_draft_current_pick
    user_set    = st.session_state.mock_draft_user_picks_set
    pin_map     = st.session_state.mock_draft_pin_map

    # Process ONE pick per render: CPU/pinned picks animate in one at a time.
    # Stops when we hit an un-pinned user pick or the draft ends.
    animating = False
    if current <= 48:
        is_user = current in user_set
        if current in pin_map:
            completed.append({"pick": current, "player": pin_map[current], "is_user": is_user, "pinned": True})
            current += 1
            animating = True
        elif not is_user:
            player = available.pop(0) if available else None
            completed.append({"pick": current, "player": player, "is_user": False, "pinned": False})
            current += 1
            animating = True

    st.session_state.mock_draft_picks = completed
    st.session_state.mock_draft_available = available
    st.session_state.mock_draft_current_pick = current

    draft_done = current > 48

    # Status bar
    hdr_l, hdr_r = st.columns([5, 1])
    with hdr_l:
        if draft_done:
            st.success("✅ Draft complete!")
        elif animating:
            st.info(f"⏳ Pick **{current - 1}/48** — other teams picking...")
        else:
            n_user_done = sum(1 for p in completed if p["is_user"])
            st.info(f"🟡 Pick **{current}/48** — your pick {n_user_done + 1} of {len(user_set)}")
    with hdr_r:
        if st.button("🔄 Restart", use_container_width=True, key="restart_draft"):
            st.session_state.mock_active = False
            st.rerun()

    # Draft board (rendered with the pick we just added, before the next rerun)
    completed_map = {p["pick"]: p for p in completed}
    _render_draft_board(completed_map, current if not draft_done else 999, user_set, draft_done)

    # ── Still animating CPU picks — sleep then trigger next pick ─────────────
    if animating and not draft_done:
        time.sleep(0.25)
        st.rerun()

    # ── Draft complete: show haul ─────────────────────────────────────────────
    if draft_done:
        st.markdown("---")
        st.markdown("### 🏆 Your Haul")
        user_picks_list = [p for p in completed if p["is_user"]]
        haul_cols = st.columns(len(user_picks_list))
        for i, pp in enumerate(user_picks_list):
            player = pp.get("player")
            lbl = _pick_label(pp["pick"])
            with haul_cols[i]:
                with st.container(border=True):
                    st.markdown(f"**{lbl}**")
                    if player:
                        cached = st.session_state.analysis_cache.get(player["player_id"], {})
                        grade = cached.get("talent_grade") or cached.get("opportunity_grade")
                        st.markdown(f"**{player['full_name']}**")
                        st.caption(f"{player.get('position','')} · {player.get('team') or 'FA'}")
                        if grade:
                            st.markdown(grade_pill(grade), unsafe_allow_html=True)
                        if st.button("🔍 Scout", key=f"haul_scout_{i}", use_container_width=True):
                            st.session_state.selected_player = player
                            st.session_state.view = "home"
                            st.rerun()
                    else:
                        st.caption("—")
        return

    # ── On the clock: pick UI ─────────────────────────────────────────────────
    st.markdown(f"### 🟡 You're on the clock — **{_pick_label(current)}**")

    cl1, cl2 = st.columns([2, 4])
    with cl1:
        pos_filter = st.multiselect(
            "Position", ["QB", "RB", "WR", "TE"],
            default=["QB", "RB", "WR", "TE"],
            key="mock_avail_pos", label_visibility="collapsed",
        )
    with cl2:
        avail_search = st.text_input(
            "Search", placeholder="Filter by name...",
            key="mock_avail_search", label_visibility="collapsed",
        )

    filtered = [
        p for p in available
        if p.get("position") in pos_filter
        and (not avail_search or avail_search.lower() in p["full_name"].lower())
    ]

    st.caption(f"{len(filtered)} available · click a name to draft")

    if not filtered:
        st.warning("No players match the filter.")
    else:
        POS_ICON  = {"QB": "🟦", "RB": "🟩", "WR": "🟨", "TE": "🟧"}

        # Column headers (HTML — stays horizontal on mobile)
        st.markdown(
            f"<div style='display:grid;grid-template-columns:1fr 48px 52px 1fr;gap:0 8px;"
            f"padding:0 4px 4px 4px;'>"
            f"<span style='font-size:0.72rem;font-weight:700;color:{P['muted']};text-transform:uppercase;letter-spacing:.05em;'>Player</span>"
            f"<span style='font-size:0.72rem;font-weight:700;color:{P['muted']};text-transform:uppercase;letter-spacing:.05em;'>Pos</span>"
            f"<span style='font-size:0.72rem;font-weight:700;color:{P['muted']};text-transform:uppercase;letter-spacing:.05em;'>Team</span>"
            f"<span style='font-size:0.72rem;font-weight:700;color:{P['muted']};text-transform:uppercase;letter-spacing:.05em;'>College</span>"
            f"</div>"
            f"<hr style='margin:0 0 4px 0;border:none;border-top:1px solid {P['border']};'>",
            unsafe_allow_html=True,
        )

        POS_COLOR_MAP = {"QB": "#3b82f6", "RB": "#3fb950", "WR": "#e8b84b", "TE": "#e3873c"}

        for i, p in enumerate(filtered[:30]):
            pos   = p.get("position", "")
            team  = p.get("team") or "FA"
            college = p.get("college") or "—"
            icon  = POS_ICON.get(pos, "⬜")
            pc    = POS_COLOR_MAP.get(pos, P["muted"])

            # Each row: two columns — info block (HTML) + invisible pick trigger
            left, right = st.columns([6, 1])

            left.markdown(
                f"<div style='display:grid;grid-template-columns:1fr 48px 52px 1fr;gap:0 8px;"
                f"align-items:center;padding:6px 4px;border-bottom:1px solid {P['border']};'>"
                f"<span style='font-weight:700;font-size:0.88rem;color:{P['text']};'>{icon} {p['full_name']}</span>"
                f"<span style='font-weight:700;font-size:0.85rem;color:{pc};'>{pos}</span>"
                f"<span style='font-size:0.85rem;color:{P['text']};'>{team}</span>"
                f"<span style='font-size:0.8rem;color:{P['muted']};'>{college}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

            if right.button("Pick", key=f"pick_row_{i}", use_container_width=True):
                completed.append({"pick": current, "player": p, "is_user": True, "pinned": False})
                available.remove(p)
                st.session_state.mock_draft_picks = completed
                st.session_state.mock_draft_available = available
                st.session_state.mock_draft_current_pick = current + 1
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────

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
if "mock_slot" not in st.session_state:
    st.session_state.mock_slot = 1
if "mock_variance" not in st.session_state:
    st.session_state.mock_variance = 2
if "mock_pins" not in st.session_state:
    st.session_state.mock_pins = {}       # {overall_pick_int: player_id_str}
if "mock_active" not in st.session_state:
    st.session_state.mock_active = False
if "mock_draft_picks" not in st.session_state:
    st.session_state.mock_draft_picks = []
if "mock_draft_available" not in st.session_state:
    st.session_state.mock_draft_available = []
if "mock_draft_current_pick" not in st.session_state:
    st.session_state.mock_draft_current_pick = 1
if "mock_draft_pin_map" not in st.session_state:
    st.session_state.mock_draft_pin_map = {}
if "mock_draft_user_picks_set" not in st.session_state:
    st.session_state.mock_draft_user_picks_set = set()

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

    # Home nav — hidden target for the floating FAB; also usable directly from sidebar
    _on_home = (st.session_state.get("view", "home") == "home"
                and not st.session_state.get("selected_player"))
    if not _on_home:
        if st.button("🏠 Home", key="sidebar_home_nav", use_container_width=True):
            st.session_state.selected_player = None
            st.session_state.view = "home"
            st.rerun()

    st.toggle("☀️ Light mode", key="ui_light_mode", value=True, help="Toggle between light (default) and dark navy theme")

    if st.button("🎯 Mock Draft", use_container_width=True, key="sidebar_mock"):
        st.session_state.view = "mock"
        st.rerun()

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


# ── Floating home button (FAB) ────────────────────────────────────────────────
# Injected into the parent document once. Clicks the sidebar home button so
# Streamlit handles the navigation — works even when the sidebar is collapsed.
if not _on_home:
    import streamlit.components.v1 as _components
    _components.html(
        """<script>
        (function() {
            var p = window.parent.document;
            if (p.getElementById('scout-home-fab')) return;
            var fab = p.createElement('button');
            fab.id = 'scout-home-fab';
            fab.title = 'Go home';
            fab.textContent = '🏠';
            fab.style.cssText = [
                'position:fixed',
                'top:0.65rem',
                'right:3.75rem',
                'z-index:999999',
                'width:2.2rem',
                'height:2.2rem',
                'border-radius:50%',
                'border:none',
                'background:#212F52',
                'color:#fff',
                'font-size:1rem',
                'cursor:pointer',
                'box-shadow:2px 4px 12px rgba(33,47,82,0.35)',
                'display:flex',
                'align-items:center',
                'justify-content:center',
                'transition:transform 0.12s ease,box-shadow 0.12s ease',
                'line-height:1'
            ].join(';');
            fab.addEventListener('mouseenter', function() {
                this.style.transform = 'scale(1.12)';
                this.style.boxShadow = '2px 6px 16px rgba(33,47,82,0.45)';
            });
            fab.addEventListener('mouseleave', function() {
                this.style.transform = 'scale(1)';
                this.style.boxShadow = '2px 4px 12px rgba(33,47,82,0.35)';
            });
            fab.addEventListener('click', function() {
                var btns = p.querySelectorAll(
                    'section[data-testid="stSidebar"] button'
                );
                for (var i = 0; i < btns.length; i++) {
                    if (btns[i].textContent.trim().startsWith('🏠')) {
                        btns[i].click();
                        return;
                    }
                }
            });
            p.body.appendChild(fab);
        })();
        </script>""",
        height=0, scrolling=False,
    )
else:
    # Remove FAB when back on home screen
    import streamlit.components.v1 as _components
    _components.html(
        """<script>
        (function() {
            var el = window.parent.document.getElementById('scout-home-fab');
            if (el) el.remove();
        })();
        </script>""",
        height=0, scrolling=False,
    )

if st.session_state.view == "mock":
    render_mock_draft(rookies)
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

    # ── Mock Draft card ───────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("### 🎯 Mock Draft Simulator")
        if st.session_state.mock_active:
            n_done = len(st.session_state.mock_draft_picks)
            cur = st.session_state.mock_draft_current_pick
            if cur > 48:
                haul = [
                    p["player"]["full_name"] for p in st.session_state.mock_draft_picks
                    if p["is_user"] and p.get("player")
                ]
                st.caption("Draft complete · Haul: " + "  ·  ".join(haul))
            else:
                st.caption(f"Draft in progress — pick {cur}/48")
        else:
            st.caption("Pick live, turn-by-turn — set your slot, pin known picks, then go on the clock.")
        if st.button("Open Mock Draft →", use_container_width=True, key="open_mock"):
            st.session_state.view = "mock"
            st.rerun()

    st.write("")
    if st.button("📊 View all prospects →", use_container_width=True):
        st.session_state.view = "all"
        st.rerun()

    st.stop()

player = st.session_state.selected_player
pid = player["player_id"]
name = player["full_name"]

# Collapse the sidebar immediately when a player is opened.
# sessionStorage (browser-side) prevents re-toggling on Streamlit rerenders
# while still allowing the user to manually re-open the sidebar.
import streamlit.components.v1 as _components
_components.html(
    f"""<script>
    try {{
        var key = 'sbCollapsed_{pid}';
        if (!sessionStorage.getItem(key)) {{
            var sb = window.parent.document.querySelector('section[data-testid="stSidebar"]');
            if (sb && sb.getBoundingClientRect().width > 50) {{
                var btn = sb.querySelector('button');
                if (btn) {{ btn.click(); sessionStorage.setItem(key, '1'); }}
            }}
        }}
    }} catch(e) {{}}
    </script>""",
    height=0, scrolling=False,
)

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

        # Veteran competition (quality, not just headcount)
        comp = analysis.get("competition", {})
        if comp:
            vet_n = comp.get("veteran_count", "—")
            repl = comp.get("replaceable_count")
            room = comp.get("room_strength", "")
            notable = comp.get("notable", []) or []

            head = f"**🪑 Veteran Competition:** {vet_n} ahead"
            if repl is not None:
                head += f" · {repl} replaceable (D/F)"
            st.markdown(head)

            if notable:
                pills = " ".join(
                    f"{c.get('name', '?')} {grade_pill(c.get('grade', '—'))}" for c in notable
                )
                st.markdown(f"Real competition: {pills}", unsafe_allow_html=True)
            else:
                st.caption("No grade-C-or-better veteran ahead — soft room.")

            if room:
                st.caption(room)
            if comp.get("summary"):
                st.caption(comp["summary"])

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
