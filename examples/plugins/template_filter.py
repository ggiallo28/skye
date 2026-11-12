"""Add a template filter.

What it is for: a template can change a value before it goes into the text, `{{ name | upper }}`.
The part after the `|` is a filter. Skye has a few built in; a template filter is how you add your
own, for a change you repeat in many prompts, written once and used by name in every template.

To add one you use the decorator `@plugins.template_filter("name")` on top of a function. It
receives the `value` of the template (`{{ name | shout }}` calls `shout(name)`), then the arguments
written in the template (`{{ total | money("EUR") }}` calls `money(total, "EUR")`), and returns the
value to put in the text. It is there as soon as the decorator runs, for every prompt builder.

Tip: a filter added with `builder.register_filter(...)` stays local to that builder.
"""

import skye
from skye.prompts import BasePromptBuilder

plugins = skye.Plugins()


@plugins.template_filter("shout")
def shout(value):
    return str(value).upper() + "!"


@plugins.template_filter("money")
def money(value, currency="USD"):
    """An amount with two decimals and a currency: `1,234.50 EUR`."""
    return f"{float(value):,.2f} {currency}"


@plugins.template_filter("mask_email")
def mask_email(value):
    """Hide the address before the text goes to the model: `a***@acme.org`."""
    name, _, domain = str(value).partition("@")
    return f"{name[:1]}***@{domain}" if domain else str(value)


def main() -> None:
    # Any builder finds the filters, with no line of setup.
    builder = BasePromptBuilder()
    builder.register_template("greeting", "Hello {{ name | shout }}", from_string=True)
    print(builder.render("greeting", {"name": "Ada"})[-1].content)

    # With an argument, and protecting a piece of data.
    builder.register_template(
        "order",
        'Customer {{ email | mask_email }} owes {{ total | money }} ({{ total | money("EUR") }})',
        from_string=True,
    )
    order = {"email": "ada@acme.org", "total": 1234.5}
    print(builder.render("order", order)[-1].content)

    # A filter added to one builder is local to it.
    builder.register_filter("whisper", lambda value: str(value).lower() + "...")
    builder.register_template("quiet", "{{ name | whisper }}", from_string=True)
    print(builder.render("quiet", {"name": "ADA"})[-1].content)


if __name__ == "__main__":
    main()
