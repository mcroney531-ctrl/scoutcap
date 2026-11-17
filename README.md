# [Project Name TBD] — Rookie Draft Scouting Agent

> A personal multi-agent system for evaluating incoming fantasy football rookies ahead of an August dynasty rookie draft.

---

## Problem

Dynasty fantasy football rookie drafts require evaluating incoming rookie prospects across multiple, often conflicting signals — college production, landing spot/opportunity, injury history, and outside expert opinion — and then weighing all of that against a specific league's scoring settings and a specific roster's actual needs. Doing this manually means juggling several disconnected sources and mentally synthesizing them under time pressure during a live draft.

This project builds a personal agent system to do that synthesis automatically, on demand, for a specific dynasty league's rookie draft in August.

## Why Agents

This isn't a single lookup-and-respond problem — it requires evaluating a prospect from genuinely different angles before combining them into one recommendation:

- **Talent**, independent of where a player lands
- **Opportunity**, independent of how talented they are
- **Roster fit**, which depends on context no general model would have (this specific league's settings and this specific roster)

A single LLM call with a big prompt could attempt this, but separating these into distinct reasoning agents keeps each evaluation focused, makes the system's reasoning inspectable (you can see *why* a recommendation landed where it did), and mirrors how human scouts actually separate these judgments in practice.

## Architecture

**League format:** currently 4 rounds, 12 picks per round (48 total picks). Recommendations are output as exact draft slots using round.pick notation (e.g. "4.04" = round 4, pick 4).

**League configuration lives in `config/league.py`**, the one source for both values below. The Mock Draft board, pick labels, slot pickers, completion check and the Synthesis prompt all read it; nothing else re-encodes them.

- `LEAGUE` holds the geometry: `rounds` (4), `picks_per_round` (12) and `total_picks` (48). An import-time check enforces `total_picks == rounds * picks_per_round`. Loading your picks from Sleeper refuses, with a visible message, a league whose roster count or traded-pick rounds disagree with it. The Mock Draft order is snake: forward in odd rounds, reverse in even rounds.
- `DRAFT_CLASS_YEAR` (2026) is the rookie class Scout evaluates. It drives ESPN draft-prospect lookups, Sleeper pick loading, the sentiment note, the MCP prospect search and the UI labels. **DRAFT_CLASS_YEAR is intentionally manual. Do not advance it from the calendar alone.** Sleeper's rookie board (`years_exp == 0`) keeps showing the current class well into the following season, so roll the year forward deliberately, once the next class is actually on the board. The "most recent completed college season" used for college stats is a separate clock and stays calendar-based.

**[Insert architecture diagram here]**

### Agents

| Agent | Role | Inputs |
|---|---|---|
| **Situation Agent** | Evaluates opportunity — depth chart competition, scheme fit, draft capital | ESPN Core API — `seasons/{year}/draft` (draft capital/round), team depth chart data; Sleeper `/v1/players/nfl` — `depth_chart_position` (current, live positioning by August, post-NFL-draft) |
| **Production Agent** | Evaluates talent — college stats, athletic profile, injury history (folded in as a Risk Modifier: 1-5 durability score + chance-of-injury %, computed internally from ESPN/Sleeper data) | ESPN Core API — `athletes`/`stats`/`leaders` scoped to `college-football` league; `athletes/{id}/injuries` for historical injury record; Sleeper `/v1/players/nfl` — `status`/`injury_start_date`/`practice_participation` for current/live injury status; optionally ESPN `seasons/{year}/recruits` for recruiting pedigree as a bonus signal |
| **Synthesis Agent** | Combines Situation + Production outputs with hardcoded league settings, live roster need (pulled from Sleeper), and crowd-sentiment signal (Sleeper trending add/drop data) to produce the final recommendation as an exact draft slot (round.pick — e.g. "4.04"). Final step: compares its own conclusion against KeepTradeCut's crowdsourced market consensus value as a sanity check — surfacing agreement, or explaining specifically why it diverges, rather than treating market consensus as an input to the recommendation itself | Situation Agent output, Production Agent output, league config, Sleeper roster API, Sleeper `/v1/players/nfl/trending/add`, KeepTradeCut dynasty rookie rankings (comparison only — not blended into the composite score) |

Situation and Production are called by Synthesis as **Agent Tools** (not full handoffs) — Synthesis stays in control of the conversation and uses their outputs as inputs to its own reasoning, the same pattern as the currency-converter example from the course.

### Tools / MCP Server

- Sleeper API integration — rookie draft board data (seed list), league settings, current roster, general player data (`depth_chart_position`, live injury/practice status), and trending add/drop data (crowd-sentiment signal)
- ESPN Public API (unofficial, free, no auth required) — draft capital, college production stats, historical injury record, recruiting data. Source: [pseudo-r/Public-ESPN-API](https://github.com/pseudo-r/Public-ESPN-API)
- KeepTradeCut dynasty rookie rankings — crowdsourced consensus value, used as a post-hoc comparison anchor for Synthesis's own conclusion, not as an input to the recommendation itself. API/scraping approach still TBD — need to check for a documented public endpoint before assuming the rendered page needs to be fetched directly.
- Curated journalist/expert-opinion tool — scoped to a small set of known, reliably free sources rather than open web search, used by Synthesis as a qualitative sanity-check signal alongside the quantitative trending signal
- *[Additional tools TBD as needed]*

### Interface

- Pulls the rookie draft board from Sleeper as the master prospect list
- User adds prospects to a personal shortlist board (cosmetic/personal — does **not** feed roster-need logic, since board composition reflects draft class depth, not actual need)
- Clicking a player opens a chat thread: first message is a collapsible structured analysis card (output of the 3-agent pipeline), with normal conversational follow-up beneath it in the same thread
- Roster need is calculated from the user's **actual current roster** via Sleeper, not from the shortlist board

### Deployment

- [ ] Deployed live at: *[URL TBD]*
- Built with: *[stack TBD — ADK / MCP server / frontend framework]*

## MCP Server

The scouting capabilities are also exposed over the **Model Context Protocol** via
`mcp_server.py` (built on the official `mcp` Python SDK / FastMCP, stdio transport).
This lets any MCP client — Claude Desktop, etc. — use the same data layer and pipeline
that the ADK agents use. Two layers are exposed:

**Granular data tools**

| Tool | Returns |
|---|---|
| `search_prospects(name)` | Draft prospects for the configured class (`DRAFT_CLASS_YEAR`, ESPN) — draft capital, scout grade, ranks |
| `player_opportunity(name)` | Sleeper depth chart, team, status |
| `draft_capital(name)` | ESPN draft round/pick, scout grade, ranks |
| `veteran_competition(team, position)` | FantasyCalc-graded quality of the veterans ahead (soft room vs. entrenched starter) |
| `dynasty_value(name)` | FantasyCalc dynasty + redraft value and positional grade (12-team SF PPR) |
| `college_production(name)` | Career college stats (ESPN) |
| `injury_history(name)` | Historical injury record (ESPN) |
| `trending_adds(limit)` | Sleeper trending-add crowd-interest signal |

**High-level pipeline tool**

| Tool | Returns |
|---|---|
| `scout_rookie(name)` | Runs the full 3-agent pipeline → structured draft recommendation (grades, risk, competition, composite, recommended/floor/ceiling pick) |

**Run it:**

```bash
uv run --locked python mcp_server.py        # stdio, in the locked project environment
```

**Claude Desktop** (`claude_desktop_config.json`; replace the directory with your scoutcap checkout):

```json
{
  "mcpServers": {
    "rookie-scout": {
      "command": "uv",
      "args": ["run", "--locked", "--directory", "C:\\path\\to\\scoutcap", "python", "mcp_server.py"]
    }
  }
}
```

`scout_rookie` requires `ANTHROPIC_API_KEY` in `.env` (the data tools do not).

## Setup

Scout is a [uv](https://docs.astral.sh/uv/) project on **Python 3.14**, matching the deployed app.

| File | Role |
|---|---|
| `pyproject.toml` | The direct dependency contract, owned by people: seven exact `==` pins plus `dynasty-core`, sourced from its canonical Git repository at one immutable commit. `requires-python = ">=3.14,<3.15"`. |
| `uv.lock` | The complete, exact resolution for every platform. It is generated by uv and committed; never edit it by hand. |
| `.python-version` | `3.14`, so uv picks the right interpreter, installing it if needed. |

There is no `requirements.txt`. One dependency system means there's nothing to drift against the lock.

**Local setup** (any OS; install uv first):

```bash
uv sync --locked                          # create/refresh .venv exactly from uv.lock; never upgrades
uv run --locked streamlit run app.py      # run the app inside that environment
```

`--locked` makes uv fail instead of quietly rewriting `uv.lock` when it is out of date with `pyproject.toml`.

On Windows, `. .\activate.ps1` from the repo root does the same sync, then activates `.venv`. The devcontainer installs a pinned uv CLI and runs the same `uv sync --locked`.

**Changing a dependency** must be deliberate:

1. Change the pin in `pyproject.toml`, for example with `uv add "streamlit==<new version>"`, or edit it and run `uv lock`. To move `dynasty-core`, change its `rev` to the new full 40-character commit.
2. Review the `uv.lock` diff that results.
3. Run the full regression:
   ```bash
   uv lock --check
   uv sync --locked
   uv run --locked python scripts/check_dependency_versions.py
   uv run --locked python -m unittest discover -s tests -t .
   ```
4. Commit `pyproject.toml` and `uv.lock` together.

`scripts/check_dependency_versions.py` enforces the contract: the allowed dependency forms, a lock that uses only PyPI plus the pinned `dynasty-core` commit, and an installed environment that matches, including `dynasty-core`'s PEP 610 commit.

**Streamlit Community Cloud** deploys `main` with `app.py` as the entrypoint. It finds `uv.lock` at the repo root, which takes priority over every other dependency file, and installs from it with uv. The **Python version is not set by any repo file**: it is chosen in the app's Community Cloud settings (currently 3.14). Changing it means deleting and redeploying the app, so keep `requires-python` matched to that setting.

## Key Concepts Demonstrated

- [x] Agent / Multi-agent system (ADK) — three-agent architecture above
- [x] MCP Server — `mcp_server.py` exposes 8 granular data tools + the high-level `scout_rookie` pipeline tool over stdio (FastMCP)
- [x] Deployability — live deployment
- [ ] Agent Skills — curated-source tool as on-demand dynamic context, framed per Day 1's static/dynamic context principle (optional 4th)
- [ ] Security features — not yet decided whether this tool takes real actions (e.g. submitting a draft pick) that would warrant human-in-the-loop confirmation, or stays read-only advice
- [ ] Antigravity — possible use for UI scaffolding (optional 5th)

## Project Journey / Decisions Log

*[Capture the "why" behind each major decision as it's made — this section is what makes the eventual retrospective/writeup easy instead of reconstructed from memory]*

- Decided against having "add to board" feed roster-need logic — board composition reflects draft class depth (e.g. a deep WR class), not actual roster need. Roster need pulled from real Sleeper roster data instead.
- Decided against a dedicated "Risk Agent" for injury history — folded into Production Agent instead, since injury data is already embedded in the same player records being pulled for talent evaluation; no separate retrieval step to justify a separate agent.
- Decided against open web search for journalist opinion — paywalls and inconsistent content make it unreliable for a live demo. Scoped to a small curated set of known free sources instead.
- Decided to hardcode league settings rather than pull dynamically — this is a personal tool for one specific league, not a generalized product.
- Decided Analysis + Chat should be one continuous interface (collapsible card + thread) rather than two separate views — preserves conversational context for follow-ups and reduces build surface area.
- Resolved data source gap for Situation/Production agents via the unofficial ESPN Public API — covers draft capital, college stats, and a dedicated per-athlete injury history endpoint, all free and requiring no authentication.
- Added Sleeper's general `/v1/players/nfl` endpoint (separate from the league-specific data already in use) as a second source — `depth_chart_position` gives live opportunity signal post-NFL-draft, and live injury/practice status complements ESPN's historical injury record. Also added Sleeper's trending add/drop endpoint to Synthesis as a quantifiable crowd-sentiment signal, sitting alongside the curated journalist tool rather than replacing it.
- League format confirmed: 4 rounds, 12 picks per round (48 total). Recommendation output upgraded from round-level to exact round.pick notation (e.g. "4.04") to match.
- Resolved: pick number stays a single, always-precise estimate regardless of data depth — functions as a relative positioning signal (same way ADP gets used in practice), not a literal "draft here" instruction. By late June, even small-school prospects have real draft outcomes, write-ups, and spring practice reports, so thin-data cases are rare at this point in the calendar. Confidence/Conviction Level decoupled into a separate optional tag for the rare genuinely thin-data prospect, rather than something that widens the recommended pick into a range.
- Talent Grade and Opportunity Grade scale decided as a hybrid: numeric (0-100) generated internally with calibration anchors built into the prompt (to prevent LLM score clustering around the 80s), converted to a letter grade (A-F, +/-) for the user-facing report. Gives the Composite Logic enough granularity to differentiate across 48 picks while keeping the actual output readable as a scouting report.
- Evaluated Draft Sharks' Injury Predictor as a potential injury data source — found their per-player pages are free and not paywalled (unlike their other tools), but discovered a soft usage cap that resets in incognito (suggesting client-side cookie tracking). Decided against fetching from them directly: an agent evaluating a full draft class would hit that limit fast, and building around it would mean deliberately circumventing a monetization mechanism rather than just using free public content. Kept their output *shape* as inspiration (a 1-5 durability score + chance-of-injury %) for the Risk Modifier, but the actual computation is sourced from ESPN/Sleeper data instead — sources with no such cap.
- Resolved Crowd Sentiment Signal as relative ranking within the current draft class rather than an absolute presence/absence threshold. Sleeper's trending endpoint is inherently top-N (not exhaustive — a player absent from results just didn't generate enough platform-wide activity to rank, there's no "everyone's count, even zero" dataset behind it). Overall activity is also seasonal — a typical offseason lull means uniformly low volume across the board, so absence reflects timing as much as disinterest. Standing out during a quiet period is a stronger signal than standing out during a high-volume spike (e.g. right after the NFL draft). Synthesis should note when overall platform activity is low league-wide so sentiment reads as directional color, not a decisive factor.
- Considered KeepTradeCut's crowdsourced dynasty value rankings as a data source, but decided against feeding it into the Composite Logic directly — doing so would risk making the agent system redundant with crowd consensus that's already been computed (undercutting the actual point of building independent agentic reasoning). Instead, KTC is used as a comparison anchor: Synthesis reaches its own conclusion first from the locked-in sources, then checks it against KTC's market value and explicitly surfaces agreement or the specific reasoning behind any divergence. Open question: whether KTC has a documented public API or requires fetching/parsing the rendered page directly — needs the same diligence applied to ESPN's endpoint structure before building against it.
- Composite Logic base weighting locked: Talent 43% / Opportunity 38% / Risk 15% / Sentiment 4%. Market Consensus deliberately excluded from the weighting entirely (kept as comparison-only, per the decision above) — initial draft had it at a small 6% input, removed and redistributed proportionally into Talent and Opportunity (the two dominant levers), leaving Risk and Sentiment untouched at their deliberately small modifier weights. Decided to keep this weighting uniform across all positions rather than flexing per position — simpler design, no per-position complexity to maintain.
- Architecture decisions complete for now. Moving into Claude Code for actual implementation.
- Added a veteran-competition quality signal (FantasyCalc dynasty/redraft values) to the Situation Agent — grading the players *ahead* of a rookie rather than just counting them, so a soft depth chart (replaceable D/F vets) reads as a plus instead of a penalty. Used redraft value for the near-term competition grade so an aging-but-productive vet (e.g. McLaurin) still counts as real competition despite low dynasty value.
- Improved the grade math: actually applied the (previously dead) positional-value multiplier for the superflex QB premium, and replaced the linear score→pick mapping with a logistic curve that compresses the elite tier into round 1 and flattens the late rounds.
- Built the MCP server (`mcp_server.py`, FastMCP/stdio) exposing both the granular data tools and a high-level `scout_rookie` pipeline tool — reusing the existing `tools/` and agent layer rather than duplicating logic, so the data layer is consumable by any MCP client.

