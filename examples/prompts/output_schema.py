"""Output schema: an ``output`` block in a .skye prompt declares the answer's shape and format.

``output format { ... }`` takes the format (json, table or xml) from the ``format`` variable; a
string after a field's type is its description for the model. ``output_instructions`` returns the
text the renderer appends to the last user message. The prompts are ``products`` and ``invoice``
in output_schema.skye, next to this file. The bundled ``extraction_generic`` takes the fields as
data, and a dataclass still works with ``set_output_schema``. Runs offline, no key.
"""

from dataclasses import dataclass
from pathlib import Path

from skye.prompts import BasePromptBuilder, load_prompt, output_instructions

PROMPT_FILE = Path(__file__).with_name("output_schema.skye")
PROMPTS = PROMPT_FILE.read_text(encoding="utf-8")


@dataclass
class Invoice:
    number: str
    total: float


def main() -> None:
    spec = load_prompt(PROMPTS, "products")
    variables = {"catalogue": "Desk lamp 24.90, in stock; Chair 89.00, sold out."}
    for output_format in ("json", "table", "xml"):
        print(f"Instructions as {output_format}")
        print(output_instructions(spec, {**variables, "format": output_format}))
        print()

    builder = BasePromptBuilder()
    print("Bundled extraction_generic, fields as data")
    schema = {"name": "string", "price": {"type": "number", "description": "Unit price in euro"}}
    request = {
        "task": "List the products",
        "input": "Lamp 24.90",
        "schema": schema,
        "format": "xml",
    }
    print(builder.render("extraction_generic", request)[-1].content)
    print()

    builder.register_template("invoice", str(PROMPT_FILE), from_string=False)
    builder.set_output_schema("invoice", Invoice, output_format="table")
    print("From a dataclass")
    print(builder.get_output_instructions("invoice"))


if __name__ == "__main__":
    main()
