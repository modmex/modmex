from dataclasses import fields
from types import SimpleNamespace

import pytest

from modmex import BaseModel, Field
from modmex.fields import (
    FieldInfo,
    _VALIDATION_ALIASES,
    field_alias,
    field_constraints,
    field_deprecated,
    field_frozen,
    field_serialization_alias,
    field_validation_aliases,
    should_exclude_field,
)


def test_field_rejects_default_and_default_factory_together() -> None:
    with pytest.raises(ValueError, match="cannot specify both default and default_factory"):
        Field(default=1, default_factory=list)


def test_field_without_default_or_default_factory_is_supported() -> None:
    class Example(BaseModel):
        value: str = Field()

    model = Example(value="ok")

    assert model.value == "ok"


def test_field_uses_default_factory() -> None:
    class Example(BaseModel):
        values: list[str] = Field(default_factory=list)

    first = Example()
    second = Example()
    first.values.append("one")

    assert first.values == ["one"]
    assert second.values == []


def test_field_returns_field_info() -> None:
    field_info = Field(default=1, gt=0)

    assert isinstance(field_info, FieldInfo)
    assert field_info.default == 1
    assert field_info.gt == 0


def test_field_info_can_be_specialized_for_parameter_metadata() -> None:
    class Param(FieldInfo):
        pass

    class Query(Param):
        pass

    class ModelField(BaseModel):
        field_info: Param
        name: str

    model_field = ModelField(name="limit", field_info=Query(default=10, gt=0, le=100))

    assert isinstance(model_field.field_info, Query)
    assert model_field.field_info.gt == 0
    assert model_field.field_info.le == 100


def test_field_info_subclass_can_configure_model_field() -> None:
    class Query(FieldInfo):
        pass

    class Filters(BaseModel):
        limit: int = Query(default=10, gt=0, le=100)

    (field,) = fields(Filters)
    model = Filters()

    assert model.limit == 10
    assert field_constraints(field)["gt"] == 0
    assert field_constraints(field)["le"] == 100


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"min_length": -1}, "min_length must be greater than or equal to 0"),
        ({"max_length": -1}, "max_length must be greater than or equal to 0"),
        ({"min_length": 3, "max_length": 2}, "min_length cannot be greater than max_length"),
        ({"gt": 1, "ge": 1}, "cannot set both gt and ge"),
        ({"lt": 1, "le": 1}, "cannot set both lt and le"),
        ({"multiple_of": 0}, "multiple_of must be non-zero"),
        ({"max_digits": 0}, "max_digits must be greater than 0"),
        ({"decimal_places": -1}, "decimal_places must be greater than or equal to 0"),
        ({"max_digits": 2, "decimal_places": 3}, "decimal_places cannot be greater than max_digits"),
    ],
)
def test_field_rejects_invalid_constraints(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Field(**kwargs)


def test_should_exclude_field_respects_metadata_and_flags() -> None:
    class Example(BaseModel):
        visible: str = Field("ok")
        hidden: str = Field("x", exclude=True)
        by_profile: str = Field("y", exclude_from="public")
        by_profiles: str = Field("z", exclude_from={"internal", "partner"})

    visible_field, hidden_field, profile_field, profiles_field = fields(Example)

    assert should_exclude_field(visible_field, explicit_exclude=True, profile=None, include_excluded=False)
    assert should_exclude_field(hidden_field, explicit_exclude=None, profile=None, include_excluded=False)
    assert should_exclude_field(profile_field, explicit_exclude=None, profile="public", include_excluded=False)
    assert should_exclude_field(profiles_field, explicit_exclude=None, profile="partner", include_excluded=False)
    assert not should_exclude_field(profile_field, explicit_exclude=None, profile="public", include_excluded=True)
    assert not should_exclude_field(visible_field, explicit_exclude=None, profile="public", include_excluded=False)


def test_field_helpers_read_modmex_metadata() -> None:
    class Example(BaseModel):
        value: int = Field(
            1,
            alias="input_name",
            validation_alias=["legacy_name", "", object()],
            serialization_alias="output_name",
            gt=0,
            lt=10,
            min_length=1,
            max_length=2,
            pattern=r"^\d$",
            multiple_of=1,
            max_digits=3,
            decimal_places=1,
            deprecated="use other",
            frozen=True,
            metadata={"external": "kept"},
        )

    (field,) = fields(Example)

    assert field.metadata["external"] == "kept"
    assert field_alias(field) == "input_name"
    assert field_validation_aliases(field) == ("legacy_name",)
    assert field_serialization_alias(field) == "output_name"
    assert field_constraints(field) == {
        "gt": 0,
        "ge": None,
        "lt": 10,
        "le": None,
        "min_length": 1,
        "max_length": 2,
        "pattern": r"^\d$",
        "multiple_of": 1,
        "max_digits": 3,
        "decimal_places": 1,
    }
    assert field_deprecated(field) == "use other"
    assert field_frozen(field)


def test_field_validation_alias_accepts_single_string() -> None:
    class Example(BaseModel):
        value: str = Field("ok", validation_alias="legacy")

    (field,) = fields(Example)

    assert field_validation_aliases(field) == ("legacy",)


def test_field_validation_aliases_handles_non_tuple_metadata() -> None:
    field = SimpleNamespace(metadata={_VALIDATION_ALIASES: ["one", "two"]})

    assert field_validation_aliases(field) == ("one", "two")
