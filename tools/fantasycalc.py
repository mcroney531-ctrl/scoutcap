"""Scout FantasyCalc tool — re-exports from dynasty_core.fantasycalc.

Stage 1 of the Dynasty Umbrella: FantasyCalc logic consolidated in dynasty_core/.
All external agent APIs preserved; no agent changes needed.
"""
from dynasty_core.fantasycalc import (  # noqa: F401
    GRADE_TIERS,
    get_dynasty_values,
    get_player_value,
    get_value_for_sleeper_id,
    index_by_sleeper_id,
    index_by_sleeper_id_with_redraft_rank,
    value_grade,
)
