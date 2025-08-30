import sys
import importlib


def test_killed_ship_renders_bomb():
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
    expected = renderer.PLAYER_SHIP_COLORS_LIGHT.get(renderer.THEME, {}).get("A")
    assert img.getpixel((x, y)) == expected
    cx = renderer.TILE_PX + renderer.TILE_PX // 2
    cy = renderer.TILE_PX + renderer.TILE_PX // 2
    assert img.getpixel((cx, cy))[:3] == (0, 0, 0)


def test_miss_highlight_changes_color():
    sys.modules.pop("PIL", None)
    sys.modules.pop("game_board15.renderer", None)
    from PIL import Image
    renderer = importlib.import_module("game_board15.renderer")
    from game_board15.state import Board15State

    board = [[0] * 15 for _ in range(15)]
    board[0][0] = 2
    state = Board15State(board=board, highlight=[(0, 0)])

    buf = renderer.render_board(state)
    img = Image.open(buf)
    x = renderer.TILE_PX + 5
    y = renderer.TILE_PX + 5
    mark_color = renderer.COLORS[renderer.THEME]["mark"]
    assert img.getpixel((x, y)) == mark_color

    state.highlight = []
    buf = renderer.render_board(state)
    img = Image.open(buf)
    miss_color = renderer.COLORS[renderer.THEME]["miss"]
    assert img.getpixel((x, y)) == miss_color
