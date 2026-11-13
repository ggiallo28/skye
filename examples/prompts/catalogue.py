"""A gallery of prompts to copy: 26 `.skye` files rendered from their own sample variables.

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


def main() -> None:
    builder = BasePromptBuilder()
    total = 0
    for path in sorted(GALLERY.glob("*.skye")):
        builder.register_template(path.stem, str(path), from_string=False)
        sample = path.with_suffix(".json")
        variables = json.loads(sample.read_text(encoding="utf-8"))
        messages = builder.render(path.stem, variables)
        print(f"{path.stem:34} {len(messages)} messages")
        total += 1
    print(f"\n{total} renders, no model called")


if __name__ == "__main__":
    main()
