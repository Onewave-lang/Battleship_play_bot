def _new_grid(size=10):
    return [[[0, None] for _ in range(size)] for _ in range(size)]


def _state(cell):
    return cell[0] if isinstance(cell, (list, tuple)) else cell
