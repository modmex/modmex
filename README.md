# modmex

Lightweight Python models built on dataclasses with validation, serialization, and type-safe data mapping.

[![CI](https://img.shields.io/github/actions/workflow/status/modmex/modmex/ci.yml?branch=main&logo=github&label=CI)](https://github.com/modmex/modmex/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/codecov/c/github/modmex/modmex?label=coverage)](https://codecov.io/gh/modmex/modmex)
[![PyPI](https://img.shields.io/pypi/v/modmex.svg)](https://pypi.org/project/modmex/)
[![Python Versions](https://img.shields.io/pypi/pyversions/modmex.svg)](https://pypi.org/project/modmex/)
[![License](https://img.shields.io/github/license/modmex/modmex.svg)](https://github.com/modmex/modmex/blob/main/LICENSE)

modmex gives you a small but powerful toolkit for:

- Typed models with minimal boilerplate.
- Automatic coercion and validation at initialization time.
- Recursive serialization to Python primitives and JSON.
- Per-field and per-model validation hooks.
- Type-based custom serializers to adapt output for different consumers.


## Why modmex

If you want stricter models than plain dataclasses, but without the weight of a large framework, modmex is designed for that middle ground.

It focuses on:

- Simplicity: small API surface.
- Predictability: explicit model lifecycle.
- Flexibility: configurable serialization without changing your model definitions.


## Installation

With pip:

```bash
pip install modmex
```

With Poetry:

```bash
poetry add modmex
```




## Quick Start

```python
from decimal import Decimal

from modmex import BaseModel, Field


class User(BaseModel):
    id: int
    name: str
    balance: Decimal = Decimal("0")
    password: str = Field("", exclude=True)


user = User(id="1", name=123, balance="10.50")

# Type coercion happens during initialization.
assert user.id == 1
assert user.name == "123"
assert user.balance == Decimal("10.50")

# model_dump returns primitive/serializable values.
assert user.model_dump() == {
    "id": 1,
    "name": "123",
    "balance": 10.5,
}

# model_dump_json returns a JSON string.
assert user.model_dump_json() == '{"id":1,"name":"123","balance":10.5}'
```

## Field Configuration

Use `Field(...)` to add serialization metadata to a model field.

Main options:

- `exclude=True`
  - Always excludes this field from `model_dump` and `model_dump_json`.
- `exclude_from={"profile_name"}`
  - Excludes this field only for selected serialization profiles.

Example:

```python
from modmex import BaseModel, Field


class Session(BaseModel):
    id: str
    secret: str = Field("", exclude_from={"public"})


class User(BaseModel):
    id: int
    private_note: str = Field("x", exclude=True)
    sessions: list[Session] = Field(default_factory=list)


user = User(id=1, sessions=[Session(id="s1", secret="abc")])

assert user.model_dump(profile="public") == {
    "id": 1,
    "sessions": [{"id": "s1"}],
}
```

Tip:

- Use `exclude=True` for values that should never leave the model.
- Use `exclude_from={...}` when omission depends on the output profile.



## Everyday Usage

### 1) Parse and normalize input data

```python
from modmex import BaseModel


class Product(BaseModel):
    id: int
    name: str
    active: bool


product = Product(id="10", name=123, active="true")

assert product.id == 10
assert product.name == "123"
assert product.active is True
```

### 2) Work with nested models

```python
from modmex import BaseModel


class Address(BaseModel):
    zipcode: int


class User(BaseModel):
    id: int
    address: Address


user = User(id="1", address={"zipcode": "90210"})
assert user.address.zipcode == 90210
```

### 3) Prepare different payloads from the same model

```python
api_payload = account.model_dump(profile="public")
internal_payload = account.model_dump()
```

### 4) Build JSON directly

```python
json_payload = account.model_dump_json(profile="public")
```


## Dynamic Models

Use `create_model` when you need to define a model at runtime.

Field definitions can use one of these forms:

- `(annotation, default)`
- `(annotation, Field(...))`
- `typing.Annotated[annotation, Field(...)]`

```python
from typing import Annotated

from modmex import BaseModel, Field, create_model, field_validator, model_validator


def normalize_name(self, value: str) -> str:
    return value.strip().title()


DynamicUser = create_model(
    "DynamicUser",
    id=(int, ...),
    name=(str, Field(default="anonymous")),
    slug=Annotated[str, Field(default="user", exclude=True)],
    __validators__={"normalize_name": field_validator("name")(normalize_name)},
)


class StaticUser(BaseModel):
    id: int
    name: str = "anonymous"
    slug: str = Field(default="user", exclude=True)

    @field_validator("name")
    def normalize_name(self, value: str) -> str:
        return value.strip().title()


dynamic_user = DynamicUser(id="1", name="  john ")
static_user = StaticUser(id="1", name="  john ")

assert dynamic_user.model_dump() == static_user.model_dump()
assert dynamic_user.name == static_user.name == "Jhon"
```


## Validators

### Field validators

Use `@field_validator("field_name")` to transform or validate a single field.

```python
from modmex import BaseModel, field_validator


class Product(BaseModel):
    name: str

    @field_validator("name")
    def normalize_name(self, value: str) -> str:
        return value.strip().title()
```


### Model validators

Use `@model_validator(mode="before" | "after")` to work with full model state.

- `before`: runs before type coercion.
- `after`: runs after field-level validation.

```python
from modmex import BaseModel, model_validator


class Product(BaseModel):
    name: str
    slug: str = ""

    @model_validator(mode="before")
    def build_slug(self, values: dict) -> dict:
        values["slug"] = values["name"].lower().replace(" ", "-")
        return values
```


## Serialization

### `model_dump(...)`

Use `model_dump` when you need a dictionary payload.

Most common options:

- `exclude={...}` to omit fields for a specific call.
- `profile="..."` to apply `exclude_from` rules.
- `include_excluded=True` to force metadata-excluded fields into the payload.
- `type_serializers={...}` to control how specific Python types are represented.


### `model_dump_json(...)`

Use `model_dump_json` when you need a JSON string output.

It supports the same practical options as `model_dump` (`exclude`, `profile`, `include_excluded`, `type_serializers`).

## Omitting Fields During Serialization

Use this feature when the same model must produce different payloads depending on where the data is going.

- `exclude_from` defines where a field should be omitted.
- `profile` selects which omission rules to apply in a specific dump call.

### What each option does

- `exclude_from={"public"}`
    - Omit this field when serializing with `profile="public"`.
- `profile="public"`
    - Apply all field rules tagged for `public` during serialization.

### Common pattern

You may want one shape for API responses and another for internal flows (logs, queues, exports, persistence payloads, etc.).

- API payload (`profile="public"`): hide internal fields.
- Internal payload (no profile, or another profile): keep those fields.

### Example

```python
from modmex import BaseModel, Field


class Account(BaseModel):
    id: int
    email: str = Field("", exclude_from={"public"})
    internal_note: str = Field("", exclude=True)


account = Account(id=1, email="a@x.com", internal_note="secret")

# No profile: only always-excluded fields are removed.
assert account.model_dump() == {
    "id": 1,
    "email": "a@x.com",
}

# public profile: profile-based exclusions are applied.
assert account.model_dump(profile="public") == {
    "id": 1,
}

# include_excluded=True: ignore Field exclusion metadata.
assert account.model_dump(profile="public", include_excluded=True) == {
    "id": 1,
    "email": "a@x.com",
    "internal_note": "secret",
}

# Dynamic omission for one call (without metadata changes).
assert account.model_dump(exclude={"email"}) == {
    "id": 1,
}
```


## Type-Based Custom Serializers

You can override serialization behavior by type with `type_serializers`.

Shape:

```python
type_serializers = {
    SomeType: serializer_function,
}
```

### Keep Decimal values as Decimal in `model_dump`

```python
from decimal import Decimal

dumped = model.model_dump(
    type_serializers={
        Decimal: lambda value: value,
    }
)
```

### Convert float to Decimal for a specific output contract

```python
from decimal import Decimal

from modmex import BaseModel


class Price(BaseModel):
    amount: float


p = Price(amount=10.25)
dumped = p.model_dump(
    type_serializers={
        float: lambda value: Decimal(str(value)),
    }
)

assert dumped["amount"] == Decimal("10.25")
```

### Emit Decimal as string in JSON

```python
from decimal import Decimal

dumped_json = model.model_dump_json(
    type_serializers={
        Decimal: lambda value: str(value),
    }
)
```

Note: some client libraries expect `Decimal` instead of `float` values (for example, common `boto3` workflows). Type serializers let you adapt output contracts cleanly, without hard-coding backend-specific behavior into your models.





## Error Handling

Validation issues raise `ValidationError`.

Each error includes:

- `loc`: location path (supports nested structures).
- `msg`: human-readable message.
- `type`: error category.

Example locations:

- `["address", "zipcode"]`
- `["tags", 1]`


## Practical Usage Pattern

Use this rule of thumb:

- Keep rich Python types in the in-memory model instance.
- Use `model_dump` / `model_dump_json` to produce transport-friendly payloads.
- Use `type_serializers` when a specific consumer requires a different type format.


## Compatibility

- Python 3.10+
