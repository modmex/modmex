"""Generated fast paths for BaseModel construction and dumping."""

from __future__ import annotations

import sys
import types
import typing
from dataclasses import MISSING, Field as DataclassField
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Literal, get_args, get_origin

from .datetime_parser import parse_date, parse_datetime, parse_duration, parse_time
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


def _trusted_init(instance: Any, model_cls: type[Any], kwargs: dict[str, Any]) -> bool:
    for name in model_cls.__modmex_required_field_names__:
        if name not in kwargs:
            return False

    for field in model_cls.__modmex_fields__:
        if field.name in kwargs:
            value = kwargs[field.name]
        elif field.default is not MISSING:
            value = field.default
        elif field.default_factory is not MISSING:
            value = field.default_factory()
        else:
            return False
        setattr(instance, field.name, value)
    return True


def _build_trusted_init(model_fields: tuple[DataclassField[Any], ...]) -> Callable[[Any, dict[str, Any]], bool]:
    namespace: dict[str, Any] = {}
    lines = ["def __modmex_trusted_init__(self, kwargs):"]

    for index, field in enumerate(model_fields):
        key = field.name
        if field.default is MISSING and field.default_factory is MISSING:
            lines.append(f"    if {key!r} not in kwargs:")
            lines.append("        return False")

    for index, field in enumerate(model_fields):
        key = field.name
        lines.append(f"    if {key!r} in kwargs:")
        lines.append(f"        self.{field.name} = kwargs[{key!r}]")
        if field.default is not MISSING:
            default_name = f"_default_{index}"
            namespace[default_name] = field.default
            lines.append("    else:")
            lines.append(f"        self.{field.name} = {default_name}")
        elif field.default_factory is not MISSING:
            factory_name = f"_factory_{index}"
            namespace[factory_name] = field.default_factory
            lines.append("    else:")
            lines.append(f"        self.{field.name} = {factory_name}()")

    lines.append("    return True")
    exec("\n".join(lines), namespace)
    return namespace["__modmex_trusted_init__"]


