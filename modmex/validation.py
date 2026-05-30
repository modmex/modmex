"""Type coercion and validation helpers for dataclass-backed models."""

from __future__ import annotations

import dataclasses
import sys
import types
import typing
from collections.abc import Callable as CallableABC
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal, DecimalException
from enum import Enum
from typing import Any, Callable, Literal, get_args, get_origin

from .datetime_parser import parse_date, parse_datetime, parse_duration, parse_time
from .errors import ValidationError

GlobalNS_T = dict[str, Any]
Loc = list[str | int]

NoneType = type(None)
_NONE_TYPES: tuple[Any, ...] = (None, NoneType, Literal[None])


def is_none_type(tp: Any) -> bool:
    """Return whether ``tp`` represents ``None`` in a type annotation."""
    return tp in _NONE_TYPES


def str_validator(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, (float, int, Decimal)):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode()
    raise ValueError("invalid str")


def int_validator(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"'{value}' is not a valid integer") from exc


BOOL_FALSE = {0, "0", "off", "f", "false", "n", "no"}
BOOL_TRUE = {1, "1", "on", "t", "true", "y", "yes"}


def bool_validator(value: Any) -> bool:
    if value is True or value is False:
        return value
    if isinstance(value, bytes):
        value = value.decode()
    if isinstance(value, str):
        value = value.lower()
    try:
        if value in BOOL_TRUE:
            return True
        if value in BOOL_FALSE:
            return False
    except TypeError as exc:
        raise ValueError("invalid bool") from exc
    raise ValueError("invalid bool")


def float_validator(value: Any) -> float:
    if isinstance(value, float):
        return value
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid float") from exc


