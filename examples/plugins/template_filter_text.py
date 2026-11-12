"""Template filters for a list and for a long text.

The same decorator as in `template_filter.py`. These two prepare what a prompt carries: a list of
facts as one line each (`bullets`) and a long text cut to its first words (`first_words`).
"""

import skye
from skye.prompts import BasePromptBuilder

plugins = skye.Plugins()


@plugins.template_filter("bullets")
def bullets(values):
    """A list as one line per item."""
    return "\n".join(f"- {item}" for item in values)


@plugins.template_filter("first_words")
def first_words(value, count=5):
    """The first `count` words of a text, with `...` if something was cut."""
    words = str(value).split()
    return " ".join(words[:count]) + (" ..." if len(words) > count else "")


def main() -> None:
    builder = BasePromptBuilder()
    builder.register_template(
        "report",
        "Issues:\n{{ issues | bullets }}\nNote: {{ note | first_words(4) }}",
        from_string=True,
    )
    data = {
        "issues": ["late delivery", "damaged box"],
        "note": "The customer wrote three long paragraphs about the delay",
    }
    print(builder.render("report", data)[-1].content)


if __name__ == "__main__":
    main()
