# agents

What you learn: agents. Read in this order:

1. `agent_with_hooks.py`: Inject optional services into an agent (proposed-interface, guarded)
2. `custom_agent_type.py`: Register and run your own agent type (Live)
3. `react_agent.py`: Wire a ReAct agent with a model and capabilities (proposed-interface, guarded)
4. `hooks.py`: Change what an agent does before and after a tool or a model call (proposed-interface)
5. `hooks_memory.py`: The same, on the memory: what it reads and what it keeps (proposed-interface)

Run: `python examples/agents/agent_with_hooks.py`

What you see: printed results; with no key a scripted client answers and the example prints which mode ran.

What you need: `pip install skyeai`; a provider key only to call a real service.
