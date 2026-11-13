"""``generation_sql`` is a case of ``generation_code`` (task 24.12, D118).

The two bundled templates were one job, generating code, with a language fixed to SQL in the second one and
three variables of its own (``database_schema``, ``database_type``, ``question``). They are one template now:
``generation_code`` with generic variables (``language``, ``input``, ``references``, ``environment``,
``constraints``, ``examples``, ``detailed``, ``format``...). SQL is ``language = "SQL"``.

``fixtures/generation_before.json`` holds the renderings of the two old templates, as they were just before
the merge: for each template and each way of using it (``label``), the old variables, the messages of the old
render (``before``) and, when the new template renders it differently, the new messages (``after``).
``to_new_from_code`` and ``to_new_from_sql`` say which options of the new template replace the old variables.

A rendering is the same before and after unless it is listed in ``CHANGES`` with the reason; the test fails
for a change that is not listed, for a listed change that did not happen, and when the new text is not the
text stored in ``after``. ``write_after()`` makes the ``after`` side again from the template as it is now.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skye.prompts import BasePromptBuilder, loaders

FIXTURE = Path(__file__).parent / "fixtures" / "generation_before.json"
TEMPLATE = "generation_code"


def _columns(table: dict) -> str:
    lines = ["Columns:"]
    for column in table.get("columns", []):
        line = f"- {column['name']} ({column['type']})"
        if column.get("description"):
            line += f" - {column['description']}"
        lines.append(line)
    return "\n".join(lines)


def to_new_from_code(old: dict) -> dict:
    """The options of ``generation_code`` that replace the variables of the old ``generation_code``."""
    new = {
        k: v
        for k, v in old.items()
        if k in ("system_prompt", "description", "input_format", "language")
    }
    new.update({k: v for k, v in old.items() if k in ("include_tests", "include_comments")})
    if "task" in old:
        new["input"] = old["task"]
    if "requirements" in old:
        new["constraints"] = old[
            "requirements"
        ]  # one list of rules (Requirements and Constraints were one idea)
    if "examples" in old:  # free text before, a list of requests and answers now
        new["examples"] = [{"input": "Example", "output": old["examples"]}]
    if (
        "output_format" in old
    ):  # what the generated code outputs, kept under a name that is not the answer format
        new["result_format"] = old["output_format"]
    return new


def to_new_from_sql(old: dict) -> dict:
    """The options of ``generation_code`` that replace the variables of the old ``generation_sql``."""
    new = {"language": "SQL"}
    new.update(
        {k: v for k, v in old.items() if k in ("system_prompt", "description", "constraints")}
    )
    if "question" in old:
        new["input"] = old["question"]
    if "database_type" in old:
        new["environment"] = old["database_type"]
    if "database_schema" in old:
        new["references"] = [
            {"name": t["name"], "description": t.get("description", ""), "content": _columns(t)}
            for t in old["database_schema"]
        ]
    if "examples" in old:
        new["examples"] = [{"input": e["question"], "output": e["sql"]} for e in old["examples"]]
    if old.get("output_format") == "explained":
        new["detailed"] = True  # the four sections of the old explained layout
    elif old.get("output_format") == "json":
        new["format"] = "json"  # the JSON answer comes from the output block now
    return new


TO_NEW = {"code_generation": to_new_from_code, "sql_generation": to_new_from_sql}

# Why a rendering changed. A rendering lists the reasons that apply to it; the reasons are the intended changes.
DEFAULT_LANGUAGE = (
    "The default language is no longer Python: without a language the request line is 'Generate code for the "
    "following task: ...' (it said 'Generate Python code for ...')."
)
ROLE_LANGUAGE = (
    "The role sentence follows the language: 'You are an expert {language} developer. Generate clean, efficient, "
    "and well-documented code.' (it was 'You are an expert programmer. ...' for any language)."
)
DESCRIPTION = (
    "The extra description is shown after the role sentence, in the system message (it was the first line of the "
    "user message)."
)
CONSTRAINTS = (
    "The requirements are the list `constraints` (Requirements and Constraints were one idea): '## Constraints:' "
    "in the system message (it was 'Requirements:' in the user message)."
)
EXAMPLES_LIST = (
    "The examples are a list of requests and answers shown in the system message as '## Examples:' with "
    "'**Request:**' and '**Code:**' (the code one took free text and showed it in the user message)."
)
SQL_ROLE = (
    "The role sentence is 'You are an expert SQL developer. Generate clean, efficient, and well-documented code.' "
    "(it was 'You are an expert SQL query generator. You can translate natural language questions into accurate, "
    "efficient SQL queries based on the provided database schema.')."
)
SQL_SHAPE = (
    "The question is the request of a user message ('Generate SQL code for the following task: ...'), no longer a "
    "'## Question:' section of the system message, and the empty layout '## SQL Query: ... ## Explanation:' is "
    "replaced by the closing line 'Code:' (there was no user message)."
)
SQL_SCHEMA = (
    "The tables are `references`: '## Reference material:' with '**table**: description' and the columns as the "
    "content (they were '## Database Schema:' with '**Table: x**', 'Description:' and 'Columns:')."
)
SQL_TYPE = (
    "The dialect is `environment`: '## Environment:' with 'Please generate code compatible with ...' (it was "
    "'## Database Type: ...' with 'Please generate queries compatible with ...')."
)
SQL_EXAMPLES = (
    "The examples are the generic ones: '**Request:**' and '**Code:**' with a fence of the language (they were "
    "'**Question:**' and '**SQL:**' with a sql fence)."
)
SQL_EXPLAINED = (
    "The explained layout is `detailed`: the sections 'Code', 'Explanation', 'Key points' and 'Usage example' "
    "(they were 'SQL Query', 'Explanation', 'Key Joins' and 'Performance Notes')."
)
SQL_JSON = (
    "The JSON answer is `format = json` through the output block: fields `code` and `explanation` with the JSON "
    "Schema and an example of the shape (it was a hand-written object with sql, explanation, tables_used and "
    "complexity)."
)

_CODE = {
    "empty": (DEFAULT_LANGUAGE,),
    "full": (ROLE_LANGUAGE, DESCRIPTION, CONSTRAINTS, EXAMPLES_LIST),
    "system": (DEFAULT_LANGUAGE,),
    "only_description": (DEFAULT_LANGUAGE, DESCRIPTION),
    "only_language": (ROLE_LANGUAGE,),
    "only_task": (DEFAULT_LANGUAGE,),
    "only_requirements": (DEFAULT_LANGUAGE, CONSTRAINTS),
    "only_examples": (DEFAULT_LANGUAGE, EXAMPLES_LIST),
    "only_input_format": (DEFAULT_LANGUAGE,),
    "only_output_format": (DEFAULT_LANGUAGE,),
    "only_tests": (DEFAULT_LANGUAGE,),
    "only_comments": (DEFAULT_LANGUAGE,),
    "sample": (ROLE_LANGUAGE, CONSTRAINTS, EXAMPLES_LIST),
}
_SQL = {
    "empty": (SQL_ROLE, SQL_SHAPE),
    "full_explained": (SQL_ROLE, SQL_SHAPE, SQL_SCHEMA, SQL_TYPE, SQL_EXAMPLES, SQL_EXPLAINED),
    "full_json": (SQL_ROLE, SQL_SHAPE, SQL_SCHEMA, SQL_TYPE, SQL_EXAMPLES, SQL_JSON),
    "system": (SQL_SHAPE,),
    "only_description": (SQL_ROLE, SQL_SHAPE),
    "only_schema": (SQL_ROLE, SQL_SHAPE, SQL_SCHEMA),
    "only_database_type": (SQL_ROLE, SQL_SHAPE, SQL_TYPE),
    "only_examples": (SQL_ROLE, SQL_SHAPE, SQL_EXAMPLES),
    "only_constraints": (SQL_ROLE, SQL_SHAPE),
    "only_question": (SQL_ROLE, SQL_SHAPE),
    "output_explained": (SQL_ROLE, SQL_SHAPE, SQL_EXPLAINED),
    "output_json": (SQL_ROLE, SQL_SHAPE, SQL_JSON),
    "output_other": (SQL_ROLE, SQL_SHAPE),
    "sample": (SQL_ROLE, SQL_SHAPE, SQL_SCHEMA, SQL_TYPE, SQL_EXAMPLES, SQL_EXPLAINED),
}

#: The renderings that change on purpose: (old template, label) -> why. Every other rendering is the same text.
CHANGES: dict[tuple[str, str], str] = {
    **{("code_generation", label): " ".join(reasons) for label, reasons in _CODE.items()},
    **{("sql_generation", label): " ".join(reasons) for label, reasons in _SQL.items()},
}


def _render(builder: BasePromptBuilder, variables: dict) -> list:
    try:
        return [[m.role, m.content] for m in builder.render(TEMPLATE, variables)]
    except Exception as error:  # a mistake is part of the result
        return ["error", str(error)]


def write_after() -> None:
    """Make the ``after`` side of the fixture from the template as it is now."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    builder = BasePromptBuilder()
    for template, cases in data.items():
        for case in cases:
            now = _render(builder, TO_NEW[template](case["variables"]))
            case.pop("after", None)
            if now != case["before"]:
                case["after"] = now
    FIXTURE.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


