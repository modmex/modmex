from __future__ import annotations

from dataclasses import field, fields
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
import warnings
from typing import Annotated, Any, Literal, Optional
from uuid import UUID, uuid4

import pytest

from modmex import (
    BaseModel,
    ConfigDict,
    Field,
    create_model,
    field_validator,
    model_validator,
)
import modmex.base_model as base_model_module
from modmex.errors import ValidationError


class Status(Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class Address(BaseModel):
    zipcode: int


class Session(BaseModel):
    id: str
    device: str
    device_secret: str = Field("", exclude_from="public")


class User(BaseModel):
    id: int
    name: str
    address: Address
    tags: list[int] = field(default_factory=list)
    profile: dict[str, int] = field(default_factory=dict)
    status: Status = Status.ACTIVE
    nickname: Optional[str] = None
    kind: Literal["user"] = "user"
    created_at: datetime = datetime(2026, 1, 2, 3, 4, 5)
    birthday: date = date(1990, 1, 1)
    wake_up_at: time = time(8, 30)
    trial_duration: timedelta = timedelta(hours=1, minutes=30)
    balance: Decimal = Decimal("10.50")
    password: str = "secret"
    token: str = "token"
    private_note: str = Field(default="private", exclude=True)
    sessions: list[Session] = Field(default_factory=list, exclude_from={"database"})

    @property
    def label(self) -> str:
        return f"{self.id}:{self.name}"


def test_model_coerces_supported_field_types() -> None:
    user = User(
        id="1",
        name=123,
        address={"zipcode": "90210"},
        tags=["1", 2],
        profile={"visits": "3"},
        status="disabled",
        nickname=None,
        wake_up_at="08:30",
        trial_duration=90,
    )

    assert user.id == 1
    assert user.name == "123"
    assert user.address == Address(zipcode=90210)
    assert user.tags == [1, 2]
    assert user.profile == {"visits": 3}
    assert user.status is Status.DISABLED
    assert user.wake_up_at == time(8, 30)
    assert user.trial_duration == timedelta(seconds=90)


def test_model_dump_serializes_nested_values_and_properties() -> None:
    user = User(id=1, name="Ana", address=Address(zipcode=90210))

    assert user.model_dump() == {
        "id": 1,
        "name": "Ana",
        "address": {"zipcode": 90210},
        "tags": [],
        "profile": {},
        "status": "active",
        "nickname": None,
        "kind": "user",
        "created_at": "2026-01-02T03:04:05",
        "birthday": "1990-01-01",
        "wake_up_at": "08:30:00",
        "trial_duration": 5400.0,
        "balance": 10.5,
        "password": "secret",
        "token": "token",
        "sessions": [],
        "label": "1:Ana",
    }


def test_model_dump_excludes_top_level_fields() -> None:
    user = User(id=1, name="Ana", address=Address(zipcode=90210))

    dumped = user.model_dump(exclude={"password", "token"})

    assert "password" not in dumped
    assert "token" not in dumped
    assert "name" in dumped


def test_model_dump_excludes_nested_fields() -> None:
    user = User(id=1, name="Ana", address=Address(zipcode=90210))

    dumped = user.model_dump(exclude={"address": {"zipcode"}})

    assert dumped["address"] == {}


def test_model_dump_excludes_properties() -> None:
    user = User(id=1, name="Ana", address=Address(zipcode=90210))

    dumped = user.model_dump(exclude={"label"})

    assert "label" not in dumped


def test_field_exclude_from_omits_field_for_profile() -> None:
    user = User(
        id=1,
        name="Ana",
        address=Address(zipcode=90210),
        sessions=[Session(id="session_1", device="desktop")],
    )

    dumped = user.model_dump(profile="database")

    assert "sessions" not in dumped


def test_field_exclude_from_applies_to_nested_list_items() -> None:
    user = User(
        id=1,
        name="Ana",
        address=Address(zipcode=90210),
        sessions=[Session(id="session_1", device="desktop", device_secret="secret")],
    )

    dumped = user.model_dump(profile="public")

    assert dumped["sessions"] == [{"id": "session_1", "device": "desktop"}]


def test_field_exclude_omits_field_by_default() -> None:
    user = User(id=1, name="Ana", address=Address(zipcode=90210))

    assert "private_note" not in user.model_dump()


def test_include_excluded_includes_field_metadata_exclusions() -> None:
    user = User(id=1, name="Ana", address=Address(zipcode=90210))

    dumped = user.model_dump(profile="database", include_excluded=True)

    assert dumped["private_note"] == "private"
    assert dumped["sessions"] == []


def test_model_dump_json_uses_json_context_by_default() -> None:
    user = User(id=1, name="Ana", address=Address(zipcode=90210))

    assert user.model_dump_json() == (
        '{"id":1,"name":"Ana","address":{"zipcode":90210},"tags":[],"profile":{},'
        '"status":"active","nickname":null,"kind":"user","created_at":"2026-01-02T03:04:05",'
        '"birthday":"1990-01-01","wake_up_at":"08:30:00","trial_duration":5400.0,'
        '"balance":10.5,"password":"secret","token":"token","sessions":[],"label":"1:Ana"}'
    )


def test_validation_errors_include_nested_locations() -> None:
    with pytest.raises(ValidationError) as exc_info:
        User(id="bad", name="Ana", address={"zipcode": "bad"}, tags=["1", "bad"])

    locations = {tuple(error["loc"]) for error in exc_info.value.errors}

    assert ("id",) in locations
    assert ("address", "zipcode") in locations
    assert ("tags", 1) in locations


def test_extra_constructor_fields_are_ignored() -> None:
    user = User(id=1, name="Ana", address=Address(zipcode=90210), ignored=True)

    assert not hasattr(user, "ignored")


def test_required_and_optional_fields_can_be_declared_in_any_order() -> None:
    class Account(BaseModel):
        display_name: str = "Anonymous"
        id: int
        email: str = Field("", exclude_from="public")
        username: str

    account = Account(id="1", username=123)

    assert account.id == 1
    assert account.username == "123"
    assert account.display_name == "Anonymous"
    assert account.model_dump(profile="public") == {
        "display_name": "Anonymous",
        "id": 1,
        "username": "123",
    }


def test_field_and_model_validators_run_in_order() -> None:
    class Product(BaseModel):
        name: str
        slug: str = ""

        @model_validator(mode="before")
        def set_slug(self, values: dict) -> dict:
            values["slug"] = values["name"].lower()
            return values

        @field_validator("name")
        def titlecase_name(self, value: str) -> str:
            return value.title()

        @model_validator(mode="after")
        def suffix_slug(self, values: dict) -> dict:
            values["slug"] = f"{values['slug']}-product"
            return values

    product = Product(name="coffee")

    assert product.name == "Coffee"
    assert product.slug == "coffee-product"


def test_model_dump_json_supports_exclude() -> None:
    user = User(id=1, name="Ana", address=Address(zipcode=90210))

    assert '"password"' not in user.model_dump_json(exclude={"password"})


def test_model_dump_supports_type_serializers_for_specific_types() -> None:
    user = User(
        id=1,
        name="Ana",
        address=Address(zipcode=90210),
        sessions=[Session(id="s_1", device="mobile", device_secret="secret")],
    )

    dumped = user.model_dump(
        profile="public",
        type_serializers={
            Decimal: lambda value: value,
            datetime: lambda value: value.strftime("%Y/%m/%d %H:%M:%S"),
        },
    )

    assert dumped["balance"] == Decimal("10.50")
    assert dumped["created_at"] == "2026/01/02 03:04:05"
    assert dumped["sessions"] == [{"id": "s_1", "device": "mobile"}]


def test_model_dump_supports_float_to_decimal_type_serializer() -> None:
    class PriceModel(BaseModel):
        amount: float

    model = PriceModel(amount=10.25)

    dumped = model.model_dump(
        type_serializers={
            float: lambda value: Decimal(str(value)),
        }
    )

    assert dumped["amount"] == Decimal("10.25")


def test_model_dump_serializes_uuid_values_to_strings() -> None:
    identifier = UUID("12345678-1234-5678-1234-567812345678")

    class Event(BaseModel):
        id: UUID
        optional_id: UUID | None = None
        related_ids: list[UUID] = field(default_factory=list)
        metadata: dict[str, UUID] = field(default_factory=dict)

        @property
        def trace_id(self) -> UUID:
            return identifier

    event = Event(
        id=identifier,
        optional_id=identifier,
        related_ids=[identifier],
        metadata={"source": identifier},
    )

    assert event.model_dump() == {
        "id": str(identifier),
        "optional_id": str(identifier),
        "related_ids": [str(identifier)],
        "metadata": {"source": str(identifier)},
        "trace_id": str(identifier),
    }


def test_model_dump_json_serializes_uuid_values_to_strings() -> None:
    identifier = uuid4()

    class Event(BaseModel):
        id: UUID

    assert Event(id=identifier).model_dump_json() == f'{{"id":"{identifier}"}}'


def test_model_dump_json_supports_type_serializers_for_specific_types() -> None:
    user = User(id=1, name="Ana", address=Address(zipcode=90210))

    dumped_json = user.model_dump_json(
        type_serializers={
            Decimal: lambda value: str(value),
            timedelta: lambda value: int(value.total_seconds()),
        }
    )

    assert '"balance":"10.50"' in dumped_json
    assert '"trial_duration":5400' in dumped_json


def test_model_validator_rejects_invalid_mode() -> None:
    with pytest.raises(ValueError, match="model validator mode"):
        model_validator(mode="during")


def test_model_validator_can_return_none_without_modifying_state() -> None:
    class Item(BaseModel):
        name: str
        calls: int = 0

        @model_validator(mode="before")
        def count(self, values: dict) -> None:
            self.calls += 1
            return None

    item = Item(name="tea")

    assert item.name == "tea"
    assert item.calls == 1


def test_create_model_matches_static_model_for_tuple_and_field_specs() -> None:
    def normalize_foo(self, value: str) -> str:
        return value.strip().title()

    DynamicFoobarModel = create_model(
        "DynamicFoobarModel",
        foo=(str, ...),
        bar=(int, 123),
        baz=Annotated[str, Field(default="x", exclude=True)],
        __validators__={"normalize_foo": field_validator("foo")(normalize_foo)},
    )

    class StaticFoobarModel(BaseModel):
        foo: str
        bar: int = 123
        baz: str = Field(default="x", exclude=True)

        @field_validator("foo")
        def normalize_foo(self, value: str) -> str:
            return value.strip().title()

    dynamic = DynamicFoobarModel(foo="  hello ")
    static = StaticFoobarModel(foo="  hello ")

    assert dynamic.model_dump() == static.model_dump()
    assert dynamic.__dict__ == static.__dict__
    assert dynamic.foo == "Hello"
    assert dynamic.bar == 123
    assert dynamic.baz == "x"


def test_create_model_can_use_base_and_field_validator_namespace() -> None:
    class AuditBase(BaseModel):
        pass

    def suffix_slug(self, values: dict) -> dict:
        values["slug"] = f"{values['slug']}-dynamic"
        return values

    Dynamic = create_model(
        "Dynamic",
        __base__=AuditBase,
        name=(str, ...),
        slug=(str, "item"),
        __validators__={"suffix_slug": model_validator(mode="after")(suffix_slug)},
    )

    item = Dynamic(name="tea")

    assert isinstance(item, AuditBase)
    assert item.slug == "item-dynamic"


def test_create_model_rejects_invalid_tuple_definition() -> None:
    with pytest.raises(TypeError, match="must be defined as"):
        create_model("InvalidTuple", foo=(str, 1, 2))


def test_create_model_rejects_invalid_field_definition() -> None:
    with pytest.raises(TypeError, match="must be defined as"):
        create_model("InvalidField", foo=str)


def test_create_model_rejects_non_basemodel_base() -> None:
    with pytest.raises(TypeError, match="BaseModel subclass"):
        create_model("InvalidBase", __base__=object, foo=(str, ...))


def test_create_model_annotated_empty_args_raises_type_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeAnnotatedOrigin:
        __qualname__ = "Annotated"

    monkeypatch.setattr(base_model_module, "get_origin", lambda _: _FakeAnnotatedOrigin)
    monkeypatch.setattr(base_model_module, "get_args", lambda _: ())

    with pytest.raises(TypeError, match="annotated type is invalid"):
        create_model("InvalidAnnotated", foo=object())


def test_create_model_module_fallback_when_frame_lookup_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_value_error(_: int) -> Any:
        raise ValueError("no frame")

    monkeypatch.setattr(base_model_module.sys, "_getframe", _raise_value_error)

    Dynamic = create_model("FallbackModuleModel", value=(int, ...))

    assert Dynamic.__module__ == "__main__"


def test_alias_is_applied_for_input_and_output() -> None:
    class AliasedUser(BaseModel):
        first_name: str = Field(alias="firstName")

    user = AliasedUser(firstName="Ana")

    assert user.first_name == "Ana"
    assert user.model_dump() == {"firstName": "Ana"}


def test_validation_alias_is_only_for_input() -> None:
    class InboundUser(BaseModel):
        first_name: str = Field(validation_alias="firstName")

    user = InboundUser(firstName="Ana")

    assert user.first_name == "Ana"
    assert user.model_dump() == {"first_name": "Ana"}


def test_serialization_alias_is_only_for_output() -> None:
    class OutboundUser(BaseModel):
        first_name: str = Field(serialization_alias="firstName")

    user = OutboundUser(first_name="Ana")

    assert user.first_name == "Ana"
    assert user.model_dump() == {"firstName": "Ana"}


def test_field_name_wins_when_alias_and_field_are_both_provided() -> None:
    class ConflictUser(BaseModel):
        first_name: str = Field(alias="firstName")

    user = ConflictUser(first_name="Internal", firstName="External")

    assert user.first_name == "Internal"


def test_alias_generator_is_applied_for_input_and_output() -> None:
    def to_camel(field_name: str) -> str:
        first, *rest = field_name.split("_")
        return first + "".join(part.title() for part in rest)

    class GeneratedAliasUser(BaseModel):
        model_config = ConfigDict(alias_generator=to_camel)

        first_name: str
        last_name: str

    user = GeneratedAliasUser(firstName="Ana", lastName="Diaz")

    assert user.first_name == "Ana"
    assert user.last_name == "Diaz"
    assert user.model_dump() == {"firstName": "Ana", "lastName": "Diaz"}


def test_field_aliases_override_alias_generator() -> None:
    def to_camel(field_name: str) -> str:
        first, *rest = field_name.split("_")
        return first + "".join(part.title() for part in rest)

    class GeneratedAliasUser(BaseModel):
        model_config = ConfigDict(alias_generator=to_camel)

        first_name: str = Field(alias="givenName")
        last_name: str = Field(validation_alias="surname")
        display_name: str = Field(serialization_alias="label")

    user = GeneratedAliasUser(givenName="Ana", surname="Diaz", displayName="Ana Diaz")

    assert user.first_name == "Ana"
    assert user.last_name == "Diaz"
    assert user.display_name == "Ana Diaz"
    assert user.model_dump() == {
        "givenName": "Ana",
        "lastName": "Diaz",
        "label": "Ana Diaz",
    }


def test_alias_generator_detects_duplicate_input_aliases() -> None:
    with pytest.raises(ValueError, match="duplicate validation alias 'same'"):
        class DuplicateAliasModel(BaseModel):
            model_config = ConfigDict(alias_generator=lambda _: "same")

            first_name: str
            last_name: str


def test_create_model_accepts_config_for_alias_generator() -> None:
    DynamicUser = create_model(
        "DynamicUserWithAliases",
        __config__=ConfigDict(alias_generator=lambda field_name: field_name.upper()),
        first_name=(str, ...),
    )

    user = DynamicUser(FIRST_NAME="Ana")

    assert user.first_name == "Ana"
    assert user.model_dump() == {"FIRST_NAME": "Ana"}


def test_extra_constructor_fields_are_ignored_for_models_with_internal_hooks() -> None:
    class HookedModel(BaseModel):
        id: int = Field(frozen=True)
        old_name: str = Field(deprecated=True)

    model = HookedModel(id=1, old_name="Ana", ignored=True)

    assert model.id == 1
    assert model.old_name == "Ana"
    assert not hasattr(model, "ignored")


def test_internal_hook_bypass_path_runs_validation_when_fast_init_is_disabled() -> None:
    class HookedValidatedModel(BaseModel):
        id: int = Field(frozen=True)
        old_name: str = Field(deprecated=True)
        name: str

        @field_validator("name")
        def normalize_name(self, value: str) -> str:
            return value.upper()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        model = HookedValidatedModel(id=1, old_name="Ana", name="ana", ignored=True)

    assert model.name == "ANA"
    assert not hasattr(model, "ignored")


def test_internal_hooks_still_run_constraints_after_rust_fast_init() -> None:
    class HookedConstrainedModel(BaseModel):
        id: int = Field(frozen=True)
        old_name: str = Field(deprecated=True)
        qty: int = Field(gt=0)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        model = HookedConstrainedModel(id=1, old_name="Ana", qty=2)

    assert model.qty == 2

    with pytest.raises(ValidationError) as exc_info:
        HookedConstrainedModel(id=1, old_name="Ana", qty=0)

    assert any(error["loc"] == ["qty"] for error in exc_info.value.errors)


def test_validation_constraints_are_enforced() -> None:
    class ConstrainedModel(BaseModel):
        qty: int = Field(gt=0, le=5)
        name: str = Field(min_length=2, max_length=5)

    model = ConstrainedModel(qty=3, name="Ana")

    assert model.qty == 3
    assert model.name == "Ana"

    with pytest.raises(ValidationError) as gt_error:
        ConstrainedModel(qty=0, name="Ana")
    assert any(error["loc"] == ["qty"] for error in gt_error.value.errors)

    with pytest.raises(ValidationError) as len_error:
        ConstrainedModel(qty=2, name="A")
    assert any(error["loc"] == ["name"] for error in len_error.value.errors)


def test_field_stores_openapi_metadata() -> None:
    class DocumentedModel(BaseModel):
        name: str = Field(
            title="User name",
            description="Display name for the user",
            examples=["Ana"],
        )

    name_field = next(model_field for model_field in fields(DocumentedModel) if model_field.name == "name")

    assert name_field.metadata["__modmex_title__"] == "User name"
    assert name_field.metadata["__modmex_description__"] == "Display name for the user"
    assert name_field.metadata["__modmex_examples__"] == ("Ana",)


def test_phase_two_constraints_are_enforced() -> None:
    class AdvancedModel(BaseModel):
        code: str = Field(pattern=r"^[A-Z]{2}-\d{3}$")
        qty: int = Field(multiple_of=5)
        price: Decimal = Field(max_digits=6, decimal_places=2)

    model = AdvancedModel(code="AB-123", qty=10, price="1234.56")

    assert model.code == "AB-123"
    assert model.qty == 10
    assert model.price == Decimal("1234.56")

    with pytest.raises(ValidationError) as pattern_error:
        AdvancedModel(code="abc", qty=10, price="1234.56")
    assert any(error["loc"] == ["code"] for error in pattern_error.value.errors)

    with pytest.raises(ValidationError) as multiple_error:
        AdvancedModel(code="AB-123", qty=11, price="1234.56")
    assert any(error["loc"] == ["qty"] for error in multiple_error.value.errors)

    with pytest.raises(ValidationError) as decimal_error:
        AdvancedModel(code="AB-123", qty=10, price="12345.678")
    assert any(error["loc"] == ["price"] for error in decimal_error.value.errors)


def test_frozen_field_cannot_be_modified_after_init() -> None:
    class FrozenModel(BaseModel):
        id: int = Field(frozen=True)
        name: str

    model = FrozenModel(id=1, name="Ana")

    with pytest.raises(AttributeError, match="frozen"):
        model.id = 2

    model.name = "Ana Maria"
    assert model.name == "Ana Maria"


def test_deprecated_field_emits_warning_once_per_instance() -> None:
    class DeprecatedModel(BaseModel):
        old_name: str = Field(deprecated="old_name is deprecated")

    model = DeprecatedModel(old_name="Ana")
    
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", DeprecationWarning)
        _ = model.old_name
        _ = model.old_name

    deprecation_messages = [
        warning
        for warning in captured
        if isinstance(warning.message, DeprecationWarning)
        or warning.category is DeprecationWarning
    ]
    assert len(deprecation_messages) == 1


def test_non_deprecated_fields_do_not_emit_warnings_when_wrapper_is_installed() -> None:
    class MixedModel(BaseModel):
        old_name: str = Field(deprecated=True)
        name: str

    model = MixedModel(old_name="Ana", name="Active")

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", DeprecationWarning)
        assert model.name == "Active"

    assert captured == []
