import sys
import importlib
import pytest


def test_killed_ship_last_move_renders_bomb():
    sys.modules.pop("PIL", None)
    sys.modules.pop("game_board15.renderer", None)
    from PIL import Image
    renderer = importlib.import_module("game_board15.renderer")
    from game_board15.state import Board15State

    board = [[0] * 15 for _ in range(15)]
    owners = [[None] * 15 for _ in range(15)]
    board[0][0] = 4
    owners[0][0] = "A"
    state = Board15State(board=board, owners=owners, highlight=[(0, 0)])
    buf = renderer.render_board(state, player_key="B")

    img = Image.open(buf)
    x = renderer.TILE_PX + 5
    y = renderer.TILE_PX + 5
    expected = renderer.PLAYER_SHIP_COLORS_LIGHT.get(renderer.THEME, {}).get("A")
    assert img.getpixel((x, y)) == expected
    cx = renderer.TILE_PX + renderer.TILE_PX // 2
    cy = renderer.TILE_PX + renderer.TILE_PX // 2
    assert img.getpixel((cx, cy))[:3] == (0, 0, 0)


def test_killed_ship_past_move_renders_dark_square():
    sys.modules.pop("PIL", None)
    sys.modules.pop("game_board15.renderer", None)
    from PIL import Image
    renderer = importlib.import_module("game_board15.renderer")
    from game_board15.state import Board15State

    board = [[0] * 15 for _ in range(15)]
    owners = [[None] * 15 for _ in range(15)]
    board[0][0] = 4
    owners[0][0] = "A"
    state = Board15State(board=board, owners=owners)
    buf = renderer.render_board(state, player_key="B")

    img = Image.open(buf)
    x = renderer.TILE_PX + 5
    y = renderer.TILE_PX + 5
    expected = renderer.PLAYER_SHIP_COLORS_DARK.get(renderer.THEME, {}).get("A")
    assert img.getpixel((x, y)) == expected
    cx = renderer.TILE_PX + renderer.TILE_PX // 2
    cy = renderer.TILE_PX + renderer.TILE_PX // 2
    assert img.getpixel((cx, cy)) == expected


def test_miss_renders_dot():
    sys.modules.pop("PIL", None)
    sys.modules.pop("game_board15.renderer", None)
    from PIL import Image
    renderer = importlib.import_module("game_board15.renderer")
    from game_board15.state import Board15State

    board = [[0] * 15 for _ in range(15)]
    board[0][0] = 2
    state = Board15State(board=board)
    buf = renderer.render_board(state)

    img = Image.open(buf)
    x0 = renderer.TILE_PX
    y0 = renderer.TILE_PX
    cx = x0 + renderer.TILE_PX // 2
    cy = y0 + renderer.TILE_PX // 2
    assert img.getpixel((cx, cy)) == renderer.COLORS[renderer.THEME]["miss"]
    sample = (cx + 6, cy)
    assert img.getpixel(sample) == renderer.COLORS[renderer.THEME]["bg"]


def test_hit_orange_player_renders_dark_orange():
    sys.modules.pop("PIL", None)
    sys.modules.pop("game_board15.renderer", None)
    from PIL import Image
    renderer = importlib.import_module("game_board15.renderer")
    from game_board15.state import Board15State

    board = [[0] * 15 for _ in range(15)]
    owners = [[None] * 15 for _ in range(15)]
    board[0][0] = 3
    owners[0][0] = "C"
    state = Board15State(board=board, owners=owners)
    buf = renderer.render_board(state)

    img = Image.open(buf)
    x = renderer.TILE_PX + 5
    y = renderer.TILE_PX + 5
    expected = renderer.PLAYER_SHIP_COLORS_DARK.get(renderer.THEME, {}).get("C")
    assert img.getpixel((x, y)) == expected


@pytest.mark.parametrize("owner", ["A", "B"])
def test_hit_player_renders_dark_color(owner):
    sys.modules.pop("PIL", None)
    sys.modules.pop("game_board15.renderer", None)
    from PIL import Image
    renderer = importlib.import_module("game_board15.renderer")
    from game_board15.state import Board15State

    board = [[0] * 15 for _ in range(15)]
    owners = [[None] * 15 for _ in range(15)]
    board[0][0] = 3
    owners[0][0] = owner
    state = Board15State(board=board, owners=owners)
    buf = renderer.render_board(state)

    img = Image.open(buf)
    x = renderer.TILE_PX + 5
    y = renderer.TILE_PX + 5
    expected = renderer.PLAYER_SHIP_COLORS_DARK.get(renderer.THEME, {}).get(owner)
    assert img.getpixel((x, y)) == expected


def test_footer_label_draws_overlay():
    sys.modules.pop("PIL", None)
    sys.modules.pop("game_board15.renderer", None)
    from PIL import Image, ImageChops
    renderer = importlib.import_module("game_board15.renderer")
    from game_board15.state import Board15State

    img_plain = Image.open(renderer.render_board(Board15State())).convert("RGBA")
    img_labeled = Image.open(
        renderer.render_board(
            Board15State(
                footer_label="match=abcd player=A ships=20 sh_disp=19 snap=N hist=15"
            )
        )
    ).convert("RGBA")

    diff = ImageChops.difference(img_plain, img_labeled)
    extrema = diff.getextrema()
    assert any(channel_max > 0 for _, channel_max in extrema[:3])

