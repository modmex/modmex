"""Schema helpers and reusable dump plans for BaseModel."""

from __future__ import annotations

import sys
import types
import typing
from dataclasses import MISSING, Field as DataclassField
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Literal, get_args, get_origin

from .fields import should_exclude_field
from .serialization import serialize_value

KIND_STR = 1
KIND_INT = 2
KIND_FLOAT = 3
KIND_BOOL = 4
KIND_TIME = 5
KIND_DURATION = 6
KIND_DATE = 7
KIND_DATETIME = 8
KIND_DECIMAL = 9

NODE_ENUM = 10
NODE_MODEL = 11
NODE_LIST = 12
NODE_DICT_STR = 13
NODE_OPTIONAL = 14
NODE_LITERAL = 15
NODE_ANY = 16

_SCALAR_NODE_BY_TYPE = {
    str: KIND_STR,
    int: KIND_INT,
    float: KIND_FLOAT,
    bool: KIND_BOOL,
    time: KIND_TIME,
    timedelta: KIND_DURATION,
    date: KIND_DATE,
    datetime: KIND_DATETIME,
    Decimal: KIND_DECIMAL,
}


def _build_dump_plan(
    model_cls: type[Any],
    model_fields: tuple[DataclassField[Any], ...],
    base_model_type: type[Any],
    profile: str | None = None,
) -> Callable[[Any], dict[str, Any]] | None:
    globalns = sys.modules[model_cls.__module__].__dict__
    try:
        type_hints = typing.get_type_hints(model_cls, globalns=globalns, include_extras=True)
    except Exception:
        type_hints = {}

    output_items: list[tuple[str, Callable[[Any], Any], bool, Any, Any]] = []
    for field in model_fields:
        if should_exclude_field(field, None, profile, False):
            continue
        field_type = type_hints.get(field.name, field.type)
        serializer = _dump_serializer_for(field_type, globalns, base_model_type, profile)
        if serializer is None:
            return None
        default_fast_types = (datetime, date, time, timedelta, Decimal)
        has_serialized_default = field.default is not MISSING and field_type in default_fast_types
        serialized_default = serialize_value(field.default) if has_serialized_default else None
        output_items.append((field.name, serializer, has_serialized_default, field.default, serialized_default))

    property_names = tuple(getattr(model_cls, "__modmex_properties__", ()))

    def dump(self: Any) -> dict[str, Any]:
        result: dict[str, Any] = {}
        state = self.__dict__
        for field_name, serializer, has_serialized_default, default, serialized_default in output_items:
            value = state[field_name]
            if has_serialized_default and value == default:
                result[field_name] = serialized_default
            else:
                result[field_name] = serializer(value)
        for attr_name in property_names:
            value = getattr(self, attr_name)
            result[attr_name] = value if value is None or type(value) in (str, int, float, bool) else serialize_value(value)
        return result

    return dump


def _dump_serializer_for(
    expected_type: Any,
    globalns: dict[str, Any],
    base_model_type: type[Any],
    profile: str | None,
) -> Callable[[Any], Any] | None:
    if isinstance(expected_type, str):
        expected_type = typing.ForwardRef(expected_type)
    if isinstance(expected_type, typing.ForwardRef):
        try:
            expected_type = expected_type._evaluate(globalns, None, recursive_guard=set())
        except Exception:
            return None

    if expected_type in (Any, str, int, float, bool):
        return _identity
    if expected_type is datetime or expected_type is date or expected_type is time:
        return _isoformat
    if expected_type is timedelta:
        return _total_seconds
    if expected_type is Decimal:
        return float
    if isinstance(expected_type, type):
        if issubclass(expected_type, Enum):
            enum_values = {member: member.value for member in expected_type}
            return enum_values.__getitem__
        if issubclass(expected_type, base_model_type):
            nested_dump = _dump_plan_for(expected_type, profile, base_model_type)
            if nested_dump is not None:
                return nested_dump
            if profile is None:
                return _model_dump_default
            return lambda value: value.model_dump(profile=profile)
        return None

    origin = get_origin(expected_type)
    if origin is list:
        inner_serializer = _dump_serializer_for(_first_arg(expected_type, Any), globalns, base_model_type, profile)
        if inner_serializer is None:
            return None
        return lambda value: [inner_serializer(item) for item in value]
    if origin is dict:
        _key_type, value_type = _dict_args(expected_type)
        value_serializer = _dump_serializer_for(value_type, globalns, base_model_type, profile)
        if value_serializer is None:
            return None
        return lambda value: {key: value_serializer(item) for key, item in value.items()}
    if origin is Literal:
        return _identity
    if origin in (typing.Union, types.UnionType):
        args = get_args(expected_type)
        non_none_args = tuple(arg for arg in args if arg is not type(None))
        if len(non_none_args) == 1 and len(non_none_args) != len(args):
            inner_serializer = _dump_serializer_for(non_none_args[0], globalns, base_model_type, profile)
            if inner_serializer is None:
                return None
            return lambda value: None if value is None else inner_serializer(value)
        return None
    return None


