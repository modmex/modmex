"""Dataclass-backed model base with validation and serialization helpers."""

from __future__ import annotations

from collections.abc import Callable as CallableABC
from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import MISSING, Field as DataclassField, dataclass, fields
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
import sys
import types
import typing
from typing import Any, Callable, Literal, TypedDict, get_args, get_origin
from uuid import UUID
import warnings

import orjson

from .fields import (
    FieldInfo,
    field_alias,
    field_constraints,
    field_deprecated,
    field_frozen,
    field_info,
    field_serialization_alias,
    field_validation_aliases,
    should_exclude_field,
)
from .errors import UnsupportedJsonSchemaTypeError
from . import rust_backend
from .model_plans import (
    _dump_plan_for,
    _rust_field_descriptors,
    _rust_schema_for,
)
from .serialization import ExcludeSpec, TypeSerializers, custom_serializer, normalize_exclude, serialize_value
from .type_resolution import resolve_model_type_hints, resolve_typevars
from .validation import validate_model_constraints, validate_model_fields


_INTERNAL_ACCESS_FLAG = "__modmex_internal_access__"


AliasGenerator = Callable[[str], str]


class ConfigDict(TypedDict, total=False):
    """Model-level configuration."""

    alias_generator: AliasGenerator | None


def _internal_state(target: Any) -> dict[str, Any]:
    return object.__getattribute__(target, "__dict__")


def _set_internal_access(target: Any, enabled: bool) -> None:
    object.__setattr__(target, _INTERNAL_ACCESS_FLAG, enabled)


def _has_internal_access(target: Any) -> bool:
    return _internal_state(target).get(_INTERNAL_ACCESS_FLAG, False)


@contextmanager
def _bypass_internal_field_hooks(target: Any):
    _set_internal_access(target, True)
    try:
        yield
    finally:
        _set_internal_access(target, False)


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
        for field_name, field_spec in tuple(namespace.items()):
            if field_name.startswith("__"):
                continue
            if isinstance(field_spec, FieldInfo):
                namespace[field_name] = field_spec.to_dataclass_field()
        
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
        model_config = _normalize_model_config(getattr(model_cls, "model_config", None))
        model_cls.model_config = model_config
        alias_generator = model_config.get("alias_generator")
        validation_alias_map: dict[str, str] = {}
        serialization_name_map: dict[str, str] = {}
        deprecated_fields: dict[str, str | bool] = {}
        frozen_fields: set[str] = set()
        has_constraints = False
        for field in model_fields:
            alias = field_alias(field)
            generated_alias = alias_generator(field.name) if alias_generator is not None else None
            if generated_alias is not None and not isinstance(generated_alias, str):
                raise TypeError("alias_generator must return str or None")
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
            default_alias = alias or generated_alias
            input_aliases = validation_aliases or ((default_alias,) if default_alias else ())
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
            output_name = field_serialization_alias(field) or default_alias or field.name
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
        model_cls.__modmex_has_internal_field_hooks__ = bool(deprecated_fields or frozen_fields)
        model_cls.__modmex_has_constraints__ = has_constraints
        model_cls.__modmex_dump_field_cache__ = {}
        model_cls.__modmex_dump_plan_cache__ = {}
        model_cls.__modmex_dump_plan_alias_cache__ = {}
        model_cls.__modmex_generic_cache__ = {}
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
        has_internal_field_hooks = model_cls.__modmex_has_internal_field_hooks__

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

            # Temporarily bypass deprecated/frozen hooks during internal model
            # construction so validation and coercion do not trigger user-facing behavior.
            if has_internal_field_hooks:
                with _bypass_internal_field_hooks(self):
                    if not args and rust_backend.try_core_construct_into(model_core, self, normalized_kwargs):
                        if has_constraints:
                            validate_model_constraints(self)
                        return
                    filtered_kwargs = normalized_kwargs if normalized_kwargs.keys() <= field_names else {
                        key: value for key, value in normalized_kwargs.items() if key in field_names
                    }
                    original_init(self, *args, **filtered_kwargs)
                return

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
                if name in model_frozen_fields and name in self.__dict__ and not _has_internal_access(self):
                    raise AttributeError(f"Field '{name}' is frozen and cannot be modified")
                original_setattr(self, name, value)

            model_cls.__setattr__ = new_setattr

        if deprecated_fields:
            original_getattribute = model_cls.__getattribute__

            def new_getattribute(self: Any, name: str) -> Any:
                value = original_getattribute(self, name)
                deprecated = deprecated_fields.get(name)
                if deprecated and not _has_internal_access(self):
                    state = _internal_state(self)
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


