"""
Tests of the palette and the stylesheet of the HTML report (spec 008, RF-06, RF-07, ADR-8, ADR-10).

Isolation: pure data. The contrast is computed here with the WCAG 2.x formula, independent of the
module that holds the colours, so a regression in the palette is a failing test and not a silent
change. Every text pair needs 4.5:1 and every graphic that carries meaning needs 3:1 (RF-07).
"""

from __future__ import annotations

import re

import pytest

from mailvigil.html_style import (
    CONTENT_SECURITY_POLICY,
    DARK,
    DECORATIVE,
    GRAPHIC_PAIRS,
    LIGHT,
    STYLESHEET,
    TEXT_PAIRS,
)

# ---------------------------------------------------------------------------
# WCAG contrast
# ---------------------------------------------------------------------------


def _channel(value: int) -> float:
    """One sRGB channel, 0 to 255, linearized as in the WCAG 2.x relative luminance."""
    unit = value / 255
    return unit / 12.92 if unit <= 0.03928 else ((unit + 0.055) / 1.055) ** 2.4


def _luminance(color: str) -> float:
    """The WCAG 2.x relative luminance of a ``#rrggbb`` colour (weights 0.2126, 0.7152, 0.0722)."""
    red, green, blue = (int(color[index : index + 2], 16) for index in (1, 3, 5))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast(first: str, second: str) -> float:
    """The WCAG contrast ratio of two ``#rrggbb`` colours, from 1 to 21."""
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_the_contrast_formula_matches_the_known_extremes() -> None:
    assert contrast("#000000", "#ffffff") == pytest.approx(21)
    assert contrast("#777777", "#777777") == pytest.approx(1)


# ---------------------------------------------------------------------------
# The palette
# ---------------------------------------------------------------------------

_SCHEMES = {"light": LIGHT, "dark": DARK}


def test_both_palettes_define_the_same_tokens() -> None:
    assert LIGHT.keys() == DARK.keys()


def test_every_color_is_a_six_digit_hex() -> None:
    for palette in _SCHEMES.values():
        for name, color in palette.items():
            assert re.fullmatch(r"#[0-9a-f]{6}", color), name


@pytest.mark.parametrize("scheme", _SCHEMES)
@pytest.mark.parametrize(("foreground", "background"), TEXT_PAIRS)
def test_text_pairs_reach_4_5_to_1(scheme: str, foreground: str, background: str) -> None:
    palette = _SCHEMES[scheme]
    assert contrast(palette[foreground], palette[background]) >= 4.5


@pytest.mark.parametrize("scheme", _SCHEMES)
@pytest.mark.parametrize(("graphic", "surface"), GRAPHIC_PAIRS)
def test_graphic_pairs_reach_3_to_1(scheme: str, graphic: str, surface: str) -> None:
    palette = _SCHEMES[scheme]
    assert contrast(palette[graphic], palette[surface]) >= 3.0


def test_every_token_is_measured_or_declared_decorative() -> None:
    measured = {name for pair in TEXT_PAIRS + GRAPHIC_PAIRS for name in pair}
    assert set(LIGHT) == measured | set(DECORATIVE)
    assert measured.isdisjoint(DECORATIVE)


# ---------------------------------------------------------------------------
# The stylesheet
# ---------------------------------------------------------------------------


def _declared(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z-]+):(#[0-9a-f]{6})", block))


def test_the_stylesheet_declares_the_light_tokens_on_root() -> None:
    root = STYLESHEET.split("@media", 1)[0]
    assert _declared(root) == LIGHT


def test_the_stylesheet_declares_the_dark_tokens_by_system_preference() -> None:
    dark = STYLESHEET.split("@media (prefers-color-scheme:dark){", 1)[1].split("}}", 1)[0]
    assert _declared(dark) == DARK


def test_the_stylesheet_announces_both_color_schemes() -> None:
    assert "color-scheme:light dark" in STYLESHEET


def test_the_stylesheet_has_a_print_block_with_the_light_palette() -> None:
    printed = STYLESHEET.split("@media print{", 1)[1]
    assert _declared(printed) == LIGHT


@pytest.mark.parametrize("forbidden", ["url(", "@import", "expression(", "<", "javascript:"])
def test_the_stylesheet_loads_nothing_and_cannot_close_its_element(forbidden: str) -> None:
    assert forbidden not in STYLESHEET.lower()


def test_every_variable_used_is_a_token() -> None:
    used = set(re.findall(r"var\(--([a-z-]+)\)", STYLESHEET))
    assert used <= set(LIGHT)


def test_every_token_is_used_by_a_rule() -> None:
    used = set(re.findall(r"var\(--([a-z-]+)\)", STYLESHEET))
    assert used == set(LIGHT)


def test_the_stylesheet_is_ascii() -> None:
    assert STYLESHEET.isascii()


# ---------------------------------------------------------------------------
# The policy (ADR-8)
# ---------------------------------------------------------------------------


def test_the_policy_is_exactly_the_one_of_the_design() -> None:
    assert CONTENT_SECURITY_POLICY == (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
    )


def test_the_policy_has_no_image_source() -> None:
    assert "img-src" not in CONTENT_SECURITY_POLICY
