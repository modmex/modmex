from collections.abc import Mapping
from dataclasses import field as dataclass_field
from typing import Any, Callable, dataclass_transform

from .fields import Field
from .serialization import ExcludeSpec, TypeSerializers


def field_validator(field_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...


def model_validator(mode: str = "before") -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...


@dataclass_transform(kw_only_default=True, field_specifiers=(Field, dataclass_field))
class BaseModel:
    def __post_init__(self) -> None: ...
    def model_dump(
        self,
        *,
        exclude: ExcludeSpec = None,
        profile: str | None = None,
        include_excluded: bool = False,
        type_serializers: TypeSerializers = None,
    ) -> dict[str, Any]: ...
    def model_dump_json(
        self,
        *,
        exclude: ExcludeSpec = None,
        profile: str | None = None,
        include_excluded: bool = False,
        type_serializers: TypeSerializers = None,
    ) -> str: ...
