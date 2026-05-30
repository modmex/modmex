use crate::types::{py_none, type_name};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBool, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple};

#[pyfunction]
pub(crate) fn serialize_scalar(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    if value.is_none()
        || value.is_instance_of::<PyString>()
        || value.is_instance_of::<PyInt>()
        || value.is_instance_of::<PyFloat>()
        || value.is_instance_of::<PyBool>()
    {
        return Ok(value.into_py(py));
    }

    if let Some(name) = type_name(value) {
        if name == "datetime" || name == "date" || name == "time" {
            if let Ok(v) = value.call_method0("isoformat") {
                return Ok(v.into_py(py));
            }
        }
        if name == "timedelta" {
            if let Ok(v) = value.call_method0("total_seconds") {
                return Ok(v.into_py(py));
            }
        }
        if name == "Decimal" {
            let builtins = py.import_bound("builtins")?;
            if let Ok(v) = builtins.getattr("float")?.call1((value,)) {
                return Ok(v.into_py(py));
            }
        }
    }

    if value.hasattr("value")? {
        if let Ok(v) = value.getattr("value") {
            return Ok(v.into_py(py));
        }
    }

    Ok(py_none(py))
}

pub(crate) fn serialize_tree_impl(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    let scalar = serialize_scalar(py, value)?;
    if !scalar.bind(py).is_none() {
        return Ok(scalar);
    }

    if let Ok(list_obj) = value.downcast::<PyList>() {
        let out = PyList::empty_bound(py);
        for item in list_obj.iter() {
            out.append(serialize_tree_impl(py, &item)?.bind(py))?;
        }
        return Ok(out.into_py(py));
    }

    if let Ok(tuple_obj) = value.downcast::<PyTuple>() {
        let out = PyList::empty_bound(py);
        for item in tuple_obj.iter() {
            out.append(serialize_tree_impl(py, &item)?.bind(py))?;
        }
        return Ok(out.into_py(py));
    }

    if let Ok(dict_obj) = value.downcast::<PyDict>() {
        let out = PyDict::new_bound(py);
        for (key, item) in dict_obj.iter() {
            out.set_item(key, serialize_tree_impl(py, &item)?.bind(py))?;
        }
        return Ok(out.into_py(py));
    }

    if value.hasattr("__modmex_rust_dump_names__")? {
        let field_names = value.getattr("__modmex_rust_dump_names__")?;
        let property_names = value.getattr("__modmex_properties__")?;
        return serialize_model_fields_impl(py, value, &field_names, &property_names);
    }

    if value.hasattr("model_dump")? {
        if let Ok(dumped) = value.call_method0("model_dump") {
            return serialize_tree_impl(py, &dumped);
        }
    }

    Ok(value.into_py(py))
}

pub(crate) fn serialize_model_fields_impl(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    field_names: &Bound<'_, PyAny>,
    property_names: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let out = PyDict::new_bound(py);

    for name in field_names.iter()? {
        let name = name?;
        let attr_name = name.extract::<String>()?;
        let raw = value.getattr(attr_name.as_str())?;
        out.set_item(attr_name, serialize_tree_impl(py, &raw)?)?;
    }

    for name in property_names.iter()? {
        let name = name?;
        let attr_name = name.extract::<String>()?;
        let raw = value.getattr(attr_name.as_str())?;
        out.set_item(attr_name, serialize_tree_impl(py, &raw)?)?;
    }

    Ok(out.into_py(py))
}

#[pyfunction]
pub(crate) fn serialize_tree(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    serialize_tree_impl(py, value)
}

#[pyfunction]
pub(crate) fn serialize_model_fields(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    field_names: &Bound<'_, PyAny>,
    property_names: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    serialize_model_fields_impl(py, value, field_names, property_names)
}
