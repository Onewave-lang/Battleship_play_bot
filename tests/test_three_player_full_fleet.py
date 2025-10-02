from logic import placement


def test_three_player_full_fleet():
    global_mask = [[0] * 15 for _ in range(15)]

    boards = [placement.random_board_global(global_mask) for _ in range(3)]

    for board in boards:
        total = sum(cell == 1 for row in board.grid for cell in row)
        assert total == 20
