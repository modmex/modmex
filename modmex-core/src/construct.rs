use crate::coerce::{
    coerce_construct_kwargs_internal, coerce_schema_kwargs_internal, construct_model_from_kwargs,
};
use crate::profile::{
    profile_add, profile_construct_enabled, PROFILE_CALLS, PROFILE_FLAT_NS, PROFILE_MODEL_BUILD_NS,
    PROFILE_SCHEMA_NS, PROFILE_TOTAL_NS,
};
use crate::types::py_none;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict};
use std::sync::atomic::Ordering;
use std::time::Instant;

#[pyfunction]
pub(crate) fn construct_model_from_schema(
    py: Python<'_>,
    kwargs: &Bound<'_, PyDict>,
    model_type: &Bound<'_, PyAny>,
    schema: &Bound<'_, PyAny>,
    min_fields: usize,
) -> PyResult<Py<PyAny>> {
    let Some(coerced) = coerce_schema_kwargs_internal(py, kwargs, schema, min_fields)? else {
        return Ok(py_none(py));
    };

    if let Some(instance) = construct_model_from_kwargs(py, model_type, &coerced.bind(py))? {
        Ok(instance)
    } else {
        Ok(py_none(py))
    }
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
pub(crate) fn construct_model_runtime(
    py: Python<'_>,
    kwargs: &Bound<'_, PyDict>,
    model_type: &Bound<'_, PyAny>,
    schema: &Bound<'_, PyAny>,
    scalar_names: Vec<String>,
    scalar_kinds: Vec<u8>,
    enum_names: Vec<String>,
    enum_types: Vec<Py<PyAny>>,
    model_names: Vec<String>,
    model_types: Vec<Py<PyAny>>,
    min_fields: usize,
) -> PyResult<Py<PyAny>> {
    if kwargs.len() < min_fields {
        return Ok(py_none(py));
    }

    let profiling = profile_construct_enabled();
    let total_start = if profiling {
        Some(Instant::now())
    } else {
        None
    };

    let working = kwargs.copy()?;

    if let Some(schema_dict) = schema.downcast::<PyDict>().ok() {
        if !schema_dict.is_empty() {
            let schema_start = if profiling {
                Some(Instant::now())
            } else {
                None
            };
            if let Some(schema_coerced) =
                coerce_schema_kwargs_internal(py, kwargs, schema, min_fields)?
            {
                profile_add(&PROFILE_SCHEMA_NS, schema_start);
                working.update(&schema_coerced.bind(py).as_mapping())?;
                let build_start = if profiling {
                    Some(Instant::now())
                } else {
                    None
                };
                if let Some(instance) = construct_model_from_kwargs(py, model_type, &working)? {
                    profile_add(&PROFILE_MODEL_BUILD_NS, build_start);
                    if profiling {
                        PROFILE_CALLS.fetch_add(1, Ordering::Relaxed);
                        profile_add(&PROFILE_TOTAL_NS, total_start);
                    }
                    return Ok(instance);
                }
                profile_add(&PROFILE_MODEL_BUILD_NS, build_start);
            } else {
                profile_add(&PROFILE_SCHEMA_NS, schema_start);
            }
        }
    }

    let flat_start = if profiling {
        Some(Instant::now())
    } else {
        None
    };
    let Some(flat_coerced) = coerce_construct_kwargs_internal(
        py,
        kwargs,
        &scalar_names,
        &scalar_kinds,
        &enum_names,
        &enum_types,
        &model_names,
        &model_types,
        min_fields,
    )?
    else {
        profile_add(&PROFILE_FLAT_NS, flat_start);
        if profiling {
            PROFILE_CALLS.fetch_add(1, Ordering::Relaxed);
            profile_add(&PROFILE_TOTAL_NS, total_start);
        }
        return Ok(py_none(py));
    };
    profile_add(&PROFILE_FLAT_NS, flat_start);

    working.update(&flat_coerced.bind(py).as_mapping())?;

    let build_start = if profiling {
        Some(Instant::now())
    } else {
        None
    };
    if let Some(instance) = construct_model_from_kwargs(py, model_type, &working)? {
        profile_add(&PROFILE_MODEL_BUILD_NS, build_start);
        if profiling {
            PROFILE_CALLS.fetch_add(1, Ordering::Relaxed);
            profile_add(&PROFILE_TOTAL_NS, total_start);
        }
        Ok(instance)
    } else {
        profile_add(&PROFILE_MODEL_BUILD_NS, build_start);
        if profiling {
            PROFILE_CALLS.fetch_add(1, Ordering::Relaxed);
            profile_add(&PROFILE_TOTAL_NS, total_start);
        }
        Ok(py_none(py))
    }
}
