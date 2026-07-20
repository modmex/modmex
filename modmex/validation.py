"""Type coercion and validation helpers for dataclass-backed models."""

from __future__ import annotations

import dataclasses
import functools
import re
import sys
import types
import typing
from collections.abc import Callable as CallableABC
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal, DecimalException, InvalidOperation
from enum import Enum
from typing import Any, Callable, Literal, get_args, get_origin

from .datetime_parser import parse_date, parse_datetime, parse_duration, parse_time
from .errors import ValidationError
from .fields import field_constraints

GlobalNS_T = dict[str, Any]
Loc = list[str | int]
ValueValidator = Callable[[Any, Loc], Any]
ConstraintValidator = Callable[[Any, Loc], None]
ConstraintValidators = tuple[ConstraintValidator, ...]

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


def _compile_simple_type(expected_type: type[Any]) -> ValueValidator:
    validator = _VALIDATORS.get(expected_type)
    if validator is not None:

        def validate_known_type(value: Any, loc: Loc) -> Any:
            try:
                return validator(value)
            except ValueError as exc:
                raise _error(loc, str(exc)) from exc

        return validate_known_type

    if expected_type is Any:
        return lambda value, loc: value

    if isinstance(expected_type, type) and issubclass(expected_type, Enum):

        def validate_enum(value: Any, loc: Loc) -> Any:
            if isinstance(value, expected_type):
                return value
            try:
                return expected_type(value)
            except ValueError as exc:
                raise _error(loc, str(exc)) from exc

        return validate_enum

    if dataclasses.is_dataclass(expected_type):

        def validate_dataclass(value: Any, loc: Loc) -> Any:
            if isinstance(value, expected_type):
                return value
            if isinstance(value, Mapping):
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

        return validate_dataclass

    def validate_instance_or_coerce(value: Any, loc: Loc) -> Any:
        if isinstance(value, expected_type):
            return value
        try:
            return expected_type(value)
        except ValueError as exc:
            raise _error(loc, str(exc)) from exc
        except TypeError as exc:
            raise _error(loc, f"Error instantiating {expected_type.__name__}: {exc}", "type_error") from exc

    return validate_instance_or_coerce


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
    union_types = get_args(expected_type)
    if value is None and any(is_none_type(item_type) for item_type in union_types):
        return None

    errors: list[dict[str, Any]] = []
    for item_type in union_types:
        try:
            return _validate_types(item_type, value, strict, globalns, loc)
        except ValidationError as exc:
            errors.extend(exc.errors)

    if errors:
        raise ValidationError(errors=errors)
    raise _error(loc, f"must be an instance of {expected_type}, but received {value}", "type_error.union")


