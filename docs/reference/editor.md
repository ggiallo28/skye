---
title: "Editor support"
status: current
---

# Editor support

This page shows you how to get highlighting, live diagnostics and formatting for `.skye` files in your editor.

The package ships a VS Code extension for `.skye` files: syntax highlighting, comments and brackets, live diagnostics from
`skye check`, and "Format Document" through `skye fmt -` (comments kept; a file with mistakes is left alone). It needs no
marketplace and no Node.js: the `skye` command builds and installs it.

## Install

```bash
skye vscode install                     # with code, code-insiders, codium or cursor (the first found)
skye vscode install --editor cursor     # with a given editor command
skye vscode install --dir DIR [--force] # copy the unpacked extension to DIR/skyeai.skye-<version>/
skye vscode status                      # up to date, outdated, edited or not installed (exit 1 if not up to date)
skye vscode uninstall                   # remove it
skye vscode package [-o FILE]           # only build skye-<version>.vsix (Extensions view > Install from VSIX...)
skye vscode path [--dir DIR]            # the folder a copied install uses
```

With an editor command, `install` builds the `.vsix` in a temporary folder and runs `<editor> --install-extension FILE --force`.
When no editor command is on PATH, or with `--dir`, it copies the extension to `~/.vscode/extensions/skyeai.skye-<version>/` (or to
`DIR`) and records the version and a hash of each file in `.skye-vscode.json`, like `skye skill install`: an unedited copy is
replaced on the next install, a file you edited is kept unless you pass `--force`. Reload VS Code after a copied install.

The extension carries the version of the installed `skyeai` package (`0.1.0.dev3` becomes `0.1.0`), so after upgrading the
package run `skye vscode status` and, if it says "outdated", `skye vscode install`.

## The `skye` command

The extension runs `skye check`, so `skye` must be on PATH, or set the `skye.command` setting to the command as a list, for
example `["uv", "run", "skye"]` in a uv project. `skye.run` chooses when to check (`onType` or `onSave`) and `skye.registry`
passes `--registry` names.

## `skye check` for editors

```bash
skye check --format json --stdin-filename app.skye -
```

`-` reads the text from standard input (the unsaved buffer); `--stdin-filename` is the name shown in the diagnostics
(`<stdin>` by default). `--format json` prints one object for the whole run:

```json
{"diagnostics": [{"file": "app.skye", "line": 2, "column": 8, "reason": "...", "fix": "...", "message": "..."}]}
```

Lines and columns count from 1; `message` is the reason followed by the fix. The exit code is 0 with no diagnostic, 1 with some,
and 2 for a usage or read error (the message goes to standard error and nothing is printed on standard output). Any other
editor can use the same command.

A mistake in a file that an `include` brought has one more key, `"via"`: the use sites in the files above it, `[{"file", "line", "column"}]`.
The extension shows such a mistake at the first use site in the open file, with the message prefixed by `in <file>:<line>:<column>:`.

## See also

- [.skye language](skye-language.md): the language itself.
- [CLI reference](cli.md#skye-vscode): every option of `skye vscode` and `skye check`.
- [The .skye language](../concepts/skye-language.md): the overview.
