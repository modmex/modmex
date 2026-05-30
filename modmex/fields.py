"""Field helpers for dataclass-backed models."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import MISSING, Field as DataclassField
from dataclasses import field as dataclass_field
from typing import Any, Callable

_EXCLUDE = "__modmex_exclude__"
_EXCLUDE_FROM = "__modmex_exclude_from__"


def Field(
    default: Any = MISSING,
    *,
    default_factory: Callable[[], Any] | Any = MISSING,
    exclude: bool = False,
    exclude_from: Iterable[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> Any:
    """Create a dataclass field with modmex serialization options."""
    field_metadata = dict(metadata or {})
    field_metadata[_EXCLUDE] = exclude
    field_metadata[_EXCLUDE_FROM] = _normalize_profiles(exclude_from)

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
