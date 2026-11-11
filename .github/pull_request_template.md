## What and why

<!-- One or two sentences. Link the issue: "Closes #123". -->

## Checklist

- [ ] `uv run pytest`, `make check` and `make budget-fast` pass
- [ ] No new dependency, or the reason and the budget change are explained below (see CONTRIBUTING, "Dependencies and size")
- [ ] Code and text are mine, or come from a source whose licence allows it and is credited
- [ ] The spec in `.kiro/specs/` is updated if this adds or changes a feature
- [ ] The Claude skill in `src/skye/utils/claude_skill/skye/` is updated if this touches the CLI, the `.skye` language or the router
- [ ] A line is added under "Unreleased" in `CHANGELOG.md` (once the file exists)
