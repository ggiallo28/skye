"""The parser of the ``.skye`` language: text in, syntax tree out.

Grammar (see ``docs/reference/skye-language.md`` for the full page)::

    file      = block*
    block     = KIND [LABEL] "{" (attribute | block)* "}"
    attribute = NAME "=" value
    field     = NAME "=" value [STRING]     (inside an ``output`` block: the string describes it)

The parser reports every mistake it can find: after a mistake it skips to the end of the line
(or of the block) and goes on.
"""

from __future__ import annotations

from skye.base.dsl.errors import (
    DEFAULT_FILENAME,
    MAX_DEPTH,
    TOO_DEEP_FIX,
    Diagnostic,
    SkyeSyntaxError,
    too_deep_reason,
)
from skye.base.dsl.lexer import (
    EOF,
    IDENT,
    NEWLINE,
    NUMBER,
    OP,
    PUNCT,
    STRING,
    Token,
    tokenize,
)
from skye.base.dsl.metadata import split_metadata
from skye.base.dsl.tree import (
    Attribute,
    Block,
    Bool,
    Expr,
    ListNode,
    MapEntry,
    MapNode,
    Name,
    Num,
    Str,
    Tree,
    TypeCall,
    Value,
)

#: The words that declare a type in ``context`` and ``variables``.
TYPE_NAMES = frozenset({"string", "number", "bool", "list", "map"})

_OPENERS = {"(": ")", "[": "]", "{": "}"}


class _AbortError(Exception):
    """A mistake was recorded; the caller skips to the next item."""


class _TooDeepError(Exception):
    """The nesting passed ``MAX_DEPTH``: the diagnostic is recorded and the parser stops."""


