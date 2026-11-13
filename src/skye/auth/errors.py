"""Errors of the ``auth`` component."""

from __future__ import annotations

from skye.base.exceptions import ConfigurationError


# Requirement 11.3
class LoginRequiredError(ConfigurationError):
    """A mode needs an earlier vendor-tool login whose cache is missing or expired.

    ``auth`` never runs an interactive login: it reads the cache the tool left
    and, when that is not usable, says which command to run again.

    Args:
        tool: The vendor tool (``aws``, ``az``, ``gcloud``).
        command: The command that logs in again.
        reason: Why the cache is not usable (``missing`` or ``expired``).
    """

    def __init__(self, tool: str, command: str, reason: str = "missing or expired") -> None:
        super().__init__(
            f"The {tool} login cache is {reason}: run `{command}` and try again",
            details={"tool": tool, "command": command, "reason": reason},
        )
