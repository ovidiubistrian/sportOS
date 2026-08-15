"""Colour maths for club branding.

A club picks its colours; the platform's job is to make sure the result is
still readable. Doc 14 sets the rule: the brand colour is used for the primary
action, active navigation, focus rings and links — and *never* for large fills,
table headers or status. A club with a yellow brand colour and one with a navy
brand colour must produce equally legible interfaces.

So we never reject a club's actual colour. We store it, and alongside it we
derive:

  * `on_<colour>`   — black or white, whichever is readable *on* the colour,
                      for text sitting on a filled button.
  * `<colour>_text` — the colour adjusted until it is readable *as* text on the
                      page background. Usually identical to the brand colour;
                      darker when the brand colour is too light.

Pure functions, no I/O — tested directly in tests/tenants/test_colors.py.
"""

from __future__ import annotations

import colorsys
import re
from dataclasses import dataclass

HEX_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# WCAG 2.2 minimums.
AA_NORMAL_TEXT = 4.5
AA_LARGE_TEXT = 3.0
AA_NON_TEXT = 3.0

WHITE = "#FFFFFF"
BLACK = "#000000"

# The surfaces brand colours are actually read against.
LIGHT_SURFACE = "#FFFFFF"
DARK_SURFACE = "#12171F"


class InvalidColor(ValueError):
    pass


def normalise(value: str) -> str:
    """Accept #abc or #aabbcc in any case; always store #AABBCC."""
    if not isinstance(value, str) or not HEX_PATTERN.match(value.strip()):
        raise InvalidColor(f"{value!r} is not a hex colour like #1F4B99")
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    return f"#{text.upper()}"


def to_rgb(value: str) -> tuple[int, int, int]:
    text = normalise(value).lstrip("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def from_rgb(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def relative_luminance(value: str) -> float:
    """WCAG relative luminance."""

    def channel(component: int) -> float:
        srgb = component / 255
        return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4

    r, g, b = to_rgb(value)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(first: str, second: str) -> float:
    """WCAG contrast ratio, between 1.0 and 21.0."""
    a, b = relative_luminance(first), relative_luminance(second)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def readable_on(background: str) -> str:
    """Black or white — whichever is more readable on this background."""
    return (
        BLACK
        if contrast_ratio(background, BLACK) >= contrast_ratio(background, WHITE)
        else WHITE
    )


def adjust_for_contrast(color: str, background: str, *, minimum: float = AA_NORMAL_TEXT) -> str:
    """Darken or lighten a colour until it is readable on a background.

    Hue and saturation are preserved, so the result still reads as the club's
    colour rather than as a different one. If even pure black or white cannot
    reach the target, the best available is returned — the caller decides
    whether to warn.
    """
    if contrast_ratio(color, background) >= minimum:
        return normalise(color)

    r, g, b = (channel / 255 for channel in to_rgb(color))
    hue, lightness, saturation = colorsys.rgb_to_hls(r, g, b)

    # Move away from the background: darker on light surfaces, lighter on dark.
    darken = relative_luminance(background) > 0.5
    best, best_ratio = normalise(color), contrast_ratio(color, background)

    for step in range(1, 101):
        candidate_lightness = (
            lightness * (1 - step / 100) if darken else lightness + (1 - lightness) * step / 100
        )
        candidate = from_rgb(
            tuple(
                channel * 255
                for channel in colorsys.hls_to_rgb(hue, candidate_lightness, saturation)
            )
        )
        ratio = contrast_ratio(candidate, background)
        if ratio > best_ratio:
            best, best_ratio = candidate, ratio
        if ratio >= minimum:
            return candidate

    return best


@dataclass(frozen=True, slots=True)
class ColorAssessment:
    color: str
    on_color: str
    text_on_light: str
    text_on_dark: str
    contrast_on_white: float
    contrast_on_black: float
    meets_aa_as_text: bool
    meets_aa_as_surface: bool

    @property
    def was_adjusted(self) -> bool:
        return self.text_on_light != self.color


def assess(color: str) -> ColorAssessment:
    """Everything the UI needs to use one brand colour safely."""
    value = normalise(color)
    on_light = adjust_for_contrast(value, LIGHT_SURFACE)
    on_dark = adjust_for_contrast(value, DARK_SURFACE)
    return ColorAssessment(
        color=value,
        on_color=readable_on(value),
        text_on_light=on_light,
        text_on_dark=on_dark,
        contrast_on_white=round(contrast_ratio(value, WHITE), 2),
        contrast_on_black=round(contrast_ratio(value, BLACK), 2),
        meets_aa_as_text=contrast_ratio(value, LIGHT_SURFACE) >= AA_NORMAL_TEXT,
        meets_aa_as_surface=contrast_ratio(value, readable_on(value)) >= AA_NON_TEXT,
    )


def build_palette(primary: str, secondary: str | None, accent: str | None) -> dict[str, str]:
    """The CSS custom properties a club site and admin shell are themed with.

    Deliberately small: three inputs produce a fixed set of tokens. There is no
    mechanism for a club to set an arbitrary CSS property, which is what keeps
    every tenant's UI recognisably the same product.
    """
    brand = assess(primary)
    palette = {
        "--brand": brand.color,
        "--brand-contrast": brand.on_color,
        "--brand-text": brand.text_on_light,
        "--brand-text-dark": brand.text_on_dark,
        "--brand-hover": adjust_for_contrast(brand.color, WHITE, minimum=AA_LARGE_TEXT),
    }
    if secondary:
        second = assess(secondary)
        palette["--brand-secondary"] = second.color
        palette["--brand-secondary-contrast"] = second.on_color
    if accent:
        third = assess(accent)
        palette["--brand-accent"] = third.color
        palette["--brand-accent-contrast"] = third.on_color
        palette["--brand-accent-text"] = third.text_on_light
    return palette
