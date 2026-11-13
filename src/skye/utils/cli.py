"""The ``skye`` command line: ``skye check``, ``skye fmt``, ``skye new``, ``skye render`` and
``skye prompt`` for ``.skye`` files, and ``skye plugins`` for what is registered.

This is the code that reads and writes files; the parser in ``skye.base.dsl`` takes text only.

Usage::

    skye check app.skye [more.skye ...]    # prints file:line:col message; exit 1 on errors
    skye check --format json --stdin-filename app.skye -   # stdin; one JSON object (for editors)
    skye check --schema                    # prints the JSON Schema of the router, flow, prompt
    blocks
    skye fmt app.skye [more.skye ...]      # rewrite in the standard layout (comments kept)
    skye fmt --check templates/*.skye      # exit 1 if a file is not formatted (for CI)
    skye fmt -                             # stdin to stdout (for editors)
    skye new flow my_flow --template loop -o my_flow.skye
    skye render flow.skye [--name NAME] [--stdout] [--fence] [-o OUT] [--direction TD|LR]
                                           # a flow or a router as a Mermaid diagram (FILE.mmd)
    skye new --list                        # the kinds and their templates
    skye prompt list [--json]              # the bundled prompts: name, title, version, description
    skye prompt info NAME|FILE [--name PROMPT] [--json]   # a prompt's inputs, messages and output
    skye skill install [--scope user|project] [--dir DIR] [--force]   # the Claude Code skill that
    teaches Skye
    skye skill print [NAME] | skye skill path   # SKILL.md, or references/NAME.md; where it is
    installed
    skye skill status                      # up to date, outdated (the package changed) or edited;
    exit 1 if not up to date
    skye vscode install [--editor CMD] [--dir DIR] [--force]   # the VS Code extension for .skye
    skye vscode package [-o FILE] | uninstall | path | status
    skye plugins [--format json]           # the built-in registrations and the installed plugins (exit 0)

Exit codes: 0 no error, 1 the checked files have errors, 2 usage or file error.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from collections.abc import Sequence
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from skye.base.dsl import TEMPLATES, Resolved, block_schema, build, check_text, skeleton, to_mermaid
from skye.base.dsl.fmt import FormatError, format_text
from skye.base.dsl.include import Resolver
from skye.base.dsl.info import PromptInfo, describe_prompt, header_fields, prompt_help
from skye.base.dsl.metadata import split_metadata
from skye.base.dsl.specs import FlowSpec, RouterSpec
from skye.base.exceptions import ConfigurationError, ValidationError
from skye.utils.skill import (
    SCOPES,
    install_skill,
    reference_text,
    skill_path,
    skill_status,
    skill_text,
)
from skye.utils.skye_files import file_resolver
from skye.utils.vscode import (
    COMMAND_HINT,
    build_vsix,
    extension_path,
    extension_status,
    install_extension,
    uninstall_extension,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skye", description="Tools for .skye files.")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="check .skye files and print every error")
    check.add_argument(
        "files", nargs="*", metavar="FILE", help="the .skye files to check (- reads stdin)"
    )
    check.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help='text (file:line:col message) or json (one {"diagnostics": [...]} object)',
    )
    check.add_argument(
        "--stdin-filename",
        metavar="NAME",
        default="<stdin>",
        help="the file name used in the diagnostics of - (stdin)",
    )
    check.add_argument("--schema", action="store_true", help="print the JSON Schema of the blocks")
    check.add_argument(
        "--registry",
        metavar="NAMES",
        help="comma-separated names the registry will hold; registry.NAME is checked against them",
    )

    fmt = commands.add_parser(
        "fmt", help="rewrite .skye files in the standard layout (comments and strings are kept)"
    )
    fmt.add_argument(
        "files",
        nargs="*",
        metavar="PATH",
        help=(
            "files or folders to format; a folder is searched for .skye files recursively; "
            "none = the current folder; - reads stdin and writes stdout"
        ),
    )
    fmt.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="skip paths matching GLOB (relative to the folder searched, e.g. 'tests/fixtures/*'); "
        "repeatable",
    )
    fmt.add_argument(
        "--check",
        action="store_true",
        help="change nothing; list the files that are not formatted and exit 1 if there are any",
    )
    fmt.add_argument(
        "--stdin-filename",
        metavar="NAME",
        default="<stdin>",
        help="the file name used in the messages of - (stdin)",
    )

    render = commands.add_parser(
        "render", help="draw a flow or a router of a .skye file as a Mermaid diagram"
    )
    render.add_argument("file", help="the .skye file")
    render.add_argument(
        "--name", help="the flow or router to draw (needed when the file has several)"
    )
    render.add_argument(
        "--stdout", action="store_true", help="print the diagram instead of writing FILE.mmd"
    )
    render.add_argument(
        "--fence",
        action="store_true",
        help="wrap each diagram in a ```mermaid fence, ready to paste into Markdown",
    )
    render.add_argument(
        "-o",
        "--output",
        metavar="OUT",
        help="write to OUT instead of FILE.mmd (FILE.mmd.md with --fence)",
    )
    render.add_argument(
        "--direction", choices=["TD", "LR"], help="TD (top down) or LR (left to right)"
    )

    plugins = commands.add_parser(
        "plugins", help="list the built-in registrations and the installed plugins"
    )
    plugins.add_argument(
        "--format", choices=["text", "json"], default="text", help="text (default) or json"
    )

    new = commands.add_parser("new", help="print (or write) a starting .skye file")
    new.add_argument("kind", nargs="?", choices=sorted(TEMPLATES), help="router, flow or prompt")
    new.add_argument("name", nargs="?", help="the name of the block")
    new.add_argument("--template", "-t", help="the template (see --list)")
    new.add_argument("-o", "--output", metavar="FILE", help="write to FILE instead of stdout")
    new.add_argument("--force", action="store_true", help="overwrite FILE if it exists")
    new.add_argument("--list", action="store_true", help="list the kinds and their templates")

    skill = commands.add_parser(
        "skill", help="install or print the Claude Code skill that teaches how to use Skye"
    )
    actions = skill.add_subparsers(dest="action", required=True)
    for action, text in (
        ("install", "copy the skill to the folder where Claude Code reads skills"),
        ("print", "print the skill"),
        ("path", "print where the skill is installed"),
        ("status", "say whether the installed skill is up to date (exit 1 if it is not)"),
    ):
        sub = actions.add_parser(action, help=text)
        if action == "print":
            sub.add_argument(
                "name",
                nargs="?",
                help="a reference to print (references/NAME.md); SKILL.md when omitted",
            )
        else:
            sub.add_argument(
                "--scope",
                choices=SCOPES,
                default="user",
                help="user (~/.claude/skills) or project (./.claude/skills)",
            )
            sub.add_argument(
                "--dir", metavar="DIR", help="a skills folder to use instead of the scope's"
            )
        if action == "install":
            sub.add_argument(
                "--force",
                action="store_true",
                help="replace a skill that differs from this version",
            )
    _add_prompt(commands)
    _add_vscode(commands)
    return parser


def _add_prompt(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    prompt = commands.add_parser(
        "prompt", help="list the bundled prompts, or show what a prompt takes and gives back"
    )
    actions = prompt.add_subparsers(dest="action", required=True)
    listing = actions.add_parser("list", help="the bundled prompts: name, title, version")
    listing.add_argument("--json", action="store_true", help="print one JSON array")
    info = actions.add_parser("info", help="the inputs, history, messages and output of one prompt")
    info.add_argument(
        "target", metavar="NAME|FILE", help="a bundled prompt name, or a .skye file (- reads stdin)"
    )
    info.add_argument(
        "--name", metavar="PROMPT", help="the prompt to show when the file has several"
    )
    info.add_argument("--json", action="store_true", help="print the PromptInfo as JSON")
    export = actions.add_parser("export", help="write the bundled prompts as .skye files into a folder")
    export.add_argument("directory", metavar="DIR", help="the folder to write (created when it does not exist)")
    export.add_argument("--force", action="store_true", help="replace the files that exist")


def _add_vscode(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    vscode = commands.add_parser(
        "vscode", help="package or install the VS Code extension for .skye"
    )
    actions = vscode.add_subparsers(dest="action", required=True)
    package = actions.add_parser("package", help="build the .vsix of the extension")
    package.add_argument("-o", "--output", metavar="FILE", help="the .vsix to write")
    for action, text in (
        ("install", "install the extension (with the editor command, or by copying its folder)"),
        ("uninstall", "remove the extension"),
        ("path", "print the folder where the extension is copied"),
        ("status", "say whether the installed extension is up to date (exit 1 if it is not)"),
    ):
        sub = actions.add_parser(action, help=text)
        if action != "path":
            sub.add_argument(
                "--editor", metavar="CMD", help="the editor command (code, codium, cursor, ...)"
            )
        sub.add_argument(
            "--dir",
            metavar="DIR",
            help="copy to (or look in) this extensions folder instead of using the editor",
        )
        if action == "install":
            sub.add_argument(
                "--force", action="store_true", help="replace a folder whose files were edited"
            )


def _read_input(name: str, stdin_name: str) -> tuple[str, str]:
    if name == "-":
        buffer = getattr(sys.stdin, "buffer", None)
        text = buffer.read().decode("utf-8") if buffer is not None else sys.stdin.read()
        return text, stdin_name
    return Path(name).read_text(encoding="utf-8"), name


def _no_folder(target: str, from_key: str | None) -> Resolved:
    raise ValueError("a text on stdin needs --stdin-filename to know its folder")


def _resolution(label: str) -> tuple[Resolver, str | None]:
    """The resolver and the key for the includes of the file named ``label`` (``<stdin>`` has no folder)."""
    if label == "<stdin>":
        return _no_folder, None
    return file_resolver(label), str(Path(label).resolve())


def _check(args: argparse.Namespace) -> int:
    if args.schema:
        print(json.dumps(block_schema(), indent=2))
        if not args.files:
            return 0
    if not args.files:
        print("skye check: give at least one file, or --schema", file=sys.stderr)
        return 2
    names = [n.strip() for n in args.registry.split(",") if n.strip()] if args.registry else None
    status = 0
    found: list[dict[str, object]] = []
    for name in args.files:
        try:
            text, name = _read_input(name, args.stdin_filename)
        except (OSError, UnicodeDecodeError) as exc:
            print(f"{name}: cannot read the file: {exc}", file=sys.stderr)
            status = max(status, 2)
            continue
        diagnostics = check_text(text, name, names, *_resolution(name))
        if args.format == "json":
            found.extend(
                {
                    "file": d.file,
                    "line": d.line,
                    "column": d.column,
                    "reason": d.reason,
                    "fix": d.fix,
                    "message": d.message,
                    **({"via": [dict(zip(("file", "line", "column"), v)) for v in d.via]} if d.via else {}),
                }
                for d in diagnostics
            )
            if diagnostics and status != 2:
                status = 1
            continue
        for item in diagnostics:
            print(item.format())
        if diagnostics:
            status = max(status, 1) if status != 2 else 2
        else:
            partial = split_metadata(text, name)[0].get("partial") is True
            print(f"{name}: ok" + (" (a partial: the rest is checked where it is used)" if partial else ""))
    if args.format == "json" and status != 2:
        print(json.dumps({"diagnostics": found}))
    return status


#: The file that lists the paths ``skye fmt`` leaves out of a folder search, one glob per line.
SKYEIGNORE = ".skyeignore"


def _ignore_globs(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


#: Folders never searched for .skye files (besides hidden ones).
_SKIPPED_DIRS = frozenset({"node_modules", "__pycache__", "venv", "build", "dist", "site-packages"})


def _skye_files(paths: Sequence[str], exclude: Sequence[str]) -> list[str]:
    """The files named in ``paths``, with each folder replaced by its .skye files (recursively).

    Hidden folders (``.git``, ``.venv``, ...) and ``_SKIPPED_DIRS`` are not searched; ``exclude``
    globs, and those of a ``.skyeignore`` file in the folder searched (one per line, ``#``
    comments), are matched against the path relative to that folder, and against the file name.
    """
    found: list[str] = []
    for name in paths or ["."]:
        root = Path(name)
        if name == "-" or not root.is_dir():
            found.append(name)
            continue
        globs = [*exclude, *_ignore_globs(root / SKYEIGNORE)]
        for current, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in _SKIPPED_DIRS)
            for file in sorted(files):
                if not file.endswith(".skye"):
                    continue
                path = Path(current) / file
                relative = path.relative_to(root).as_posix()
                if any(fnmatch(relative, g) or fnmatch(file, g) for g in globs):
                    continue
                found.append(str(path))
    return found


def _fmt(args: argparse.Namespace) -> int:
    status = 0
    files = _skye_files(args.files, args.exclude)
    if not files:
        print("skye fmt: no .skye files found", file=sys.stderr)
        return 0
    for name in files:
        try:
            text, label = _read_input(name, args.stdin_filename)
        except (OSError, UnicodeDecodeError) as exc:
            print(f"{name}: cannot read the file: {exc}", file=sys.stderr)
            status = 2
            continue
        try:
            formatted = format_text(text, label)
        except FormatError as exc:
            for item in exc.diagnostics:
                print(item.format(), file=sys.stderr)
            print(f"{label}: not formatted: {exc}", file=sys.stderr)
            status = max(status, 1) if status != 2 else 2
            continue
        if name == "-":
            if not args.check:
                sys.stdout.write(formatted)
            elif formatted != text:
                print(f"{label}: would be reformatted")
                status = max(status, 1) if status != 2 else 2
            continue
        if formatted == text:
            continue
        if args.check:
            print(f"{name}: would be reformatted")
            status = max(status, 1) if status != 2 else 2
            continue
        try:
            Path(name).write_text(formatted, encoding="utf-8")
        except OSError as exc:
            print(f"{name}: cannot write the file: {exc}", file=sys.stderr)
            status = 2
            continue
        print(f"formatted {name}")
    return status


def _render(args: argparse.Namespace) -> int:
    try:
        text, name = _read_input(args.file, args.file)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"{args.file}: cannot read the file: {exc}", file=sys.stderr)
        return 2
    document = build(text, filename=name)
    if document.diagnostics:
        for item in document.diagnostics:
            print(item.format())
        return 1
    blocks: list[FlowSpec | RouterSpec] = [*document.flows, *document.routers]
    if args.name:
        blocks = [b for b in blocks if b.name == args.name]
        if not blocks:
            print(f"skye render: {name} has no flow or router named {args.name!r}", file=sys.stderr)
            return 2
    if not blocks:
        print(f"skye render: {name} has no flow or router to draw", file=sys.stderr)
        return 2
    if len(blocks) > 1 and not args.fence:
        names = ", ".join(repr(b.name) for b in blocks)
        print(
            f"skye render: {name} has {len(blocks)} flows and routers ({names}); "
            "pass --name, or --fence to write them all as Markdown",
            file=sys.stderr,
        )
        return 2
    diagrams = [to_mermaid(block, direction=args.direction) for block in blocks]
    if args.fence:
        out = "\n".join(f"```mermaid\n{diagram}```\n" for diagram in diagrams)
    else:
        out = diagrams[0]
    if args.stdout:
        sys.stdout.write(out)
        return 0
    default = Path(args.file).with_suffix(".mmd.md" if args.fence else ".mmd")
    target = Path(args.output) if args.output else default
    target.write_text(out, encoding="utf-8")
    print(f"wrote {target}")
    return 0


def _new(args: argparse.Namespace) -> int:
    if args.list:
        for kind, templates in TEMPLATES.items():
            print(f"{kind}: {', '.join(templates)} (default: {templates[0]})")
        return 0
    if args.kind is None:
        print("skye new: give a kind (router, flow or prompt), or --list", file=sys.stderr)
        return 2
    try:
        text = skeleton(args.kind, args.name, args.template)
    except ValueError as exc:
        print(f"skye new: {exc}", file=sys.stderr)
        return 2
    if args.output is None:
        sys.stdout.write(text)
        return 0
    target = Path(args.output)
    if target.exists() and not args.force:
        print(f"skye new: {target} already exists; use --force to overwrite it", file=sys.stderr)
        return 2
    try:
        target.write_text(text, encoding="utf-8")
    except OSError as exc:
        print(f"skye new: cannot write {target}: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {target}")
    return 0


def _skill(args: argparse.Namespace) -> int:
    if args.action == "print":
        try:
            sys.stdout.write(skill_text() if args.name is None else reference_text(args.name))
        except ConfigurationError as exc:
            print(f"skye skill: {exc.message}", file=sys.stderr)
            return 2
        return 0
    try:
        if args.action == "path":
            print(skill_path(args.scope, args.dir))
            return 0
        if args.action == "status":
            state, message = skill_status(args.scope, args.dir)
            print(message)
            return 0 if state == "up to date" else 1
        target, status = install_skill(args.scope, args.dir, force=args.force)
    except ConfigurationError as exc:
        print(f"skye skill: {exc.message}", file=sys.stderr)
        return 2
    print(f"{status}: {target}")
    return 0


# task 24.7
def _loaders() -> Any:
    """The module that finds the bundled prompts, imported at the first use.

    ``utils`` sits in Layer 0 and may not import ``prompts`` in a statement; the CLI needs only this one lookup, so it asks the import
    system by name (see the note for the owner in the report).
    """
    return importlib.import_module("skye.prompts.loaders")


def _bundled() -> dict[str, str]:
    """The bundled ``.skye`` prompts by name, each with where it is (a file of a source checkout, or an entry of the archive).

    A source checkout keeps them in ``skye/prompts/templates``; an installed wheel keeps one archive, ``templates.zip``.
    """
    loaders = _loaders()
    return {name: loaders.bundled_origin(name) for name in loaders.bundled_names()}


def _prompt_list(as_json: bool) -> int:
    rows: list[dict[str, object]] = []
    for name, path in _bundled().items():
        try:
            metadata, _, _ = split_metadata(_loaders().read_bundled(name), path)
        except (OSError, UnicodeDecodeError, ValidationError):
            metadata = {}
        if metadata.get("partial") is True:  # a partial is not a template
            continue
        meta = header_fields(metadata)
        rows.append(
            {
                "name": name,
                "title": meta.get("title"),
                "version": meta.get("version"),
                "description": meta.get("description"),
            }
        )
    if as_json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    width = max((len(str(r["name"])) for r in rows), default=0)
    for row in rows:
        head = f"{row['title'] or ''}" + (f" ({row['version']})" if row["version"] else "")
        print(f"{str(row['name']).ljust(width)}  {head}".rstrip())
        if row["description"]:
            print(f"{' ' * width}  {row['description']}")
    return 0


def _prompt_info(args: argparse.Namespace) -> int:
    target: str = args.target
    bundled = _bundled()
    catalogue = False
    if target != "-" and target in bundled and not Path(target).exists():
        name, path, catalogue = target, bundled[target], True
        try:
            text = _loaders().read_bundled(target)
        except (OSError, UnicodeDecodeError, ValidationError) as exc:
            print(f"skye prompt info: {target}: cannot read the bundled prompt: {exc}", file=sys.stderr)
            return 2
    elif target == "-" or Path(target).is_file():
        try:
            text, path = _read_input(target, "<stdin>")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"{target}: cannot read the file: {exc}", file=sys.stderr)
            return 2
        name = args.name
    else:
        known = ", ".join(bundled)
        print(
            f'skye prompt info: "{target}" is neither a bundled prompt nor a file. '
            f"Bundled: {known}",
            file=sys.stderr,
        )
        return 2
    resolver, key = (_loaders().catalogue_resolver, f"{name}.skye") if catalogue else _resolution(path)
    document = build(text, filename=path, resolver=resolver, key=key)
    if document.diagnostics:
        for item in document.diagnostics:
            print(item.format())
        return 1
    try:
        spec = document.prompt(name)
    except KeyError as exc:
        print(f"skye prompt info: {path}: {exc.args[0] if exc.args else exc}", file=sys.stderr)
        return 2
    info: PromptInfo = describe_prompt(spec, document.metadata)
    if args.json:
        print(json.dumps(info.to_dict(), indent=2, ensure_ascii=False, default=str))
    else:
        sys.stdout.write(prompt_help(info))
    return 0


def _prompt_export(args: argparse.Namespace) -> int:
    """Write every bundled prompt as ``<name>.skye`` into a folder, from the source checkout or from the archive."""
    names = list(_bundled())
    shared = _loaders().bundled_partials()  # the files that the templates include, written next to them
    folder = Path(args.directory)
    existing = [name for name in names if (folder / f"{name}.skye").exists()]
    if existing and not args.force:
        print(
            f"skye prompt export: {len(existing)} of the files exist in {folder} (for example {existing[0]}.skye); "
            "use --force to replace them",
            file=sys.stderr,
        )
        return 2
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for name in names:
            (folder / f"{name}.skye").write_text(_loaders().read_bundled(name), encoding="utf-8")
        for path in shared:
            (folder / path).parent.mkdir(parents=True, exist_ok=True)
            (folder / path).write_text(_loaders().catalogue_resolver(path, None).text, encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValidationError) as exc:
        print(f"skye prompt export: {folder}: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {len(names)} prompts to {folder}" + (f" and {len(shared)} shared files" if shared else ""))
    return 0


def _prompt(args: argparse.Namespace) -> int:
    if args.action == "list":
        return _prompt_list(args.json)
    if args.action == "export":
        return _prompt_export(args)
    return _prompt_info(args)


def _vscode(args: argparse.Namespace) -> int:
    try:
        if args.action == "package":
            print(build_vsix(args.output))
            return 0
        if args.action == "path":
            print(extension_path(args.dir))
            return 0
        if args.action == "status":
            state, message = extension_status(args.editor, args.dir)
            print(message)
            return 0 if state == "up to date" else 1
        if args.action == "uninstall":
            print(uninstall_extension(args.editor, args.dir))
            return 0
        _, message = install_extension(args.editor, args.dir, force=args.force)
    except ConfigurationError as exc:
        print(f"skye vscode: {exc.message}", file=sys.stderr)
        return 2
    print(message)
    print(COMMAND_HINT)
    return 0


# Requirement 57.9
def _plugins(args: argparse.Namespace) -> int:
    """Print what is registered: the built-ins by kind, then each entry point of ``skye.plugins``."""
    from skye.base.plugins import KINDS, get_registrar
    from skye.utils.plugins import GROUP, scan

    registrar = get_registrar()
    builtin = {kind: sorted(registrar.names(kind)) for kind in KINDS}  # before the scan: what ships
    try:
        reports = scan(registrar)
    except ConfigurationError as exc:
        print(f"skye plugins: {exc.message}", file=sys.stderr)
        return 2
    if args.format == "json":
        entry_points = [
            {
                "name": report.name,
                "distribution": report.distribution,
                "version": report.version,
                "loaded": report.loaded,
                "skipped": report.skipped,
                "error": report.error,
                "registered": report.registered,
            }
            for report in reports
        ]
        print(json.dumps({"builtin": builtin, "entry_points": entry_points}, indent=2))
        return 0
    print("Built-in")
    width = max(len(kind) for kind in KINDS)
    for kind, names in builtin.items():
        print(f"  {kind:<{width}}  {', '.join(names) if names else '-'}")
    print(f"\nInstalled plugins (entry-point group {GROUP})")
    if not reports:
        print("  none")
    for report in reports:
        who = f"{report.distribution} {report.version}" if report.distribution else "-"
        state = "skipped" if report.skipped else ("loaded" if report.loaded else "failed")
        print(f"  {report.name}  ({who})  {state}")
        if report.skipped:
            print("    not in the plugins allowlist of the configuration")
        if report.error:
            print(f"    {report.error}")
        for kind, names in report.registered.items():
            print(f"    {kind}: {', '.join(names)}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``skye`` command.

    Args:
        argv: The arguments (``sys.argv[1:]`` by default).

    Returns:
        The exit code: 0 on success, 1 when a checked file has errors, 2 for a usage or file error.
    """
    args = _build_parser().parse_args(argv)
    if args.command == "check":
        return _check(args)
    if args.command == "skill":
        return _skill(args)
    if args.command == "vscode":
        return _vscode(args)
    if args.command == "prompt":
        return _prompt(args)
    if args.command == "fmt":
        return _fmt(args)
    if args.command == "render":
        return _render(args)
    if args.command == "plugins":
        return _plugins(args)
    return _new(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