def _build_compiled_init(
    model_cls: type[Any],
    model_fields: tuple[DataclassField[Any], ...],
    base_model_type: type[Any],
    present_names: frozenset[str] | None = None,
    assumed_types: dict[str, type[Any]] | None = None,
) -> Callable[[Any, dict[str, Any]], bool] | None:
    globalns = sys.modules[model_cls.__module__].__dict__
    try:
        type_hints = typing.get_type_hints(model_cls, globalns=globalns, include_extras=True)
    except Exception:
        type_hints = {}

    namespace: dict[str, Any] = {
        "_MISSING": MISSING,
        "_Enum": Enum,
        "_Decimal": Decimal,
        "_type": type,
        "_len": len,
        "_isinstance": isinstance,
        "_int": int,
        "_str": str,
        "_float": float,
        "_bool": bool,
        "_bytes_types": (bytes, bytearray),
        "_object_new": object.__new__,
        "_date": date,
        "_datetime": datetime,
        "_time": time,
        "_timedelta": timedelta,
        "_parse_date": parse_date,
        "_parse_datetime": parse_datetime,
        "_parse_duration": parse_duration,
        "_parse_time": parse_time,
    }
    lines = ["def __modmex_compiled_init__(self, kwargs):"]
    if present_names is None:
        lines.append("    _get = kwargs.get")
    counter = [0]

    def temp(prefix: str) -> str:
        counter[0] += 1
        return f"_{prefix}_{counter[0]}"

    def emit(
        expected_type: Any,
        source: str,
        target: str,
        indent: str,
        source_type: type[Any] | None = None,
    ) -> bool:
        if isinstance(expected_type, str):
            expected_type = typing.ForwardRef(expected_type)
        if isinstance(expected_type, typing.ForwardRef):
            try:
                expected_type = expected_type._evaluate(globalns, None, recursive_guard=set())
            except Exception:
                return False

        if expected_type is Any:
            lines.append(f"{indent}{target} = {source}")
            return True

        if expected_type is str:
            if source_type is str:
                lines.append(f"{indent}{target} = {source}")
                return True
            lines.append(f"{indent}if _type({source}) is str:")
            lines.append(f"{indent}    {target} = {source}")
            lines.append(f"{indent}elif _isinstance({source}, str):")
            lines.append(f"{indent}    {target} = {source}")
            lines.append(f"{indent}elif _isinstance({source}, _Enum):")
            lines.append(f"{indent}    {target} = _str({source}.value)")
            lines.append(f"{indent}elif _isinstance({source}, (float, int, _Decimal)):")
            lines.append(f"{indent}    {target} = _str({source})")
            lines.append(f"{indent}elif _isinstance({source}, _bytes_types):")
            lines.append(f"{indent}    {target} = {source}.decode()")
            lines.append(f"{indent}else:")
            lines.append(f"{indent}    return False")
            return True

        if expected_type is int:
            if source_type is int:
                lines.append(f"{indent}{target} = {source}")
                return True
            int_cache = temp("int_cache")
            namespace[int_cache] = {}
            cached = temp("cached")
            lines.append(f"{indent}if _type({source}) is int:")
            lines.append(f"{indent}    {target} = {source}")
            lines.append(f"{indent}elif _type({source}) is str:")
            lines.append(f"{indent}    {cached} = {int_cache}.get({source})")
            lines.append(f"{indent}    if {cached} is None:")
            lines.append(f"{indent}        try:")
            lines.append(f"{indent}            {target} = _int({source})")
            lines.append(f"{indent}        except (TypeError, ValueError, OverflowError):")
            lines.append(f"{indent}            return False")
            lines.append(f"{indent}        {int_cache}[{source}] = {target}")
            lines.append(f"{indent}    else:")
            lines.append(f"{indent}        {target} = {cached}")
            lines.append(f"{indent}else:")
            lines.append(f"{indent}    try:")
            lines.append(f"{indent}        {target} = _int({source})")
            lines.append(f"{indent}    except (TypeError, ValueError, OverflowError):")
            lines.append(f"{indent}        return False")
            return True

        if expected_type is bool:
            if source_type is bool:
                lines.append(f"{indent}{target} = {source}")
                return True
            lines.append(f"{indent}if {source} is True or {source} is False:")
            lines.append(f"{indent}    {target} = {source}")
            lines.append(f"{indent}else:")
            lines.append(f"{indent}    _bool_value = {source}.decode() if _isinstance({source}, bytes) else {source}")
            lines.append(f"{indent}    if _isinstance(_bool_value, str):")
            lines.append(f"{indent}        _bool_value = _bool_value.lower()")
            lines.append(f"{indent}    if _bool_value in (1, '1', 'on', 't', 'true', 'y', 'yes'):")
            lines.append(f"{indent}        {target} = True")
            lines.append(f"{indent}    elif _bool_value in (0, '0', 'off', 'f', 'false', 'n', 'no'):")
            lines.append(f"{indent}        {target} = False")
            lines.append(f"{indent}    else:")
            lines.append(f"{indent}        return False")
            return True

        if expected_type is float:
            if source_type is float:
                lines.append(f"{indent}{target} = {source}")
                return True
            lines.append(f"{indent}if _type({source}) is float:")
            lines.append(f"{indent}    {target} = {source}")
            lines.append(f"{indent}else:")
            lines.append(f"{indent}    try:")
            lines.append(f"{indent}        {target} = _float({source})")
            lines.append(f"{indent}    except (TypeError, ValueError):")
            lines.append(f"{indent}        return False")
            return True

        if expected_type is datetime:
            if source_type is datetime:
                lines.append(f"{indent}{target} = {source}")
                return True
            lines.append(f"{indent}if _type({source}) is _datetime:")
            lines.append(f"{indent}    {target} = {source}")
            lines.append(f"{indent}elif _type({source}) is str or _isinstance({source}, str):")
            lines.append(f"{indent}    try:")
            lines.append(f"{indent}        {target} = _datetime.fromisoformat({source})")
            lines.append(f"{indent}    except ValueError:")
            lines.append(f"{indent}        try:")
            lines.append(f"{indent}            {target} = _parse_datetime({source})")
            lines.append(f"{indent}        except (TypeError, ValueError):")
            lines.append(f"{indent}            return False")
            lines.append(f"{indent}else:")
            lines.append(f"{indent}    try:")
            lines.append(f"{indent}        {target} = _parse_datetime({source})")
            lines.append(f"{indent}    except (TypeError, ValueError):")
            lines.append(f"{indent}        return False")
            return True

        if expected_type is date:
            if source_type is date:
                lines.append(f"{indent}{target} = {source}")
                return True
            lines.append(f"{indent}if _type({source}) is _date:")
            lines.append(f"{indent}    {target} = {source}")
            lines.append(f"{indent}elif _isinstance({source}, _date):")
            lines.append(f"{indent}    {target} = {source}.date() if _isinstance({source}, _datetime) else {source}")
            lines.append(f"{indent}elif _type({source}) is str or _isinstance({source}, str):")
            lines.append(f"{indent}    try:")
            lines.append(f"{indent}        {target} = _date.fromisoformat({source})")
            lines.append(f"{indent}    except ValueError:")
            lines.append(f"{indent}        try:")
            lines.append(f"{indent}            {target} = _parse_date({source})")
            lines.append(f"{indent}        except (TypeError, ValueError):")
            lines.append(f"{indent}            return False")
            lines.append(f"{indent}else:")
            lines.append(f"{indent}    try:")
            lines.append(f"{indent}        {target} = _parse_date({source})")
            lines.append(f"{indent}    except (TypeError, ValueError):")
            lines.append(f"{indent}        return False")
            return True

        if expected_type is time:
            if source_type is time:
                lines.append(f"{indent}{target} = {source}")
                return True
            lines.append(f"{indent}if _type({source}) is _time:")
            lines.append(f"{indent}    {target} = {source}")
            lines.append(f"{indent}elif _type({source}) is str or _isinstance({source}, str):")
            lines.append(f"{indent}    try:")
            lines.append(f"{indent}        {target} = _time.fromisoformat({source})")
            lines.append(f"{indent}    except ValueError:")
            lines.append(f"{indent}        try:")
            lines.append(f"{indent}            {target} = _parse_time({source})")
            lines.append(f"{indent}        except (TypeError, ValueError):")
            lines.append(f"{indent}            return False")
            lines.append(f"{indent}else:")
            lines.append(f"{indent}    try:")
            lines.append(f"{indent}        {target} = _parse_time({source})")
            lines.append(f"{indent}    except (TypeError, ValueError):")
            lines.append(f"{indent}        return False")
            return True

        if expected_type is timedelta:
            if source_type is timedelta:
                lines.append(f"{indent}{target} = {source}")
                return True
            duration_cache = temp("duration_cache")
            namespace[duration_cache] = {}
            cached = temp("cached_duration")
            lines.append(f"{indent}if _type({source}) is _timedelta:")
            lines.append(f"{indent}    {target} = {source}")
            lines.append(f"{indent}elif _type({source}) is int or _type({source}) is float:")
            lines.append(f"{indent}    {cached} = {duration_cache}.get({source})")
            lines.append(f"{indent}    if {cached} is None:")
            lines.append(f"{indent}        {target} = _timedelta(seconds={source})")
            lines.append(f"{indent}        {duration_cache}[{source}] = {target}")
            lines.append(f"{indent}    else:")
            lines.append(f"{indent}        {target} = {cached}")
            lines.append(f"{indent}elif _isinstance({source}, (int, float)):")
            lines.append(f"{indent}    {target} = _timedelta(seconds={source})")
            lines.append(f"{indent}else:")
            lines.append(f"{indent}    try:")
            lines.append(f"{indent}        {target} = _parse_duration({source})")
            lines.append(f"{indent}    except (TypeError, ValueError):")
            lines.append(f"{indent}        return False")
            return True

        if expected_type is Decimal:
            if source_type is Decimal:
                lines.append(f"{indent}{target} = {source}")
                return True
            lines.append(f"{indent}if _isinstance({source}, _Decimal):")
            lines.append(f"{indent}    {target} = {source}")
            lines.append(f"{indent}else:")
            lines.append(f"{indent}    try:")
            lines.append(f"{indent}        _decimal_raw = {source}.decode() if _isinstance({source}, _bytes_types) else {source}")
            lines.append(f"{indent}        {target} = _Decimal(_str(_decimal_raw).strip())")
            lines.append(f"{indent}    except Exception:")
            lines.append(f"{indent}        return False")
            lines.append(f"{indent}    if not {target}.is_finite():")
            lines.append(f"{indent}        return False")
            return True

        if isinstance(expected_type, type):
            if issubclass(expected_type, Enum):
                enum_name = temp("enum")
                enum_map = temp("enum_map")
                namespace[enum_name] = expected_type
                namespace[enum_map] = {member.value: member for member in expected_type}
                if source_type is expected_type:
                    lines.append(f"{indent}{target} = {source}")
                    return True
                if source_type is str:
                    lines.append(f"{indent}if {source} in {enum_map}:")
                    lines.append(f"{indent}    {target} = {enum_map}[{source}]")
                    lines.append(f"{indent}else:")
                    lines.append(f"{indent}    return False")
                    return True
                lines.append(f"{indent}if _isinstance({source}, {enum_name}):")
                lines.append(f"{indent}    {target} = {source}")
                lines.append(f"{indent}elif {source} in {enum_map}:")
                lines.append(f"{indent}    {target} = {enum_map}[{source}]")
                lines.append(f"{indent}else:")
                lines.append(f"{indent}    return False")
                return True
            if issubclass(expected_type, base_model_type):
                model_name = temp("model")
                model_init = temp("model_init")
                model_full_init = temp("model_full_init")
                model_full_len = temp("model_full_len")
                namespace[model_name] = expected_type
                namespace[model_init] = getattr(expected_type, "__modmex_compiled_init__", None)
                nested_fields = getattr(expected_type, "__modmex_fields__", ())
                nested_names = frozenset(field.name for field in nested_fields)
                namespace[model_full_init] = (
                    _build_compiled_init(expected_type, nested_fields, base_model_type, nested_names)
                    if nested_fields
                    else None
                )
                namespace[model_full_len] = len(nested_names)
                if source_type is expected_type:
                    lines.append(f"{indent}{target} = {source}")
                    return True
                if source_type is dict:
                    lines.append(f"{indent}if {model_full_init} is not None and _len({source}) == {model_full_len}:")
                    lines.append(f"{indent}    {target} = _object_new({model_name})")
                    lines.append(f"{indent}    if not {model_full_init}({target}, {source}):")
                    lines.append(f"{indent}        return False")
                    lines.append(f"{indent}elif {model_init} is not None:")
                    lines.append(f"{indent}    {target} = _object_new({model_name})")
                    lines.append(f"{indent}    if not {model_init}({target}, {source}):")
                    lines.append(f"{indent}        return False")
                    lines.append(f"{indent}else:")
                    lines.append(f"{indent}    try:")
                    lines.append(f"{indent}        {target} = {model_name}(**{source})")
                    lines.append(f"{indent}    except Exception:")
                    lines.append(f"{indent}        return False")
                    return True
                lines.append(f"{indent}if _isinstance({source}, {model_name}):")
                lines.append(f"{indent}    {target} = {source}")
                lines.append(f"{indent}elif _type({source}) is dict and {model_full_init} is not None and _len({source}) == {model_full_len}:")
                lines.append(f"{indent}    {target} = _object_new({model_name})")
                lines.append(f"{indent}    if not {model_full_init}({target}, {source}):")
                lines.append(f"{indent}        return False")
                lines.append(f"{indent}elif _isinstance({source}, dict) and {model_init} is not None:")
                lines.append(f"{indent}    {target} = _object_new({model_name})")
                lines.append(f"{indent}    if not {model_init}({target}, {source}):")
                lines.append(f"{indent}        return False")
                lines.append(f"{indent}elif _isinstance({source}, dict):")
                lines.append(f"{indent}    try:")
                lines.append(f"{indent}        {target} = {model_name}(**{source})")
                lines.append(f"{indent}    except Exception:")
                lines.append(f"{indent}        return False")
                lines.append(f"{indent}else:")
                lines.append(f"{indent}    return False")
                return True
            return False

        origin = get_origin(expected_type)
        if origin is list:
            inner_type = _first_arg(expected_type, Any)
            if inner_type is int:
                item = temp("item")
                if source_type is not list:
                    lines.append(f"{indent}if _type({source}) is not list:")
                    lines.append(f"{indent}    if not _isinstance({source}, list):")
                    lines.append(f"{indent}        return False")
                lines.append(f"{indent}try:")
                lines.append(f"{indent}    {target} = [{item} if _type({item}) is int else _int({item}) for {item} in {source}]")
                lines.append(f"{indent}except (TypeError, ValueError, OverflowError):")
                lines.append(f"{indent}    return False")
                return True
            item = temp("item")
            coerced = temp("coerced")
            if source_type is not list:
                lines.append(f"{indent}if _type({source}) is not list:")
                lines.append(f"{indent}    if not _isinstance({source}, list):")
                lines.append(f"{indent}        return False")
            lines.append(f"{indent}{target} = []")
            lines.append(f"{indent}for {item} in {source}:")
            if not emit(inner_type, item, coerced, indent + "    "):
                return False
            lines.append(f"{indent}    {target}.append({coerced})")
            return True

        if origin is dict:
            key_type, value_type = _dict_args(expected_type)
            if key_type not in (str, Any):
                return False
            if key_type is str and value_type is int:
                key = temp("key")
                item = temp("item")
                if source_type is not dict:
                    lines.append(f"{indent}if _type({source}) is not dict:")
                    lines.append(f"{indent}    if not _isinstance({source}, dict):")
                    lines.append(f"{indent}        return False")
                lines.append(f"{indent}try:")
                lines.append(f"{indent}    {target} = {{({key} if _type({key}) is str else (_str({key}) if not _isinstance({key}, str) else {key})): ({item} if _type({item}) is int else _int({item})) for {key}, {item} in {source}.items()}}")
                lines.append(f"{indent}except (TypeError, ValueError, OverflowError):")
                lines.append(f"{indent}    return False")
                return True
            key = temp("key")
            item = temp("item")
            coerced_key = temp("key_coerced")
            coerced = temp("coerced")
            if source_type is not dict:
                lines.append(f"{indent}if _type({source}) is not dict:")
                lines.append(f"{indent}    if not _isinstance({source}, dict):")
                lines.append(f"{indent}        return False")
            lines.append(f"{indent}{target} = {{}}")
            lines.append(f"{indent}for {key}, {item} in {source}.items():")
            if key_type is str:
                if not emit(str, key, coerced_key, indent + "    "):
                    return False
            else:
                lines.append(f"{indent}    {coerced_key} = {key}")
            if not emit(value_type, item, coerced, indent + "    "):
                return False
            lines.append(f"{indent}    {target}[{coerced_key}] = {coerced}")
            return True

        if origin is Literal:
            allowed_name = temp("literal")
            namespace[allowed_name] = get_args(expected_type)
            lines.append(f"{indent}if {source} in {allowed_name}:")
            lines.append(f"{indent}    {target} = {source}")
            lines.append(f"{indent}else:")
            lines.append(f"{indent}    return False")
            return True

        if origin in (typing.Union, types.UnionType):
            args = get_args(expected_type)
            non_none_args = tuple(arg for arg in args if arg is not type(None))
            if len(non_none_args) == 1 and len(non_none_args) != len(args):
                lines.append(f"{indent}if {source} is None:")
                lines.append(f"{indent}    {target} = None")
                lines.append(f"{indent}else:")
                return emit(non_none_args[0], source, target, indent + "    ")
            return False

        return False

    for index, field in enumerate(model_fields):
        field_type = type_hints.get(field.name, field.type)
        raw = temp("raw")
        value = temp("value")
        if present_names is not None:
            if field.name in present_names:
                lines.append(f"    {raw} = kwargs[{field.name!r}]")
                source_type = assumed_types.get(field.name) if assumed_types else None
                if not emit(field_type, raw, value, "    ", source_type):
                    return None
                lines.append(f"    self.{field.name} = {value}")
            elif field.default is not MISSING:
                default_name = f"_default_{index}"
                namespace[default_name] = field.default
                lines.append(f"    self.{field.name} = {default_name}")
            elif field.default_factory is not MISSING:
                factory_name = f"_factory_{index}"
                namespace[factory_name] = field.default_factory
                lines.append(f"    self.{field.name} = {factory_name}()")
            else:
                return None
        else:
            lines.append(f"    {raw} = _get({field.name!r}, _MISSING)")
            lines.append(f"    if {raw} is _MISSING:")
            if field.default is not MISSING:
                default_name = f"_default_{index}"
                namespace[default_name] = field.default
                lines.append(f"        self.{field.name} = {default_name}")
            elif field.default_factory is not MISSING:
                factory_name = f"_factory_{index}"
                namespace[factory_name] = field.default_factory
                lines.append(f"        self.{field.name} = {factory_name}()")
            else:
                lines.append("        return False")
            lines.append("    else:")
            if not emit(field_type, raw, value, "        "):
                return None
            lines.append(f"        self.{field.name} = {value}")

    lines.append("    return True")
    fast_locals = ", ".join(f"{name}={name}" for name in namespace)
    if fast_locals:
        lines[0] = f"def __modmex_compiled_init__(self, kwargs, {fast_locals}):"
    exec("\n".join(lines), namespace)
    return namespace["__modmex_compiled_init__"]


