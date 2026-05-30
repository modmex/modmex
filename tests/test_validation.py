from __future__ import annotations

from dataclasses import field
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, ForwardRef, Generic, Literal, Optional, TypeVar

import pytest

from modmex import BaseModel
from modmex.errors import ValidationError
from modmex import validation as validation_module
from modmex.validation import bool_validator, decimal_validator, float_validator, validate_model_fields


class Role(Enum):
    USER = "user"


class Child(BaseModel):
    code: int


class ComplexModel(BaseModel):
    values: list[int] = field(default_factory=list)
    fixed_pair: tuple[int, str] = (1, "ok")
    options: frozenset[int] = frozenset()
    chooser: Literal["a", "b"] = "a"
    maybe_number: Optional[int] = None
    callback: Callable[..., object] = lambda: None
    role: Role = Role.USER
    child: Child = field(default_factory=lambda: Child(code=1))


def test_bool_and_decimal_validators_cover_edge_cases() -> None:
    assert bool_validator(b"YES") is True
    assert bool_validator("off") is False
    assert decimal_validator("10.50") == Decimal("10.50")

    with pytest.raises(ValueError, match="invalid bool"):
        bool_validator({})

    with pytest.raises(ValueError, match="decimal is not finite"):
        decimal_validator("NaN")


def test_validate_model_fields_reports_multiple_type_errors() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ComplexModel(
            values=["1", "bad"],
            fixed_pair=(1, "ok", "extra"),
            options=frozenset({"1", "bad"}),
            chooser="c",
            maybe_number="not-int",
            callback="not-callable",
            child={"code": "bad"},
        )

    locations = {tuple(error["loc"]) for error in exc_info.value.errors}

    assert ("values", 1) in locations
    assert ("fixed_pair",) in locations
    assert ("options", 0) in locations or ("options", 1) in locations
    assert ("chooser",) in locations
    assert ("maybe_number",) in locations
    assert ("callback",) in locations
    assert ("child", "code") in locations


def test_validate_model_fields_handles_none_type_and_enum_parsing() -> None:
    class NoneAndEnumModel(BaseModel):
        maybe_number: Optional[int] = None
        role: Role = Role.USER

    model = NoneAndEnumModel(maybe_number=None, role="user")

    assert model.maybe_number is None
    assert model.role is Role.USER

    with pytest.raises(ValidationError) as exc_info:
        NoneAndEnumModel(maybe_number="x", role="missing")

    locations = {tuple(error["loc"]) for error in exc_info.value.errors}
    assert ("maybe_number",) in locations
    assert ("role",) in locations


def test_low_level_validators_and_type_paths() -> None:
    class Label(Enum):
        ADMIN = "admin"

    assert validation_module.is_none_type(type(None))
    assert validation_module.str_validator(Label.ADMIN) == "admin"
    assert validation_module.str_validator(bytearray(b"x")) == "x"
    assert bool_validator(True) is True
    with pytest.raises(ValueError, match="invalid bool"):
        bool_validator(object())

    assert float_validator(1.5) == 1.5
    with pytest.raises(ValueError, match="invalid float"):
        float_validator("x")

    assert decimal_validator(b"10.5") == Decimal("10.5")
    with pytest.raises(ValueError, match="invalid decimal"):
        decimal_validator("bad")

    assert validation_module.callable_validator(lambda: None) is not None


