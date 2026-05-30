use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::OnceLock;
use std::time::Instant;

static PROFILE_ENABLED: OnceLock<bool> = OnceLock::new();
pub(crate) static PROFILE_CALLS: AtomicU64 = AtomicU64::new(0);
pub(crate) static PROFILE_TOTAL_NS: AtomicU64 = AtomicU64::new(0);
pub(crate) static PROFILE_SCHEMA_NS: AtomicU64 = AtomicU64::new(0);
pub(crate) static PROFILE_FLAT_NS: AtomicU64 = AtomicU64::new(0);
pub(crate) static PROFILE_MODEL_BUILD_NS: AtomicU64 = AtomicU64::new(0);

pub(crate) fn profile_construct_enabled() -> bool {
    *PROFILE_ENABLED.get_or_init(|| {
        std::env::var("MODMEX_RUST_PROFILE_CONSTRUCT")
            .map(|v| {
                let s = v.trim();
                s == "1" || s.eq_ignore_ascii_case("true") || s.eq_ignore_ascii_case("yes")
            })
            .unwrap_or(false)
    })
}

pub(crate) fn profile_add(target: &AtomicU64, start: Option<Instant>) {
    if let Some(started) = start {
        target.fetch_add(started.elapsed().as_nanos() as u64, Ordering::Relaxed);
    }
}

#[pyfunction]
pub(crate) fn reset_construct_profile() {
    PROFILE_CALLS.store(0, Ordering::Relaxed);
    PROFILE_TOTAL_NS.store(0, Ordering::Relaxed);
    PROFILE_SCHEMA_NS.store(0, Ordering::Relaxed);
    PROFILE_FLAT_NS.store(0, Ordering::Relaxed);
    PROFILE_MODEL_BUILD_NS.store(0, Ordering::Relaxed);
}

#[pyfunction]
pub(crate) fn get_construct_profile(py: Python<'_>) -> PyResult<Py<PyAny>> {
    let out = PyDict::new_bound(py);
    let enabled = profile_construct_enabled();
    let calls = PROFILE_CALLS.load(Ordering::Relaxed);
    let total_ns = PROFILE_TOTAL_NS.load(Ordering::Relaxed);
    let schema_ns = PROFILE_SCHEMA_NS.load(Ordering::Relaxed);
    let flat_ns = PROFILE_FLAT_NS.load(Ordering::Relaxed);
    let model_build_ns = PROFILE_MODEL_BUILD_NS.load(Ordering::Relaxed);

    out.set_item("enabled", enabled)?;
    out.set_item("calls", calls)?;
    out.set_item("total_ns", total_ns)?;
    out.set_item("schema_ns", schema_ns)?;
    out.set_item("flat_ns", flat_ns)?;
    out.set_item("model_build_ns", model_build_ns)?;

    if calls > 0 {
        out.set_item("avg_total_ns", total_ns / calls)?;
        out.set_item("avg_schema_ns", schema_ns / calls)?;
        out.set_item("avg_flat_ns", flat_ns / calls)?;
        out.set_item("avg_model_build_ns", model_build_ns / calls)?;
    } else {
        out.set_item("avg_total_ns", 0)?;
        out.set_item("avg_schema_ns", 0)?;
        out.set_item("avg_flat_ns", 0)?;
        out.set_item("avg_model_build_ns", 0)?;
    }

    Ok(out.into_py(py))
}
