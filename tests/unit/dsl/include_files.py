"""The libraries and prompts of the examples of the include design, and an in-memory resolver."""

from __future__ import annotations

import dataclasses
from typing import Any

from skye.base.dsl import Document, Resolved, build

AGENT = """---
partial = true
---
prompt "agent" {
  variables = {
    system_prompt = string("")  "Replaces the default system instructions when not empty"
    tools = list({
      name        = string      "Tool name"
      description = string      "What the tool does"
      parameters  = map({})     "Arguments: name to type or description"
      returns     = string("")  "What the tool returns"
    }, []) "Tools the agent may call"
  }
  message "system" {
    when system_prompt     { text = "{{ system_prompt }}" }
    when not system_prompt { text = "You are an intelligent AI assistant that can use tools." }
    when tools {
      text = "## Tools"
      each t in tools { text = "- {{ t.name }}: {{ t.description }}" }
    }
  }
}
"""

MEMORY = """---
partial = true
---
prompt "memory" {
  variables = {
    persona_memory = list({
      content = string      "What is known about the user or the agent"
      source  = string("")  "Where it comes from"
    }, []) "Who the user and the agent are"
    episodic_memory = list({
      content   = string      "What happened"
      timestamp = string("")  "When it happened"
      source    = string("")  "Where it comes from"
    }, []) "Past events"
  }
  message "system" {
    when persona_memory {
      text = "### Persona"
      each m in persona_memory {
        when m.source     { text = "- {{ m.content }} (source: {{ m.source }})" }
        when not m.source { text = "- {{ m.content }}" }
      }
    }
    when episodic_memory {
      text = "### Past events"
      each m in episodic_memory {
        when m.timestamp     { text = "- [{{ m.timestamp }}] {{ m.content }}" }
        when not m.timestamp { text = "- {{ m.content }}" }
      }
    }
  }
}
"""

FILES = {"lib/agent.skye": AGENT, "lib/memory.skye": MEMORY}

#: Section 2.2 of the design: names taken one by one from two files.
TOOL_AGENT = """from "lib/agent.skye"  import system_prompt, tools
from "lib/memory.skye" import persona_memory, episodic_memory

prompt "tool_agent" {
  variables = {
    use system_prompt
    use tools
    examples = list({ question = string "Example request" }, []) "Worked examples"
    input    = string("")  "The user's message"
    use persona_memory
    use episodic_memory
  }

  message "system" {
    use system_prompt
    use tools
    when persona_memory or episodic_memory {
      text = "## Memory"
      use persona_memory
      use episodic_memory
    }
  }
}
"""

#: The same prompt written with no include.
TOOL_AGENT_EXPANDED = """prompt "tool_agent" {
  variables = {
    system_prompt = string("")  "Replaces the default system instructions when not empty"
    tools = list({
      name        = string      "Tool name"
      description = string      "What the tool does"
      parameters  = map({})     "Arguments: name to type or description"
      returns     = string("")  "What the tool returns"
    }, []) "Tools the agent may call"
    examples = list({ question = string "Example request" }, []) "Worked examples"
    input    = string("")  "The user's message"
    persona_memory = list({
      content = string      "What is known about the user or the agent"
      source  = string("")  "Where it comes from"
    }, []) "Who the user and the agent are"
    episodic_memory = list({
      content   = string      "What happened"
      timestamp = string("")  "When it happened"
      source    = string("")  "Where it comes from"
    }, []) "Past events"
  }

  message "system" {
    when system_prompt     { text = "{{ system_prompt }}" }
    when not system_prompt { text = "You are an intelligent AI assistant that can use tools." }
    when tools {
      text = "## Tools"
      each t in tools { text = "- {{ t.name }}: {{ t.description }}" }
    }
    when persona_memory or episodic_memory {
      text = "## Memory"
      when persona_memory {
        text = "### Persona"
        each m in persona_memory {
          when m.source     { text = "- {{ m.content }} (source: {{ m.source }})" }
          when not m.source { text = "- {{ m.content }}" }
        }
      }
      when episodic_memory {
        text = "### Past events"
        each m in episodic_memory {
          when m.timestamp     { text = "- [{{ m.timestamp }}] {{ m.content }}" }
          when not m.timestamp { text = "- {{ m.content }}" }
        }
      }
    }
  }
}
"""

#: Section 2.1: the whole file, `include` once and `use name`.
CHAT_AGENT = """include "lib/memory.skye" as memory

prompt "chat_agent" {
  variables = {
    use memory
    input = string("")  "The user's message"
  }
  message "system" {
    use memory
    text = "Answer the user."
  }
}
"""

CHAT_AGENT_EXPANDED = """prompt "chat_agent" {
  variables = {
    persona_memory = list({
      content = string      "What is known about the user or the agent"
      source  = string("")  "Where it comes from"
    }, []) "Who the user and the agent are"
    episodic_memory = list({
      content   = string      "What happened"
      timestamp = string("")  "When it happened"
      source    = string("")  "Where it comes from"
    }, []) "Past events"
    input = string("")  "The user's message"
  }
  message "system" {
    when persona_memory {
      text = "### Persona"
      each m in persona_memory {
        when m.source     { text = "- {{ m.content }} (source: {{ m.source }})" }
        when not m.source { text = "- {{ m.content }}" }
      }
    }
    when episodic_memory {
      text = "### Past events"
      each m in episodic_memory {
        when m.timestamp     { text = "- [{{ m.timestamp }}] {{ m.content }}" }
        when not m.timestamp { text = "- {{ m.content }}" }
      }
    }
    text = "Answer the user."
  }
}
"""


def resolver(
    files: dict[str, str] | None = None, calls: list[tuple[str, str | None]] | None = None
):
    """A resolver over a dict: a missing target is ``FileNotFoundError``, ``..`` is refused."""
    table = FILES if files is None else files

    def resolve(target: str, from_key: str | None) -> Resolved:
        if calls is not None:
            calls.append((target, from_key))
        if ".." in target.split("/"):
            raise ValueError(f"{target} leaves the root")
        if target not in table:
            raise FileNotFoundError(f"no file {target}")
        return Resolved(text=table[target], name=target, key=target)

    return resolve


def built(text: str, files: dict[str, str] | None = None, name: str = "app.skye") -> Document:
    return build(text, filename=name, resolver=resolver(files))


def plain(spec: Any) -> Any:
    """A spec as plain data without the ``line`` and ``column`` fields (they differ by file)."""
    data = dataclasses.asdict(spec)

    def strip(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k not in ("line", "column")}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value

    return strip(data)


def reasons(document: Document) -> list[str]:
    return [d.reason for d in document.diagnostics]
