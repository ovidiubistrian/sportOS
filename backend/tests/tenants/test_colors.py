"""Colour maths.

The point of these is that a club's own brand colour must never make its own
site unreadable — whatever colour it picks. Pure functions, no I/O.
"""

from __future__ import annotations

import pytest

from app.tenants.colors import (
    AA_NON_TEXT,
    AA_NORMAL_TEXT,
    BLACK,
    LIGHT_SURFACE,
    WHITE,
    InvalidColor,
    adjust_for_contrast,
    assess,
    build_palette,
    contrast_ratio,
    normalise,
    readable_on,
    relative_luminance,
)

pytestmark = pytest.mark.branding

# Deliberately awkward: a very light yellow, a mid red, a near-black navy.
YELLOW = "#FFE600"
RED = "#C8102E"
NAVY = "#0A1A33"


class TestNormalise:
    @pytest.mark.parametrize(
        ("given", "expected"),
        [("#abc", "#AABBCC"), ("#AABBCC", "#AABBCC"), (" #1f4b99 ", "#1F4B99")],
    )
    def test_accepts_shorthand_and_case(self, given: str, expected: str) -> None:
        assert normalise(given) == expected

    @pytest.mark.parametrize("given", ["1F4B99", "#12345", "#GGGGGG", "", "red", None])
    def test_rejects_anything_else(self, given: object) -> None:
        with pytest.raises((InvalidColor, TypeError)):
            normalise(given)  # type: ignore[arg-type]


class TestContrast:
    def test_known_reference_values(self) -> None:
        # The two anchors of the WCAG scale.
        assert contrast_ratio(WHITE, BLACK) == pytest.approx(21.0, abs=0.01)
        assert contrast_ratio(WHITE, WHITE) == pytest.approx(1.0, abs=0.01)

    def test_is_symmetric(self) -> None:
        assert contrast_ratio(NAVY, WHITE) == pytest.approx(contrast_ratio(WHITE, NAVY))

    def test_luminance_is_ordered(self) -> None:
        assert relative_luminance(BLACK) < relative_luminance(RED) < relative_luminance(WHITE)

    def test_readable_on_picks_the_better_side(self) -> None:
        assert readable_on(YELLOW) == BLACK
        assert readable_on(NAVY) == WHITE


class TestAdjustment:
    def test_a_colour_that_already_passes_is_untouched(self) -> None:
        assert adjust_for_contrast(NAVY, WHITE) == normalise(NAVY)

    def test_a_too_light_colour_is_darkened_until_readable(self) -> None:
        adjusted = adjust_for_contrast(YELLOW, WHITE)
        assert adjusted != normalise(YELLOW)
        assert contrast_ratio(adjusted, WHITE) >= AA_NORMAL_TEXT

    def test_adjustment_preserves_the_hue(self) -> None:
        """The result must still read as the club's colour, not a different one."""
        import colorsys

        from app.tenants.colors import to_rgb

        original = colorsys.rgb_to_hls(*(c / 255 for c in to_rgb(YELLOW)))
        darkened = adjust_for_contrast(YELLOW, WHITE)
        adjusted = colorsys.rgb_to_hls(*(c / 255 for c in to_rgb(darkened)))
        assert adjusted[0] == pytest.approx(original[0], abs=0.02)

    def test_lightens_against_a_dark_surface(self) -> None:
        adjusted = adjust_for_contrast(NAVY, "#0C0F14")
        assert contrast_ratio(adjusted, "#0C0F14") > contrast_ratio(NAVY, "#0C0F14")

    @pytest.mark.parametrize("color", [YELLOW, RED, NAVY, "#FFFFFF", "#000000", "#808080"])
    def test_always_reaches_aa_on_white(self, color: str) -> None:
        """Whatever the club picks, body text derived from it is readable."""
        adjusted = adjust_for_contrast(color, LIGHT_SURFACE)
        assert contrast_ratio(adjusted, WHITE) >= AA_NORMAL_TEXT


class TestAssessment:
    def test_a_light_brand_reports_the_problem_and_a_fix(self) -> None:
        result = assess(YELLOW)
        assert result.color == YELLOW
        assert result.meets_aa_as_text is False  # unreadable as text on white
        assert result.on_color == BLACK  # but fine as a button fill with black text
        assert result.was_adjusted is True
        assert contrast_ratio(result.text_on_light, WHITE) >= AA_NORMAL_TEXT

    def test_a_dark_brand_needs_no_adjustment(self) -> None:
        result = assess(NAVY)
        assert result.meets_aa_as_text is True
        assert result.was_adjusted is False
        assert result.on_color == WHITE

    @pytest.mark.parametrize("color", [YELLOW, RED, NAVY, "#00FF00", "#FF00FF"])
    def test_button_text_is_always_readable(self, color: str) -> None:
        """The rule that makes the BOLD template safe for any brand colour."""
        result = assess(color)
        assert contrast_ratio(result.color, result.on_color) >= AA_NON_TEXT


class TestPalette:
    def test_produces_the_expected_tokens(self) -> None:
        palette = build_palette(NAVY, YELLOW, RED)
        assert palette["--brand"] == normalise(NAVY)
        for token in (
            "--brand-contrast",
            "--brand-text",
            "--brand-text-dark",
            "--brand-hover",
            "--brand-secondary",
            "--brand-accent",
        ):
            assert token in palette, f"{token} missing from the palette"

    def test_optional_colours_are_omitted_not_defaulted(self) -> None:
        palette = build_palette(NAVY, None, None)
        assert "--brand-secondary" not in palette
        assert "--brand-accent" not in palette

    def test_every_token_is_a_valid_hex(self) -> None:
        palette = build_palette(YELLOW, RED, NAVY)
        for token, value in palette.items():
            assert normalise(value) == value, f"{token} is not normalised: {value}"

    def test_the_palette_is_a_closed_set(self) -> None:
        """A club supplies three colours and gets a fixed set of tokens.

        No mechanism exists for a club to add an arbitrary CSS property — that
        constraint is what keeps every tenant's UI the same product.
        """
        palette = build_palette(NAVY, YELLOW, RED)
        assert set(palette) == {
            "--brand",
            "--brand-contrast",
            "--brand-text",
            "--brand-text-dark",
            "--brand-hover",
            "--brand-secondary",
            "--brand-secondary-contrast",
            "--brand-accent",
            "--brand-accent-contrast",
            "--brand-accent-text",
        }
