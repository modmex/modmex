"""Optional Rust acceleration hooks.

This module loads the native extension when available and provides
small wrappers that fall back to pure Python behavior otherwise.
"""

from __future__ import annotations

import importlib
import os
from typing import Any

_NATIVE = None
_ENABLE_RUST_TREE = os.getenv("MODMEX_ENABLE_RUST_TREE", "0") in {"1", "true", "TRUE", "yes", "YES"}
_ENABLE_RUST_CONSTRUCT = os.getenv("MODMEX_ENABLE_RUST_CONSTRUCT", "1") in {"1", "true", "TRUE", "yes", "YES"}

try:
    _NATIVE = importlib.import_module("modmex._modmex_rust")
except Exception:
    try:
        _NATIVE = importlib.import_module("_modmex_rust")
    except Exception:
        _NATIVE = None


def rust_core_available() -> bool:
    return _NATIVE is not None


def rust_tree_enabled() -> bool:
    if _NATIVE is None or not _ENABLE_RUST_TREE:
        return False
    return hasattr(_NATIVE, "serialize_tree")


def rust_construct_enabled() -> bool:
    if _NATIVE is None or not _ENABLE_RUST_CONSTRUCT:
        return False
    return hasattr(_NATIVE, "coerce_values")


def rust_construct_kwargs_enabled() -> bool:
    if _NATIVE is None or not _ENABLE_RUST_CONSTRUCT:
        return False
    return hasattr(_NATIVE, "coerce_kwargs")


def rust_runtime_construct_enabled() -> bool:
    if _NATIVE is None or not _ENABLE_RUST_CONSTRUCT:
        return False
    return hasattr(_NATIVE, "construct_model_runtime")


def build_model_core(model_type: type[Any], descriptors: tuple[Any, ...]) -> Any:
    if _NATIVE is None or not _ENABLE_RUST_CONSTRUCT:
        return None
    model_core = getattr(_NATIVE, "ModelCore", None)
    if model_core is None:
        return None
    try:
        return model_core(model_type, descriptors)
    except Exception:
        return None


def try_core_construct_into(core: Any, target: Any, kwargs: dict[str, Any]) -> bool:
    if core is None or _NATIVE is None or not _ENABLE_RUST_CONSTRUCT:
        return False
    try:
        return bool(core.construct_into(target, kwargs))
    except Exception:
        return False


def try_core_validate_kwargs(core: Any, kwargs: dict[str, Any]) -> Any:
    if core is None or _NATIVE is None or not _ENABLE_RUST_CONSTRUCT:
        return None
    try:
        return core.validate_kwargs(kwargs)
    except Exception:
        return None


def try_core_validate_updates(core: Any, kwargs: dict[str, Any]) -> Any:
    if core is None or _NATIVE is None or not _ENABLE_RUST_CONSTRUCT:
        return None
    try:
        return core.validate_updates(kwargs)
    except Exception:
        return None


def try_serialize_scalar(value: Any) -> Any:
    """Try native scalar serialization.

    Returns ``None`` when native backend is unavailable or when the value
    is not handled by the native function.
    """

    if _NATIVE is None:
        return None
    return _NATIVE.serialize_scalar(value)


def try_serialize_tree(value: Any) -> Any:
    if _NATIVE is None or not _ENABLE_RUST_TREE:
        return None
    serializer = getattr(_NATIVE, "serialize_tree", None)
    if serializer is None:
        return None
    try:
        return serializer(value)
    except Exception:
        return None


def try_serialize_model_fields(
    value: Any,
    field_names: tuple[str, ...],
    property_names: tuple[str, ...],
) -> Any:
    if _NATIVE is None or not _ENABLE_RUST_TREE:
        return None
    serializer = getattr(_NATIVE, "serialize_model_fields", None)
    if serializer is None:
        return None
    try:
        return serializer(value, field_names, property_names)
    except Exception:
        return None


def try_coerce_values(values: list[Any], kinds: tuple[int, ...]) -> Any:
    if _NATIVE is None or not _ENABLE_RUST_CONSTRUCT:
        return None
    coerce = getattr(_NATIVE, "coerce_values", None)
    if coerce is None:
        return None
    try:
        return coerce(values, kinds)
    except Exception:
        return None


def try_coerce_kwargs(
    kwargs: dict[str, Any],
    names: tuple[str, ...],
    kinds: tuple[int, ...],
    min_mismatches: int,
) -> Any:
    if _NATIVE is None or not _ENABLE_RUST_CONSTRUCT:
        return None
    coerce = getattr(_NATIVE, "coerce_kwargs", None)
    if coerce is None:
        return None
    try:
        return coerce(kwargs, names, kinds, min_mismatches)
    except Exception:
        return None


