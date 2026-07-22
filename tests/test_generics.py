from __future__ import annotations

from typing import Generic, TypeVar

from modmex import BaseModel


T = TypeVar("T")


class Payload(BaseModel):
    name: str


class Envelope(BaseModel, Generic[T]):
    data: T
    history: list[T]
    fallback: T | None = None


class PayloadEnvelope(Envelope[Payload]):
    pass


U = TypeVar("U")


class ForwardingEnvelope(Envelope[U], Generic[U]):
    pass


def test_concrete_generic_subclass_constructs_nested_modmex_models() -> None:
    envelope = PayloadEnvelope(
        data={"name": "current"},
        history=[{"name": "previous"}],
        fallback={"name": "fallback"},
    )

    assert envelope.data == Payload(name="current")
    assert envelope.history == [Payload(name="previous")]
    assert envelope.fallback == Payload(name="fallback")


def test_parameterized_generic_model_constructs_nested_modmex_models() -> None:
    ConcreteEnvelope = Envelope[Payload]
    envelope = ConcreteEnvelope(data={"name": "current"}, history=[])

    assert envelope.data == Payload(name="current")
    assert ConcreteEnvelope is Envelope[Payload]


def test_generic_model_json_schema_uses_concrete_model_references() -> None:
    schema = Envelope[Payload].model_json_schema()

    assert schema["properties"]["data"] == {"$ref": "#/$defs/Payload"}
    assert schema["properties"]["history"] == {
        "type": "array",
        "items": {"$ref": "#/$defs/Payload"},
    }
    assert schema["properties"]["fallback"] == {
        "anyOf": [{"$ref": "#/$defs/Payload"}, {"type": "null"}],
        "default": None,
    }


def test_multilevel_generic_bindings_are_forwarded() -> None:
    class ConcreteEnvelope(ForwardingEnvelope[Payload]):
        pass

    envelope = ConcreteEnvelope(data={"name": "current"}, history=[])

    assert envelope.data == Payload(name="current")
    assert ConcreteEnvelope.model_json_schema()["properties"]["data"] == {
        "$ref": "#/$defs/Payload"
    }
