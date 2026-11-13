"""Group chat: three agents share one conversation through the group chat prompts of the gallery.

``agent_groupchat_participant`` tells each agent when to speak (an @mention or one of its topics) and to
answer ``[PASS]`` otherwise; ``agent_groupchat_manager`` asks for the next speakers as JSON. A scripted
fake model stands in for a real one, so the round runs offline, no key. Both prompts are read from
``examples/prompts/catalogue/`` with ``register_template``.
"""

import json
import re
from pathlib import Path

from skye.prompts import BasePromptBuilder

GALLERY = Path(__file__).parent / "catalogue"

GOAL = "Agree on a launch plan."
TOPICS = {"planner": ["plan", "schedule"], "finance": ["budget", "cost"], "legal": ["contract"]}
PARTICIPANTS = [{"name": name, "triggers": words} for name, words in TOPICS.items()]
SHARED = {"participants": PARTICIPANTS}


def fake_model(messages: list) -> str:
    """Speaks when its @name or one of its topics is in the last line of the conversation."""
    lines = messages[-1].content.splitlines()
    line = [text for text in lines if text.split(": ")[0] in {"user", *TOPICS}][-1].lower()
    words = {name: [f"@{name}", *topics] for name, topics in TOPICS.items()}
    called = [name for name in TOPICS if any(word in line for word in words[name])]
    match = re.search(r"^You are (\w+),", messages[0].content)
    if match is None:  # the manager
        return json.dumps({"next_speakers": called[:2], "reason": "their topics came up"})
    name = match.group(1)
    speaks = name in called and not line.startswith(name)
    return f"{name} here: I will take care of it." if speaks else "[PASS]"


def round_of(builder: BasePromptBuilder, transcript: list[dict]) -> None:
    """Every agent reads the same transcript; the replies are added after the round."""
    replies = []
    for name, words in TOPICS.items():
        variables = {"agent_name": name, "goal": GOAL, "triggers": words, "transcript": transcript}
        reply = fake_model(builder.render("agent_groupchat_participant", {**variables, **SHARED}))
        print(f"  {name:<9} {reply}")
        if reply != "[PASS]":
            replies.append({"speaker": name, "content": reply})
    transcript.extend(replies)


def main() -> None:
    builder = BasePromptBuilder()
    for name in ("agent_groupchat_participant", "agent_groupchat_manager"):
        builder.register_template(name, str(GALLERY / f"{name}.skye"), from_string=False)
    transcript = [{"speaker": "user", "content": "What will the launch cost?"}]

    print("Round 1: user asks about cost")
    round_of(builder, transcript)

    transcript.append({"speaker": "user", "content": "Please review the contract and the plan."})
    print("Round 2: user names the contract and the plan")
    round_of(builder, transcript)

    print("Manager on the last user message")
    variables = {"goal": GOAL, "transcript": transcript[:3], **SHARED}
    manager = builder.render("agent_groupchat_manager", variables)
    print(f"  reply:    {fake_model(manager)}")
    print(f"  messages: {len(transcript)} in the transcript")


if __name__ == "__main__":
    main()
