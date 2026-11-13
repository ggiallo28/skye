"""``@capability`` on a method of a class (task 18.1 of plugins, Requirements 62.2 and 62.5).

A capability is a descriptor: read through an instance it is bound to that instance, read through
the class it is
the capability itself, and ``self`` is never part of the schema or of the validation of the
arguments.
"""

import asyncio

import pytest

from skye.tools import CapabilityRegistry, LocalFunctionCapability, capability
from skye.tools.exceptions import CapabilityValidationError


class Counter:
    def __init__(self, start: int) -> None:
        self.total = start

    @capability
    def add(self, amount: int, label: str = "x") -> int:
        """Add an amount to the total.

        Args:
            amount: How much to add.
            label: A label that is not used.
        """
        self.total += amount
        return self.total

    @capability(name="peek", description="Read the total.")
    async def read_total(self) -> int:
        return self.total


@capability
def free_add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def test_a_method_capability_runs_on_its_instance():
    counter = Counter(10)
    assert counter.add.execute(amount=5) == 15
    assert counter.total == 15


def test_two_instances_keep_their_own_state():
    first, second = Counter(0), Counter(100)
    first.add.execute(amount=1)
    second.add.execute(amount=2)
    assert (first.total, second.total) == (1, 102)


def test_the_schema_has_no_self():
    schema = Counter(0).add.get_schema()
    assert schema.name == "add"
    assert schema.description == "Add an amount to the total."
    assert set(schema.parameters["properties"]) == {"amount", "label"}
    assert schema.parameters["required"] == ["amount"]
    assert schema.parameters["properties"]["amount"]["description"] == "How much to add."
    assert "self" not in str(schema.parameters)


def test_the_schema_of_the_capability_read_through_the_class_has_no_self_either():
    schema = Counter.add.get_schema()
    assert set(schema.parameters["properties"]) == {"amount", "label"}


def test_reading_through_the_class_gives_the_capability_itself():
    assert Counter.add is Counter.__dict__["add"]
    assert isinstance(Counter.add, LocalFunctionCapability)


def test_reading_through_an_instance_gives_a_new_bound_object_each_time():
    counter = Counter(0)
    assert counter.add is not Counter.add
    assert counter.add is not counter.add
    assert counter.add.func.__self__ is counter


def test_an_async_method_runs_with_aexecute():
    counter = Counter(7)
    assert asyncio.run(counter.read_total.aexecute()) == 7
    assert counter.read_total.get_schema().name == "peek"
    assert counter.read_total.get_schema().description == "Read the total."


def test_an_async_method_refuses_execute():
    with pytest.raises(CapabilityValidationError):
        Counter(0).read_total.execute()


def test_a_sync_method_runs_with_aexecute_in_a_thread():
    counter = Counter(1)
    assert asyncio.run(counter.add.aexecute(amount=2)) == 3


def test_the_arguments_are_validated_without_self():
    counter = Counter(0)
    with pytest.raises(CapabilityValidationError):
        counter.add.execute()  # amount is missing
    with pytest.raises(CapabilityValidationError):
        counter.add.execute(amount=1, other=2)  # only the parameters of the schema are accepted


def test_a_free_function_is_unchanged():
    assert free_add.execute(a=1, b=2) == 3
    assert set(free_add.get_schema().parameters["properties"]) == {"a", "b"}


def test_a_free_function_stored_in_a_class_is_not_bound():
    class Holder:
        add = free_add  # its first parameter is not self: it stays a free function

    assert Holder().add is free_add
    assert Holder().add.execute(a=2, b=3) == 5


def test_a_staticmethod_that_holds_a_capability_is_not_bound():
    class Holder:
        add = staticmethod(free_add)

    assert Holder().add is free_add
    assert Holder.add is free_add
    assert Holder().add.execute(a=4, b=5) == 9


def test_a_bound_capability_goes_in_a_registry():
    registry = CapabilityRegistry()
    counter = Counter(0)
    registry.add(counter.add)
    assert registry.get("add").execute(amount=3) == 3
    assert counter.total == 3


def test_a_first_parameter_named_cls_is_bound_to_the_class():
    class Maker:
        kind = "maker"

        @capability
        def describe(cls) -> str:  # noqa: N805 - the name cls is what the capability looks at
            return cls.kind

    assert Maker().describe.execute() == "maker"
    assert "cls" not in Maker().describe.get_schema().parameters["properties"]


def test_a_classmethod_object_is_not_a_function_to_wrap():
    with pytest.raises(CapabilityValidationError):
        capability(classmethod(lambda cls: None))  # type: ignore[call-overload]
