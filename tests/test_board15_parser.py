import pytest

from game_board15.parser import CYRILLIC_ALIASES, LATIN, parse_coord


@pytest.mark.parametrize("cyr, latin", CYRILLIC_ALIASES.items())
def test_cyrillic_aliases(cyr, latin):
    col = LATIN.index(latin)
    assert parse_coord(f"{cyr}1") == (0, col)
    assert parse_coord(f"{cyr.upper()}1") == (0, col)


@pytest.mark.parametrize("letter", list(LATIN))
def test_latin_case_insensitive(letter):
    col = LATIN.index(letter)
    assert parse_coord(f"{letter}1") == (0, col)
    assert parse_coord(f"{letter.upper()}1") == (0, col)


@pytest.mark.parametrize("letter", ["p", "q", "ж", "щ", "ы"])
def test_unsupported_letters(letter):
    assert parse_coord(f"{letter}1") is None
    assert parse_coord(f"{letter.upper()}1") is None
