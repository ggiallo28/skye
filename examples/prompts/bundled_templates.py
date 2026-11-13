"""Every bundled prompt rendered from its own sample variables.

The prompts that ship with the package (`text_classification`, `extraction_structured`, `agent_react` and more) have one
data file each in `examples/prompts/bundled/`: the variables of a call that renders. A file holds
one object, the variables of one render, or a list of them when the prompt shows several calls.
Write the prompts out to edit them with `skye prompt export DIR`. Runs offline, no key.
"""

import json
from pathlib import Path

from skye.prompts import BasePromptBuilder

SAMPLES = Path(__file__).parent / "bundled"


def renders(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else [data]


def main() -> None:
    builder = BasePromptBuilder()
    total = 0
    for path in sorted(SAMPLES.glob("*.json")):
        for variables in renders(path):
            messages = builder.render(path.stem, variables)
            roles = ", ".join(message.role for message in messages)
            print(f"{path.stem:28} {len(messages)} messages ({roles})")
            total += 1
    print(f"\n{total} renders, no model called")


if __name__ == "__main__":
    main()
