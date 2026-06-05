"""Field helpers for dataclass-backed models."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import Field as DataclassField
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
_PATTERN = "__modmex_pattern__"
_MULTIPLE_OF = "__modmex_multiple_of__"
_MAX_DIGITS = "__modmex_max_digits__"
_DECIMAL_PLACES = "__modmex_decimal_places__"
_DEPRECATED = "__modmex_deprecated__"
_FROZEN = "__modmex_frozen__"
_FIELD_INFO = "__modmex_field_info__"


class UndefinedType:
    """Sentinel type for fields without an explicit value."""

    def __repr__(self) -> str:
        return "Undefined"

    def __copy__(self) -> UndefinedType:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> UndefinedType:
        return self


Undefined = UndefinedType()


class FieldInfo:
    """Modmex field metadata before it is adapted to a dataclass backend."""

    def __init__(
        self,
        default: Any = Undefined,
        *,
        annotation: Any = Undefined,
        default_factory: Callable[[], Any] | Any = Undefined,
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
        pattern: str | None = None,
        multiple_of: float | int | None = None,
        max_digits: int | None = None,
        decimal_places: int | None = None,
        deprecated: str | bool | None = None,
        frozen: bool = False,
        exclude: bool = False,
        exclude_from: Iterable[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
        dataclass_kwargs: Mapping[str, Any] | None = None,
    ) -> None:
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
        if multiple_of == 0:
            raise ValueError("multiple_of must be non-zero")
        if max_digits is not None and max_digits <= 0:
            raise ValueError("max_digits must be greater than 0")
        if decimal_places is not None and decimal_places < 0:
            raise ValueError("decimal_places must be greater than or equal to 0")
        if max_digits is not None and decimal_places is not None and decimal_places > max_digits:
            raise ValueError("decimal_places cannot be greater than max_digits")
        if default is not Undefined and default_factory is not Undefined:
            raise ValueError("cannot specify both default and default_factory")
        self.annotation = annotation
        self.default = default
        self.default_factory = default_factory
        self.alias = alias
        self.validation_alias = validation_alias
        self.serialization_alias = serialization_alias
        self.title = title
        self.description = description
        self.examples = examples
        self.gt = gt
        self.ge = ge
        self.lt = lt
        self.le = le
        self.min_length = min_length
        self.max_length = max_length
        self.pattern = pattern
        self.multiple_of = multiple_of
        self.max_digits = max_digits
        self.decimal_places = decimal_places
        self.deprecated = deprecated
        self.frozen = frozen
        self.exclude = exclude
        self.exclude_from = exclude_from
        self.metadata = metadata
        self.dataclass_kwargs = dataclass_kwargs

    def is_required(self) -> bool:
        """Check whether the field has no default value or factory."""
        return self.default is Undefined and self.default_factory is Undefined

    def get_default(self, *, call_default_factory: bool = False) -> Any:
        """Return the default value, optionally calling the default factory."""
        if self.default is not Undefined:
            return deepcopy(self.default)
        if self.default_factory is not Undefined and call_default_factory:
            return self.default_factory()
        return Undefined if self.default_factory is Undefined else None

    def as_metadata(self) -> dict[str, Any]:
        field_metadata = dict(self.metadata or {})
        field_metadata[_FIELD_INFO] = self
        field_metadata[_EXCLUDE] = self.exclude
        field_metadata[_EXCLUDE_FROM] = _normalize_profiles(self.exclude_from)
        field_metadata[_ALIAS] = self.alias
        field_metadata[_VALIDATION_ALIASES] = _normalize_aliases(self.validation_alias)
        field_metadata[_SERIALIZATION_ALIAS] = self.serialization_alias
        field_metadata[_TITLE] = self.title
        field_metadata[_DESCRIPTION] = self.description
        field_metadata[_EXAMPLES] = tuple(self.examples) if self.examples is not None else None
        field_metadata[_GT] = self.gt
        field_metadata[_GE] = self.ge
        field_metadata[_LT] = self.lt
        field_metadata[_LE] = self.le
        field_metadata[_MIN_LENGTH] = self.min_length
        field_metadata[_MAX_LENGTH] = self.max_length
        field_metadata[_PATTERN] = self.pattern
        field_metadata[_MULTIPLE_OF] = self.multiple_of
        field_metadata[_MAX_DIGITS] = self.max_digits
        field_metadata[_DECIMAL_PLACES] = self.decimal_places
        field_metadata[_DEPRECATED] = self.deprecated
        field_metadata[_FROZEN] = self.frozen
        return field_metadata

    def to_dataclass_field(self) -> DataclassField[Any]:
        kwargs = dict(self.dataclass_kwargs or {})
        field_metadata = self.as_metadata()
        if self.default is not Undefined:
            return dataclass_field(default=self.default, metadata=field_metadata, **kwargs)
        if self.default_factory is not Undefined:
            return dataclass_field(
                default_factory=self.default_factory,
                metadata=field_metadata,
                **kwargs,
            )
        return dataclass_field(metadata=field_metadata, **kwargs)


def Field(
    default: Any = Undefined,
    *,
    default_factory: Callable[[], Any] | Any = Undefined,
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
    pattern: str | None = None,
    multiple_of: float | int | None = None,
    max_digits: int | None = None,
    decimal_places: int | None = None,
    deprecated: str | bool | None = None,
    frozen: bool = False,
    exclude: bool = False,
    exclude_from: Iterable[str] | None = None,
    metadata: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> FieldInfo:
    """Create modmex field metadata."""
    return FieldInfo(
        default=default,
        default_factory=default_factory,
        alias=alias,
        validation_alias=validation_alias,
        serialization_alias=serialization_alias,
        title=title,
        description=description,
        examples=examples,
        gt=gt,
        ge=ge,
        lt=lt,
        le=le,
        min_length=min_length,
        max_length=max_length,
        pattern=pattern,
        multiple_of=multiple_of,
        max_digits=max_digits,
        decimal_places=decimal_places,
        deprecated=deprecated,
        frozen=frozen,
        exclude=exclude,
        exclude_from=exclude_from,
        metadata=metadata,
        dataclass_kwargs=kwargs,
    )


def field_info(field: DataclassField[Any]) -> FieldInfo | None:
    value = field.metadata.get(_FIELD_INFO)
    return value if isinstance(value, FieldInfo) else None



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
        "pattern": metadata.get(_PATTERN),
        "multiple_of": metadata.get(_MULTIPLE_OF),
        "max_digits": metadata.get(_MAX_DIGITS),
        "decimal_places": metadata.get(_DECIMAL_PLACES),
    }


def field_deprecated(field: DataclassField[Any]) -> str | bool | None:
    return field.metadata.get(_DEPRECATED)


def field_frozen(field: DataclassField[Any]) -> bool:
    return bool(field.metadata.get(_FROZEN, False))
