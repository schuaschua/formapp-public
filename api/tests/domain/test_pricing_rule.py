"""Story 2.2: prices are computed only in api/domain/pricing.py (spine AD-5, AD-10).

The pricing constants (x1.05 per band, x0.95 for paying yearly) may appear in no other source file
of the api or the web app. Stylesheets are left out: CSS cannot compute a price, and its line
heights and colours use the same numbers.
"""

import re
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[2]
WEB_SRC = API_DIR.parent / "web" / "src"
PRICING = API_DIR / "domain" / "pricing.py"

_PRICING_CONSTANT = re.compile(r"(?<![\d.])(?:1\.05|0\.95)(?!\d)")
_SKIPPED_DIRS = {".venv", "tests", "node_modules", "__pycache__"}
_WEB_SUFFIXES = {".ts", ".tsx", ".js", ".jsx"}


def _sources() -> list[Path]:
    api = [p for p in API_DIR.rglob("*.py") if not _skipped(p, API_DIR)]
    web = [
        p
        for p in WEB_SRC.rglob("*")
        if p.suffix in _WEB_SUFFIXES and not _skipped(p, WEB_SRC)
    ]
    return sorted(api + web)


def _skipped(path: Path, root: Path) -> bool:
    return bool(_SKIPPED_DIRS & set(path.relative_to(root).parts))


def pricing_constants(source: str) -> list[str]:
    """Return the pricing constants that appear in source."""
    return _PRICING_CONSTANT.findall(source)


def test_story_2_2_prices_are_computed_only_in_domain_pricing() -> None:
    sources = _sources()
    violations = {
        str(path): found
        for path in sources
        if path != PRICING and (found := pricing_constants(path.read_text("utf-8")))
    }

    assert PRICING in sources
    assert any(path.is_relative_to(WEB_SRC) for path in sources)
    assert pricing_constants(PRICING.read_text("utf-8"))
    assert violations == {}


def test_story_2_2_pricing_rule_catches_violations() -> None:
    source = "const monthly = baseline * 1.05 ** band;\nyearly = m * 12 * 0.95\n"

    assert pricing_constants(source) == ["1.05", "0.95"]
    assert pricing_constants("x = 11.05 + 0.955 + 21.050") == []
