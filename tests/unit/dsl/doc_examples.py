"""Fences of ``skye`` examples in the docs and in the skill, and the files of a multi-file example.

A fence ``skye`` is one file and is checked alone. A fence ``skye title="lib/memory.skye"`` is one
file of a set: all the titled fences of one page
form the files of an example (the title is the path), each one is checked with the others as the
files its ``include`` and ``from`` lines can reach.
"""

from __future__ import annotations

import re

from skye.base.dsl import Resolved

FENCE = re.compile(r'^```skye(?: title="([^"]+)")?\n(.*?)^```', re.DOTALL | re.MULTILINE)


def split(text: str) -> tuple[list[str], dict[str, str]]:
    """The plain ``skye`` blocks of a page and the titled ones by path."""
    plain, titled = [], {}
    for title, body in FENCE.findall(text):
        if title:
            titled[title] = body
        else:
            plain.append(body)
    return plain, titled


def resolver(files: dict[str, str]):
    """A resolver over the titled blocks of a page: a target is the title of one of them."""

    def resolve(target: str, from_key: str | None) -> Resolved:
        if target not in files:
            raise FileNotFoundError(f"no file {target} in this example; it has: {', '.join(files)}")
        return Resolved(text=files[target], name=target, key=target)

    return resolve
