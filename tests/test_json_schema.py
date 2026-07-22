from __future__ import annotations

from dataclasses import field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import UUID

import pytest

from modmex import BaseModel, Field, UnsupportedJsonSchemaTypeError


class AddressSchemaModel(BaseModel):
    city: str
    state: str | None = None


class CarrierSchemaModel(BaseModel):
    name: str
    contact_email: str | None
    notes: str | None = None
    lanes: list[str] = field(default_factory=list)
    address: AddressSchemaModel | None = None


class PrioritySchemaEnum(Enum):
    LOW = "low"
    HIGH = "high"


class UnsupportedLocation:
    pass


class GeoPoint:
    @classmethod
    def __modmex_json_schema__(cls) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
            },
            "required": ["latitude", "longitude"],
            "additionalProperties": False,
        }


class InvalidCustomSchema:
    @classmethod
    def __modmex_json_schema__(cls) -> object:
        return ["not", "an", "object"]


def test_model_json_schema_tracks_required_defaults_and_nullable_fields() -> None:
    schema = CarrierSchemaModel.model_json_schema()

    assert schema["required"] == ["name", "contact_email"]
    assert schema["properties"]["contact_email"] == {"type": ["string", "null"]}
    assert schema["properties"]["notes"] == {
        "type": ["string", "null"],
        "default": None,
    }
    assert schema["properties"]["lanes"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert schema["properties"]["address"] == {
        "anyOf": [
            {"$ref": "#/$defs/AddressSchemaModel"},
            {"type": "null"},
        ],
        "default": None,
    }
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["AddressSchemaModel"] == {
        "title": "AddressSchemaModel",
        "type": "object",
        "properties": {
            "city": {"type": "string"},
            "state": {"type": ["string", "null"], "default": None},
        },
        "required": ["city"],
        "additionalProperties": False,
    }


def test_model_json_schema_does_not_call_default_factory() -> None:
    calls = 0

    def factory() -> list[str]:
        nonlocal calls
        calls += 1
        return []

    class FactoryModel(BaseModel):
        values: list[str] = field(default_factory=factory)

    schema = FactoryModel.model_json_schema()

    assert calls == 0
    assert schema["required"] == []
    assert "default" not in schema["properties"]["values"]


def test_model_json_schema_uses_serialization_aliases() -> None:
    class AliasModel(BaseModel):
        first_name: str = Field(alias="firstName")
        internal_code: int = Field(serialization_alias="code")

    schema = AliasModel.model_json_schema()

    assert schema["properties"] == {
        "firstName": {"type": "string"},
        "code": {"type": "integer"},
    }
    assert schema["required"] == ["firstName", "code"]


def test_model_json_schema_supports_collections_literals_enums_and_unions() -> None:
    class SupportedTypesModel(BaseModel):
        labels: dict[str, int]
        kind: Literal["road", "rail"]
        priority: PrioritySchemaEnum
        identifier: int | str

    schema = SupportedTypesModel.model_json_schema()

    assert schema["properties"]["labels"] == {
        "type": "object",
        "additionalProperties": {"type": "integer"},
    }
    assert schema["properties"]["kind"] == {
        "enum": ["road", "rail"],
        "type": "string",
    }
    assert schema["properties"]["priority"] == {
        "enum": ["low", "high"],
        "type": "string",
    }
    assert schema["properties"]["identifier"] == {"type": ["integer", "string"]}


class RecursiveSchemaModel(BaseModel):
    name: str
    child: RecursiveSchemaModel | None = None


def test_model_json_schema_avoids_infinite_recursion() -> None:
    schema = RecursiveSchemaModel.model_json_schema()

    assert schema["properties"]["child"] == {
        "anyOf": [{"$ref": "#"}, {"type": "null"}],
        "default": None,
    }
    assert "$defs" not in schema


def test_model_json_schema_supports_standard_formats_and_container_shapes() -> None:
    class RichTypesModel(BaseModel):
        created_at: datetime
        birthday: date
        wake_at: time
        duration: timedelta
        amount: Decimal
        identifier: UUID
        pair: tuple[str, int]
        values: tuple[int, ...]
        tags: set[str]

    properties = RichTypesModel.model_json_schema()["properties"]

    assert properties["created_at"] == {"type": "string", "format": "date-time"}
    assert properties["birthday"] == {"type": "string", "format": "date"}
    assert properties["wake_at"] == {"type": "string", "format": "time"}
    assert properties["duration"] == {"type": "number"}
    assert properties["amount"] == {"type": "number"}
    assert properties["identifier"] == {"type": "string", "format": "uuid"}
    assert properties["pair"] == {
        "type": "array",
        "prefixItems": [{"type": "string"}, {"type": "integer"}],
        "minItems": 2,
        "maxItems": 2,
    }
    assert properties["values"] == {"type": "array", "items": {"type": "integer"}}
    assert properties["tags"] == {
        "type": "array",
        "items": {"type": "string"},
        "uniqueItems": True,
    }


def test_model_json_schema_includes_field_metadata_and_constraints() -> None:
    class DocumentedModel(BaseModel):
        name: str | None = Field(
            title="Display name",
            description="Human-readable name",
            examples=["Ana"],
            min_length=2,
            max_length=20,
            pattern=r"^[A-Z]",
            deprecated=True,
        )
        quantity: int = Field(gt=0, le=100, multiple_of=5)
        price: Decimal = Field(max_digits=6, decimal_places=2)

    properties = DocumentedModel.model_json_schema()["properties"]

    assert properties["name"] == {
        "type": ["string", "null"],
        "title": "Display name",
        "description": "Human-readable name",
        "examples": ["Ana"],
        "deprecated": True,
        "pattern": r"^[A-Z]",
        "minLength": 2,
        "maxLength": 20,
    }
    assert properties["quantity"] == {
        "type": "integer",
        "exclusiveMinimum": 0,
        "maximum": 100,
        "multipleOf": 5,
    }
    assert properties["price"] == {
        "type": "number",
        "multipleOf": 0.01,
        "exclusiveMinimum": -10000,
        "exclusiveMaximum": 10000,
    }


def test_model_json_schema_serializes_declared_non_primitive_defaults() -> None:
    fixed_id = UUID("12345678-1234-5678-1234-567812345678")

    class DefaultsModel(BaseModel):
        day: date = date(2026, 7, 21)
        amount: Decimal = Decimal("12.50")
        identifier: UUID = fixed_id

    properties = DefaultsModel.model_json_schema()["properties"]

    assert properties["day"]["default"] == "2026-07-21"
    assert properties["amount"]["default"] == 12.5
    assert properties["identifier"]["default"] == str(fixed_id)


def test_model_json_schema_rejects_arbitrary_classes_without_a_hook() -> None:
    class DeliveryModel(BaseModel):
        location: UnsupportedLocation

    with pytest.raises(
        UnsupportedJsonSchemaTypeError,
        match=(
            "Cannot generate JSON Schema for field 'location': "
            "UnsupportedLocation has no JSON Schema representation\\."
        ),
    ):
        DeliveryModel.model_json_schema()


def test_model_json_schema_uses_custom_type_hook() -> None:
    class DeliveryModel(BaseModel):
        location: GeoPoint

    assert DeliveryModel.model_json_schema()["properties"]["location"] == {
        "type": "object",
        "properties": {
            "latitude": {"type": "number"},
            "longitude": {"type": "number"},
        },
        "required": ["latitude", "longitude"],
        "additionalProperties": False,
    }


def test_model_json_schema_validates_custom_type_hook_result() -> None:
    class InvalidHookModel(BaseModel):
        value: InvalidCustomSchema

    with pytest.raises(
        UnsupportedJsonSchemaTypeError,
        match="InvalidCustomSchema.__modmex_json_schema__\\(\\) must return a JSON Schema object",
    ):
        InvalidHookModel.model_json_schema()
