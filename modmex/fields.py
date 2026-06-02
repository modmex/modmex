"""Field helpers for dataclass-backed models."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import MISSING, Field as DataclassField
from dataclasses import field as dataclass_field
from typing import Any, Callable

_EXCLUDE = "__modmex_exclude__"
_EXCLUDE_FROM = "__modmex_exclude_from__"
_ALIAS = "__modmex_alias__"
_VALIDATION_ALIASES = "__modmex_validation_aliases__"
_SERIALIZATION_ALIAS = "__modmex_serialization_alias__"
_TITLE = "__modmex_title__"
_DESCRIPTION = "__modmex_description__"
_EXAMPLES = "__modmex_examples__"
_GT = "__modmex_gt__"
_GE = "__modmex_ge__"
_LT = "__modmex_lt__"
_LE = "__modmex_le__"
_MIN_LENGTH = "__modmex_min_length__"
_MAX_LENGTH = "__modmex_max_length__"


def Field(
    default: Any = MISSING,
    *,
    default_factory: Callable[[], Any] | Any = MISSING,
    alias: str | None = None,
    validation_alias: str | Iterable[str] | None = None,
    serialization_alias: str | None = None,
    title: str | None = None,
    description: str | None = None,
    examples: Iterable[Any] | None = None,
    gt: float | int | None = None,
    ge: float | int | None = None,
    lt: float | int | None = None,
    le: float | int | None = None,
    min_length: int | None = None,
    max_length: int | None = None,
    exclude: bool = False,
    exclude_from: Iterable[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> Any:
    """Create a dataclass field with modmex serialization options."""
    field_metadata = dict(metadata or {})
    field_metadata[_EXCLUDE] = exclude
    field_metadata[_EXCLUDE_FROM] = _normalize_profiles(exclude_from)
    field_metadata[_ALIAS] = alias
    field_metadata[_VALIDATION_ALIASES] = _normalize_aliases(validation_alias)
    field_metadata[_SERIALIZATION_ALIAS] = serialization_alias
    field_metadata[_TITLE] = title
    field_metadata[_DESCRIPTION] = description
    field_metadata[_EXAMPLES] = tuple(examples) if examples is not None else None
    field_metadata[_GT] = gt
    field_metadata[_GE] = ge
    field_metadata[_LT] = lt
    field_metadata[_LE] = le
    field_metadata[_MIN_LENGTH] = min_length
    field_metadata[_MAX_LENGTH] = max_length

    if min_length is not None and min_length < 0:
        raise ValueError("min_length must be greater than or equal to 0")
    if max_length is not None and max_length < 0:
        raise ValueError("max_length must be greater than or equal to 0")
    if min_length is not None and max_length is not None and min_length > max_length:
        raise ValueError("min_length cannot be greater than max_length")
    if gt is not None and ge is not None:
        raise ValueError("cannot set both gt and ge")
    if lt is not None and le is not None:
        raise ValueError("cannot set both lt and le")

    if default is not MISSING and default_factory is not MISSING:
        raise ValueError("cannot specify both default and default_factory")
    if default is not MISSING:
        return dataclass_field(default=default, metadata=field_metadata, **kwargs)
    if default_factory is not MISSING:
        return dataclass_field(default_factory=default_factory, metadata=field_metadata, **kwargs)
    return dataclass_field(metadata=field_metadata, **kwargs)


def should_exclude_field(
    field: DataclassField[Any],
    explicit_exclude: Any,
    profile: str | None,
    include_excluded: bool,
) -> bool:
    if explicit_exclude is True:
        return True
    if include_excluded:
        return False
    if field.metadata.get(_EXCLUDE, False):
        return True
    return profile is not None and profile in field.metadata.get(_EXCLUDE_FROM, frozenset())


def _normalize_profiles(profiles: Iterable[str] | None) -> frozenset[str]:
    if profiles is None:
        return frozenset()
    if isinstance(profiles, str):
        return frozenset({profiles})
    return frozenset(profiles)


def _normalize_aliases(validation_alias: str | Iterable[str] | None) -> tuple[str, ...]:
    if validation_alias is None:
        return ()
    if isinstance(validation_alias, str):
        return (validation_alias,)
    return tuple(alias for alias in validation_alias if isinstance(alias, str) and alias)


def field_alias(field: DataclassField[Any]) -> str | None:
    return field.metadata.get(_ALIAS)


def field_validation_aliases(field: DataclassField[Any]) -> tuple[str, ...]:
    aliases = field.metadata.get(_VALIDATION_ALIASES, ())
    return aliases if isinstance(aliases, tuple) else tuple(aliases)


def field_serialization_alias(field: DataclassField[Any]) -> str | None:
    return field.metadata.get(_SERIALIZATION_ALIAS)


def field_constraints(field: DataclassField[Any]) -> dict[str, Any]:
    metadata = field.metadata
    return {
        "gt": metadata.get(_GT),
        "ge": metadata.get(_GE),
        "lt": metadata.get(_LT),
        "le": metadata.get(_LE),
        "min_length": metadata.get(_MIN_LENGTH),
        "max_length": metadata.get(_MAX_LENGTH),
    }
