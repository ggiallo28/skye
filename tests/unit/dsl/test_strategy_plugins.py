"""The ``strategy`` of a ``.skye`` router accepts a name that a plugin registered (plugins task 9.1, Requirement 58.1)."""

from __future__ import annotations

from skye.base.dsl import build
from tests.unit.plugins.registrar_state import restored_default_registrar

TEXT = """router "r" {
  strategy = "shortest-name"
  route "main" {
    strategy = "shortest-name"
    target {
      model = "gpt-4o"
      provider = "openai"
    }
  }
}
"""


def test_a_registered_name_is_accepted_in_the_router_and_in_a_route():
    with restored_default_registrar() as registrar:
        registrar.routing_strategy("shortest-name", lambda models: min(models, key=len))
        document = build(TEXT)
    assert document.diagnostics == []
    router = document.routers[0]
    assert router.strategy == "shortest-name" and router.routes[0].strategy == "shortest-name"


def test_a_name_nobody_registered_is_still_an_error_with_the_names_that_exist():
    with restored_default_registrar():
        document = build(TEXT)
    reasons = {d.reason for d in document.diagnostics}
    assert reasons == {'strategy "shortest-name" is not valid.'}
    assert all("round_robin" in d.fix for d in document.diagnostics)


def test_a_built_in_name_needs_no_registrar():
    text = TEXT.replace("shortest-name", "least_busy")
    assert build(text).diagnostics == []


def test_a_misspelled_built_in_name_gets_a_suggestion():
    text = TEXT.replace("shortest-name", "round_robbin")
    fixes = [d.fix for d in build(text).diagnostics]
    assert fixes and all("round_robin" in fix for fix in fixes)
