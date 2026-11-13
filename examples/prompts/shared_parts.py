"""Shared parts of a prompt: one file holds the tone, two prompts take it.

`lib/tone.skye` is a partial (`partial = true`): a prompt-shaped file that no one renders alone.
`support.skye` takes two names from it (`from "lib/tone.skye" import tone, signature`) and writes
`use tone` where the text must stand, in `variables` and in the system message.
`support_formal.skye` takes the whole file (`include ... as tone`) and changes a default with
`override`. A prompt registered from a path resolves its includes from that path.
Runs offline, no key.
"""

from pathlib import Path

from skye.prompts import BasePromptBuilder

HERE = Path(__file__).parent / "shared_parts"


def system_message(builder: BasePromptBuilder, name: str, variables: dict) -> str:
    return builder.render(name, variables)[0].content


def main() -> None:
    builder = BasePromptBuilder()
    for name in ("support", "support_formal"):
        builder.register_template(name, str(HERE / f"{name}.skye"), from_string=False)

    question = {"question": "How do I reset my password?"}
    print("support, the default tone:\n" + system_message(builder, "support", question))
    print("\nsupport, with a signature:")
    print(system_message(builder, "support", {**question, "signature": "The Support Team"}))
    print("\nsupport_formal, the default changed by override:")
    print(system_message(builder, "support_formal", question))


if __name__ == "__main__":
    main()
