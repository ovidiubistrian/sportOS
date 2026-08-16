"""Matching a club to the results feed.

The question these answer is not "does it work" but "what does it refuse to
do". A wrong link puts another club's fixtures on this club's website, and
nobody finds out until a match day that never happens — so the interesting
cases are all the ones where nothing should be connected.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.integrations.api_football.autolink import fold, season_year
from app.integrations.models import FEED_MODES

pytestmark = pytest.mark.integrations


class TestFoldingANameToWhatTwoCataloguesAgreeOn:
    @pytest.mark.parametrize(
        ("ours", "theirs"),
        [
            # The provider writes ASCII. A Romanian club does not.
            ("CSM Reșița", "CSM Resita"),
            ("Universitatea Craiova", "Universitatea Craiova"),
            ("FC Argeș Pitești", "Arges Pitesti"),
            ("Sepsi OSK Sfântu Gheorghe", "Sepsi OSK Sfantu Gheorghe"),
            # Legal boilerplate on one side and not the other.
            ("AFC Example", "Example FC"),
            ("CS Mioveni", "Mioveni"),
            ("Asociația Fotbal Club Hermannstadt", "Hermannstadt"),
            # Punctuation and spacing are not evidence of anything.
            ("F.C. Voluntari", "FC Voluntari"),
            ("  Rapid   București ", "Rapid Bucuresti"),
        ],
    )
    def test_the_same_club_written_two_ways_agrees(self, ours: str, theirs: str) -> None:
        assert fold(ours) == fold(theirs)

    @pytest.mark.parametrize(
        ("one", "other"),
        [
            # Two real, different clubs. Neither may ever be taken for the
            # other: this is the failure that costs a club its fixture list.
            ("CSM Reșița", "CSM Slatina"),
            ("Dinamo București", "Dinamo Bacău"),
            ("Universitatea Craiova", "Universitatea Cluj"),
            ("FC Botoșani", "FC Buzău"),
        ],
    )
    def test_two_different_clubs_stay_different(self, one: str, other: str) -> None:
        assert fold(one) != fold(other)

    def test_a_name_of_nothing_but_boilerplate_folds_to_nothing(self) -> None:
        """And `try_link` refuses on an empty fold rather than matching everything."""
        assert fold("FC Club Sportiv") == ""

    def test_folding_is_stable(self) -> None:
        assert fold(fold("CSM Reșița")) == fold("CSM Reșița")


def test_the_mode_the_linker_writes_is_one_the_database_allows() -> None:
    """`mode` is a CHECK constraint, and a wrong value fails at the flush.

    It was `AUTO` for a while, which is not one of them: the API rejected it as
    invalid input, and had it got past that the insert would have failed inside
    a request that was otherwise succeeding. Reading the constant is worth more
    than remembering the string.
    """
    source = (
        pathlib.Path(__file__).resolve().parents[2]
        / "app/integrations/api_football/autolink.py"
    ).read_text()
    written = re.findall(r'feed\.mode = "([A-Z_]+)"', source)
    assert written, "the linker no longer sets a mode — has it moved?"
    assert set(written) <= set(FEED_MODES), f"{written} is not among {FEED_MODES}"


class TestReadingTheSeasonYear:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [("2025/26", 2025), ("2025-2026", 2025), ("2025", 2025), (" 2024/25", 2024)],
    )
    def test_the_provider_numbers_a_season_by_the_year_it_starts(
        self, name: str, expected: int
    ) -> None:
        assert season_year(name) == expected

    @pytest.mark.parametrize("name", ["", "Sezonul curent", "26/27x", None])
    def test_anything_it_cannot_read_is_refused_rather_than_guessed(self, name: str) -> None:
        assert season_year(name) is None