DATA = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES = [(template, case) for template, cases in DATA.items() for case in cases]
IDS = [f"{template}/{case['label']}" for template, case in CASES]


def test_the_fixture_has_the_two_old_templates_with_more_than_eight_renderings_each():
    assert sorted(DATA) == ["code_generation", "sql_generation"]
    assert all(len(cases) >= 8 for cases in DATA.values())
    for cases in DATA.values():
        labels = [c["label"] for c in cases]
        assert len(labels) == len(set(labels))
        assert {"empty", "system"} <= set(labels) and any(
            label.startswith("full") for label in labels
        )


@pytest.mark.parametrize(("template", "case"), CASES, ids=IDS)
def test_a_rendering_is_the_same_as_before_except_for_the_listed_changes(template, case):
    now = _render(BasePromptBuilder(), TO_NEW[template](case["variables"]))
    key = (template, case["label"])
    if key in CHANGES:
        assert now != case["before"], f"{key} is listed as a change but renders as before"
        assert now == case["after"], f"{key}: the new text is not the one of the fixture"
    else:
        assert now == case["before"], f"{key} changed and is not listed in CHANGES"
        assert "after" not in case


def test_every_change_is_listed_once_with_a_reason_and_names_a_rendering_of_the_fixture():
    present = {(t, c["label"]) for t, c in CASES}
    assert set(CHANGES) <= present
    assert all(isinstance(reason, str) and len(reason) > 20 for reason in CHANGES.values())
    assert {(t, c["label"]) for t, c in CASES if "after" in c} == set(CHANGES)


def test_generation_sql_is_gone_and_generation_code_is_the_one_template():
    names = sorted(loaders.bundled_names())
    assert "generation_sql" not in names and "generation_code" in names


def test_the_new_template_has_no_variable_that_names_a_database_or_a_table():
    builder = BasePromptBuilder()
    spec = builder._entry(builder._latest_key(TEMPLATE)).spec
    variables = {v.name for v in spec.variables}
    assert not {v for v in variables if "database" in v or "table" in v or "sql" in v}
    assert {
        "language",
        "input",
        "references",
        "environment",
        "constraints",
        "examples",
    } <= variables
