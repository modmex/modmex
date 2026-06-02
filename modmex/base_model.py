"""Dataclass-backed model base with validation and serialization helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import MISSING, dataclass, fields
from typing import Any, Callable
import warnings

import orjson

from .fields import (
    field_alias,
    field_constraints,
    field_deprecated,
    field_frozen,
    field_serialization_alias,
    field_validation_aliases,
    should_exclude_field,
)
from . import rust_backend
from .model_plans import (
    _dump_plan_for,
    _rust_field_descriptors,
    _rust_schema_for,
)
from .serialization import ExcludeSpec, TypeSerializers, custom_serializer, normalize_exclude, serialize_value
from .validation import validate_model_constraints, validate_model_fields


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
        validation_alias_map: dict[str, str] = {}
        serialization_name_map: dict[str, str] = {}
        deprecated_fields: dict[str, str | bool] = {}
        frozen_fields: set[str] = set()
        has_constraints = False
        for field in model_fields:
            alias = field_alias(field)
            validation_aliases = field_validation_aliases(field)
            constraints = field_constraints(field)
            deprecated = field_deprecated(field)
            frozen = field_frozen(field)
            if any(value is not None for value in constraints.values()):
                has_constraints = True
            if deprecated:
                deprecated_fields[field.name] = deprecated
            if frozen:
                frozen_fields.add(field.name)
            input_aliases = validation_aliases or ((alias,) if alias else ())
            for alias_name in input_aliases:
                if alias_name == field.name:
                    continue
                existing_field = validation_alias_map.get(alias_name)
                if existing_field is not None and existing_field != field.name:
                    raise ValueError(
                        f"duplicate validation alias '{alias_name}' for fields "
                        f"'{existing_field}' and '{field.name}'"
                    )
                validation_alias_map[alias_name] = field.name
            output_name = field_serialization_alias(field) or alias or field.name
            serialization_name_map[field.name] = output_name
        model_cls.__modmex_validation_alias_map__ = validation_alias_map
        model_cls.__modmex_has_validation_aliases__ = bool(validation_alias_map)
        model_cls.__modmex_serialization_name_map__ = serialization_name_map
        model_cls.__modmex_has_serialization_aliases__ = any(
            output_name != field_name
            for field_name, output_name in serialization_name_map.items()
        )
        model_cls.__modmex_deprecated_fields__ = deprecated_fields
        model_cls.__modmex_frozen_fields__ = frozenset(frozen_fields)
        model_cls.__modmex_has_constraints__ = has_constraints
        model_cls.__modmex_dump_field_cache__ = {}
        model_cls.__modmex_dump_plan_cache__ = {}
        model_cls.__modmex_dump_plan_alias_cache__ = {}
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
        model_cls.__modmex_dump_plan__ = _dump_plan_for(model_cls, None, base_model_type)
        model_cls.__modmex_core__ = (
            rust_backend.build_model_core(model_cls, model_cls.__modmex_rust_descriptors__)
            if model_cls.__modmex_rust_fast_init__
            else None
        )
        original_init = model_cls.__init__
        model_core = model_cls.__modmex_core__
        field_names = model_cls.__modmex_field_names__
        validation_alias_map = model_cls.__modmex_validation_alias_map__
        has_validation_aliases = model_cls.__modmex_has_validation_aliases__
        has_constraints = model_cls.__modmex_has_constraints__
        model_frozen_fields = model_cls.__modmex_frozen_fields__

        def new_init(self: Any, *args: Any, **kwargs: Any) -> None:
            normalized_kwargs = kwargs
            if has_validation_aliases and kwargs:
                for alias_name, field_name in validation_alias_map.items():
                    if alias_name not in normalized_kwargs:
                        continue
                    if normalized_kwargs is kwargs:
                        normalized_kwargs = dict(kwargs)
                    if field_name not in normalized_kwargs:
                        normalized_kwargs[field_name] = normalized_kwargs[alias_name]
                    del normalized_kwargs[alias_name]

            if not args and rust_backend.try_core_construct_into(model_core, self, normalized_kwargs):
                if has_constraints:
                    validate_model_constraints(self)
                return
            filtered_kwargs = normalized_kwargs if normalized_kwargs.keys() <= field_names else {
                key: value for key, value in normalized_kwargs.items() if key in field_names
            }
            original_init(self, *args, **filtered_kwargs)

        if model_frozen_fields:
            original_setattr = model_cls.__setattr__

            def new_setattr(self: Any, name: str, value: Any) -> None:
                if name in model_frozen_fields and name in self.__dict__:
                    raise AttributeError(f"Field '{name}' is frozen and cannot be modified")
                original_setattr(self, name, value)

            model_cls.__setattr__ = new_setattr

        if deprecated_fields:
            original_getattribute = model_cls.__getattribute__

            def new_getattribute(self: Any, name: str) -> Any:
                value = original_getattribute(self, name)
                deprecated = deprecated_fields.get(name)
                if deprecated:
                    state = original_getattribute(self, "__dict__")
                    warned = state.get("__modmex_deprecation_warned__")
                    if warned is None:
                        warned = set()
                        state["__modmex_deprecation_warned__"] = warned
                    if name not in warned:
                        message = (
                            deprecated
                            if isinstance(deprecated, str)
                            else f"Field '{name}' is deprecated"
                        )
                        warnings.warn(message, DeprecationWarning, stacklevel=2)
                        warned.add(name)
                return value

            model_cls.__getattribute__ = new_getattribute

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
        has_serialization_aliases = type(self).__modmex_has_serialization_aliases__
        serialization_name_map = type(self).__modmex_serialization_name_map__

        if exclude is None and not include_excluded and not type_serializers:
            if not has_serialization_aliases:
                dump_plan = (
                    type(self).__modmex_dump_plan__
                    if profile is None
                    else _dump_plan_for(
                        type(self),
                        profile,
                        type(self).__modmex_base_model_type__,
                    )
                )
            else:
                dump_plan = _dump_plan_for(
                    type(self),
                    profile,
                    type(self).__modmex_base_model_type__,
                    serialization_name_map,
                )
            if dump_plan is not None:
                return dump_plan(self)
        exclude_map = normalize_exclude(exclude)
        if exclude_map:
            result: dict[str, Any] = {}
            for field in type(self).__modmex_fields__:
                field_name = field.name
                if should_exclude_field(field, exclude_map.get(field_name), profile, include_excluded):
                    continue
                result[serialization_name_map.get(field_name, field_name)] = serialize_value(
                    getattr(self, field_name),
                    exclude=exclude_map.get(field_name),
                    profile=profile,
                    include_excluded=include_excluded,
                    type_serializers=type_serializers,
                )
        else:
            result = {
                serialization_name_map.get(field.name, field.name): serialize_value(
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
        if exclude is None and not include_excluded and not type_serializers:
            has_serialization_aliases = type(self).__modmex_has_serialization_aliases__
            if not has_serialization_aliases:
                dump_plan = (
                    type(self).__modmex_dump_plan__
                    if profile is None
                    else _dump_plan_for(
                        type(self),
                        profile,
                        type(self).__modmex_base_model_type__,
                    )
                )
            else:
                dump_plan = _dump_plan_for(
                    type(self),
                    profile,
                    type(self).__modmex_base_model_type__,
                    type(self).__modmex_serialization_name_map__,
                )
            if dump_plan is not None:
                return dump_plan(self)
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
            if not type(self).__modmex_has_serialization_aliases__:
                dump_plan = (
                    type(self).__modmex_dump_plan__
                    if profile is None
                    else _dump_plan_for(
                        type(self),
                        profile,
                        type(self).__modmex_base_model_type__,
                    )
                )
            else:
                dump_plan = _dump_plan_for(
                    type(self),
                    profile,
                    type(self).__modmex_base_model_type__,
                    type(self).__modmex_serialization_name_map__,
                )
            if dump_plan is not None:
                return orjson.dumps(dump_plan(self)).decode("utf-8")
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
