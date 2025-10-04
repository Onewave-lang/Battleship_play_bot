import pytest
from logic.parser import parse_coord

@pytest.mark.parametrize(
    "text,expected",
    [
        ("а1", (0, 0)),
        ("A1", (0, 0)),
        ("к10", (9, 9)),
        ("k10", (9, 9)),
        ("v3", (2, 2)),
        ("g5", (4, 3)),
        ("d6", (5, 4)),
        ("e7", (6, 5)),
        ("j8", (7, 6)),
        ("z9", (8, 7)),
    ],
)
def test_parse_coord_valid(text, expected):
    assert parse_coord(text) == expected

@pytest.mark.parametrize("text", ["x1", "a0", "d11", "", "л1"])
def test_parse_coord_invalid(text):
    assert parse_coord(text) is None