def test_validate_types_low_level_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    globalns = globals().copy()

    class ValueErrorCtor:
        def __init__(self, value: object) -> None:
            raise ValueError("bad ctor")

    class TypeErrorCtor:
        def __init__(self, value: object) -> None:
            raise TypeError("bad ctor")

    class DataclassTypeError(BaseModel):
        req: int

    tvar = TypeVar("tvar")

    class UnknownOrigin(Generic[tvar]):
        pass

    assert validation_module._validate_simple_type(Any, "x", ["f"]) == "x"
    assert validation_module._evaluate_forward_reference(ForwardRef("int"), globals()) is int
    assert validation_module._validate_tuple(tuple, (1, 2), strict=False, globalns=globalns, loc=["t"]) == (1, 2)
    assert validation_module._validate_tuple(tuple[int, ...], ("1", 2), strict=False, globalns=globalns, loc=["t"]) == (1, 2)
    assert validation_module._validate_tuple(tuple[int, str], ("1", 2), strict=False, globalns=globalns, loc=["t"]) == (1, "2")
    assert validation_module._validate_dict(dict, {"a": "1"}, strict=False, globalns=globalns, loc=["d"]) == {"a": "1"}
    assert validation_module._validate_types("int", "1", strict=False, globalns=globalns, loc=["s"]) == 1
    any_sentinel = object()
    monkeypatch.setattr(validation_module, "Any", any_sentinel)
    assert validation_module._validate_types(any_sentinel, "value", strict=False, globalns=globalns, loc=["a"]) == "value"
    assert validation_module._validate_types(set[int], {"1"}, strict=False, globalns=globalns, loc=["set"]) == {1}
    assert validation_module._validate_types(123, "value", strict=False, globalns=globalns, loc=["u"]) == "value"

    with pytest.raises(ValidationError, match="must be a list"):
        validation_module._validate_list(list[int], "x", strict=False, globalns=globalns, loc=["l"])
    with pytest.raises(ValidationError, match="must be a tuple"):
        validation_module._validate_tuple(tuple[int], "x", strict=False, globalns=globalns, loc=["t"])
    with pytest.raises(ValidationError, match="must be a dict"):
        validation_module._validate_dict(dict[str, int], "x", strict=False, globalns=globalns, loc=["d"])
    with pytest.raises(ValidationError, match="must be a set"):
        validation_module._validate_set(set[int], "x", strict=False, globalns=globalns, loc=["s"])
    with pytest.raises(ValidationError, match="must be a frozenset"):
        validation_module._validate_types(frozenset[int], {"1"}, strict=False, globalns=globalns, loc=["f"])

    with pytest.raises(ValidationError, match="bad ctor"):
        validation_module._validate_simple_type(ValueErrorCtor, "x", ["v"])
    with pytest.raises(ValidationError, match="Error instantiating TypeErrorCtor"):
        validation_module._validate_simple_type(TypeErrorCtor, "x", ["v"])
    with pytest.raises(ValidationError, match="missing 1 required keyword-only argument"):
        validation_module._validate_simple_type(DataclassTypeError, {}, ["v"])

    assert validation_module._dict_args(dict) == (validation_module.Any, validation_module.Any)
    assert validation_module._validate_types(UnknownOrigin[int], "value", strict=False, globalns=globalns, loc=["u"]) == "value"
    with pytest.raises(RuntimeError, match="Unknown type"):
        validation_module._validate_types(UnknownOrigin[int], "value", strict=True, globalns=globalns, loc=["u"])
    with pytest.raises(RuntimeError, match="Unknown type"):
        validation_module._validate_types(123, "value", strict=True, globalns=globalns, loc=["u"])

    monkeypatch.setattr(validation_module, "get_args", lambda _expected: ())
    with pytest.raises(ValidationError, match="must be an instance"):
        validation_module._validate_union(object(), "value", strict=False, globalns=globalns, loc=["u"])

    monkeypatch.setattr(validation_module.sys, "version_info", (3, 8, 0))
    with pytest.raises(TypeError):
        validation_module._evaluate_forward_reference(ForwardRef("int"), globals())


def test_validate_model_fields_fallback_and_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class Raw(BaseModel):
        amount: int

    original_get_type_hints = validation_module.typing.get_type_hints
    original_validate_types = validation_module._validate_types

    def raising_get_type_hints(*args: object, **kwargs: object) -> dict[str, object]:
        raise RuntimeError("boom")

    def raising_validate_types(*args: object, **kwargs: object) -> object:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(validation_module.typing, "get_type_hints", raising_get_type_hints)
    monkeypatch.setattr(validation_module, "_validate_types", raising_validate_types)

    try:
        with pytest.raises(ValidationError) as exc_info:
            validate_model_fields(Raw(amount=1))
    finally:
        monkeypatch.setattr(validation_module.typing, "get_type_hints", original_get_type_hints)
        monkeypatch.setattr(validation_module, "_validate_types", original_validate_types)

    assert exc_info.value.errors[0]["type"] == "unexpected_error"
