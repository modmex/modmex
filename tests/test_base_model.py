from __future__ import annotations

from dataclasses import field, fields
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional

import pytest

from modmex import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)
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
