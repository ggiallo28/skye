"""Store packaging: no driver at import time (task 5.1), backends only in ``store`` (task 5.2)."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "skye"
PORTS = {"StorageBackend", "KeyValueStore", "CounterStore", "ExpiryStore", "ScanStore"}
DRIVERS = ["boto3", "botocore", "redis", "valkey", "pg8000", "asyncpg"]


def test_importing_the_store_loads_no_driver() -> None:
    code = (
        "import sys, skye.store, skye.store.conformance\n"
        f"print(sorted(m for m in {DRIVERS!r} if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]", out.stdout


def test_only_store_implements_the_storage_ports() -> None:
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith("store/") or rel == "base/interfaces/storage.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef):
                bases = {getattr(b, "id", getattr(b, "attr", None)) for b in node.bases}
                if bases & PORTS:
                    offenders.append(f"{rel}:{node.lineno} {node.name}")
    assert offenders == [], f"a storage backend outside store (Requirement 12.1): {offenders}"
