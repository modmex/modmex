from __future__ import annotations

import dataclasses
import importlib
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, List, Literal, Optional

import pytest

from modmex import BaseModel
from modmex import base_model as base_model_module
from modmex import model_plans
import modmex.rust_backend as rust_backend


class Tier(Enum):
    BASIC = "basic"


class Child(BaseModel):
    value: int


class SimpleModel(BaseModel):
    when: datetime = datetime(2026, 1, 1, 10, 30, 0)
    delay: timedelta = timedelta(seconds=5)

    @property
    def computed(self) -> datetime:
        return datetime(2026, 1, 2, 0, 0, 0)


def test_build_dump_plan_uses_fallback_type_hints_and_serializes_properties(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_plans.typing, "get_type_hints", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    plan = model_plans._build_dump_plan(SimpleModel, SimpleModel.__modmex_fields__, BaseModel)

    assert plan is not None
    dumped = plan(SimpleModel())
    assert dumped["when"] == "2026-01-01T10:30:00"
    assert dumped["delay"] == 5.0
    assert dumped["computed"] == "2026-01-02T00:00:00"


def test_build_dump_plan_returns_none_for_unsupported_serializer() -> None:
    class Unsupported(BaseModel):
        pair: tuple[int, int] = (1, 2)

    plan = model_plans._build_dump_plan(Unsupported, Unsupported.__modmex_fields__, BaseModel)
    assert plan is None


def test_dump_serializer_and_dump_plan_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    globalns = globals().copy()

    assert model_plans._dump_serializer_for("MissingType", globalns, BaseModel, None) is None

    enum_serializer = model_plans._dump_serializer_for(Tier, globalns, BaseModel, None)
    assert enum_serializer is not None
    assert enum_serializer(Tier.BASIC) == "basic"

    with monkeypatch.context() as patch_ctx:
        patch_ctx.setattr(model_plans, "_dump_plan_for", lambda *args, **kwargs: None)
        profile_none_serializer = model_plans._dump_serializer_for(Child, globalns, BaseModel, None)
        profile_serializer = model_plans._dump_serializer_for(Child, globalns, BaseModel, "public")
    assert profile_none_serializer is not None
    assert profile_serializer is not None

    child = Child(value=3)
    assert profile_none_serializer(child) == {"value": 3}
    assert profile_serializer(child) == {"value": 3}

    optional_serializer = model_plans._dump_serializer_for(Optional[int], globalns, BaseModel, None)
    assert optional_serializer is not None
    assert optional_serializer(None) is None
    assert optional_serializer(7) == 7

    assert model_plans._dump_serializer_for(list[tuple[int, int]], globalns, BaseModel, None) is None
    assert model_plans._dump_serializer_for(dict[str, tuple[int, int]], globalns, BaseModel, None) is None
    assert model_plans._dump_serializer_for(int | str, globalns, BaseModel, None) is None

    class NoCache:
        pass

    assert model_plans._dump_plan_for(NoCache, None, BaseModel) is None

    cache = Child.__modmex_dump_plan_cache__
    cache.clear()
    generated = model_plans._dump_plan_for(Child, None, BaseModel)
    assert generated is not None
    assert None in cache


def test_rust_schema_node_and_descriptor_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    globalns = globals().copy()

    assert model_plans._rust_node_for("MissingType", globalns, BaseModel) is None
    assert model_plans._rust_node_for(Any, globalns, BaseModel) == (model_plans.NODE_ANY,)
    assert model_plans._rust_node_for(Tier, globalns, BaseModel) == (model_plans.NODE_ENUM, Tier)
    assert model_plans._rust_node_for(dict[int, int], globalns, BaseModel) is None

    list_node = model_plans._rust_node_for(list[int], globalns, BaseModel)
    if list_node is None:
        list_node = model_plans._rust_node_for(List[int], globalns, BaseModel)
    assert list_node is not None
    assert list_node[0] == model_plans.NODE_LIST

    literal_node = model_plans._rust_node_for(Literal["a", "b"], globalns, BaseModel)
    assert literal_node == (model_plans.NODE_LITERAL, ("a", "b"))

    optional_node = model_plans._rust_node_for(Optional[int], globalns, BaseModel)
    assert optional_node is not None
    assert optional_node[0] == model_plans.NODE_OPTIONAL
    assert model_plans._rust_node_for(int | str, globalns, BaseModel) is None

    class NoCoreChild(BaseModel):
        value: int

    setattr(NoCoreChild, "__modmex_core__", None)
    setattr(NoCoreChild, "__modmex_rust_schema__", {})
    assert model_plans._rust_node_for(NoCoreChild, globalns, BaseModel) is None

    class CoreChild(BaseModel):
        value: int

    setattr(CoreChild, "__modmex_core__", object())
    setattr(CoreChild, "__modmex_rust_schema__", {"value": (model_plans.KIND_INT,)})
    model_node = model_plans._rust_node_for(CoreChild, globalns, BaseModel)
    assert model_node is not None
    assert model_node[0] == model_plans.NODE_MODEL

    monkeypatch.setattr(model_plans.typing, "get_type_hints", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    schema = model_plans._rust_schema_for(SimpleModel, SimpleModel.__modmex_fields__, BaseModel)
    assert "when" in schema

    class UnsupportedSchema(BaseModel):
        pair: tuple[int, int] = (1, 2)

    assert model_plans._rust_schema_for(UnsupportedSchema, UnsupportedSchema.__modmex_fields__, BaseModel) == {}

    class DescriptorModel(BaseModel):
        req: int
        opt: int = 1
        items: list[int] = dataclasses.field(default_factory=list)

    complete_schema = {
        "req": (model_plans.KIND_INT,),
        "opt": (model_plans.KIND_INT,),
        "items": (model_plans.NODE_LIST, (model_plans.KIND_INT,)),
    }
    descriptors = model_plans._rust_field_descriptors(DescriptorModel.__modmex_fields__, complete_schema)
    assert len(descriptors) == 3
    assert descriptors[0][2] is True
    assert descriptors[1][2] is False
    assert callable(descriptors[2][4])

    assert model_plans._rust_field_descriptors(DescriptorModel.__modmex_fields__, {"req": (model_plans.KIND_INT,)}) == ()


def test_remaining_model_plans_branches() -> None:
    globalns = globals().copy()

    class NotModel:
        pass

    assert model_plans._dump_serializer_for(NotModel, globalns, BaseModel, None) is None
    assert model_plans._dump_serializer_for(Optional[tuple[int, int]], globalns, BaseModel, None) is None
    assert model_plans._rust_node_for(NotModel, globalns, BaseModel) is None
    assert model_plans._dict_args(dict) == (Any, Any)


def test_rust_backend_import_fallback_and_wrappers(monkeypatch: pytest.MonkeyPatch) -> None:
    import modmex.rust_backend as module

    with monkeypatch.context() as ctx:
        calls: list[str] = []

        def fail_both(name: str) -> object:
            calls.append(name)
            raise ImportError(name)

        ctx.setattr(importlib, "import_module", fail_both)
        reloaded = importlib.reload(module)
        assert reloaded._NATIVE is None
        assert calls == ["modmex._modmex_rust", "_modmex_rust"]
        assert reloaded.rust_core_available() is False

    with monkeypatch.context() as ctx:
        calls: list[str] = []

        class Native:
            pass

        native = Native()

        def fallback_success(name: str) -> object:
            calls.append(name)
            if name == "modmex._modmex_rust":
                raise ImportError(name)
            if name == "_modmex_rust":
                return native
            raise AssertionError(name)

        ctx.setattr(importlib, "import_module", fallback_success)
        reloaded = importlib.reload(module)
        assert reloaded._NATIVE is native
        assert calls == ["modmex._modmex_rust", "_modmex_rust"]

    importlib.reload(module)

    monkeypatch.setattr(rust_backend, "_NATIVE", None)
    assert rust_backend.build_model_core(BaseModel, ()) is None
    assert rust_backend.try_core_construct_into(object(), object(), {}) is False

    class NativeNoCore:
        pass

    monkeypatch.setattr(rust_backend, "_NATIVE", NativeNoCore())
    assert rust_backend.build_model_core(BaseModel, ()) is None

    class RaisingNative:
        @staticmethod
        def ModelCore(model_type: type[Any], descriptors: tuple[Any, ...]) -> object:
            raise RuntimeError("boom")

    monkeypatch.setattr(rust_backend, "_NATIVE", RaisingNative())
    assert rust_backend.build_model_core(BaseModel, ()) is None

    class WorkingCore:
        def __init__(self, model_type: type[Any], descriptors: tuple[Any, ...]) -> None:
            self.model_type = model_type
            self.descriptors = descriptors

        def construct_into(self, target: object, kwargs: dict[str, Any]) -> int:
            return 1

    class WorkingNative:
        ModelCore = WorkingCore

    monkeypatch.setattr(rust_backend, "_NATIVE", WorkingNative())
    core = rust_backend.build_model_core(BaseModel, (("id",),))
    assert isinstance(core, WorkingCore)
    assert rust_backend.try_core_construct_into(core, object(), {"id": 1}) is True

    class BrokenCore:
        def construct_into(self, target: object, kwargs: dict[str, Any]) -> bool:
            raise RuntimeError("boom")

    assert rust_backend.try_core_construct_into(BrokenCore(), object(), {}) is False


def test_base_model_serialize_uses_prebuilt_and_profile_dump_plans(monkeypatch: pytest.MonkeyPatch) -> None:
    class FastDump(BaseModel):
        value: int

    model = FastDump(value=1)

    monkeypatch.setattr(FastDump, "__modmex_dump_plan__", lambda instance: {"fast": instance.value})
    assert model.model_dump() == {"fast": 1}
    assert model._serialize() == {"fast": 1}

    monkeypatch.setattr(base_model_module, "_dump_plan_for", lambda *args, **kwargs: (lambda instance: {"profile": instance.value}))
    monkeypatch.setattr(FastDump, "__modmex_dump_plan__", None)
    assert model.model_dump(profile="public") == {"profile": 1}
    assert model._serialize(profile="public") == {"profile": 1}