def _normalize_model_config(config: Any) -> ConfigDict:
    if config is None:
        return {}
    if not isinstance(config, Mapping):
        raise TypeError("model_config must be a mapping")
    normalized = dict(config)
    alias_generator = normalized.get("alias_generator")
    if alias_generator is not None and not callable(alias_generator):
        raise TypeError("model_config.alias_generator must be callable")
    return normalized


class BaseModel(metaclass=BaseModelMeta):
    """Base class for lightweight validated models."""

    def _run_validation_lifecycle(self) -> None:
        self._validate_model_before()
        self._validate_types()
        self._validate_fields()
        self._validate_model_after()

    def __post_init__(self) -> None:
        # Temporarily bypass deprecated/frozen hooks during internal validation
        # passes so framework reads/writes do not emit warnings or block updates.
        if type(self).__modmex_has_internal_field_hooks__:
            with _bypass_internal_field_hooks(self):
                self._run_validation_lifecycle()
            return

        self._run_validation_lifecycle()

    def __class_getitem__(cls, type_arguments: Any) -> type[Any]:
        """Create and cache a concrete Modmex model for generic arguments."""

        parameters = getattr(cls, "__parameters__", ())
        if not parameters:
            raise TypeError(f"{cls.__name__} is not a generic model")
        arguments = type_arguments if isinstance(type_arguments, tuple) else (type_arguments,)
        if len(arguments) != len(parameters):
            raise TypeError(
                f"{cls.__name__} expects {len(parameters)} type argument(s), got {len(arguments)}"
            )
        cache = cls.__modmex_generic_cache__
        if arguments in cache:
            return cache[arguments]

        argument_names = ", ".join(getattr(argument, "__name__", str(argument)) for argument in arguments)
        new_bindings = dict(zip(parameters, arguments))
        inherited_bindings = getattr(cls, "__modmex_explicit_typevar_map__", {})
        concrete_bindings = {
            parameter: resolve_typevars(argument, new_bindings)
            for parameter, argument in inherited_bindings.items()
        }
        concrete_bindings.update(new_bindings)
        specialized = BaseModelMeta(
            f"{cls.__name__}[{argument_names}]",
            (cls,),
            {
                "__module__": cls.__module__,
                "__modmex_explicit_typevar_map__": concrete_bindings,
            },
        )
        cache[arguments] = specialized
        return specialized

    @classmethod
    def model_json_schema(cls) -> dict[str, Any]:
        """Return a provider-neutral JSON Schema for this model."""

        return _JsonSchemaBuilder(cls).build()

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


_JSON_TYPE_BY_PYTHON_TYPE = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    type(None): "null",
}


