"""Every example runs with no key and no network, and ends without a traceback (Requirement 24.4, task 5.4 of the uxui spec).

Each example runs in a subprocess with the provider variables removed and outbound sockets refused. It fails on a non-zero exit code or
on ``Traceback`` in the output.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
SKIPPED_FOLDERS: set[str] = set()
SCRIPTS = sorted(
    p
    for p in EXAMPLES.rglob("*.py")
    if p.name != "__init__.py" and "__pycache__" not in p.parts and p.relative_to(EXAMPLES).parts[0] not in SKIPPED_FOLDERS
)
SECRET_MARKERS = ("API_KEY", "SECRET", "TOKEN", "AWS_", "AZURE_", "GOOGLE_", "OPENAI_", "ANTHROPIC_", "COHERE_", "MCP_SERVER_URL")

# Runs the example as __main__ after making every outbound connection fail, as it would with no network.
RUNNER = """
import runpy, socket, sys
def _refuse(*args, **kwargs):
    raise OSError("network disabled for this test")
socket.socket.connect = _refuse
socket.socket.connect_ex = _refuse
socket.create_connection = _refuse
socket.getaddrinfo = _refuse
script = sys.argv[1]
sys.argv = [script]
runpy.run_path(script, run_name="__main__")
"""


def _clean_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not any(m in k.upper() for m in SECRET_MARKERS)}
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


EXPECTED_TO_FAIL = {
    "agents/hooks.py": "waits for the hooks of the agents spec (3-runtime-agents)",
    "agents/hooks_memory.py": "waits for the hooks of the agents spec (3-runtime-agents)",
}


def _params(scripts):
    params = []
    for script in scripts:
        reason = EXPECTED_TO_FAIL.get(str(script.relative_to(EXAMPLES))) or EXPECTED_TO_FAIL.get(
            script.relative_to(EXAMPLES).parts[0]
        )
        marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
        params.append(pytest.param(script, marks=marks, id=str(script.relative_to(EXAMPLES))))
    return params


@pytest.mark.parametrize("script", _params(SCRIPTS))
def test_example_runs_offline_without_traceback(script: Path):
    done = subprocess.run(
        [sys.executable, "-c", RUNNER, str(script)],
        cwd=script.parent,
        env=_clean_env(),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = done.stdout + done.stderr
    assert "Traceback" not in output, output[-1500:]
    assert done.returncode == 0, output[-1500:]
