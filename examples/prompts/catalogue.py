"""A gallery of prompts to copy: 27 `.skye` files rendered from their own sample variables.

The package bundles only a few prompts (`skye prompt list`). The rest were written for Skye as
starting points and live in `examples/prompts/catalogue/`: agents (tool, planner, reasoning,
smolagents style, supervisors, group chat, memory upkeep), `chat_assistant` and more. Copy one next
to your code and change it. Each file has a data file with the variables of a call that renders, and
the files that `include` a shared part read it from `catalogue/common/`. Runs offline, no key.
"""

import json
from pathlib import Path

from skye.prompts import BasePromptBuilder

GALLERY = Path(__file__).parent / "catalogue"
# `extraction_generic` does the job of three bundled prompts; its samples are named after them
BUNDLED = {"entities": "extraction_entities", "relations": "extraction_relations", "table": "extraction_table"}


def samples(path: Path) -> list[Path]:
    """The sample files of a prompt: `name.json` and any `name.<part>.json`."""
    return sorted(GALLERY.glob(f"{path.stem}.json")) + sorted(GALLERY.glob(f"{path.stem}.*.json"))


def main() -> None:
    builder = BasePromptBuilder()
    total = 0
    for path in sorted(GALLERY.glob("*.skye")):
        builder.register_template(path.stem, str(path), from_string=False)
        for sample in samples(path):
            variables = json.loads(sample.read_text(encoding="utf-8"))
            messages = builder.render(path.stem, variables)
            part = sample.stem.removeprefix(path.stem).lstrip(".")
            note = f"  like the bundled {BUNDLED[part]}" if part in BUNDLED else ""
            print(f"{sample.stem:34} {len(messages)} messages{note}")
            total += 1
    print(f"\n{total} renders, no model called")


if __name__ == "__main__":
    main()
