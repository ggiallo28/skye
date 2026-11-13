---
title: "CLI"
status: current
---

# CLI

This page lists every `skye` subcommand with its synopsis, options, exit codes and an example, so you can use the command line in a
terminal, in CI or from an editor.

The `skye` command is installed with the package (`pip install skyeai`); in a uv project run it as `uv run skye`. It works on `.skye`
files and reads no network.

| Command | What it does |
|---|---|
| [`skye check`](#skye-check) | check `.skye` files and print every error |
| [`skye fmt`](#skye-fmt) | rewrite `.skye` files in the standard layout, keeping comments and strings |
| [`skye render`](#skye-render) | draw a flow or a router as a Mermaid diagram |
| [`skye new`](#skye-new) | print or write a starting `.skye` file |
| [`skye prompt`](#skye-prompt) | list the bundled prompts, show what a prompt takes and gives back, or copy them to a folder |
| [`skye skill`](#skye-skill) | install or print the Claude Code skill that teaches Skye |
| [`skye vscode`](#skye-vscode) | build or install the VS Code extension for `.skye` |
| [`skye plugins`](#skye-plugins) | list the built-in registrations and the installed plugins |

## Exit codes

Every subcommand uses the same three codes:

| Code | Meaning |
|---|---|
| `0` | success: no error, or the action was done |
| `1` | the files have errors (`check`, `render`, `prompt info`), are not formatted (`fmt --check`), or the installed copy is not up to date (`skill status`, `vscode status`) |
| `2` | a usage or file error: a wrong option, a file that cannot be read or written, a missing name |

Messages about usage and files go to standard error; results go to standard output.

## skye check

```text
skye check [--format {text,json}] [--stdin-filename NAME] [--schema] [--registry NAMES] [FILE ...]
```

Parses and checks each file and prints every error it finds, one per line, as `file:line:column message`. A file with no error
prints `FILE: ok`.

| Option | Meaning |
|---|---|
| `FILE ...` | the `.skye` files to check; `-` reads standard input |
| `--format text` | `file:line:col message` lines (the default) |
| `--format json` | one object for the whole run: `{"diagnostics": [{"file", "line", "column", "reason", "fix", "message"}]}`; a mistake in a file that an `include` brought also has `"via"`, the use sites `[{"file", "line", "column"}]` |
| `--stdin-filename NAME` | the file name shown in the diagnostics of `-` (default `<stdin>`) |
| `--schema` | print the JSON Schema of the `router`, `flow` and `prompt` blocks; with no file, exit 0 after printing |
| `--registry NAMES` | comma-separated names your registry will hold; every `registry.NAME` is checked against them |

A file that takes parts of other files (`include`, `from ... import`, see [Include and partial files](skye-language.md#include-and-partial-files))
is checked with its includes read from the folder of the file, and standard input needs `--stdin-filename` to know that folder. A
partial file (`partial = true`) is checked for syntax only: `FILE: ok (a partial: the rest is checked where it is used)`. A mistake in an
`override` is reported at the `override` line of your file.

Exit codes: `0` no error, `1` at least one error, `2` no file given or a file cannot be read.

```bash
$ skye check router.skye
router.skye:3:3 unknown field "stratgy" in router "x". Did you mean "strategy"?
$ skye check --registry planner,web_search flow.skye
$ skye check --format json --stdin-filename app.skye - < app.skye
```

## skye fmt

```text
skye fmt [--exclude GLOB] [--check] [--stdin-filename NAME] [PATH ...]
```

Rewrites each file in the standard layout: two spaces per open bracket, no trailing spaces, at most one blank line in a row. It works
on the text, so comments, `"""` strings and the front matter stay. It refuses a file with errors and a result that would build a
different model. Running it twice changes nothing. It keeps the `include`, `from ... import`, `use` and `override` lines where they are and formats
partial files too; it never expands them.

| Option | Meaning |
|---|---|
| `PATH ...` | files or folders; a folder is searched for `.skye` files recursively; none means the current folder; `-` reads standard input and writes standard output |
| `--exclude GLOB` | skip paths matching `GLOB`, relative to the folder searched (for example `'tests/fixtures/*'`); repeatable |
| `--check` | change nothing; list the files that are not formatted |
| `--stdin-filename NAME` | the file name used in the messages of `-` (default `<stdin>`) |

A folder search skips hidden folders, `node_modules`, `__pycache__`, `venv`, `build`, `dist` and `site-packages`. A `.skyeignore`
file in the folder searched adds globs, one per line (`#` starts a comment).

Exit codes: `0` done (also when no `.skye` file is found), `1` a file has errors or, with `--check`, is not formatted, `2` a file
cannot be read or written.

```bash
skye fmt                                  # every .skye file under the current folder
skye fmt --check --exclude 'tests/*' .    # for CI: list what is not formatted, exit 1 if any
skye fmt - < app.skye                     # for editors: standard input to standard output
```

## skye render

```text
skye render [--name NAME] [--stdout] [--fence] [-o OUT] [--direction {TD,LR}] FILE
```

Draws a flow or a router of a `.skye` file as a Mermaid `flowchart` and writes it to `FILE.mmd`. A step is a box with what it runs,
a `choice` a diamond whose edges carry the `when` text, a `parallel` block a subgraph; a router shows each route with its strategy,
targets and fallbacks.

| Option | Meaning |
|---|---|
| `FILE` | the `.skye` file |
| `--name NAME` | the flow or router to draw; needed when the file has several (unless `--fence`) |
| `--stdout` | print the diagram instead of writing a file |
| `--fence` | wrap each diagram in a `mermaid` code fence, ready for Markdown; with several blocks, draws them all; writes `FILE.mmd.md` |
| `-o OUT`, `--output OUT` | write to `OUT` instead of `FILE.mmd` |
| `--direction TD` or `LR` | top down or left to right; the default is `TD` for a flow and `LR` for a router |

Exit codes: `0` written, `1` the file has errors (they are printed), `2` the file cannot be read, has no flow or router, has no block
named `NAME`, or has several and neither `--name` nor `--fence` was given.

```bash
skye render app.skye --name triage --stdout --fence
```

The same function is public in Python as `skye.dsl.to_mermaid`.

## skye new

```text
skye new [--template TEMPLATE] [-o FILE] [--force] [--list] [{flow,prompt,router}] [name]
```

Prints a starting file for a block. The text passes `skye check`, starts with front matter (`title` is the block name,
`version = "0.1.0"`), and marks the lines to edit with `CHANGE ME`.

| Option | Meaning |
|---|---|
| `flow`, `prompt`, `router` | the kind of block |
| `name` | the name of the block |
| `-t TEMPLATE`, `--template TEMPLATE` | the template; `router`: `shorthand` (default), `full`; `flow`: `sequence` (default), `branch`, `parallel`, `loop`, `full`; `prompt`: `basic` (default), `chat` |
| `-o FILE`, `--output FILE` | write to `FILE` instead of standard output |
| `--force` | overwrite `FILE` if it exists |
| `--list` | list the kinds and their templates |

Exit codes: `0` printed or written, `2` no kind given, an unknown template, `FILE` exists without `--force`, or `FILE` cannot be
written.

```bash
skye new --list
skye new router main
skye new flow my_flow --template loop -o my_flow.skye
```

## skye prompt

```text
skye prompt list [--json]
skye prompt info [--name PROMPT] [--json] NAME|FILE
skye prompt export [--force] DIR
```

`list` prints the bundled prompts: name, title, version and description (a partial file, `partial = true`, is not a prompt and is not listed). `info` describes one prompt: its inputs with their types,
defaults and descriptions, the history placeholder, the messages and the output.

| Option | Meaning |
|---|---|
| `list --json` | print one JSON array |
| `info NAME` or `info FILE` | a bundled prompt name, or a `.skye` file; `-` reads standard input |
| `info --name PROMPT` | the prompt to show when the file has several |
| `info --json` | print the description as JSON |

Exit codes: `0` printed, `1` the file has errors (they are printed), `2` the name is neither a bundled prompt nor a file, the file
cannot be read, or it has no prompt of that name.

```bash
skye prompt list
skye prompt info extraction_structured
skye prompt info prompts.skye --name summarize --json
skye prompt export my-prompts
```

`export` writes every bundled prompt as a `.skye` file into `DIR`, creating it, and the shared files they include into `DIR/common/`, so you can copy one and edit it. It refuses to replace a file that is already there (exit `2`, nothing is written) unless you pass `--force`. An installed package keeps the prompts in one `templates.zip` without comments, so a prompt exported from it has no comments; a source checkout exports the files as they are. `list` and `info` work the same in both cases.

From Python, `skye.prompts.describe_prompt` and `skye.prompts.prompt_help` give the same description.

## skye skill

```text
skye skill install [--scope {user,project}] [--dir DIR] [--force]
skye skill print [NAME]
skye skill path [--scope {user,project}] [--dir DIR]
skye skill status [--scope {user,project}] [--dir DIR]
```

Manages the Claude Code skill shipped inside the package. It teaches a model the `skye` command, the `.skye` language and the rules
of the library: a short `SKILL.md` and one file per topic in `references/`.

| Option | Meaning |
|---|---|
| `install` | copy the skill to the folder where Claude Code reads skills |
| `print [NAME]` | print `SKILL.md`, or `references/NAME.md` |
| `path` | print where the skill is installed |
| `status` | say whether the installed skill is up to date, outdated or edited |
| `--scope user` | `~/.claude/skills` (the default) |
| `--scope project` | `./.claude/skills` |
| `--dir DIR` | a skills folder to use instead of the scope's |
| `--force` | with `install`, replace files that differ from this version |

`install` records what it wrote in `.skye-skill.json`: an unedited copy is replaced on the next install, a file you edited is kept
unless you pass `--force`.

Exit codes: `0` done, `1` `status` found the skill not up to date, `2` an unknown reference or a folder that cannot be written.

```bash
skye skill install --scope project
skye skill status
```

## skye plugins

```text
skye plugins [--format {text,json}]
```

Lists what is registered, for each kind of integration (the kinds of the registrar: `provider`, `backend`, `agent`, `toolkit` and the
others), and the plugins installed in the entry-point group `skye.plugins`. The command runs the scan of the group, so an installed
plugin is imported as it is when a lookup misses, and the list shows what each one registered.

For each entry point it prints the name, the distribution and its version, and one state: `loaded`, `failed` (with the error) or
`skipped` (the `plugins` key of the configuration file did not list it, so it was not imported).

| Option | Meaning |
|---|---|
| `--format text` | a readable list (the default) |
| `--format json` | one JSON object: `builtin` (kind to the sorted names) and `entry_points` (a list of objects with `name`, `distribution`, `version`, `loaded`, `skipped`, `error`, `registered`) |

Exit codes: `0` printed, also when an entry point failed (the failure is in the output), `2` the configuration file cannot be read
or its `plugins` key is not a list of names, or a wrong option.

```bash
skye plugins
skye plugins --format json
```

## skye vscode

```text
skye vscode package [-o FILE]
skye vscode install [--editor CMD] [--dir DIR] [--force]
skye vscode uninstall [--editor CMD] [--dir DIR]
skye vscode path [--dir DIR]
skye vscode status [--editor CMD] [--dir DIR]
```

Builds or installs the VS Code extension for `.skye` files, which ships inside the package and needs no Node.js.

| Option | Meaning |
|---|---|
| `package` | build the `.vsix` of the extension |
| `install` | install with the editor command (`code`, `code-insiders`, `codium` or `cursor`, the first found), or copy the folder when none is found |
| `uninstall` | remove the extension |
| `path` | print the folder where a copied install goes |
| `status` | say whether the installed extension is up to date |
| `-o FILE`, `--output FILE` | with `package`, the `.vsix` to write |
| `--editor CMD` | the editor command to use |
| `--dir DIR` | copy to, or look in, this extensions folder instead of using the editor |
| `--force` | with `install`, replace a folder whose files were edited |

Exit codes: `0` done, `1` `status` found the extension not up to date, `2` the editor command failed or a folder cannot be written.

```bash
skye vscode install
skye vscode install --editor cursor
skye vscode status
```

[Editor support](editor.md) explains the extension and its settings.

## See also

- [.skye language](skye-language.md): what `skye check` checks.
- [Editor support](editor.md): the VS Code extension.
- [skye.dsl](api/dsl.md): `check_text`, `format_text` and `to_mermaid` in Python.
- [The .skye language](../concepts/skye-language.md): the overview.
