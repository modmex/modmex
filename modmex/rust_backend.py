"""Optional Rust acceleration hooks.

This module loads the native extension when available and provides
small wrappers that fall back to pure Python behavior otherwise.
"""

from __future__ import annotations

import importlib
from typing import Any

_NATIVE = None
try:
    _NATIVE = importlib.import_module("modmex._modmex_rust")
except Exception:
    try:
        _NATIVE = importlib.import_module("_modmex_rust")
    except Exception:
        _NATIVE = None


def rust_core_available() -> bool:
    return _NATIVE is not None


def build_model_core(model_type: type[Any], descriptors: tuple[Any, ...]) -> Any:
    if _NATIVE is None:
        return None
    model_core = getattr(_NATIVE, "ModelCore", None)
    if model_core is None:
        return None
    try:
        return model_core(model_type, descriptors)
    except Exception:
        return None


def try_core_construct_into(core: Any, target: Any, kwargs: dict[str, Any]) -> bool:
    if core is None or _NATIVE is None:
        return False
    try:
        return bool(core.construct_into(target, kwargs))
    except Exception:
        return False
