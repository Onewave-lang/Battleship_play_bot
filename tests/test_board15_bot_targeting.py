import random

from game_board15.battle import HIT, KILL, ShotResult
from game_board15.handlers import _choose_bot_target, _update_bot_target_state
from game_board15.models import Match15, Ship


def test_bot_target_single_hit_prefers_adjacent() -> None:
    match = Match15(match_id="single")
    field = match.field
    entry = match.shots["B"]
    entry["target_hits"] = [(4, 4)]
    entry["target_owner"] = "A"

    field.set_state((4, 4), 3, "A")
    field.set_state((3, 4), 2, None)
    field.set_state((5, 4), 2, None)
    field.set_state((4, 3), 2, None)

    rng = random.Random(0)
    coord = _choose_bot_target(field, "B", entry, rng)

    assert coord == (4, 5)


def test_bot_target_multiple_hits_extends_line() -> None:
    match = Match15(match_id="line")
    field = match.field
    entry = match.shots["B"]
    entry["target_hits"] = [(5, 5), (5, 6)]
    entry["target_owner"] = "A"

    field.set_state((5, 5), 3, "A")
    field.set_state((5, 6), 3, "A")
    field.set_state((5, 4), 2, None)
    field.set_state((4, 5), 2, None)
    field.set_state((6, 5), 2, None)
    field.set_state((4, 6), 2, None)
    field.set_state((6, 6), 2, None)

    rng = random.Random(1)
    coord = _choose_bot_target(field, "B", entry, rng)

    assert coord == (5, 7)


def test_update_bot_target_state_tracks_hits_and_resets_on_kill() -> None:
    match = Match15(match_id="update")
    entry = match.shots["B"]

    first_hit = ShotResult(result=HIT, owner="A", coord=(2, 2))
    _update_bot_target_state(match, "B", first_hit)
    assert entry["target_hits"] == [(2, 2)]
    assert entry["target_owner"] == "A"

    second_hit = ShotResult(result=HIT, owner="A", coord=(2, 3))
    _update_bot_target_state(match, "B", second_hit)
    assert entry["target_hits"] == [(2, 2), (2, 3)]

    ship = Ship(cells=[(2, 2), (2, 3)], owner="A", alive=False)
    kill = ShotResult(result=KILL, owner="A", coord=(2, 3), killed_ship=ship)
    _update_bot_target_state(match, "B", kill)

    assert entry["target_hits"] == []
    assert entry["target_owner"] is None


def test_bot_target_clears_stale_hits_when_ship_destroyed_elsewhere() -> None:
    match = Match15(match_id="stale")
    field = match.field
    entry = match.shots["B"]
    entry["target_hits"] = [(3, 3)]
    entry["target_owner"] = "A"

    field.set_state((3, 3), 4, "A")

    rng = random.Random(2)
    coord = _choose_bot_target(field, "B", entry, rng)

    assert entry["target_hits"] == []
    assert entry["target_owner"] is None
    assert coord is not None
