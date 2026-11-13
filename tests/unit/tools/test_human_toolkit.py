"""The built-in toolkit ``human`` (task 19.7, Requirement 62.7): questions and escalations to a
person through a channel."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from skye.base.exceptions import ConfigurationError, ValidationError
from skye.base.messages import CapabilityStatus
from skye.completion import CapabilityCall
from skye.tools.plugins import human as door
from skye.tools.plugins.human import EscalationMessage, HumanToolkit
from skye.tools.plugins.human import toolkit as module


@pytest.fixture
def inbox(tmp_path: Path) -> Path:
    return tmp_path / "inbox"


@pytest.fixture
def toolkit(inbox: Path) -> HumanToolkit:
    return HumanToolkit(channel="file", directory=inbox)


def ticket_of(line: str) -> str:
    return line.rsplit(" ", 1)[1]


async def call(toolkit: HumanToolkit, name: str, **arguments: object):
    return await toolkit.run(CapabilityCall(id="1", name=f"human.{name}", arguments=arguments))


# -- registration and options
# -------------------------------------------------------------------------------------------


def test_the_door_registers_the_name_by_text_in_a_private_registrar():
    from skye.base.plugins import Registrar

    registrar = Registrar()
    door.register(registrar)
    assert registrar._tables["toolkit"]["human"].target == "skye.tools.plugins.human:HumanToolkit"


def test_an_unknown_channel_lists_the_two_built_in_ones():
    with pytest.raises(ConfigurationError) as caught:
        HumanToolkit(channel="smoke-signal")
    assert "console" in str(caught.value) and "file" in str(caught.value)


def test_the_file_channel_needs_a_directory():
    with pytest.raises(ValidationError) as caught:
        HumanToolkit(channel="file")
    assert "directory" in str(caught.value)
    with pytest.raises(ValidationError):
        HumanToolkit()  # the default channel is the file one


@pytest.mark.parametrize("name", ["timeout", "poll_interval"])
@pytest.mark.parametrize("value", [0, -1, True, "5"])
def test_the_times_must_be_positive_numbers(inbox: Path, name: str, value):
    with pytest.raises(ValidationError):
        HumanToolkit(directory=inbox, **{name: value})


def test_a_channel_object_takes_no_options_and_needs_send_and_poll():
    class Fake:
        def send(self, message):
            return "0" * 12

        def poll(self, ticket):
            return None

    HumanToolkit(channel=Fake())
    with pytest.raises(ConfigurationError):
        HumanToolkit(channel=Fake(), directory="x")
    with pytest.raises(ConfigurationError):
        HumanToolkit(channel=object())


def test_the_schemas_have_the_prefix_and_no_self(toolkit: HumanToolkit):
    schemas = {s.name: s for s in asyncio.run(toolkit.list_schemas())}
    assert set(schemas) == {"human.ask_human", "human.escalate", "human.check_escalation"}
    for schema in schemas.values():
        assert "self" not in schema.parameters.get("properties", {})
    assert schemas["human.escalate"].parameters["required"] == ["reason", "summary"]


# -- escalate and check_escalation
# --------------------------------------------------------------------------------------


def test_escalate_writes_the_message_and_returns_the_ticket(toolkit: HumanToolkit, inbox: Path):
    line = toolkit.escalate.execute(
        reason="refund over the limit", summary="order 42", severity="high"
    )
    ticket = ticket_of(line)
    assert line == f"escalation sent, ticket {ticket}"
    data = json.loads((inbox / f"{ticket}.json").read_text(encoding="utf-8"))
    assert data["ticket"] == ticket
    assert data["kind"] == "escalation"
    assert data["text"] == "refund over the limit"
    assert data["context"] == "order 42"
    assert data["severity"] == "high"
    assert data["created"].endswith("+00:00")


def test_the_time_comes_from_a_function_a_test_can_replace(
    toolkit: HumanToolkit, inbox: Path, monkeypatch
):
    monkeypatch.setattr(module, "_now", lambda: "2026-01-01T00:00:00+00:00")
    ticket = ticket_of(toolkit.escalate.execute(reason="r", summary="s"))
    assert (
        json.loads((inbox / f"{ticket}.json").read_text())["created"] == "2026-01-01T00:00:00+00:00"
    )


def test_check_escalation_before_and_after_a_reply(toolkit: HumanToolkit, inbox: Path):
    ticket = ticket_of(toolkit.escalate.execute(reason="r", summary="s"))
    assert toolkit.check_escalation.execute(ticket=ticket) == "no reply yet"
    (inbox / f"{ticket}.reply.txt").write_text("approved\n", encoding="utf-8")
    assert toolkit.check_escalation.execute(ticket=ticket) == "approved"


def test_an_empty_reply_file_is_no_reply_yet(toolkit: HumanToolkit, inbox: Path):
    ticket = ticket_of(toolkit.escalate.execute(reason="r", summary="s"))
    (inbox / f"{ticket}.reply.txt").write_text("  \n", encoding="utf-8")
    assert toolkit.check_escalation.execute(ticket=ticket) == "no reply yet"


@pytest.mark.parametrize("severity", ["", "critical", "HIGH", None])
async def test_a_severity_outside_the_four_is_an_error(toolkit: HumanToolkit, severity):
    message = await call(toolkit, "escalate", reason="r", summary="s", severity=severity)
    assert message.status is CapabilityStatus.ERROR
    assert "low, normal, high, urgent" in message.content


@pytest.mark.parametrize("reason", ["", "   ", None])
async def test_an_empty_reason_is_an_error(toolkit: HumanToolkit, reason):
    message = await call(toolkit, "escalate", reason=reason, summary="s")
    assert message.status is CapabilityStatus.ERROR


def test_a_long_text_is_cut_and_says_so(toolkit: HumanToolkit, inbox: Path):
    ticket = ticket_of(toolkit.escalate.execute(reason="x" * 5000, summary="y" * 5000))
    data = json.loads((inbox / f"{ticket}.json").read_text())
    assert len(data["text"]) < 4100 and data["text"].endswith("[cut]")
    assert len(data["context"]) == 4000


@pytest.mark.parametrize(
    "ticket", ["../x", "/etc/passwd", "ABCDEF123456", "abc", "0" * 13, "", "..%2f..%2fx"]
)
async def test_the_ticket_is_checked_before_it_is_used_in_a_path(
    toolkit: HumanToolkit, ticket: str
):
    message = await call(toolkit, "check_escalation", ticket=ticket)
    assert message.status is CapabilityStatus.ERROR
    assert "ticket" in message.content


def test_the_file_channel_refuses_a_bad_ticket_itself(inbox: Path):
    channel = module.FileChannel(inbox)
    with pytest.raises(Exception):
        channel.poll("../../x")


def test_the_write_is_atomic_and_leaves_only_the_final_file(toolkit: HumanToolkit, inbox: Path):
    tickets = [ticket_of(toolkit.escalate.execute(reason=f"r{i}", summary="s")) for i in range(5)]
    assert sorted(p.name for p in inbox.iterdir()) == sorted(f"{t}.json" for t in tickets)


# -- ask_human
# --------------------------------------------------------------------------------------------------


async def test_ask_human_returns_a_reply_written_after_a_short_delay(
    toolkit: HumanToolkit, inbox: Path, monkeypatch
):
    async def quick_sleep(seconds: float) -> None:
        await asyncio.sleep(0.01)

    monkeypatch.setattr(module, "_sleep", quick_sleep)

    def person() -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            sent = sorted(inbox.glob("*.json")) if inbox.exists() else []
            if sent:
                time.sleep(0.05)
                (inbox / f"{sent[0].stem}.reply.txt").write_text("yes, go on", encoding="utf-8")
                return
            time.sleep(0.005)

    thread = threading.Thread(target=person)
    thread.start()
    try:
        message = await call(
            toolkit, "ask_human", question="May I refund order 42?", context="the customer waited"
        )
    finally:
        thread.join()
    assert message.status is CapabilityStatus.OK
    assert message.content == "yes, go on"
    sent = json.loads(next(inbox.glob("*.json")).read_text())
    assert sent["kind"] == "question" and sent["context"] == "the customer waited"


async def test_ask_human_times_out_with_the_ticket_in_the_error(
    toolkit: HumanToolkit, inbox: Path, monkeypatch
):
    clock = [0.0]

    async def fake_sleep(seconds: float) -> None:
        clock[0] += seconds

    monkeypatch.setattr(module, "_sleep", fake_sleep)
    monkeypatch.setattr(module, "_monotonic", lambda: clock[0])
    message = await call(toolkit, "ask_human", question="Anyone there?")
    assert message.status is CapabilityStatus.ERROR
    ticket = next(inbox.glob("*.json")).stem
    assert ticket in message.content
    assert "not answered" in message.content and "check_escalation" in message.content
    assert clock[0] >= 300  # it waited the whole time, by the fake clock, and not by the real one


async def test_ask_human_polls_at_the_interval(inbox: Path, monkeypatch):
    seen: list[float] = []
    clock = [0.0]

    async def fake_sleep(seconds: float) -> None:
        seen.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(module, "_sleep", fake_sleep)
    monkeypatch.setattr(module, "_monotonic", lambda: clock[0])
    toolkit = HumanToolkit(directory=inbox, timeout=10, poll_interval=2.5)
    await call(toolkit, "ask_human", question="q")
    assert seen and set(seen) == {2.5}


# -- a channel of the user's own, and the console
# -----------------------------------------------------------------------


async def test_a_custom_channel_object_works(monkeypatch):
    class Fake:
        def __init__(self) -> None:
            self.sent: list[EscalationMessage] = []
            self.polls = 0

        def send(self, message: EscalationMessage) -> str:
            self.sent.append(message)
            return "abcdef012345"

        def poll(self, ticket: str) -> str | None:
            self.polls += 1
            return "done" if self.polls >= 2 else None

    async def no_wait(seconds: float) -> None:
        return None

    monkeypatch.setattr(module, "_sleep", no_wait)
    fake = Fake()
    toolkit = HumanToolkit(channel=fake)
    message = await call(toolkit, "ask_human", question="q")
    assert message.content == "done"
    assert fake.sent[0].kind == "question" and fake.polls == 2
    assert (
        toolkit.escalate.execute(reason="r", summary="s") == "escalation sent, ticket abcdef012345"
    )


def test_the_console_channel_prints_to_stderr_and_does_not_read_without_a_terminal(
    capsys, monkeypatch
):
    class NotATerminal:
        def isatty(self) -> bool:
            return False

        def readline(self) -> str:  # pragma: no cover - must not be called
            raise AssertionError("read from a stream that is not a terminal")

    monkeypatch.setattr(sys, "stdin", NotATerminal())
    toolkit = HumanToolkit(channel="console")
    line = toolkit.escalate.execute(reason="disk is full", summary="node 3", severity="urgent")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "disk is full" in captured.err and "urgent" in captured.err and "node 3" in captured.err
    assert toolkit.check_escalation.execute(ticket=ticket_of(line)) == "no reply yet"


def test_the_console_channel_reads_one_line_from_a_terminal(monkeypatch):
    class Terminal:
        def isatty(self) -> bool:
            return True

        def readline(self) -> str:
            return "go ahead\n"

    monkeypatch.setattr(sys, "stdin", Terminal())
    toolkit = HumanToolkit(channel="console")
    ticket = ticket_of(toolkit.escalate.execute(reason="r", summary="s"))
    assert toolkit.check_escalation.execute(ticket=ticket) == "go ahead"


# -- lazy
# --------------------------------------------------------------------------------------------------


def test_import_skye_tools_does_not_import_the_module():
    code = "import sys, skye.tools; print('skye.tools.plugins.human.toolkit' in sys.modules)"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "False"
