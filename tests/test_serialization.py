from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

import pytest

from modmex import BaseModel, Field
from modmex.serialization import (
    _serialize_by_type,
    custom_serializer,
    excludes_entire_value,
    normalize_exclude,
    serialize_value,
)


class Kind(Enum):
    ADMIN = "admin"


class Child(BaseModel):
    token: str = Field("secret", exclude_from="public")


class Parent(BaseModel):
    child: Child


def test_normalize_exclude_accepts_multiple_shapes() -> None:
    assert normalize_exclude(None) == {}
    assert normalize_exclude("password") == {"password": True}
    assert normalize_exclude(["a", "b"]) == {"a": True, "b": True}
    assert normalize_exclude({"nested": {"value": True}}) == {"nested": {"value": True}}


def test_excludes_entire_value_only_excludes_true() -> None:
    assert excludes_entire_value(True)
    assert not excludes_entire_value({"nested": True})
    assert not excludes_entire_value(None)


def test_serialize_by_type_handles_empty_matching_and_non_matching_serializers() -> None:
    assert _serialize_by_type(1, None) == 1
    assert _serialize_by_type(1, {int: lambda value: f"id-{value}"}) == "id-1"
    assert _serialize_by_type("one", {int: str}) == "one"


def test_serialize_value_handles_scalar_values() -> None:
    assert serialize_value(None) is None
    assert serialize_value("ok") == "ok"
    assert serialize_value(1) == 1
    assert serialize_value(1.5) == 1.5
    assert serialize_value(True) is True


def test_serialize_value_handles_nested_models_and_dict_exclusions() -> None:
    payload = {
        "user": Parent(child=Child()),
        "items": [Child()],
    }

    dumped = serialize_value(payload, exclude={"user": {"child": {"token": True}}, "items": True}, profile="public")

    assert dumped == {"user": {"child": {}}}


def test_serialize_value_passes_list_items_through_when_whole_list_excluded() -> None:
    assert serialize_value([date(2026, 1, 1)], exclude=True) == ["2026-01-01"]


def test_serialize_value_handles_tuples() -> None:
    serialized = serialize_value((datetime(2026, 1, 1), Kind.ADMIN), exclude=True)

    assert serialized == ("2026-01-01T00:00:00", "admin")


def test_serialize_value_handles_supported_builtin_types() -> None:
    identifier = uuid4()

    assert serialize_value(date(2026, 1, 1)) == "2026-01-01"
    assert serialize_value(time(8, 30)) == "08:30:00"
    assert serialize_value(timedelta(seconds=10)) == 10
    assert serialize_value(Decimal("1.5")) == 1.5
    assert serialize_value(identifier) == str(identifier)
    assert serialize_value(object()) is not None


def test_serialize_value_applies_type_serializers_before_builtin_serialization() -> None:
    serialized = serialize_value(
        {"count": 2, "other": "kept"},
        type_serializers={int: lambda value: f"custom-{value}"},
    )

    assert serialized == {"count": "custom-2", "other": "kept"}


def test_custom_serializer_handles_supported_types_and_errors() -> None:
    identifier = UUID("12345678-1234-5678-1234-567812345678")

    assert custom_serializer(Kind.ADMIN) == "admin"
    assert custom_serializer(datetime(2026, 1, 1, 0, 0, 0)) == "2026-01-01T00:00:00"
    assert custom_serializer(date(2026, 1, 1)) == "2026-01-01"
    assert custom_serializer(time(8, 30)) == "08:30:00"
    assert custom_serializer(timedelta(seconds=10)) == 10
    assert custom_serializer(Decimal("1.5")) == 1.5
    assert custom_serializer(identifier) == "12345678-1234-5678-1234-567812345678"

    with pytest.raises(TypeError, match="not serializable"):
        custom_serializer(object())