def _compile_validator(expected_type: Any, strict: bool, globalns: GlobalNS_T) -> ValueValidator:
    if isinstance(expected_type, str):
        expected_type = typing.ForwardRef(expected_type)

    if isinstance(expected_type, typing.ForwardRef):
        expected_type = _evaluate_forward_reference(expected_type, globalns)

    if is_none_type(expected_type):

        def validate_none(value: Any, loc: Loc) -> None:
            if value is None:
                return None
            raise _error(loc, f"{value} is not a valid none value", "value_error.none")

        return validate_none

    origin = get_origin(expected_type)
    if origin is None:
        if isinstance(expected_type, type):
            return _compile_simple_type(expected_type)
        if expected_type is Any:
            return lambda value, loc: value
        if strict:
            raise RuntimeError(f"Unknown type of {expected_type}")
        return lambda value, loc: value

    if origin is list:
        item_validator = _compile_validator(_first_arg(expected_type, Any), strict, globalns)

        def validate_list(value: Any, loc: Loc) -> list[Any]:
            if not isinstance(value, list):
                raise _error(loc, "must be a list", "type_error.list")
            return [item_validator(item, loc + [index]) for index, item in enumerate(value)]

        return validate_list

    if origin is tuple:
        args = get_args(expected_type)
        if not args:

            def validate_tuple_any(value: Any, loc: Loc) -> tuple[Any, ...]:
                if not isinstance(value, tuple):
                    raise _error(loc, "must be a tuple", "type_error.tuple")
                return value

            return validate_tuple_any
        if len(args) == 2 and args[1] is Ellipsis:
            item_validator = _compile_validator(args[0], strict, globalns)

            def validate_variable_tuple(value: Any, loc: Loc) -> tuple[Any, ...]:
                if not isinstance(value, tuple):
                    raise _error(loc, "must be a tuple", "type_error.tuple")
                return tuple(item_validator(item, loc + [index]) for index, item in enumerate(value))

            return validate_variable_tuple

        item_validators = tuple(_compile_validator(item_type, strict, globalns) for item_type in args)

        def validate_fixed_tuple(value: Any, loc: Loc) -> tuple[Any, ...]:
            if not isinstance(value, tuple):
                raise _error(loc, "must be a tuple", "type_error.tuple")
            if len(item_validators) != len(value):
                raise _error(loc, f"expected {len(item_validators)} items, received {len(value)}", "value_error.tuple.length")
            return tuple(
                item_validator(item, loc + [index])
                for index, (item_validator, item) in enumerate(zip(item_validators, value))
            )

        return validate_fixed_tuple

    if origin is dict:
        key_type, value_type = _dict_args(expected_type)
        key_validator = _compile_validator(key_type, strict, globalns)
        value_validator = _compile_validator(value_type, strict, globalns)

        def validate_dict(value: Any, loc: Loc) -> dict[Any, Any]:
            if not isinstance(value, dict):
                raise _error(loc, "must be a dict", "type_error.dict")
            return {
                key_validator(key, loc + [key]): value_validator(item, loc + [key])
                for key, item in value.items()
            }

        return validate_dict

    if origin is set:
        item_validator = _compile_validator(_first_arg(expected_type, Any), strict, globalns)

        def validate_set(value: Any, loc: Loc) -> set[Any]:
            if not isinstance(value, set):
                raise _error(loc, "must be a set", "type_error.set")
            return {item_validator(item, loc + [index]) for index, item in enumerate(value)}

        return validate_set

    if origin is frozenset:
        item_validator = _compile_validator(_first_arg(expected_type, Any), strict, globalns)

        def validate_frozenset(value: Any, loc: Loc) -> frozenset[Any]:
            if not isinstance(value, frozenset):
                raise _error(loc, "must be a frozenset", "type_error.frozenset")
            return frozenset(item_validator(item, loc + [index]) for index, item in enumerate(value))

        return validate_frozenset

    if origin is Literal:
        allowed = get_args(expected_type)
        values = ", ".join(map(str, allowed))

        def validate_literal(value: Any, loc: Loc) -> Any:
            if value not in allowed:
                raise _error(loc, f"must be one of [{values}] but received {value}", "value_error.literal")
            return value

        return validate_literal

    if origin in (typing.Union, types.UnionType):
        union_types = get_args(expected_type)
        accepts_none = any(is_none_type(item_type) for item_type in union_types)
        item_validators = tuple(_compile_validator(item_type, strict, globalns) for item_type in union_types)

        def validate_union(value: Any, loc: Loc) -> Any:
            if value is None and accepts_none:
                return None

            errors: list[dict[str, Any]] = []
            for item_validator in item_validators:
                try:
                    return item_validator(value, loc)
                except ValidationError as exc:
                    errors.extend(exc.errors)
            if errors:
                raise ValidationError(errors=errors)
            raise _error(loc, f"must be an instance of {expected_type}, but received {value}", "type_error.union")

        return validate_union

    if origin in (Callable, CallableABC):
        return lambda value, loc: callable_validator(value)

    if strict:
        raise RuntimeError(f"Unknown type of {expected_type}")
    return lambda value, loc: value


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


@functools.lru_cache(maxsize=None)
def _validation_schema(
    model_cls: type[Any],
    strict: bool = False,
) -> tuple[tuple[str, ValueValidator, ConstraintValidators], ...]:
    globalns = sys.modules[model_cls.__module__].__dict__
    try:
        type_hints = typing.get_type_hints(model_cls, globalns=globalns, include_extras=True)
    except Exception:
        type_hints = {}
    return tuple(
        (
            field.name,
            _compile_validator(type_hints.get(field.name, field.type), strict, globalns),
            _compile_constraints(field),
        )
        for field in dataclasses.fields(model_cls)
    )


