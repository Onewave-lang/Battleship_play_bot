import pytest

from game_board15.parser import CYRILLIC_ALIASES, LATIN, parse_coord


@pytest.mark.parametrize("cyr, latin", CYRILLIC_ALIASES.items())
def test_cyrillic_aliases(cyr, latin):
    if latin in LATIN:
        col = LATIN.index(latin)
        expected = (0, col)
    else:
        expected = None
    assert parse_coord(f"{cyr}1") == expected
    assert parse_coord(f"{cyr.upper()}1") == expected


@pytest.mark.parametrize("letter", list(LATIN))
def test_latin_case_insensitive(letter):
    col = LATIN.index(letter)
    assert parse_coord(f"{letter}1") == (0, col)
    assert parse_coord(f"{letter.upper()}1") == (0, col)


@pytest.mark.parametrize("letter", ["p", "q", "v", "ж", "щ", "ы", "в"])
def test_unsupported_letters(letter):
    assert parse_coord(f"{letter}1") is None
    assert parse_coord(f"{letter.upper()}1") is None