class _Parser:
    def __init__(self, text: str, filename: str) -> None:
        # The front matter is read first and replaced by empty lines, so line numbers stay true.
        self.metadata, self.text, header_errors = split_metadata(text, filename)
        self.filename = filename
        self.depth = 0
        # > 0 inside an ``output`` block or the ``variables`` map of a prompt: a value may be
        # followed by a string, its description.
        self.described = 0
        # True from the ``variables`` of a prompt to the first map: there ``use name`` is an entry.
        self.use_map = False
        # True once the file holds an ``include``, a ``from ... import`` or a ``use``.
        self.has_include = False
        # The kinds of the blocks being parsed, innermost last.
        self.kinds: list[str] = []
        self.tokens, self.errors = tokenize(self.text, filename)
        self.errors[:0] = header_errors
        self.pos = 0

    # -- token helpers -------------------------------------------------------------------------
    def peek(self, offset: int = 0) -> Token:
        index = min(self.pos + offset, len(self.tokens) - 1)
        return self.tokens[index]

    def enter(self, tok: Token) -> None:
        """Open one level of nesting; past ``MAX_DEPTH`` record one diagnostic and stop."""
        self.depth += 1
        if self.depth > MAX_DEPTH:
            self.errors.append(
                Diagnostic(
                    file=self.filename,
                    line=tok.line,
                    column=tok.column,
                    reason=too_deep_reason(),
                    fix=TOO_DEEP_FIX,
                )
            )
            raise _TooDeepError

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind != EOF:
            self.pos += 1
        return tok

    def is_punct(self, char: str, offset: int = 0) -> bool:
        tok = self.peek(offset)
        return tok.kind == PUNCT and tok.text == char

    def skip_newlines(self) -> None:
        while self.peek().kind == NEWLINE:
            self.pos += 1

    def fail(self, tok: Token, reason: str, fix: str = "") -> _AbortError:
        self.errors.append(
            Diagnostic(file=self.filename, line=tok.line, column=tok.column, reason=reason, fix=fix)
        )
        return _AbortError()

    def describe(self, tok: Token) -> str:
        if tok.kind == EOF:
            return "the end of the file"
        if tok.kind == NEWLINE:
            return "the end of the line"
        return f'"{tok.text}"'

    def sync(self) -> None:
        """Skip to the end of the current item: a newline or comma at depth 0, or the ``}`` that
        closes the block.
        """
        depth = 0
        while True:
            tok = self.peek()
            if tok.kind == EOF:
                return
            if tok.kind == PUNCT and tok.text in "{[(":
                depth += 1
            elif tok.kind == PUNCT and tok.text in "}])":
                if depth == 0:
                    return
                depth -= 1
            elif depth == 0 and (tok.kind == NEWLINE or (tok.kind == PUNCT and tok.text == ",")):
                return
            self.pos += 1

    # -- document ------------------------------------------------------------------------------
    def parse(self) -> Tree:
        tree = Tree(filename=self.filename, metadata=self.metadata)
        try:
            self.parse_blocks(tree)
        except _TooDeepError:
            pass
        tree.has_include = self.has_include
        return tree

    def parse_blocks(self, tree: Tree) -> None:
        while True:
            self.skip_separators()
            tok = self.peek()
            if tok.kind == EOF:
                break
            try:
                if tok.kind != IDENT:
                    raise self.fail(
                        tok,
                        f"expected a block such as flow, router or prompt, found "
                        f"{self.describe(tok)}",
                    )
                item = self.parse_item()
                if not isinstance(item, Block):
                    raise self.fail(
                        tok,
                        f'"{tok.text}" is an attribute, and a file holds blocks',
                        'Write a block such as: flow "name" { ... }',
                    )
                tree.blocks.append(item)
                self.end_of_item(top=True)
            except _AbortError:
                self.sync()
                if self.peek().kind == PUNCT:  # a stray closer at the top level
                    self.advance()

    def skip_separators(self) -> None:
        while self.peek().kind == NEWLINE or self.is_punct(","):
            self.pos += 1

    def end_of_item(self, *, top: bool = False) -> None:
        tok = self.peek()
        if tok.kind in (NEWLINE, EOF) or (tok.kind == PUNCT and tok.text == ","):
            return
        if not top and tok.kind == PUNCT and tok.text == "}":
            return
        raise self.fail(
            tok,
            f"unexpected {self.describe(tok)} after the end of the item",
            "Put the next item on a new line or separate it with a comma.",
        )

    # -- items ---------------------------------------------------------------------------------
    def parse_item(self) -> Attribute | Block:
        head = self.advance()
        word = head.text
        nxt = self.peek()
        if word in ("include", "from") and nxt.kind == STRING and not self.kinds:
            return self.parse_include(head)
        if word == "override" and nxt.kind == IDENT and nxt.text == "when":
            self.has_include = True
            block = self.parse_item()  # the ``when`` block; the word marks it
            assert isinstance(block, Block)
            block.override, block.line, block.column = True, head.line, head.column
            return block
        if (
            word == "set"
            and nxt.kind == IDENT
            and self.peek(1).kind == PUNCT
            and self.peek(1).text == "="
        ):
            field_tok = self.advance()
            self.advance()  # =
            value = self.parse_value()
            return Attribute(
                line=head.line,
                column=head.column,
                name=field_tok.text,
                value=value,
                keyword="set",
                name_line=field_tok.line,
                name_column=field_tok.column,
            )
        if word == "emit" and nxt.kind == STRING:
            value = self.parse_value()
            return Attribute(
                line=head.line,
                column=head.column,
                name="emit",
                value=value,
                keyword="emit",
                name_line=head.line,
                name_column=head.column,
            )
        if word == "when":
            cond = self.parse_head()
            block = Block(line=head.line, column=head.column, kind="when", head=cond)
            self.parse_braces(block)
            return block
        if word == "each":
            var = self.peek()
            if var.kind != IDENT:
                raise self.fail(var, "expected a loop variable: each item in items { ... }")
            self.advance()
            kw = self.peek()
            if kw.kind != IDENT or kw.text != "in":
                raise self.fail(
                    kw, 'expected "in" after the loop variable', "Write: each item in items { ... }"
                )
            self.advance()
            seq = self.parse_head()
            block = Block(line=head.line, column=head.column, kind="each", var=var.text, head=seq)
            self.parse_braces(block)
            return block
        if self.is_punct("="):
            self.advance()
            # ``variables = { task = string "What the agent must achieve" }`` in a prompt
            described = word == "variables" and self.kinds[-1:] == ["prompt"]
            self.described += described
            self.use_map = described
            try:
                value = self.parse_value()
            finally:
                self.described -= described
                self.use_map = False
            return Attribute(
                line=head.line,
                column=head.column,
                name=word,
                value=value,
                name_line=head.line,
                name_column=head.column,
                description=self.parse_description(),
            )
        block = Block(line=head.line, column=head.column, kind=word)
        if word == "use" and nxt.kind == IDENT:
            self.has_include = True
        if nxt.kind == STRING:
            self.advance()
            block.label = Str(line=nxt.line, column=nxt.column, value=str(nxt.value), raw=nxt.text)
        elif nxt.kind == IDENT:
            block.label = self.parse_dotted()
        if self.is_punct("="):
            if block.label is None:
                raise self.fail(self.peek(), f'unexpected "=" after "{word}"')
            self.advance()
            block.value = self.parse_value()
            block.braces = False
            return block
        if self.is_punct("{"):
            self.parse_braces(block)
            return block
        block.braces = False
        return block

    def parse_include(self, head: Token) -> Block:
        """``include "path" as name`` or ``from "path" import a, b as c`` (a file-level line)."""
        self.has_include = True
        path = self.advance()
        label = Str(line=path.line, column=path.column, value=str(path.value), raw=path.text)
        block = Block(line=head.line, column=head.column, kind=head.text, label=label, braces=False)
        if head.text == "include":
            if self.peek().kind == IDENT and self.peek().text == "as":
                self.advance()
                block.var = self.parse_word('a name after "as"').text
            return block
        word = self.peek()
        if word.kind != IDENT or word.text != "import":
            raise self.fail(
                word, 'expected "import" after the path', 'Write: from "x.skye" import a'
            )
        self.advance()
        while True:
            name = self.parse_word("a name to import")
            item = Block(
                line=name.line,
                column=name.column,
                kind="import",
                label=Name(line=name.line, column=name.column, path=(name.text,)),
                braces=False,
            )
            if self.peek().kind == IDENT and self.peek().text == "as":
                self.advance()
                item.var = self.parse_word('a name after "as"').text
            block.body.append(item)
            if not self.is_punct(","):
                return block
            self.advance()

    def parse_word(self, what: str) -> Token:
        tok = self.peek()
        if tok.kind != IDENT:
            raise self.fail(tok, f"expected {what}, found {self.describe(tok)}")
        return self.advance()

    def parse_dotted(self) -> Name:
        first = self.advance()
        parts = [first.text]
        while self.is_punct(".") and self.peek(1).kind == IDENT:
            self.advance()
            parts.append(self.advance().text)
        return Name(line=first.line, column=first.column, path=tuple(parts))

    def parse_braces(self, block: Block) -> None:
        opener = self.peek()
        if not (opener.kind == PUNCT and opener.text == "{"):
            raise self.fail(
                opener,
                f'expected "{{" after "{block.kind}", found {self.describe(opener)}',
                "Open the block with {.",
            )
        self.advance()
        self.enter(opener)
        output = block.kind == "output"
        self.described += output
        self.kinds.append(block.kind)
        try:
            self.parse_body(block, opener)
        finally:
            self.depth -= 1
            self.described -= output
            self.kinds.pop()

    def parse_description(self) -> Str | None:
        """The string after a value inside an ``output`` block or the ``variables`` map of a
        prompt (its description), if any.
        """
        tok = self.peek()
        if not self.described or tok.kind != STRING:
            return None
        self.advance()
        return Str(line=tok.line, column=tok.column, value=str(tok.value), raw=tok.text)

    def parse_body(self, block: Block, opener: Token) -> None:
        while True:
            self.skip_separators()
            tok = self.peek()
            if tok.kind == EOF:
                self.errors.append(
                    Diagnostic(
                        file=self.filename,
                        line=opener.line,
                        column=opener.column,
                        reason=f'"{{" of {block.kind} was never closed',
                        fix='Add a closing "}".',
                    )
                )
                return
            if tok.kind == PUNCT and tok.text == "}":
                self.advance()
                return
            try:
                if tok.kind != IDENT:
                    raise self.fail(
                        tok,
                        f"expected a field or a block, found {self.describe(tok)}",
                    )
                block.body.append(self.parse_item())
                self.end_of_item()
            except _AbortError:
                self.sync()
                if self.peek().kind == PUNCT and self.peek().text in "])":
                    self.advance()

    # -- values --------------------------------------------------------------------------------
    def parse_head(self) -> Value:
        """The condition of ``when`` or the list of ``each``: an expression up to the ``{``."""
        tokens = self.scan(stop_at_brace=True)
        if not tokens:
            raise self.fail(self.peek(), "expected an expression before the {")
        return self.classify(tokens)

    def parse_value(self) -> Value:
        tok = self.peek()
        if tok.kind == PUNCT and tok.text == "[":
            value: Value = self.parse_list()
            self.after_structure(value)
            return value
        if tok.kind == PUNCT and tok.text == "{":
            value = self.parse_map()
            self.after_structure(value)
            return value
        if tok.kind == IDENT and tok.text in TYPE_NAMES and self.is_punct("(", 1):
            self.advance()
            self.enter(self.advance())
            default: Value | None = None
            second: Value | None = None
            self.skip_newlines()
            try:
                if not self.is_punct(")"):
                    default = self.parse_value()
                    self.skip_newlines()
                    if self.is_punct(","):  # list({ ... }, []): the shape, then the default
                        self.advance()
                        self.skip_newlines()
                        second = self.parse_value()
                        self.skip_newlines()
            finally:
                self.depth -= 1
            close = self.peek()
            if not (close.kind == PUNCT and close.text == ")"):
                raise self.fail(close, f'expected ")", found {self.describe(close)}')
            self.advance()
            call = TypeCall(
                line=tok.line, column=tok.column, name=tok.text, default=default, second=second
            )
            self.after_structure(call)
            return call
        tokens = self.scan()
        if not tokens:
            raise self.fail(tok, f"expected a value, found {self.describe(tok)}")
        return self.classify(tokens)

    def after_structure(self, value: Value) -> None:
        tok = self.peek()
        if tok.kind in (NEWLINE, EOF) or (tok.kind == PUNCT and tok.text in ",]})"):
            return
        if self.described and tok.kind == STRING:  # the description of an output field
            return
        raise self.fail(
            tok,
            f"unexpected {self.describe(tok)} after the value",
            "Put the next item on a new line or separate it with a comma.",
        )

    def parse_list(self) -> ListNode:
        opener = self.advance()
        self.enter(opener)
        try:
            return self.parse_list_items(opener)
        finally:
            self.depth -= 1

    def parse_list_items(self, opener: Token) -> ListNode:
        node = ListNode(line=opener.line, column=opener.column)
        while True:
            self.skip_newlines()
            if self.is_punct("]"):
                self.advance()
                return node
            if self.peek().kind == EOF:
                raise self.fail(
                    opener, 'the "[" of this list was never closed', 'Add a closing "]".'
                )
            node.items.append(self.parse_value())
            self.skip_newlines()
            if self.is_punct(","):
                self.advance()
            elif not self.is_punct("]"):
                raise self.fail(
                    self.peek(),
                    f'expected "," or "]" in the list, found {self.describe(self.peek())}',
                )

    def parse_map(self) -> MapNode:
        opener = self.advance()
        self.enter(opener)
        try:
            return self.parse_map_entries(opener)
        finally:
            self.depth -= 1

    def parse_map_entries(self, opener: Token) -> MapNode:
        node = MapNode(line=opener.line, column=opener.column)
        allow_use, self.use_map = self.use_map, False
        while True:
            while self.peek().kind == NEWLINE or self.is_punct(","):
                self.pos += 1
            if self.is_punct("}"):
                self.advance()
                return node
            tok = self.peek()
            if tok.kind == EOF:
                raise self.fail(
                    opener, 'the "{" of this map was never closed', 'Add a closing "}".'
                )
            if tok.kind not in (IDENT, STRING):
                raise self.fail(tok, f"expected a key, found {self.describe(tok)}")
            over = (
                allow_use
                and tok.kind == IDENT
                and tok.text == "override"
                and self.peek(1).kind in (IDENT, STRING)
            )
            if over:  # ``override name = ...``; ``override = ...`` is still a key
                self.advance()
                self.has_include = True
                tok = self.peek()
            if allow_use and not over and tok.text == "use" and self.peek(1).kind == IDENT:
                self.advance()
                used = self.parse_dotted()
                self.has_include = True
                node.entries.append(
                    MapEntry(line=tok.line, column=tok.column, key=used.text, value=used, use=True)
                )
                tail = self.peek()
                if not (tail.kind == NEWLINE or (tail.kind == PUNCT and tail.text in ",}")):
                    raise self.fail(tail, f"unexpected {self.describe(tail)} in the map")
                continue
            self.advance()
            if not self.is_punct("="):
                raise self.fail(self.peek(), f'expected "=" after the key "{tok.text}"')
            self.advance()
            value = self.parse_value()
            key = str(tok.value)
            node.entries.append(
                MapEntry(
                    line=tok.line,
                    column=tok.column,
                    key=key,
                    value=value,
                    description=self.parse_description(),
                    override=over,
                )
            )
            tail = self.peek()
            if not (tail.kind in (NEWLINE,) or (tail.kind == PUNCT and tail.text in ",}")):
                raise self.fail(tail, f"unexpected {self.describe(tail)} in the map")

    def scan(self, *, stop_at_brace: bool = False) -> list[Token]:
        """Collect the tokens of an expression, up to the end of the value (not consumed)."""
        out: list[Token] = []
        depth = 0
        while True:
            tok = self.peek()
            if tok.kind == EOF:
                break
            if tok.kind == NEWLINE:
                if depth == 0:
                    break
                self.pos += 1
                continue
            if tok.kind == PUNCT:
                if tok.text in "([":
                    depth += 1
                elif tok.text == "{":
                    if stop_at_brace and depth == 0:
                        break
                    depth += 1
                elif tok.text in ")]}":
                    if depth == 0:
                        break
                    depth -= 1
                elif tok.text == "," and depth == 0:
                    break
            elif tok.kind == STRING and depth == 0 and out and self.described:
                break  # ``total = number "Total amount"``: the string is the description
            out.append(tok)
            self.pos += 1
        return out

    def classify(self, tokens: list[Token]) -> Value:
        first = tokens[0]
        if len(tokens) == 1:
            if first.kind == STRING:
                return Str(
                    line=first.line, column=first.column, value=str(first.value), raw=first.text
                )
            if first.kind == NUMBER:
                number = first.value
                assert isinstance(number, (int, float))
                return Num(line=first.line, column=first.column, value=number, raw=first.text)
            if first.kind == IDENT and first.text in ("true", "false"):
                return Bool(line=first.line, column=first.column, value=first.text == "true")
        if len(tokens) == 2 and first.kind == OP and first.text == "-" and tokens[1].kind == NUMBER:
            negative = tokens[1].value
            assert isinstance(negative, (int, float))
            return Num(
                line=first.line, column=first.column, value=-negative, raw=f"-{tokens[1].text}"
            )
        if self.is_dotted_name(tokens):
            return Name(
                line=first.line,
                column=first.column,
                path=tuple(t.text for t in tokens if t.kind == IDENT),
            )
        return Expr(line=first.line, column=first.column, text=self._expression_text(tokens))

    def _expression_text(self, tokens: list[Token]) -> str:
        """The exact text of an expression; a ``/* */`` comment between two tokens becomes a
        space."""
        parts = [tokens[0].text]
        for before, after in zip(tokens, tokens[1:]):
            gap = self.text[before.end : after.start]
            parts.append(" " if "/*" in gap else gap)
            parts.append(after.text)
        return "".join(parts)

    @staticmethod
    def is_dotted_name(tokens: list[Token]) -> bool:
        if len(tokens) % 2 == 0 or tokens[0].kind != IDENT:
            return False
        for i, tok in enumerate(tokens):
            if i % 2 == 0:
                if tok.kind != IDENT:
                    return False
            elif not (tok.kind == PUNCT and tok.text == "."):
                return False
        return True


def parse_collect(text: str, filename: str | None = None) -> tuple[Tree, list[Diagnostic]]:
    """Parse ``text`` and return the tree together with every syntax mistake found.

    Args:
        text: The ``.skye`` text.
        filename: The name used in diagnostics (``<string>`` by default).

    Returns:
        The (possibly partial) tree and the diagnostics, sorted by position.
    """
    parser = _Parser(text, filename or DEFAULT_FILENAME)
    tree = parser.parse()
    return tree, sorted(parser.errors, key=lambda d: (d.line, d.column))


def parse(text: str, filename: str | None = None) -> Tree:
    """Parse ``text`` into a syntax tree.

    Args:
        text: The ``.skye`` text (the parser reads no file).
        filename: The name used in diagnostics (``<string>`` by default).

    Returns:
        The syntax tree; every node has a line and a column.

    Raises:
        SkyeSyntaxError: With every syntax mistake found in the text.
    """
    tree, errors = parse_collect(text, filename)
    if errors:
        raise SkyeSyntaxError(errors)
    return tree
