"""Dataclass-backed model base with validation and serialization helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import MISSING, dataclass, fields
from typing import Any, Callable

import orjson

from .fields import should_exclude_field
from . import rust_backend
from .model_codegen import (
    _build_compiled_init,
    _build_trusted_init,
    _compiled_dump_for,
    _rust_field_descriptors,
    _rust_schema_for,
)
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
        model_fields = fields(model_cls)
        base_model_type = next(
            (
                getattr(base, "__modmex_base_model_type__", base)
                for base in bases
                if hasattr(base, "__modmex_fields__")
            ),
            model_cls,
        )

        model_cls.__modmex_base_model_type__ = base_model_type
        model_cls.__modmex_fields__ = model_fields
        model_cls.__modmex_field_names__ = {field.name for field in model_fields}
        model_cls.__modmex_dump_field_cache__ = {}
        model_cls.__modmex_compiled_dump_cache__ = {}
        model_cls.__modmex_shape_init_cache__ = {}
        model_cls.__modmex_properties__ = tuple(
            attr_name
            for attr_name in dir(model_cls)
            if isinstance(getattr(model_cls, attr_name, None), property)
        )
        model_cls.__modmex_model_validators__ = {
            mode: tuple(
                attr_name
                for attr_name in dir(model_cls)
                if callable(getattr(model_cls, attr_name, None))
                and getattr(getattr(model_cls, attr_name), "_validator_mode", None) == mode
            )
            for mode in ("before", "after")
        }
        model_cls.__modmex_field_validators__ = tuple(
            (attr_name, getattr(getattr(model_cls, attr_name), "_validator_field"))
            for attr_name in dir(model_cls)
            if callable(getattr(model_cls, attr_name, None))
            and getattr(getattr(model_cls, attr_name), "_validator_field", None)
        )
        model_cls.__modmex_required_field_names__ = tuple(
            field.name
            for field in model_fields
            if field.default is MISSING and field.default_factory is MISSING
        )
        model_cls.__modmex_trusted_init__ = _build_trusted_init(model_fields)
        model_cls.__modmex_compiled_init__ = None
        model_cls.__modmex_rust_schema__ = _rust_schema_for(model_cls, model_fields, base_model_type)
        model_cls.__modmex_rust_descriptors__ = _rust_field_descriptors(
            model_fields,
            model_cls.__modmex_rust_schema__,
        )
        model_cls.__modmex_rust_fast_init__ = (
            bool(model_cls.__modmex_rust_schema__)
            and len(model_cls.__modmex_rust_schema__) == len(model_fields)
            and not model_cls.__modmex_field_validators__
            and not model_cls.__modmex_model_validators__["before"]
            and not model_cls.__modmex_model_validators__["after"]
        )
        if model_cls.__modmex_rust_fast_init__:
            model_cls.__modmex_compiled_init__ = _build_compiled_init(model_cls, model_fields, base_model_type)
        model_cls.__modmex_compiled_dump__ = _compiled_dump_for(model_cls, None, base_model_type)
        model_cls.__modmex_core__ = (
            rust_backend.build_model_core(model_cls, model_cls.__modmex_rust_descriptors__)
            if model_cls.__modmex_rust_fast_init__
            else None
        )
        model_cls.__modmex_rust_dump_names__ = tuple(
            field.name
            for field in model_fields
            if not should_exclude_field(field, None, None, False)
        )

        original_init = model_cls.__init__
        compiled_init = model_cls.__modmex_compiled_init__
        shape_init_cache = model_cls.__modmex_shape_init_cache__
        model_core = model_cls.__modmex_core__
        rust_fast_init = model_cls.__modmex_rust_fast_init__
        rust_schema = model_cls.__modmex_rust_schema__
        trusted_init = model_cls.__modmex_trusted_init__
        field_names = model_cls.__modmex_field_names__

        def new_init(self: Any, *args: Any, **kwargs: Any) -> None:
            if not args and compiled_init is not None:
                shape = tuple(kwargs)
                shape_init = shape_init_cache.get(shape)
                if shape_init is None:
                    present_names = frozenset(name for name in shape if name in field_names)
                    shape_init = _build_compiled_init(
                        model_cls,
                        model_fields,
                        base_model_type,
                        present_names,
                    ) or False
                    shape_init_cache[shape] = shape_init
                if shape_init and shape_init(self, kwargs):
                    return
                if compiled_init(self, kwargs):
                    return
            filtered_kwargs = kwargs if kwargs.keys() <= field_names else {
                key: value for key, value in kwargs.items() if key in field_names
            }
            if not args:
                core_updates = rust_backend.try_core_validate_updates(model_core, filtered_kwargs)
                if core_updates is not None:
                    core_kwargs = dict(filtered_kwargs)
                    core_kwargs.update(core_updates)
                    if trusted_init(self, core_kwargs):
                        return
            if not args and rust_fast_init:
                coerced_kwargs = rust_backend.try_coerce_schema_kwargs(
                    filtered_kwargs,
                    rust_schema,
                    0,
                )
                if coerced_kwargs is not None:
                    merged_kwargs = dict(filtered_kwargs)
                    merged_kwargs.update(coerced_kwargs)
                    if trusted_init(self, merged_kwargs):
                        return
            original_init(self, *args, **filtered_kwargs)

        model_cls.__init__ = new_init
        if model_cls.__modmex_rust_fast_init__:

            @classmethod
            def _modmex_from_trusted_kwargs(cls: type[Any], kwargs: dict[str, Any]) -> Any:
                instance = cls.__new__(cls)
                if cls.__modmex_trusted_init__(instance, kwargs):
                    return instance
                return cls(**kwargs)

            model_cls._modmex_from_trusted_kwargs = _modmex_from_trusted_kwargs
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
        for attr_name in type(self).__modmex_model_validators__[mode]:
            updated_values = getattr(self, attr_name)(self.__dict__.copy())
            if updated_values is not None:
                self.__dict__.update(updated_values)

    def _validate_fields(self) -> None:
        for attr_name, field_name in type(self).__modmex_field_validators__:
            validator = getattr(self, attr_name)
            setattr(self, field_name, validator(getattr(self, field_name, None)))

    def _append_properties(
        self,
        data: dict[str, Any],
        exclude: Mapping[str, Any],
        profile: str | None,
        type_serializers: TypeSerializers,
    ) -> dict[str, Any]:
        for attr_name in type(self).__modmex_properties__:
            if attr_name in exclude:
                continue
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
        if exclude is None and profile is None and not include_excluded and not type_serializers:
            compiled_dump = type(self).__modmex_compiled_dump__
            if compiled_dump is not None:
                return compiled_dump(self)
        if exclude is None and profile is not None and not include_excluded and not type_serializers:
            compiled_dump = _compiled_dump_for(
                type(self),
                profile,
                type(self).__modmex_base_model_type__,
            )
            if compiled_dump is not None:
                return compiled_dump(self)
        if exclude is None and profile is None and not include_excluded and not type_serializers:
            rust_result = rust_backend.try_serialize_model_fields(
                self,
                type(self).__modmex_rust_dump_names__,
                type(self).__modmex_properties__,
            )
            if rust_result is not None:
                return rust_result

        exclude_map = normalize_exclude(exclude)
        if exclude_map:
            result = {
                field.name: serialize_value(
                    getattr(self, field.name),
                    exclude=exclude_map.get(field.name),
                    profile=profile,
                    include_excluded=include_excluded,
                    type_serializers=type_serializers,
                )
                for field in type(self).__modmex_fields__
                if not should_exclude_field(field, exclude_map.get(field.name), profile, include_excluded)
            }
        else:
            result = {
                field.name: serialize_value(
                    getattr(self, field.name),
                    exclude=None,
                    profile=profile,
                    include_excluded=include_excluded,
                    type_serializers=type_serializers,
                )
                for field in _dump_fields_for(type(self), profile, include_excluded)
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
        if exclude is None and profile is None and not include_excluded and not type_serializers:
            compiled_dump = type(self).__modmex_compiled_dump__
            if compiled_dump is not None:
                return compiled_dump(self)
        if exclude is None and profile is not None and not include_excluded and not type_serializers:
            compiled_dump = _compiled_dump_for(
                type(self),
                profile,
                type(self).__modmex_base_model_type__,
            )
            if compiled_dump is not None:
                return compiled_dump(self)
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
        if exclude is None and not include_excluded and not type_serializers:
            compiled_dump = (
                type(self).__modmex_compiled_dump__
                if profile is None
                else _compiled_dump_for(
                    type(self),
                    profile,
                    type(self).__modmex_base_model_type__,
                )
            )
            if compiled_dump is not None:
                return orjson.dumps(compiled_dump(self)).decode("utf-8")
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


def _dump_fields_for(model_cls: type[Any], profile: str | None, include_excluded: bool) -> tuple[Any, ...]:
    cache = model_cls.__modmex_dump_field_cache__
    key = (profile, include_excluded)
    if key not in cache:
        cache[key] = tuple(
            field
            for field in model_cls.__modmex_fields__
            if not should_exclude_field(field, None, profile, include_excluded)
        )
    return cache[key]