def try_coerce_enum_kwargs(
    kwargs: dict[str, Any],
    names: tuple[str, ...],
    enum_types: tuple[type[Any], ...],
    min_fields: int,
) -> Any:
    if _NATIVE is None or not _ENABLE_RUST_CONSTRUCT:
        return None
    coerce = getattr(_NATIVE, "coerce_enum_kwargs", None)
    if coerce is None:
        return None
    try:
        return coerce(kwargs, names, enum_types, min_fields)
    except Exception:
        return None


def try_coerce_model_kwargs(
    kwargs: dict[str, Any],
    names: tuple[str, ...],
    model_types: tuple[type[Any], ...],
    min_fields: int,
) -> Any:
    if _NATIVE is None or not _ENABLE_RUST_CONSTRUCT:
        return None
    coerce = getattr(_NATIVE, "coerce_model_kwargs", None)
    if coerce is None:
        return None
    try:
        return coerce(kwargs, names, model_types, min_fields)
    except Exception:
        return None


def try_coerce_construct_kwargs(
    kwargs: dict[str, Any],
    scalar_names: tuple[str, ...],
    scalar_kinds: tuple[int, ...],
    enum_names: tuple[str, ...],
    enum_types: tuple[type[Any], ...],
    model_names: tuple[str, ...],
    model_types: tuple[type[Any], ...],
    min_fields: int,
) -> Any:
    if _NATIVE is None or not _ENABLE_RUST_CONSTRUCT:
        return None
    coerce = getattr(_NATIVE, "coerce_construct_kwargs", None)
    if coerce is None:
        return None
    try:
        return coerce(
            kwargs,
            scalar_names,
            scalar_kinds,
            enum_names,
            enum_types,
            model_names,
            model_types,
            min_fields,
        )
    except Exception:
        return None


def try_coerce_schema_kwargs(
    kwargs: dict[str, Any],
    schema: dict[str, Any],
    min_fields: int,
) -> Any:
    if _NATIVE is None or not _ENABLE_RUST_CONSTRUCT:
        return None
    coerce = getattr(_NATIVE, "coerce_schema_kwargs", None)
    if coerce is None:
        return None
    try:
        return coerce(kwargs, schema, min_fields)
    except Exception:
        return None


def try_construct_model_from_schema(
    kwargs: dict[str, Any],
    model_type: type[Any],
    schema: dict[str, Any],
    min_fields: int,
) -> Any:
    if _NATIVE is None or not _ENABLE_RUST_CONSTRUCT:
        return None
    construct = getattr(_NATIVE, "construct_model_from_schema", None)
    if construct is None:
        return None
    try:
        return construct(kwargs, model_type, schema, min_fields)
    except Exception:
        return None


def try_construct_model_runtime(
    kwargs: dict[str, Any],
    model_type: type[Any],
    schema: dict[str, Any],
    scalar_names: tuple[str, ...],
    scalar_kinds: tuple[int, ...],
    enum_names: tuple[str, ...],
    enum_types: tuple[type[Any], ...],
    model_names: tuple[str, ...],
    model_types: tuple[type[Any], ...],
    min_fields: int,
) -> Any:
    if _NATIVE is None or not _ENABLE_RUST_CONSTRUCT:
        return None
    construct = getattr(_NATIVE, "construct_model_runtime", None)
    if construct is None:
        return None
    try:
        return construct(
            kwargs,
            model_type,
            schema,
            scalar_names,
            scalar_kinds,
            enum_names,
            enum_types,
            model_names,
            model_types,
            min_fields,
        )
    except Exception:
        return None


def try_coerce_str(value: Any) -> Any:
    if _NATIVE is None:
        return None
    return _NATIVE.coerce_str(value)


def try_coerce_int(value: Any) -> Any:
    if _NATIVE is None:
        return None
    return _NATIVE.coerce_int(value)


def try_coerce_float(value: Any) -> Any:
    if _NATIVE is None:
        return None
    return _NATIVE.coerce_float(value)


def try_coerce_bool(value: Any) -> Any:
    if _NATIVE is None:
        return None
    return _NATIVE.coerce_bool(value)


def try_coerce_time(value: Any) -> Any:
    if _NATIVE is None:
        return None
    coerce = getattr(_NATIVE, "coerce_time", None)
    if coerce is None:
        return None
    return coerce(value)


def try_coerce_date(value: Any) -> Any:
    if _NATIVE is None:
        return None
    coerce = getattr(_NATIVE, "coerce_date", None)
    if coerce is None:
        return None
    return coerce(value)


def try_coerce_datetime(value: Any) -> Any:
    if _NATIVE is None:
        return None
    coerce = getattr(_NATIVE, "coerce_datetime", None)
    if coerce is None:
        return None
    return coerce(value)
