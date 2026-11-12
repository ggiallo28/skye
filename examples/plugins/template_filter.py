"""Add a template filter.

What it is for: a prompt is written as a template, and a template can change a value before it goes
into the text: `{{ name | upper }}` puts the name in capital letters. The part after the `|` is a
filter. Skye has a few built in; a template filter is how you add your own, for a change you repeat in
many prompts (a format for dates or money, a clean-up of user text, a short form of a long id), so
that you write it once and use it by name in every template instead of preparing the value in code
before each call.

To add a template filter you use the decorator `@plugins.template_filter("name")` on top of a function.

The function receives:

* The `value` that the template passes to the filter: `{{ name | shout }}` calls `shout(name)`.
* The arguments written in the template, if any: `{{ total | money("EUR") }}` calls `money(total, "EUR")`.
* It returns the value to put in the text.

The examples below go from the simplest to the ones you would really write: one with an argument
(`money`), one that protects data before it reaches the model (`mask_email`), one that turns a
list into a block of text (`bullets`) and one that cuts a long text (`first_words`).

The filter is there as soon as the decorator runs, wherever that code runs, and it works in the text and in the `.skye` prompts of every prompt builder.

Tip: a filter added to one builder with `builder.register_filter(...)` stays local to that builder.
"""

import skye
from skye.prompts import BasePromptBuilder

plugins = skye.Plugins()


@plugins.template_filter("shout")
def shout(value):
    return str(value).upper() + "!"


@plugins.template_filter("money")
def money(value, currency="USD"):
    """An amount with two decimals and a currency: `{{ total | money("EUR") }}` -> `1,234.50 EUR`."""
    return f"{float(value):,.2f} {currency}"


@plugins.template_filter("mask_email")
def mask_email(value):
    """Hide the address before the text goes to the model: `ada@acme.org` -> `a***@acme.org`."""
    name, _, domain = str(value).partition("@")
    return f"{name[:1]}***@{domain}" if domain else str(value)


@plugins.template_filter("bullets")
def bullets(values):
    """A list as one line per item, so a prompt can carry a list of facts."""
    return "\n".join(f"- {item}" for item in values)


@plugins.template_filter("first_words")
def first_words(value, count=5):
    """The first `count` words of a long text, with `...` if something was cut."""
    words = str(value).split()
    return " ".join(words[:count]) + (" ..." if len(words) > count else "")


def main() -> None:
    # Use it: `{{ name | shout }}` in a template. Any builder finds the filter, with no line of setup.
    builder = BasePromptBuilder()
    builder.register_template("greeting", "Hello {{ name | shout }}", from_string=True)
    print("everywhere:", builder.render("greeting", {"name": "Ada"})[-1].content)

    # A second builder, created later, has it too.
    other = BasePromptBuilder()
    other.register_template("farewell", "Bye {{ name | shout }}", from_string=True)
    print("everywhere:", other.render("farewell", {"name": "Ada"})[-1].content)

    # More realistic filters: with an argument, protecting data, formatting a list, cutting a text.
    report = BasePromptBuilder()
    report.register_template(
        "report",
        "Customer: {{ email | mask_email }}\n"
        'Total: {{ total | money }} ({{ total | money("EUR") }})\n'
        "Issues:\n{{ issues | bullets }}\n"
        "Note: {{ note | first_words(4) }}",
        from_string=True,
    )
    data = {
        "email": "ada@acme.org",
        "total": 1234.5,
        "issues": ["late delivery", "damaged box"],
        "note": "The customer wrote three long paragraphs about the delay",
    }
    print(report.render("report", data)[-1].content)

    # A filter added to one builder is local to it: the other builder does not have it.
    builder.register_filter("whisper", lambda value: str(value).lower() + "...")
    builder.register_template("quiet", "{{ name | whisper }}", from_string=True)
    print("local:", builder.render("quiet", {"name": "ADA"})[-1].content)


if __name__ == "__main__":
    main()