def _json_default(value: Any) -> Any:
    """Convert declared defaults without ever evaluating a default factory."""

    if isinstance(value, Enum):
        return _json_default(value.value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return value.model_dump()
    if isinstance(value, (tuple, set, frozenset)):
        return [_json_default(item) for item in value]
    if isinstance(value, list):
        return [_json_default(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_default(item) for key, item in value.items()}
    return value


class _JsonSchemaBuilder:
    def __init__(self, root_model: type[Any]) -> None:
        self.root_model = root_model
        self.defs: dict[str, dict[str, Any]] = {}
        self._definition_names: dict[type[Any], str] = {}
        self._building: set[type[Any]] = set()

    def build(self) -> dict[str, Any]:
        schema = self._model_schema(self.root_model)
        if self.defs:
            schema["$defs"] = self.defs
        return schema

    def _model_schema(self, model_cls: type[Any]) -> dict[str, Any]:
        globalns = vars(sys.modules[model_cls.__module__])
        try:
            type_hints = typing.get_type_hints(model_cls, globalns=globalns, include_extras=True)
        except Exception:
            type_hints = {}
            for model_field in model_cls.__modmex_fields__:
                annotation = model_field.type
                if isinstance(annotation, str):
                    try:
                        annotation = eval(annotation, globalns, vars(model_cls))
                    except Exception:
                        pass
                type_hints[model_field.name] = annotation
        type_hints = resolve_model_type_hints(model_cls, type_hints)

        properties: dict[str, Any] = {}
        required_names = set(model_cls.__modmex_required_field_names__)
        required: list[str] = []
        output_names = model_cls.__modmex_serialization_name_map__
        for model_field in model_cls.__modmex_fields__:
            output_name = output_names.get(model_field.name, model_field.name)
            annotation = type_hints.get(model_field.name, model_field.type)
            field_schema = self._type_schema(annotation, model_field.name)
            self._apply_field_metadata(field_schema, model_field)
            if model_field.default is not MISSING:
                field_schema["default"] = _json_default(model_field.default)
            properties[output_name] = field_schema
            if model_field.name in required_names:
                required.append(output_name)

        return {
            "title": model_cls.__name__,
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }

    def _type_schema(self, annotation: Any, field_name: str) -> dict[str, Any]:
        if annotation is Any:
            return {}
        if annotation is list:
            return {"type": "array"}
        if annotation is dict:
            return {"type": "object", "additionalProperties": {}}
        json_type = _JSON_TYPE_BY_PYTHON_TYPE.get(annotation)
        if json_type is not None:
            return {"type": json_type}
        if isinstance(annotation, type) and issubclass(annotation, Enum):
            values = [_json_default(member.value) for member in annotation]
            schema: dict[str, Any] = {"enum": values}
            value_types = {
                _JSON_TYPE_BY_PYTHON_TYPE.get(type(value))
                for value in values
                if value is not None
            }
            if len(value_types) == 1 and None not in value_types:
                schema["type"] = value_types.pop()
            return schema
        if isinstance(annotation, type) and hasattr(annotation, "__modmex_fields__"):
            return self._model_ref(annotation)

        if annotation is datetime:
            return {"type": "string", "format": "date-time"}
        if annotation is date:
            return {"type": "string", "format": "date"}
        if annotation is time:
            return {"type": "string", "format": "time"}
        if annotation is timedelta:
            # Modmex serializes timedeltas as seconds.
            return {"type": "number"}
        if annotation is Decimal:
            return {"type": "number"}
        if annotation is UUID:
            return {"type": "string", "format": "uuid"}

        origin = get_origin(annotation)
        args = get_args(annotation)
        if origin is typing.Annotated:
            if not args:
                self._unsupported_type(field_name, annotation)
            return self._type_schema(args[0], field_name)
        if origin is Literal:
            values = [_json_default(value) for value in args]
            schema = {"enum": values}
            literal_types = {_JSON_TYPE_BY_PYTHON_TYPE.get(type(value)) for value in values}
            if None not in literal_types and len(literal_types) == 1:
                schema["type"] = literal_types.pop()
            return schema
        if origin in (list, typing.List):
            return {
                "type": "array",
                "items": self._type_schema(args[0], field_name) if args else {},
            }
        if origin is tuple:
            if not args:
                return {"type": "array"}
            if len(args) == 2 and args[1] is Ellipsis:
                return {"type": "array", "items": self._type_schema(args[0], field_name)}
            return {
                "type": "array",
                "prefixItems": [self._type_schema(arg, field_name) for arg in args],
                "minItems": len(args),
                "maxItems": len(args),
            }
        if origin in (set, frozenset):
            return {
                "type": "array",
                "items": self._type_schema(args[0], field_name) if args else {},
                "uniqueItems": True,
            }
        if origin in (dict, typing.Dict):
            value_schema = self._type_schema(args[1], field_name) if len(args) == 2 else {}
            return {"type": "object", "additionalProperties": value_schema}
        if origin in (typing.Union, types.UnionType):
            variants = [self._type_schema(arg, field_name) for arg in args]
            if all(set(variant) == {"type"} and isinstance(variant["type"], str) for variant in variants):
                return {"type": [variant["type"] for variant in variants]}
            return {"anyOf": variants}
        if origin in (Callable, CallableABC):
            self._unsupported_type(field_name, annotation)

        if isinstance(annotation, type):
            hook = getattr(annotation, "__modmex_json_schema__", None)
            if callable(hook):
                schema = hook()
                if not isinstance(schema, dict):
                    raise UnsupportedJsonSchemaTypeError(
                        f"Cannot generate JSON Schema for field '{field_name}': "
                        f"{annotation.__name__}.__modmex_json_schema__() must return a JSON Schema object."
                    )
                try:
                    orjson.dumps(schema)
                except (TypeError, ValueError) as exc:
                    raise UnsupportedJsonSchemaTypeError(
                        f"Cannot generate JSON Schema for field '{field_name}': "
                        f"{annotation.__name__}.__modmex_json_schema__() must return a JSON-serializable "
                        "JSON Schema object."
                    ) from exc
                return deepcopy(schema)

        self._unsupported_type(field_name, annotation)

    @staticmethod
    def _unsupported_type(field_name: str, annotation: Any) -> typing.NoReturn:
        type_name = getattr(annotation, "__name__", str(annotation))
        raise UnsupportedJsonSchemaTypeError(
            f"Cannot generate JSON Schema for field '{field_name}': "
            f"{type_name} has no JSON Schema representation."
        )

    def _apply_field_metadata(self, schema: dict[str, Any], model_field: Any) -> None:
        info = field_info(model_field)
        if info is not None:
            if info.title is not None:
                schema["title"] = info.title
            if info.description is not None:
                schema["description"] = info.description
            if info.examples is not None:
                schema["examples"] = [_json_default(example) for example in info.examples]
            if info.deprecated:
                schema["deprecated"] = True

        constraints = field_constraints(model_field)
        keyword_map = {
            "gt": "exclusiveMinimum",
            "ge": "minimum",
            "lt": "exclusiveMaximum",
            "le": "maximum",
            "multiple_of": "multipleOf",
            "pattern": "pattern",
        }
        for constraint_name, keyword in keyword_map.items():
            value = constraints[constraint_name]
            if value is not None:
                schema[keyword] = value

        schema_type = schema.get("type")
        min_length = constraints["min_length"]
        max_length = constraints["max_length"]
        schema_types = {schema_type} if isinstance(schema_type, str) else set(schema_type or ())
        if "string" in schema_types:
            if min_length is not None:
                schema["minLength"] = min_length
            if max_length is not None:
                schema["maxLength"] = max_length
        elif "array" in schema_types:
            if min_length is not None:
                schema["minItems"] = min_length
            if max_length is not None:
                schema["maxItems"] = max_length
        elif "object" in schema_types:
            if min_length is not None:
                schema["minProperties"] = min_length
            if max_length is not None:
                schema["maxProperties"] = max_length

        decimal_places = constraints["decimal_places"]
        if decimal_places is not None and "multipleOf" not in schema:
            schema["multipleOf"] = float(Decimal(1).scaleb(-decimal_places))
        max_digits = constraints["max_digits"]
        if max_digits is not None:
            integer_digits = max_digits - (decimal_places or 0)
            bound = 10 ** integer_digits
            schema["exclusiveMinimum"] = -bound
            schema["exclusiveMaximum"] = bound

    def _model_ref(self, model_cls: type[Any]) -> dict[str, str]:
        if model_cls is self.root_model:
            return {"$ref": "#"}
        name = self._definition_names.get(model_cls)
        if name is None:
            base_name = model_cls.__name__
            name = base_name
            suffix = 2
            while name in self.defs:
                name = f"{base_name}_{suffix}"
                suffix += 1
            self._definition_names[model_cls] = name
        if model_cls not in self._building and name not in self.defs:
            self._building.add(model_cls)
            # Reserve the key before descending so mutually recursive models terminate.
            self.defs[name] = {}
            self.defs[name] = self._model_schema(model_cls)
            self._building.remove(model_cls)
        return {"$ref": f"#/$defs/{name}"}


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


def _create_model_field_spec(field_name: str, field_definition: Any) -> tuple[Any, Any]:
    if isinstance(field_definition, tuple):
        if len(field_definition) != 2:
            raise TypeError(
                f"field '{field_name}' must be defined as (annotation, default) or (annotation, Field(...))"
            )
        annotation, default_spec = field_definition
        if default_spec is Ellipsis:
            return annotation, MISSING
        return annotation, default_spec

    origin = get_origin(field_definition)
    if origin is not None and getattr(origin, "__qualname__", "") == "Annotated":
        annotated_args = get_args(field_definition)
        if not annotated_args:
            raise TypeError(f"field '{field_name}' annotated type is invalid")
        annotation = annotated_args[0]
        default_spec: Any = MISSING
        for metadata_item in annotated_args[1:]:
            if isinstance(metadata_item, (DataclassField, FieldInfo)):
                default_spec = metadata_item
                break
        return annotation, default_spec

    raise TypeError(
        f"field '{field_name}' must be defined as (annotation, default), (annotation, Field(...)) or Annotated[annotation, Field(...)]"
    )


def create_model(
    model_name: str,
    __base__: type[Any] = None,
    __module__: str | None = None,
    __config__: Mapping[str, Any] | None = None,
    __validators__: Mapping[str, Any] | None = None,
    **field_definitions: Any,
) -> type[Any]:
    """Create a ``BaseModel`` subclass dynamically from field definitions."""

    base_model = BaseModel if __base__ is None else __base__
    if not isinstance(base_model, type) or not issubclass(base_model, BaseModel):
        raise TypeError("__base__ must be a BaseModel subclass")

    if __module__ is None:
        try:
            __module__ = sys._getframe(1).f_globals.get("__name__", "__main__")
        except (AttributeError, ValueError):
            __module__ = "__main__"

    namespace: dict[str, Any] = {"__module__": __module__, "__annotations__": {}}
    if __config__ is not None:
        namespace["model_config"] = dict(__config__)
    if __validators__:
        namespace.update(__validators__)

    annotations = namespace["__annotations__"]
    for field_name, field_definition in field_definitions.items():
        annotation, default_spec = _create_model_field_spec(field_name, field_definition)
        annotations[field_name] = annotation
        if default_spec is not MISSING:
            namespace[field_name] = (
                default_spec.to_dataclass_field()
                if isinstance(default_spec, FieldInfo)
                else default_spec
            )

    return BaseModelMeta(model_name, (base_model,), namespace)
