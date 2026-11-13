"""Agent prompt: ``agent_planner`` from the gallery, with optional tools and memories.

The gallery in ``examples/prompts/catalogue/`` holds agent prompts to copy; ``register_template``
reads one from its path, with the shared parts it includes. An agent prompt's optional sections
(tools, memories, constraints) are ``when`` blocks: they appear only when their variable is given.
Runs offline, no key.
"""

from pathlib import Path

from skye.prompts import BasePromptBuilder

PLANNER = Path(__file__).parent / "catalogue" / "agent_planner.skye"

TOOLS = [{"name": "search_restaurants", "description": "Find restaurants by city and date"}]
MEMORIES = {
    "semantic_memory": [{"content": "The user is vegetarian."}],
    "episodic_memory": [{"content": "Booked Da Enzo last time.", "timestamp": "2026-10-02"}],
}


def headings(text: str) -> str:
    return ", ".join(line.lstrip("# ") for line in text.splitlines() if line.startswith("#"))


def section(text: str, start: str, stop: str) -> str:
    """The lines of ``text`` from the line starting with ``start`` up to the one with ``stop``."""
    lines = text.splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith(start))
    last = next(i for i, line in enumerate(lines) if i > first and line.startswith(stop))
    return "\n".join(lines[first:last])


def main() -> None:
    builder = BasePromptBuilder()
    builder.register_template("agent_planner", str(PLANNER), from_string=False)
    task = {"task": "Book a table for four in Rome on Friday."}

    bare = builder.render("agent_planner", task)[0].content
    full = builder.render("agent_planner", {**task, "tools": TOOLS, **MEMORIES})[0].content

    print("Sections")
    print(f"  bare:              {headings(bare)}")
    print(f"  tools and memory:  {headings(full)}")
    print()

    print("Tools and memory, as rendered")
    print(section(full, "## Tools", "## Your job"))
    print()

    print("Without tools")
    print(next(line for line in bare.splitlines() if line.startswith("No tools")))


if __name__ == "__main__":
    main()