def decimal_validator(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()

    try:
        decimal_value = Decimal(str(value).strip())
    except DecimalException as exc:
        raise ValueError("invalid decimal") from exc

    if not decimal_value.is_finite():
        raise ValueError("decimal is not finite")
    return decimal_value


def callable_validator(value: Any) -> Callable[..., Any]:
    if callable(value):
        return value
    raise ValueError("invalid callable")


_VALIDATORS: dict[Any, Callable[[Any], Any]] = {
    str: str_validator,
    int: int_validator,
    bool: bool_validator,
    float: float_validator,
    datetime: parse_datetime,
    date: parse_date,
    time: parse_time,
    timedelta: parse_duration,
    Decimal: decimal_validator,
    Callable: callable_validator,
}


def _error(loc: Loc, message: str, error_type: str = "value_error") -> ValidationError:
    return ValidationError(errors=[{"loc": loc, "msg": message, "type": error_type}])


def _merge_nested_errors(loc: Loc, exc: ValidationError) -> ValidationError:
    return ValidationError(
        errors=[
            {
                "loc": loc + list(error.get("loc", [])),
                "msg": error.get("msg", str(error)),
                "type": error.get("type", "type_error"),
            }
            for error in exc.errors
        ]
    )


def _evaluate_forward_reference(ref_type: typing.ForwardRef, globalns: GlobalNS_T) -> Any:
    if sys.version_info < (3, 9):
        return ref_type._evaluate(globalns, None)
    return ref_type._evaluate(globalns, None, recursive_guard=set())


def _validate_simple_type(expected_type: type[Any], value: Any, loc: Loc) -> Any:
    if expected_type in _VALIDATORS:
        try:
            return _VALIDATORS[expected_type](value)
        except ValueError as exc:
            raise _error(loc, str(exc)) from exc

    if expected_type is Any:
        return value

    if isinstance(expected_type, type) and issubclass(expected_type, Enum):
        if isinstance(value, expected_type):
            return value
        try:
            return expected_type(value)
        except ValueError as exc:
            raise _error(loc, str(exc)) from exc

    if isinstance(value, expected_type):
        return value

    if dataclasses.is_dataclass(expected_type) and isinstance(value, Mapping):
        try:
            return expected_type(**value)
        except ValidationError as exc:
            raise _merge_nested_errors(loc, exc) from exc
        except TypeError as exc:
            raise _error(loc, str(exc), "type_error") from exc

    try:
        return expected_type(value)
    except ValueError as exc:
        raise _error(loc, str(exc)) from exc
    except TypeError as exc:
        raise _error(loc, f"Error instantiating {expected_type.__name__}: {exc}", "type_error") from exc


def _validate_list(expected_type: Any, value: Any, strict: bool, globalns: GlobalNS_T, loc: Loc) -> list[Any]:
    if not isinstance(value, list):
        raise _error(loc, "must be a list", "type_error.list")

    item_type = _first_arg(expected_type, Any)
    return [
        _validate_types(item_type, item, strict, globalns, loc + [index])
        for index, item in enumerate(value)
    ]


def _validate_tuple(expected_type: Any, value: Any, strict: bool, globalns: GlobalNS_T, loc: Loc) -> tuple[Any, ...]:
    if not isinstance(value, tuple):
        raise _error(loc, "must be a tuple", "type_error.tuple")

    args = get_args(expected_type)
    if not args:
        return value
    if len(args) == 2 and args[1] is Ellipsis:
        return tuple(
            _validate_types(args[0], item, strict, globalns, loc + [index])
            for index, item in enumerate(value)
        )
    if len(args) != len(value):
        raise _error(loc, f"expected {len(args)} items, received {len(value)}", "value_error.tuple.length")
    return tuple(
        _validate_types(item_type, item, strict, globalns, loc + [index])
        for index, (item_type, item) in enumerate(zip(args, value))
    )


def _validate_dict(expected_type: Any, value: Any, strict: bool, globalns: GlobalNS_T, loc: Loc) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise _error(loc, "must be a dict", "type_error.dict")

    key_type, value_type = _dict_args(expected_type)
    return {
        _validate_types(key_type, key, strict, globalns, loc + [key]): _validate_types(
            value_type,
            item,
            strict,
            globalns,
            loc + [key],
        )
        for key, item in value.items()
    }


def _validate_set(expected_type: Any, value: Any, strict: bool, globalns: GlobalNS_T, loc: Loc) -> set[Any]:
    if not isinstance(value, set):
        raise _error(loc, "must be a set", "type_error.set")

    item_type = _first_arg(expected_type, Any)
    return {
        _validate_types(item_type, item, strict, globalns, loc + [index])
        for index, item in enumerate(value)
    }


def _validate_literal(expected_type: Any, value: Any, loc: Loc) -> Any:
    allowed = get_args(expected_type)
    if value not in allowed:
        values = ", ".join(map(str, allowed))
        raise _error(loc, f"must be one of [{values}] but received {value}", "value_error.literal")
    return value


def _validate_union(expected_type: Any, value: Any, strict: bool, globalns: GlobalNS_T, loc: Loc) -> Any:
    errors: list[dict[str, Any]] = []
    for item_type in get_args(expected_type):
        try:
            return _validate_types(item_type, value, strict, globalns, loc)
        except ValidationError as exc:
            errors.extend(exc.errors)

    if errors:
        raise ValidationError(errors=errors)
    raise _error(loc, f"must be an instance of {expected_type}, but received {value}", "type_error.union")


def _first_arg(expected_type: Any, default: Any) -> Any:
    args = get_args(expected_type)
    return args[0] if args else default


def _dict_args(expected_type: Any) -> tuple[Any, Any]:
    args = get_args(expected_type)
    if len(args) == 2:
        return args
    return Any, Any


def _validate_types(expected_type: Any, value: Any, strict: bool, globalns: GlobalNS_T, loc: Loc | None = None) -> Any:
    loc = loc or []

    if isinstance(expected_type, str):
        expected_type = typing.ForwardRef(expected_type)

    if isinstance(expected_type, typing.ForwardRef):
        expected_type = _evaluate_forward_reference(expected_type, globalns)

    if is_none_type(expected_type):
        if value is None:
            return None
        raise _error(loc, f"{value} is not a valid none value", "value_error.none")

    origin = get_origin(expected_type)
    if origin is None:
        if isinstance(expected_type, type):
            return _validate_simple_type(expected_type, value, loc)
        if expected_type is Any:
            return value
        if strict:
            raise RuntimeError(f"Unknown type of {expected_type}")
        return value

    if origin is list:
        return _validate_list(expected_type, value, strict, globalns, loc)
    if origin is tuple:
        return _validate_tuple(expected_type, value, strict, globalns, loc)
    if origin is dict:
        return _validate_dict(expected_type, value, strict, globalns, loc)
    if origin is set:
        return _validate_set(expected_type, value, strict, globalns, loc)
    if origin is frozenset:
        if not isinstance(value, frozenset):
            raise _error(loc, "must be a frozenset", "type_error.frozenset")
        return frozenset(_validate_set(expected_type, set(value), strict, globalns, loc))
    if origin is Literal:
        return _validate_literal(expected_type, value, loc)
    if origin in (typing.Union, types.UnionType):
        return _validate_union(expected_type, value, strict, globalns, loc)
    if origin in (Callable, CallableABC):
        return callable_validator(value)

    if strict:
        raise RuntimeError(f"Unknown type of {expected_type}")
    return value


def validate_model_fields(target: Any, strict: bool = False) -> None:
    """Coerce and validate all dataclass fields on ``target`` in place."""
    globalns = sys.modules[target.__module__].__dict__.copy()
    try:
        type_hints = typing.get_type_hints(target.__class__, globalns=globalns, include_extras=True)
    except Exception:
        type_hints = {}
    errors: list[dict[str, Any]] = []

    for field in dataclasses.fields(target):
        value = getattr(target, field.name)
        expected_type = type_hints.get(field.name, field.type)
        try:
            validated = _validate_types(expected_type, value, strict, globalns, loc=[field.name])
            setattr(target, field.name, validated)
        except ValidationError as exc:
            errors.extend(exc.errors)
        except Exception as exc:
            errors.append({"loc": [field.name], "msg": str(exc), "type": "unexpected_error"})

    if errors:
        raise ValidationError(errors=errors)
