"""Examples are small (Requirement 24.5 of steering, task 5.8 of the uxui spec).

One idea per example, about 80 lines. ``KNOWN_LONG`` maps each file still over the limit to the most lines it may have; the entry only
goes down, and a file that fits is removed from the list. Files that start with an underscore (the shared helper ``examples/_offline.py``) are not examples.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
LIMIT = 80
EXEMPT_FOLDERS: set[str] = set()

# custom_providers.py stays long because BaseModelProvider has 11 abstract methods that every provider must write (streaming and
# capability hooks included). Making them optional with safe defaults is proposal S5.5 of the simplicity report; it is not a task
# or a decision yet. The cap is the file's size today and only shrinks.
KNOWN_LONG: dict[str, int] = {
    "advanced/custom_providers.py": 88,
}


def _lines() -> dict[str, int]:
    sizes = {}
    for path in sorted(EXAMPLES.rglob("*.py")):
        rel = path.relative_to(EXAMPLES)
        if path.name == "__init__.py" or path.name.startswith("_") or "__pycache__" in rel.parts or rel.parts[0] in EXEMPT_FOLDERS:
            continue
        sizes[rel.as_posix()] = len(path.read_text(encoding="utf-8").splitlines())
    return sizes


def test_no_empty_example():
    assert [f for f, n in _lines().items() if n == 0] == []


def test_examples_fit_the_limit():
    sizes = _lines()
    too_long = {f: n for f, n in sizes.items() if n > LIMIT and f not in KNOWN_LONG}
    assert not too_long, f"examples over {LIMIT} lines (split or cut, do not add to KNOWN_LONG): {too_long}"
    grown = {f: (sizes[f], cap) for f, cap in KNOWN_LONG.items() if sizes.get(f, 0) > cap}
    assert not grown, f"a known long example grew: {grown}"


def test_known_long_only_shrinks():
    sizes = _lines()
    stale = [f for f in KNOWN_LONG if sizes.get(f, 0) <= LIMIT]
    assert not stale, f"fits the limit now (or is gone), remove from KNOWN_LONG: {stale}"
