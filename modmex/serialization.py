"""Serialization helpers for model dumps and JSON encoding."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Callable

ExcludeSpec = str | Iterable[str] | Mapping[str, Any] | None
TypeSerializer = Callable[[Any], Any]
TypeSerializers = Mapping[type[Any], TypeSerializer] | None


def _serialize_by_type(value: Any, type_serializers: TypeSerializers) -> Any:
    if not type_serializers:
        return value

    for expected_type, serializer in type_serializers.items():
        if isinstance(value, expected_type):
            return serializer(value)
    return value


def normalize_exclude(exclude: ExcludeSpec) -> dict[str, Any]:
    if exclude is None:
        return {}
    if isinstance(exclude, str):
        return {exclude: True}
    if isinstance(exclude, Mapping):
        return dict(exclude)
    return {field_name: True for field_name in exclude}


def excludes_entire_value(exclude: Any) -> bool:
    return exclude is True


def serialize_value(
    value: Any,
    exclude: ExcludeSpec = None,
    profile: str | None = None,
    include_excluded: bool = False,
    type_serializers: TypeSerializers = None,
) -> Any:
    value = _serialize_by_type(value, type_serializers)

    if hasattr(value, "model_dump") and callable(value.model_dump):
        nested_exclude = None if exclude is True else exclude
        return value.model_dump(
            exclude=nested_exclude,
            profile=profile,
            include_excluded=include_excluded,
            type_serializers=type_serializers,
        )
    if isinstance(value, list):
        nested_exclude = None if exclude is True else exclude
        return [
            serialize_value(
                item,
                exclude=nested_exclude,
                profile=profile,
                include_excluded=include_excluded,
                type_serializers=type_serializers,
            )
            for item in value
        ]
    if isinstance(value, tuple):
        nested_exclude = None if exclude is True else exclude
        return tuple(
            serialize_value(
                item,
                exclude=nested_exclude,
                profile=profile,
                include_excluded=include_excluded,
                type_serializers=type_serializers,
            )
            for item in value
        )
    if isinstance(value, dict):
        exclude_map = normalize_exclude(exclude)
        return {
            key: serialize_value(
                item,
                exclude=exclude_map.get(key),
                profile=profile,
                include_excluded=include_excluded,
                type_serializers=type_serializers,
            )
            for key, item in value.items()
            if not excludes_entire_value(exclude_map.get(key))
        }
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return float(value)
    return value


def custom_serializer(obj: Any) -> Any:
    """Serialize values that orjson does not handle by default."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, time):
        return obj.isoformat()
    if isinstance(obj, timedelta):
        return obj.total_seconds()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")
