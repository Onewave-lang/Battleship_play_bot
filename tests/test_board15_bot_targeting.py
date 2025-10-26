import random

from game_board15.battle import HIT, KILL, ShotResult
from game_board15.bot_targeting import _is_available_target
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
    field = match.field
    entry = match.shots["B"]

    field.owners[2][2] = "A"
    field.owners[2][3] = "A"
    field.grid[2][2] = 1
    field.grid[2][3] = 1

    first_hit = ShotResult(result=HIT, owner="A", coord=(2, 2))
    field.set_state((2, 2), 3, "A")
    _update_bot_target_state(match, "B", first_hit)
    assert entry["target_hits"] == [(2, 2)]
    assert entry["target_owner"] == "A"

    second_hit = ShotResult(result=HIT, owner="A", coord=(2, 3))
    field.set_state((2, 3), 3, "A")
    _update_bot_target_state(match, "B", second_hit)
    assert entry["target_hits"] == [(2, 2), (2, 3)]

    ship = Ship(cells=[(2, 2), (2, 3)], owner="A", alive=False)
    match.field.ships["A"] = [ship]
    field.set_state((2, 2), 4, "A")
    field.set_state((2, 3), 4, "A")
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


def test_bot_target_retains_line_after_other_player_hit() -> None:
    match = Match15(match_id="assist")
    field = match.field
    entry_bot = match.shots["B"]
    entry_bot["target_hits"] = [(5, 5)]
    entry_bot["target_owner"] = "A"

    ship = Ship(cells=[(5, 5), (5, 6), (5, 7)], owner="A", alive=True)
    match.field.ships["A"] = [ship]
    for coord in ship.cells:
        field.owners[coord[0]][coord[1]] = "A"
        field.grid[coord[0]][coord[1]] = 1
    field.set_state((5, 5), 3, "A")
    field.set_state((5, 6), 3, "A")

    result = ShotResult(result=HIT, owner="A", coord=(5, 6))
    _update_bot_target_state(match, "C", result)

    assert entry_bot["target_hits"] == [(5, 5), (5, 6)]
    assert entry_bot["target_owner"] == "A"

    rng = random.Random(3)
    coord = _choose_bot_target(field, "B", entry_bot, rng)
    assert coord == (5, 7)


def test_bot_target_ignores_other_ship_hits() -> None:
    match = Match15(match_id="separate")
    field = match.field
    entry_bot = match.shots["B"]
    entry_bot["target_hits"] = [(1, 1)]
    entry_bot["target_owner"] = "A"

    ship_main = Ship(cells=[(1, 1), (1, 2)], owner="A", alive=True)
    ship_other = Ship(cells=[(3, 3)], owner="A", alive=True)
    match.field.ships["A"] = [ship_main, ship_other]
    for coord in ship_main.cells + ship_other.cells:
        field.owners[coord[0]][coord[1]] = "A"
        field.grid[coord[0]][coord[1]] = 1

    field.set_state((1, 1), 3, "A")
    field.set_state((3, 3), 3, "A")

    foreign_hit = ShotResult(result=HIT, owner="A", coord=(3, 3))
    _update_bot_target_state(match, "C", foreign_hit)

    assert entry_bot["target_hits"] == [(1, 1)]
    assert entry_bot["target_owner"] == "A"


def test_bot_target_clears_when_ship_killed_by_other_player() -> None:
    match = Match15(match_id="kill_assist")
    field = match.field
    entry_bot = match.shots["B"]
    entry_bot["target_hits"] = [(2, 2)]
    entry_bot["target_owner"] = "A"

    ship = Ship(cells=[(2, 2), (2, 3)], owner="A", alive=False)
    match.field.ships["A"] = [ship]
    for coord in ship.cells:
        field.owners[coord[0]][coord[1]] = "A"
        field.grid[coord[0]][coord[1]] = 4

    kill_result = ShotResult(result=KILL, owner="A", coord=(2, 3), killed_ship=ship)
    _update_bot_target_state(match, "C", kill_result)


def test_available_target_skips_diagonal_near_wounded() -> None:
    match = Match15(match_id="diag")
    field = match.field
    field.set_state((5, 5), 3, "A")

    assert not _is_available_target(field, "B", (4, 4))
    assert not _is_available_target(field, "B", (6, 6))
    assert _is_available_target(field, "B", (5, 6))
