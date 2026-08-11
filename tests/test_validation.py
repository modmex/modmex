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


def test_union_preserves_exact_runtime_types_before_coercion() -> None:
    class IdentifierModel(BaseModel):
        value: str | int

    assert IdentifierModel(value=42).value == 42
    assert type(IdentifierModel(value=42).value) is int
    assert IdentifierModel(value="42").value == "42"
    assert type(IdentifierModel(value="42").value) is str


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
    original_int_validator = validation_module._VALIDATORS[int]
    validation_module._validation_schema.cache_clear()

    def raising_get_type_hints(*args: object, **kwargs: object) -> dict[str, object]:
        raise RuntimeError("boom")

    def raising_int_validator(value: object) -> object:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(validation_module.typing, "get_type_hints", raising_get_type_hints)
    validation_module._VALIDATORS[int] = raising_int_validator

    try:
        with pytest.raises(ValidationError) as exc_info:
            validate_model_fields(Raw(amount=1))
    finally:
        monkeypatch.setattr(validation_module.typing, "get_type_hints", original_get_type_hints)
        validation_module._VALIDATORS[int] = original_int_validator
        validation_module._validation_schema.cache_clear()

    assert exc_info.value.errors[0]["type"] == "unexpected_error"


def test_validate_simple_type_covers_direct_branches() -> None:
    class Status(Enum):
        ACTIVE = "active"

    @validation_module.dataclasses.dataclass
    class Pair:
        left: int
        right: int

    class Box:
        def __init__(self, value: object) -> None:
            self.value = value

    token = object()
    assert validation_module._validate_simple_type(Any, token, ["any"]) is token

    active = Status.ACTIVE
    assert validation_module._validate_simple_type(Status, active, ["enum"]) is active

    box = Box("kept")
    assert validation_module._validate_simple_type(Box, box, ["box"]) is box

    with pytest.raises(ValidationError, match="missing 1 required positional argument"):
        validation_module._validate_simple_type(Pair, {"left": 1}, ["pair"])


def test_compile_validator_and_compile_simple_type_branch_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    globalns = globals().copy()

    @validation_module.dataclasses.dataclass
    class Pair:
        left: int
        right: int

    @validation_module.dataclasses.dataclass
    class StrictValue:
        value: Any

        def __post_init__(self) -> None:
            if self.value == "boom":
                raise ValueError("boom")

    class Coercible:
        def __init__(self, value: object) -> None:
            if value == "bad":
                raise ValueError("bad")
            if value is None:
                raise TypeError("missing")
            self.value = int(value)

    class ChildType(BaseModel):
        code: int

    dataclass_validator = validation_module._compile_simple_type(ChildType)
    child = ChildType(code=1)
    assert dataclass_validator(child, ["child"]) is child
    assert dataclass_validator({"code": "2"}, ["child"]).code == 2

    with pytest.raises(ValidationError, match="code"):
        dataclass_validator({}, ["child"])

    pair_validator = validation_module._compile_simple_type(Pair)
    with pytest.raises(ValidationError, match="Error instantiating Pair"):
        pair_validator("x", ["pair"])

    strict_validator = validation_module._compile_simple_type(StrictValue)
    with pytest.raises(ValidationError, match="boom"):
        strict_validator("boom", ["strict"])

    coercible_validator = validation_module._compile_simple_type(Coercible)
    existing = Coercible(1)
    assert coercible_validator(existing, ["coerce"]) is existing
    assert coercible_validator("2", ["coerce"]).value == 2
    with pytest.raises(ValidationError, match="bad"):
        coercible_validator("bad", ["coerce"])
    with pytest.raises(ValidationError, match="Error instantiating Coercible"):
        coercible_validator(None, ["coerce"])

    any_validator = validation_module._compile_simple_type(Any)
    token = object()
    assert any_validator(token, ["any"]) is token

    assert validation_module._compile_validator(validation_module.Any, strict=False, globalns=globalns)("v", ["a"]) == "v"
    with monkeypatch.context() as patch_ctx:
        sentinel_any = object()
        patch_ctx.setattr(validation_module, "Any", sentinel_any)
        assert validation_module._compile_validator(sentinel_any, strict=False, globalns=globalns)("v", ["a"]) == "v"
    assert validation_module._compile_validator(123, strict=False, globalns=globalns)("v", ["a"]) == "v"
    with pytest.raises(RuntimeError, match="Unknown type"):
        validation_module._compile_validator(123, strict=True, globalns=globalns)

    list_validator = validation_module._compile_validator(list[int], strict=False, globalns=globalns)
    with pytest.raises(ValidationError, match="must be a list"):
        list_validator((1,), ["list"])

    with monkeypatch.context() as patch_ctx:
        patch_ctx.setattr(validation_module, "get_args", lambda _tp: ())
        tuple_any_validator = validation_module._compile_validator(tuple[int], strict=False, globalns=globalns)
        assert tuple_any_validator((1, "x"), ["tuple-any"]) == (1, "x")
        with pytest.raises(ValidationError, match="must be a tuple"):
            tuple_any_validator([1, 2], ["tuple-any"])

    tuple_var_validator = validation_module._compile_validator(tuple[int, ...], strict=False, globalns=globalns)
    assert tuple_var_validator(("1", 2), ["tuple-var"]) == (1, 2)
    with pytest.raises(ValidationError, match="must be a tuple"):
        tuple_var_validator([1], ["tuple-var"])

    tuple_fixed_validator = validation_module._compile_validator(tuple[int, str], strict=False, globalns=globalns)
    assert tuple_fixed_validator(("1", 2), ["tuple-fixed"]) == (1, "2")
    with pytest.raises(ValidationError, match="expected 2 items"):
        tuple_fixed_validator((1,), ["tuple-fixed"])
    with pytest.raises(ValidationError, match="must be a tuple"):
        tuple_fixed_validator([1, "x"], ["tuple-fixed"])

    dict_validator = validation_module._compile_validator(dict[str, int], strict=False, globalns=globalns)
    with pytest.raises(ValidationError, match="must be a dict"):
        dict_validator([], ["dict"])

    set_validator = validation_module._compile_validator(set[int], strict=False, globalns=globalns)
    assert set_validator({"1", 2}, ["set"]) == {1, 2}
    with pytest.raises(ValidationError, match="must be a set"):
        set_validator([], ["set"])

    frozenset_validator = validation_module._compile_validator(frozenset[int], strict=False, globalns=globalns)
    with pytest.raises(ValidationError, match="must be a frozenset"):
        frozenset_validator({1}, ["fset"])

    with monkeypatch.context() as patch_ctx:
        patch_ctx.setattr(validation_module, "get_args", lambda _tp: ())
        empty_union_validator = validation_module._compile_validator(int | str, strict=False, globalns=globalns)
    with pytest.raises(ValidationError, match="must be an instance"):
        empty_union_validator("x", ["union"])

    tvar = TypeVar("tvar")

    class UnknownOrigin(Generic[tvar]):
        pass

    unknown_validator = validation_module._compile_validator(UnknownOrigin[int], strict=False, globalns=globalns)
    assert unknown_validator("value", ["unknown"]) == "value"
    with pytest.raises(RuntimeError, match="Unknown type"):
        validation_module._compile_validator(UnknownOrigin[int], strict=True, globalns=globalns)
