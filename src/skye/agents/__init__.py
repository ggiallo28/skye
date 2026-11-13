"""Agent runtime and execution engine (optional extra).

This module provides the agent runtime and execution engine for orchestrating
model calls, capabilities, and memory. Available with skyeai[agents].

Component: agents. Layer: runtime (3). Declared-but-minimal; content belongs to the agents spec.
Only the agent-type registry and a ReAct placeholder live here.

Codename: cyclone.
"""

from skye.base.lazy_import import lazy_names as _lazy_names
from skye.agents.registry import (
    REACT,
    ReActAgent,
    create_agent,
    get_agent_type,
    list_agent_types,
    register_agent_type,
)

# The offline check is read at first use, so importing the package does not import it.
_LAZY = {"check_agent": "conformance"}
__getattr__ = _lazy_names(__name__, _LAZY)

__all__ = [
    *_LAZY,
    "REACT",
    "ReActAgent",
    "create_agent",
    "get_agent_type",
    "list_agent_types",
    "register_agent_type",
]
