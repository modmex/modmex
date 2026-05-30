from dataclasses import dataclass, fields
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum

import pytest

from modmex import BaseModel, Field
from modmex.fields import should_exclude_field
from modmex.serialization import custom_serializer, normalize_exclude, serialize_value


class Kind(Enum):
    ADMIN = "admin"


class Child(BaseModel):
    token: str = Field("secret", exclude_from="public")


class Parent(BaseModel):
    child: Child


def test_field_rejects_default_and_default_factory_together() -> None:
    with pytest.raises(ValueError, match="cannot specify both default and default_factory"):
        Field(default=1, default_factory=list)


def test_field_without_default_or_default_factory_is_supported() -> None:
    @dataclass
    class Example:
        value: str = Field()

    model = Example(value="ok")

    assert model.value == "ok"


def test_should_exclude_field_respects_metadata_and_flags() -> None:
    @dataclass
    class Example:
        hidden: str = Field("x", exclude=True)
        by_profile: str = Field("y", exclude_from={"public"})

    hidden_field, profile_field = fields(Example)

    assert should_exclude_field(hidden_field, explicit_exclude=None, profile=None, include_excluded=False)
    assert should_exclude_field(profile_field, explicit_exclude=None, profile="public", include_excluded=False)
    assert not should_exclude_field(profile_field, explicit_exclude=None, profile="public", include_excluded=True)


def test_normalize_exclude_accepts_multiple_shapes() -> None:
    assert normalize_exclude(None) == {}
    assert normalize_exclude("password") == {"password": True}
    assert normalize_exclude(["a", "b"]) == {"a": True, "b": True}
    assert normalize_exclude({"nested": {"value": True}}) == {"nested": {"value": True}}


def test_serialize_value_handles_nested_models_and_dict_exclusions() -> None:
    payload = {
        "user": Parent(child=Child()),
        "items": [Child()],
    }

    dumped = serialize_value(payload, exclude={"user": {"child": {"token": True}}, "items": True}, profile="public")

    assert dumped == {"user": {"child": {}}}


def test_serialize_value_handles_tuples() -> None:
    serialized = serialize_value((datetime(2026, 1, 1), Kind.ADMIN), exclude=True)

    assert serialized == ("2026-01-01T00:00:00", "admin")


def test_custom_serializer_handles_supported_types_and_errors() -> None:
    assert custom_serializer(Kind.ADMIN) == "admin"
    assert custom_serializer(datetime(2026, 1, 1, 0, 0, 0)) == "2026-01-01T00:00:00"
    assert custom_serializer(date(2026, 1, 1)) == "2026-01-01"
    assert custom_serializer(time(8, 30)) == "08:30:00"
    assert custom_serializer(timedelta(seconds=10)) == 10
    assert custom_serializer(Decimal("1.5")) == 1.5

    with pytest.raises(TypeError, match="not serializable"):
        custom_serializer(object())
