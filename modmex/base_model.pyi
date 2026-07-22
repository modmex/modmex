from collections.abc import Mapping
from dataclasses import field as dataclass_field
from typing import Any, Callable, TypedDict, dataclass_transform

from .fields import Field
from .serialization import ExcludeSpec, TypeSerializers


AliasGenerator = Callable[[str], str]


class ConfigDict(TypedDict, total=False):
    alias_generator: AliasGenerator | None


def field_validator(field_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...


def model_validator(mode: str = "before") -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...


@dataclass_transform(kw_only_default=True, field_specifiers=(Field, dataclass_field))
class BaseModel:
    model_config: ConfigDict
    def __post_init__(self) -> None: ...
    @classmethod
    def model_json_schema(cls) -> dict[str, Any]: ...
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


def create_model(
    model_name: str,
    __base__: type[BaseModel] | None = None,
    __module__: str | None = None,
    __config__: Mapping[str, Any] | None = None,
    __validators__: Mapping[str, Any] | None = None,
    **field_definitions: Any,
) -> type[BaseModel]: ...
