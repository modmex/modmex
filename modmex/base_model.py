"""Dataclass-backed model base with validation and serialization helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any, Callable

import orjson

from .fields import should_exclude_field
from .serialization import ExcludeSpec, TypeSerializers, custom_serializer, normalize_exclude, serialize_value
from .validation import validate_model_fields


def field_validator(field_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate a method that validates or transforms one field."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        func._validator_field = field_name  # type: ignore[attr-defined]
        return func

    return decorator


def model_validator(mode: str = "before") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorate a method that validates or transforms the full model."""

    if mode not in {"before", "after"}:
        raise ValueError("model validator mode must be 'before' or 'after'")

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        func._validator_mode = mode  # type: ignore[attr-defined]
        return func

    return decorator


class BaseModelMeta(type):
    def __new__(mcls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]) -> type:
        model_cls = super().__new__(mcls, name, bases, namespace)
        dataclass(model_cls, kw_only=True)

        original_init = model_cls.__init__

        def new_init(self: Any, *args: Any, **kwargs: Any) -> None:
            valid_fields = {field.name for field in fields(model_cls)}
            filtered_kwargs = {key: value for key, value in kwargs.items() if key in valid_fields}
            original_init(self, *args, **filtered_kwargs)

        model_cls.__init__ = new_init
        return model_cls


class BaseModel(metaclass=BaseModelMeta):
    """Base class for lightweight validated models."""

    def __post_init__(self) -> None:
        self._validate_model_before()
        self._validate_types()
        self._validate_fields()
        self._validate_model_after()

    def _validate_types(self) -> None:
        validate_model_fields(self)

    def _validate_model_before(self) -> None:
        self._run_model_validators("before")

    def _validate_model_after(self) -> None:
        self._run_model_validators("after")

    def _run_model_validators(self, mode: str) -> None:
        for attr_name in dir(self):
            if isinstance(getattr(type(self), attr_name, None), property):
                continue

            attr = getattr(self, attr_name)
            if callable(attr) and getattr(attr, "_validator_mode", None) == mode:
                updated_values = attr(self.__dict__.copy())
                if updated_values is not None:
                    self.__dict__.update(updated_values)

    def _validate_fields(self) -> None:
        for attr_name in dir(self):
            if isinstance(getattr(type(self), attr_name, None), property):
                continue

            attr = getattr(self, attr_name)
            field_name = getattr(attr, "_validator_field", None)
            if callable(attr) and field_name:
                setattr(self, field_name, attr(getattr(self, field_name, None)))

    def _append_properties(
        self,
        data: dict[str, Any],
        exclude: Mapping[str, Any],
        profile: str | None,
        type_serializers: TypeSerializers,
    ) -> dict[str, Any]:
        for attr_name in dir(self):
            if attr_name in exclude:
                continue
            if isinstance(getattr(type(self), attr_name, None), property):
                data[attr_name] = serialize_value(
                    getattr(self, attr_name),
                    exclude=None,
                    profile=profile,
                    type_serializers=type_serializers,
                )
        return data

    def _serialize(
        self,
        exclude: ExcludeSpec = None,
        profile: str | None = None,
        include_excluded: bool = False,
        type_serializers: TypeSerializers = None,
    ) -> dict[str, Any]:
        exclude_map = normalize_exclude(exclude)
        result = {
            field.name: serialize_value(
                getattr(self, field.name),
                exclude=exclude_map.get(field.name),
                profile=profile,
                include_excluded=include_excluded,
                type_serializers=type_serializers,
            )
            for field in fields(self)
            if not should_exclude_field(field, exclude_map.get(field.name), profile, include_excluded)
        }
        return self._append_properties(result, exclude_map, profile, type_serializers)

    def model_dump(
        self,
        *,
        exclude: ExcludeSpec = None,
        profile: str | None = None,
        include_excluded: bool = False,
        type_serializers: TypeSerializers = None,
    ) -> dict[str, Any]:
        return self._serialize(
            exclude=exclude,
            profile=profile,
            include_excluded=include_excluded,
            type_serializers=type_serializers,
        )

    def model_dump_json(
        self,
        *,
        exclude: ExcludeSpec = None,
        profile: str | None = None,
        include_excluded: bool = False,
        type_serializers: TypeSerializers = None,
    ) -> str:
        return orjson.dumps(
            self.model_dump(
                exclude=exclude,
                profile=profile,
                include_excluded=include_excluded,
                type_serializers=type_serializers,
            ),
            option=orjson.OPT_PASSTHROUGH_DATETIME,
            default=custom_serializer,
        ).decode("utf-8")