def _identity(value: Any) -> Any:
    return value


def _isoformat(value: Any) -> str:
    return value.isoformat()


def _total_seconds(value: timedelta) -> float:
    return value.total_seconds()


def _model_dump_default(value: Any) -> dict[str, Any]:
    return value.model_dump()


def _dump_plan_for(
    model_cls: type[Any],
    profile: str | None,
    base_model_type: type[Any],
) -> Callable[[Any], dict[str, Any]] | None:
    cache = getattr(model_cls, "__modmex_dump_plan_cache__", None)
    if cache is None:
        return None
    if profile not in cache:
        cache[profile] = _build_dump_plan(model_cls, model_cls.__modmex_fields__, base_model_type, profile)
    return cache[profile]


def _rust_schema_for(
    model_cls: type[Any],
    model_fields: tuple[DataclassField[Any], ...],
    base_model_type: type[Any],
) -> dict[str, Any]:
    globalns = sys.modules[model_cls.__module__].__dict__
    try:
        type_hints = typing.get_type_hints(model_cls, globalns=globalns, include_extras=True)
    except Exception:
        type_hints = {}

    schema: dict[str, Any] = {}
    for field in model_fields:
        node = _rust_node_for(type_hints.get(field.name, field.type), globalns, base_model_type)
        if node is None:
            return {}
        schema[field.name] = node
    return schema


def _rust_field_descriptors(model_fields: tuple[DataclassField[Any], ...], schema: dict[str, Any]) -> tuple[Any, ...]:
    descriptors: list[Any] = []
    for field in model_fields:
        node = schema.get(field.name)
        if node is None:
            return ()
        required = field.default is MISSING and field.default_factory is MISSING
        default = None if field.default is MISSING else field.default
        default_factory = None if field.default_factory is MISSING else field.default_factory
        descriptors.append((field.name, node, required, default, default_factory))
    return tuple(descriptors)


def _rust_node_for(expected_type: Any, globalns: dict[str, Any], base_model_type: type[Any]) -> Any:
    if isinstance(expected_type, str):
        expected_type = typing.ForwardRef(expected_type)

    if isinstance(expected_type, typing.ForwardRef):
        try:
            expected_type = expected_type._evaluate(globalns, None, recursive_guard=set())
        except Exception:
            return None

    if expected_type is Any:
        return (NODE_ANY,)

    scalar_kind = _SCALAR_NODE_BY_TYPE.get(expected_type)
    if scalar_kind is not None:
        return (scalar_kind,)

    if isinstance(expected_type, type):
        if issubclass(expected_type, Enum):
            return (NODE_ENUM, expected_type)
        if issubclass(expected_type, base_model_type):
            core = getattr(expected_type, "__modmex_core__", None)
            schema = getattr(expected_type, "__modmex_rust_schema__", None)
            if core is not None and schema:
                return (NODE_MODEL, expected_type, core)
            return None
        return None

    origin = get_origin(expected_type)
    if origin is list:
        inner = _rust_node_for(_first_arg(expected_type, Any), globalns, base_model_type)
        return (NODE_LIST, inner) if inner is not None else None

    if origin is dict:
        key_type, value_type = _dict_args(expected_type)
        if key_type not in (str, Any):
            return None
        inner = _rust_node_for(value_type, globalns, base_model_type)
        return (NODE_DICT_STR, inner) if inner is not None else None

    if origin is Literal:
        return (NODE_LITERAL, get_args(expected_type))

    if origin in (typing.Union, types.UnionType):
        args = get_args(expected_type)
        non_none_args = tuple(arg for arg in args if arg is not type(None))
        if len(non_none_args) == 1 and len(non_none_args) != len(args):
            inner = _rust_node_for(non_none_args[0], globalns, base_model_type)
            return (NODE_OPTIONAL, inner) if inner is not None else None
        return None

    return None


def _first_arg(expected_type: Any, default: Any) -> Any:
    args = get_args(expected_type)
    return args[0] if args else default


def _dict_args(expected_type: Any) -> tuple[Any, Any]:
    args = get_args(expected_type)
    if len(args) == 2:
        return args
    return Any, Any
