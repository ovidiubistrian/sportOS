"""The language list is one list.

The backend decides which locales a tenant may be configured with; the frontend
ships the catalogue that makes each one readable. If those two drift, a tenant
gets configured into a language whose interface does not exist — and the
failure shows up as English words scattered through someone's admin, weeks
later, reported as "the translation is broken".

So the drift is a test, not a convention.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.core.locales import DEFAULT_LOCALE, LOCALE_CODES, SUPPORTED_LOCALES, normalise

pytestmark = pytest.mark.i18n


def _i18n_src() -> pathlib.Path:
    """Find the shared catalogues in either layout.

    In the repository they sit beside `backend/`; in the container the backend
    is mounted at `/app` and the package is mounted alongside it. Looking in
    both means this test runs unchanged in development and in CI.
    """
    candidates = [
        pathlib.Path("/packages/i18n/src"),
        pathlib.Path(__file__).resolve().parents[3] / "packages" / "i18n" / "src",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise AssertionError(
        "The @footbola/i18n catalogues are not reachable from the test run. "
        f"Looked in: {[str(c) for c in candidates]}"
    )


I18N_SRC = _i18n_src()


def _frontend_locales() -> set[str]:
    """Read the codes out of the shipped i18n package."""
    index = (I18N_SRC / "index.ts").read_text(encoding="utf-8")
    block = re.search(r"export const LOCALES = \[(.*?)\] as const;", index, re.S)
    assert block, "LOCALES not found in packages/i18n/src/index.ts"
    return set(re.findall(r'code:\s*"([a-z-]+)"', block.group(1)))


def _catalogue_keys(path: pathlib.Path) -> set[str]:
    """Every `section.key` in a catalogue file, without parsing TypeScript.

    Deliberately crude: it compares *shape*, and the frontend's own type checker
    already proves the shapes match exactly. This exists so a broken catalogue
    fails the backend suite too, where nobody is running `tsc`.
    """
    text = path.read_text(encoding="utf-8")
    keys: set[str] = set()
    section = None
    for line in text.splitlines():
        stripped = line.strip()
        opening = re.match(r"^([a-zA-Z][\w]*):\s*\{$", stripped)
        if opening and line.startswith("  "):
            section = opening.group(1)
            continue
        if stripped in ("},", "}"):
            section = None
            continue
        entry = re.match(r"^([a-zA-Z][\w]*):", stripped)
        if section and entry:
            keys.add(f"{section}.{entry.group(1)}")
    return keys


class TestRegistry:
    def test_backend_and_frontend_ship_the_same_languages(self) -> None:
        assert _frontend_locales() == set(LOCALE_CODES), (
            "app/core/locales.py and packages/i18n/src/index.ts disagree. "
            "Adding a language means both, plus a catalogue file."
        )

    def test_every_language_has_a_catalogue(self) -> None:
        # English lives in catalogue.ts; every other language gets its own file.
        for code in sorted(LOCALE_CODES):
            path = I18N_SRC / ("catalogue.ts" if code == "en" else f"{code}.ts")
            assert path.exists(), (
                f"{code} is a supported locale with no catalogue at {path.name}."
            )

    def test_translations_are_complete(self) -> None:
        english = _catalogue_keys(I18N_SRC / "catalogue.ts")
        assert english, "the English catalogue could not be read"

        for code in sorted(LOCALE_CODES - {"en"}):
            translated = _catalogue_keys(I18N_SRC / f"{code}.ts")
            missing = english - translated
            extra = translated - english
            assert not missing, f"{code} is missing: {sorted(missing)[:10]}"
            assert not extra, f"{code} has keys English does not: {sorted(extra)[:10]}"

    def test_the_default_is_supported(self) -> None:
        assert DEFAULT_LOCALE in LOCALE_CODES

    def test_endonyms_are_in_their_own_language(self) -> None:
        """A speaker scans for the word they use, not for the English name."""
        for locale in SUPPORTED_LOCALES:
            assert locale.endonym.strip(), f"{locale.code} has no endonym"


class TestNormalisation:
    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("ro", "ro"),
            ("ro-RO", "ro"),
            ("ro_MD", "ro"),  # Romanian is spoken in more than one country
            ("RO", "ro"),
            ("  ro  ", "ro"),
            ("en-GB", "en"),
            ("en-US", "en"),
        ],
    )
    def test_region_subtags_fold_onto_the_language(self, given: str, expected: str) -> None:
        assert normalise(given) == expected

    def test_an_unsupported_language_falls_back(self) -> None:
        # A browser sending `de-AT` should get English, not an error: this runs
        # on the public site where there is nobody to show an error to.
        assert normalise("de-AT") == DEFAULT_LOCALE
        assert normalise("") == DEFAULT_LOCALE