def _build_compiled_dump(
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

    namespace: dict[str, Any] = {
        "_Enum": Enum,
        "_Decimal": Decimal,
        "_date": date,
        "_datetime": datetime,
        "_time": time,
        "_timedelta": timedelta,
        "_float": float,
        "_isinstance": isinstance,
        "_scalar_types": (str, int, float, bool),
        "_serialize_value": serialize_value,
    }
    lines = ["def __modmex_compiled_dump__(self):"]
    counter = [0]

    def temp(prefix: str) -> str:
        counter[0] += 1
        return f"_{prefix}_{counter[0]}"

    def emit(expected_type: Any, source: str, target: str, indent: str) -> bool:
        if isinstance(expected_type, str):
            expected_type = typing.ForwardRef(expected_type)
        if isinstance(expected_type, typing.ForwardRef):
            try:
                expected_type = expected_type._evaluate(globalns, None, recursive_guard=set())
            except Exception:
                return False

        if expected_type in (Any, str, int, float, bool):
            lines.append(f"{indent}{target} = {source}")
            return True
        if expected_type is datetime or expected_type is date or expected_type is time:
            lines.append(f"{indent}{target} = {source}.isoformat()")
            return True
        if expected_type is timedelta:
            lines.append(f"{indent}{target} = {source}.total_seconds()")
            return True
        if expected_type is Decimal:
            lines.append(f"{indent}{target} = _float({source})")
            return True
        if isinstance(expected_type, type):
            if issubclass(expected_type, Enum):
                enum_values = temp("enum_values")
                namespace[enum_values] = {member: member.value for member in expected_type}
                lines.append(f"{indent}{target} = {enum_values}[{source}]")
                return True
            if issubclass(expected_type, base_model_type):
                dump_name = temp("dump")
                namespace[dump_name] = _compiled_dump_for(expected_type, profile, base_model_type)
                lines.append(f"{indent}if {dump_name} is not None:")
                lines.append(f"{indent}    {target} = {dump_name}({source})")
                lines.append(f"{indent}else:")
                if profile is None:
                    lines.append(f"{indent}    {target} = {source}.model_dump()")
                else:
                    profile_name = temp("profile")
                    namespace[profile_name] = profile
                    lines.append(f"{indent}    {target} = {source}.model_dump(profile={profile_name})")
                return True
            return False

        origin = get_origin(expected_type)
        if origin is list:
            inner_type = _first_arg(expected_type, Any)
            item = temp("item")
            dumped = temp("dumped")
            lines.append(f"{indent}{target} = []")
            lines.append(f"{indent}for {item} in {source}:")
            if not emit(inner_type, item, dumped, indent + "    "):
                return False
            lines.append(f"{indent}    {target}.append({dumped})")
            return True
        if origin is dict:
            _key_type, value_type = _dict_args(expected_type)
            key = temp("key")
            item = temp("item")
            dumped = temp("dumped")
            lines.append(f"{indent}{target} = {{}}")
            lines.append(f"{indent}for {key}, {item} in {source}.items():")
            if not emit(value_type, item, dumped, indent + "    "):
                return False
            lines.append(f"{indent}    {target}[{key}] = {dumped}")
            return True
        if origin is Literal:
            lines.append(f"{indent}{target} = {source}")
            return True
        if origin in (typing.Union, types.UnionType):
            args = get_args(expected_type)
            non_none_args = tuple(arg for arg in args if arg is not type(None))
            if len(non_none_args) == 1 and len(non_none_args) != len(args):
                lines.append(f"{indent}if {source} is None:")
                lines.append(f"{indent}    {target} = None")
                lines.append(f"{indent}else:")
                return emit(non_none_args[0], source, target, indent + "    ")
            return False
        return False

    output_items: list[tuple[str, str]] = []
    for field in model_fields:
        if should_exclude_field(field, None, profile, False):
            continue
        field_type = type_hints.get(field.name, field.type)
        value = temp("value")
        dumped = temp("dumped")
        lines.append(f"    {value} = self.{field.name}")
        default_fast_types = (datetime, date, time, timedelta, Decimal)
        if field.default is not MISSING and field_type in default_fast_types:
            default_name = temp("default")
            serialized_default_name = temp("serialized_default")
            namespace[default_name] = field.default
            namespace[serialized_default_name] = serialize_value(field.default)
            lines.append(f"    if {value} == {default_name}:")
            lines.append(f"        {dumped} = {serialized_default_name}")
            lines.append("    else:")
            if not emit(field_type, value, dumped, "        "):
                return None
        elif not emit(field_type, value, dumped, "    "):
            return None
        output_items.append((field.name, dumped))

    for attr_name in getattr(model_cls, "__modmex_properties__", ()):
        prop_value = temp("prop")
        prop_dumped = temp("prop_dumped")
        lines.append(f"    {prop_value} = self.{attr_name}")
        lines.append(f"    {prop_dumped} = {prop_value} if {prop_value} is None or type({prop_value}) in _scalar_types else _serialize_value({prop_value})")
        output_items.append((attr_name, prop_dumped))

    return_items = ", ".join(f"{name!r}: {value}" for name, value in output_items)
    lines.append(f"    return {{{return_items}}}")
    exec("\n".join(lines), namespace)
    return namespace["__modmex_compiled_dump__"]


def _compiled_dump_for(
    model_cls: type[Any],
    profile: str | None,
    base_model_type: type[Any],
) -> Callable[[Any], dict[str, Any]] | None:
    cache = getattr(model_cls, "__modmex_compiled_dump_cache__", None)
    if cache is None:
        return None
    if profile not in cache:
        cache[profile] = _build_compiled_dump(model_cls, model_cls.__modmex_fields__, base_model_type, profile)
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
            if core is not None and schema and getattr(expected_type, "__modmex_rust_fast_init__", False):
                return (NODE_MODEL, expected_type, schema, expected_type._modmex_from_trusted_kwargs, core)
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


