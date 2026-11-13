# The `skye` command

```text
skye check FILE...            check .skye files; prints file:line:col message and the fix; exit 1 on errors
skye check --schema           print the JSON Schema of the router, flow and prompt blocks
skye check --registry a,b F   also check registry.NAME against the names a,b
skye check --format json [--stdin-filename NAME] -    read stdin; print one {"diagnostics": [...]} object
skye fmt [PATH...]            rewrite in the standard layout (comments, """ strings, front matter kept); no PATH = every .skye under .
skye fmt --check [PATH...]    change nothing; exit 1 if a file would be reformatted (CI); --exclude GLOB, .skyeignore
skye fmt [--stdin-filename NAME] -    format stdin to stdout (editors)
skye new KIND [NAME] [--template T | -t T] [-o FILE | --output FILE] [--force]    a starting .skye file you can edit
skye new --list               the kinds (router, flow, prompt) and their templates
skye render FILE [--name NAME] [--stdout] [--fence] [-o OUT | --output OUT] [--direction TD|LR]    a flow or a router as a Mermaid diagram
skye prompt list [--json]     the bundled prompts: name, title, version and description (from the front matter)
skye prompt info NAME|FILE [--name PROMPT] [--json]    what a prompt takes and gives back: inputs, history, messages, output
skye prompt export DIR [--force]    write every bundled prompt as a .skye file into DIR (no overwrite without --force, exit 2)
skye skill install [--scope user|project] [--dir DIR] [--force]    install this skill for Claude Code
skye skill print [NAME]       print SKILL.md, or references/NAME.md
skye skill path [--scope user|project] [--dir DIR]                 where the skill is installed
skye skill status [--scope user|project] [--dir DIR]               up to date, outdated or edited (exit 1 if it is not up to date)
skye vscode package [-o FILE | --output FILE]      build skye-<version>.vsix (the VS Code extension for .skye)
skye vscode install [--editor CMD] [--dir DIR] [--force]    install it with code/code-insiders/codium/cursor, or copy it to DIR
skye vscode uninstall [--editor CMD] [--dir DIR]   remove it
skye vscode path [--dir DIR]                       the folder a copied install uses
skye vscode status [--editor CMD] [--dir DIR]      up to date, outdated, edited or not installed (exit 1 if it is not up to date)
skye plugins [--format text|json]     what is registered per kind, and each installed plugin: loaded, failed (with the error) or skipped; exit 0
```

Exit codes: 0 no error, 1 the checked files have errors, 2 usage or file error.

## Templates (`skye new`)

| Kind | Templates (the first is the default) |
|---|---|
| router | `shorthand`, `full` |
| flow | `sequence`, `branch`, `parallel`, `loop`, `full` |
| prompt | `basic`, `chat` |

`skye new` prints to standard output unless you pass `-o`; it refuses to overwrite a file without `--force`.
Every template passes `skye check`, so the first check of a new file is clean and every later error is yours.

## Prompt help (`skye prompt`)

`skye prompt info agent_react` explains a bundled prompt; `skye prompt info prompts.skye --name chat` a prompt of a file (`--name`
picks one when the file has several; `-` reads stdin). It prints the header `name — title (version)`, the description, then `Inputs`
(name, type, `required` / `optional` / `= default`, description), `History` (the placeholders), `Messages` (the roles in order, `user*`
inside `each`, `system?` inside `when`) and `Output` (the format and the fields, or `free text`). `--json` prints the same as a
`PromptInfo` object. Exit 2 for an unknown name, a missing file or a missing `--name` prompt; exit 1, with the diagnostics, when the file
has mistakes. Run it before you call a prompt you did not write, instead of reading the whole file.

## Checking with the registry

A flow names its steps as `registry.NAME`: names that the Python caller passes in a dictionary. Pass them to the checker so a typo is caught:
`skye check --registry planner,web_search flow.skye`. Without `--registry` those names are not checked.

## This skill

`skye skill install` copies this skill to `~/.claude/skills/skye/` (`--scope project` for `./.claude/skills/skye/`, `--dir DIR` for another
skills folder). After upgrading the package, run `skye skill status`: if it says "outdated", `skye skill install` brings the skill up to date
(a skill nobody edited is replaced without `--force`; a file edited by hand is kept unless you pass `--force`).

## Editors

`skye check --format json` prints `{"diagnostics": [{"file", "line", "column", "reason", "fix", "message"}]}` (lines and columns from 1; a mistake in an included file also has `via`;
exit 0 none, 1 some, 2 read error with nothing on stdout). `-` reads the text from stdin; `--stdin-filename` names it in the diagnostics.
`skye vscode install` gives VS Code highlighting and live diagnostics for `.skye` files; the extension runs `skye check`, so `skye` must be
on PATH or set the `skye.command` setting (for example `["uv", "run", "skye"]`). "Format Document" runs `skye fmt -`. Without an editor command, or with `--dir`, it copies the
extension to `~/.vscode/extensions/skyeai.skye-<version>/` (reload VS Code); an edited copy is kept unless you pass `--force`.

## Diagrams (`skye render`)

`skye render FILE` writes `FILE.mmd`, a Mermaid `flowchart` of the one flow or router in the file. `--stdout` prints it instead;
`--fence` wraps each diagram in a ```` ```mermaid ```` fence (all the flows and routers of the file, or the one `--name` picks) so it can be
pasted into Markdown, and without `--stdout` writes `FILE.mmd.md`; `-o OUT` chooses the file; `--direction TD|LR` (flows default to `TD`,
routers to `LR`). A file with several blocks needs `--name` or `--fence`; a prompt has nothing to draw (exit 2). When you document a flow
or a router in Markdown, run `skye render FILE --name NAME --stdout --fence` and paste the output, so the diagram matches the file. From
Python: `from skye.dsl import to_mermaid` and `to_mermaid(document.flow("name"))`.

