"""Helpers for resolving concrete types in generic model subclasses."""

from __future__ import annotations

import functools
import operator
import types
import typing
from typing import Any, TypeVar, get_args, get_origin


def model_typevar_map(model_cls: type[Any]) -> dict[TypeVar, Any]:
    """Return TypeVar bindings inherited by a concrete model class."""

    explicit = getattr(model_cls, "__modmex_explicit_typevar_map__", {})
    bindings: dict[TypeVar, Any] = dict(explicit)
    visited: set[tuple[type[Any], tuple[tuple[TypeVar, Any], ...]]] = set()

    def visit(current: type[Any], inherited: dict[TypeVar, Any]) -> None:
        key = (current, tuple(inherited.items()))
        if key in visited:
            return
        visited.add(key)
        bindings.update(inherited)
        for base in getattr(current, "__orig_bases__", ()):
            origin = get_origin(base)
            if not isinstance(origin, type):
                continue
            args = tuple(resolve_typevars(arg, inherited) for arg in get_args(base))
            parameters = getattr(origin, "__parameters__", ())
            local = dict(inherited)
            local.update(zip(parameters, args))
            bindings.update(zip(parameters, args))
            visit(origin, local)

    visit(model_cls, dict(explicit))
    return bindings


def resolve_typevars(annotation: Any, bindings: dict[TypeVar, Any]) -> Any:
    """Recursively substitute TypeVars in a type annotation."""

    if isinstance(annotation, TypeVar):
        resolved = bindings.get(annotation, annotation)
        return annotation if resolved is annotation else resolve_typevars(resolved, bindings)

    args = get_args(annotation)
    if not args:
        return annotation
    resolved_args = tuple(resolve_typevars(arg, bindings) for arg in args)
    if resolved_args == args:
        return annotation

    origin = get_origin(annotation)
    if origin is types.UnionType:
        return functools.reduce(operator.or_, resolved_args)
    if origin is typing.Union:
        return typing.Union[resolved_args]
    copy_with = getattr(annotation, "copy_with", None)
    if callable(copy_with):
        return copy_with(resolved_args)
    try:
        return origin[resolved_args[0] if len(resolved_args) == 1 else resolved_args]
    except (TypeError, AttributeError):
        return annotation


def resolve_model_type_hints(model_cls: type[Any], type_hints: dict[str, Any]) -> dict[str, Any]:
    """Apply a model's inherited generic bindings to resolved type hints."""

    bindings = model_typevar_map(model_cls)
    if not bindings:
        return type_hints
    return {name: resolve_typevars(annotation, bindings) for name, annotation in type_hints.items()}