def _compile_constraints(field: dataclasses.Field[Any]) -> ConstraintValidators:
    constraints = field_constraints(field)
    gt = constraints.get("gt")
    ge = constraints.get("ge")
    lt = constraints.get("lt")
    le = constraints.get("le")
    min_length = constraints.get("min_length")
    max_length = constraints.get("max_length")
    pattern = constraints.get("pattern")
    multiple_of = constraints.get("multiple_of")
    max_digits = constraints.get("max_digits")
    decimal_places = constraints.get("decimal_places")

    regex = re.compile(pattern) if pattern is not None else None

    if all(
        constraint is None
        for constraint in (
            gt,
            ge,
            lt,
            le,
            min_length,
            max_length,
            pattern,
            multiple_of,
            max_digits,
            decimal_places,
        )
    ):
        return ()

    def validate_constraints(value: Any, loc: Loc) -> None:
        if gt is not None and not value > gt:
            raise _error(loc, f"must be > {gt}", "value_error.number.not_gt")
        if ge is not None and not value >= ge:
            raise _error(loc, f"must be >= {ge}", "value_error.number.not_ge")
        if lt is not None and not value < lt:
            raise _error(loc, f"must be < {lt}", "value_error.number.not_lt")
        if le is not None and not value <= le:
            raise _error(loc, f"must be <= {le}", "value_error.number.not_le")

        if min_length is not None or max_length is not None:
            try:
                current_length = len(value)
            except TypeError as exc:
                raise _error(loc, "value has no length", "type_error.length") from exc

            if min_length is not None and current_length < min_length:
                raise _error(loc, f"length must be >= {min_length}", "value_error.any_str.min_length")
            if max_length is not None and current_length > max_length:
                raise _error(loc, f"length must be <= {max_length}", "value_error.any_str.max_length")

        if regex is not None:
            if not isinstance(value, str):
                raise _error(loc, "value must be a string for pattern validation", "type_error.pattern")
            if regex.search(value) is None:
                raise _error(loc, f"must match pattern '{pattern}'", "value_error.str.pattern")

        if multiple_of is not None:
            try:
                value_decimal = Decimal(str(value))
                multiple_decimal = Decimal(str(multiple_of))
                if value_decimal % multiple_decimal != 0:
                    raise _error(loc, f"must be a multiple of {multiple_of}", "value_error.number.not_multiple_of")
            except (InvalidOperation, ValueError) as exc:
                if isinstance(exc, ValidationError):
                    raise
                raise _error(loc, "value must be numeric for multiple_of", "type_error.number") from exc

        if max_digits is not None or decimal_places is not None:
            try:
                decimal_value = Decimal(str(value))
            except (InvalidOperation, ValueError) as exc:
                raise _error(loc, "value must be numeric for decimal constraints", "type_error.decimal") from exc

            if decimal_value.is_zero():
                digits_count = 1
                decimals_count = 0
            else:
                sign, digits, exponent = decimal_value.as_tuple()
                digits_count = len(digits)
                decimals_count = -exponent if exponent < 0 else 0
                if exponent > 0:
                    digits_count += exponent

            if max_digits is not None and digits_count > max_digits:
                raise _error(loc, f"must have at most {max_digits} digits", "value_error.decimal.max_digits")
            if decimal_places is not None and decimals_count > decimal_places:
                raise _error(
                    loc,
                    f"must have at most {decimal_places} decimal places",
                    "value_error.decimal.max_places",
                )

    return (validate_constraints,)


def _apply_constraints(value: Any, loc: Loc, constraints: ConstraintValidators) -> None:
    for constraint_validator in constraints:
        constraint_validator(value, loc)


def validate_model_fields(target: Any, strict: bool = False) -> None:
    """Coerce and validate all dataclass fields on ``target`` in place."""
    validators = _validation_schema(type(target), strict)
    errors: list[dict[str, Any]] = []

    for field_name, validator, constraints in validators:
        value = getattr(target, field_name)
        try:
            validated = validator(value, [field_name])
            _apply_constraints(validated, [field_name], constraints)
            setattr(target, field_name, validated)
        except ValidationError as exc:
            errors.extend(exc.errors)
        except Exception as exc:
            errors.append({"loc": [field_name], "msg": str(exc), "type": "unexpected_error"})

    if errors:
        raise ValidationError(errors=errors)


@functools.lru_cache(maxsize=None)
def _constraint_schema(model_cls: type[Any]) -> tuple[tuple[str, ConstraintValidators], ...]:
    return tuple((field.name, _compile_constraints(field)) for field in dataclasses.fields(model_cls))


def validate_model_constraints(target: Any) -> None:
    """Validate only declared field constraints on ``target`` in place."""
    constraints_schema = _constraint_schema(type(target))
    errors: list[dict[str, Any]] = []

    for field_name, constraints in constraints_schema:
        if not constraints:
            continue
        value = getattr(target, field_name)
        try:
            _apply_constraints(value, [field_name], constraints)
        except ValidationError as exc:
            errors.extend(exc.errors)
        except Exception as exc:
            errors.append({"loc": [field_name], "msg": str(exc), "type": "unexpected_error"})

    if errors:
        raise ValidationError(errors=errors)
