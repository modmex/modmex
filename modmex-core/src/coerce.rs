use crate::types::*;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBool, PyBytes, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple};

pub(crate) fn coerce_str_impl(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    if value.is_none() {
        return Ok(py_none(py));
    }

    if let Ok(v) = value.extract::<String>() {
        return Ok(v.into_py(py));
    }

    if let Ok(b) = value.downcast::<PyBytes>() {
        return Ok(String::from_utf8_lossy(b.as_bytes())
            .to_string()
            .into_py(py));
    }

    if value.is_instance_of::<PyInt>() || value.is_instance_of::<PyFloat>() {
        return Ok(value.str()?.to_str()?.to_owned().into_py(py));
    }

    Ok(py_none(py))
}

pub(crate) fn coerce_int_impl(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    if value.is_instance_of::<PyBool>() {
        return Ok(py_none(py));
    }

    if let Ok(v) = value.extract::<i64>() {
        return Ok(v.into_py(py));
    }

    if let Ok(s) = value.extract::<String>() {
        if let Ok(v) = s.trim().parse::<i64>() {
            return Ok(v.into_py(py));
        }
    }

    if let Ok(b) = value.downcast::<PyBytes>() {
        if let Ok(s) = std::str::from_utf8(b.as_bytes()) {
            if let Ok(v) = s.trim().parse::<i64>() {
                return Ok(v.into_py(py));
            }
        }
    }

    let builtins = py.import_bound("builtins")?;
    match builtins.getattr("int")?.call1((value,)) {
        Ok(v) => Ok(v.into_py(py)),
        Err(_) => Ok(py_none(py)),
    }
}

pub(crate) fn coerce_float_impl(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    if let Ok(v) = value.extract::<f64>() {
        return Ok(v.into_py(py));
    }

    if let Ok(s) = value.extract::<String>() {
        if let Ok(v) = s.trim().parse::<f64>() {
            return Ok(v.into_py(py));
        }
    }

    if let Ok(b) = value.downcast::<PyBytes>() {
        if let Ok(s) = std::str::from_utf8(b.as_bytes()) {
            if let Ok(v) = s.trim().parse::<f64>() {
                return Ok(v.into_py(py));
            }
        }
    }

    let builtins = py.import_bound("builtins")?;
    match builtins.getattr("float")?.call1((value,)) {
        Ok(v) => Ok(v.into_py(py)),
        Err(_) => Ok(py_none(py)),
    }
}

pub(crate) fn coerce_bool_impl(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    if let Ok(v) = value.extract::<bool>() {
        return Ok(v.into_py(py));
    }

    if let Ok(s) = value.extract::<String>() {
        match s.to_lowercase().as_str() {
            "1" | "on" | "t" | "true" | "y" | "yes" => return Ok(true.into_py(py)),
            "0" | "off" | "f" | "false" | "n" | "no" => return Ok(false.into_py(py)),
            _ => {}
        }
    }

    Ok(py_none(py))
}

pub(crate) fn coerce_time_impl(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    if type_name(value).as_deref() == Some("time") {
        return Ok(value.into_py(py));
    }

    let text = if let Ok(s) = value.extract::<String>() {
        Some(s)
    } else if let Ok(b) = value.downcast::<PyBytes>() {
        std::str::from_utf8(b.as_bytes()).ok().map(|s| s.to_owned())
    } else {
        None
    };

    if let Some(s) = text {
        let datetime_mod = py.import_bound("datetime")?;
        let time_cls = datetime_mod.getattr("time")?;
        if let Ok(v) = time_cls.getattr("fromisoformat")?.call1((s.as_str(),)) {
            return Ok(v.into_py(py));
        }
    }

    Ok(py_none(py))
}

pub(crate) fn coerce_date_impl(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    if type_name(value).as_deref() == Some("date") {
        return Ok(value.into_py(py));
    }

    let text = if let Ok(s) = value.extract::<String>() {
        Some(s)
    } else if let Ok(b) = value.downcast::<PyBytes>() {
        std::str::from_utf8(b.as_bytes()).ok().map(|s| s.to_owned())
    } else {
        None
    };

    if let Some(s) = text {
        let datetime_mod = py.import_bound("datetime")?;
        let date_cls = datetime_mod.getattr("date")?;
        if let Ok(v) = date_cls.getattr("fromisoformat")?.call1((s.as_str(),)) {
            return Ok(v.into_py(py));
        }
    }

    Ok(py_none(py))
}

pub(crate) fn coerce_datetime_impl(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    if type_name(value).as_deref() == Some("datetime") {
        return Ok(value.into_py(py));
    }

    let text = if let Ok(s) = value.extract::<String>() {
        Some(s)
    } else if let Ok(b) = value.downcast::<PyBytes>() {
        std::str::from_utf8(b.as_bytes()).ok().map(|s| s.to_owned())
    } else {
        None
    };

    if let Some(s) = text {
        let datetime_mod = py.import_bound("datetime")?;
        let datetime_cls = datetime_mod.getattr("datetime")?;
        if let Ok(v) = datetime_cls.getattr("fromisoformat")?.call1((s.as_str(),)) {
            return Ok(v.into_py(py));
        }
    }

    Ok(py_none(py))
}

pub(crate) fn coerce_duration_impl(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    if type_name(value).as_deref() == Some("timedelta") {
        return Ok(value.into_py(py));
    }

    let seconds = if let Ok(v) = value.extract::<f64>() {
        Some(v)
    } else if let Ok(s) = value.extract::<String>() {
        s.trim().parse::<f64>().ok()
    } else if let Ok(b) = value.downcast::<PyBytes>() {
        std::str::from_utf8(b.as_bytes())
            .ok()
            .and_then(|s| s.trim().parse::<f64>().ok())
    } else {
        None
    };

    if let Some(sec) = seconds {
        let kwargs = PyDict::new_bound(py);
        kwargs.set_item("seconds", sec)?;
        let datetime_mod = py.import_bound("datetime")?;
        if let Ok(v) = datetime_mod.getattr("timedelta")?.call((), Some(&kwargs)) {
            return Ok(v.into_py(py));
        }
    }

    Ok(py_none(py))
}

pub(crate) fn coerce_decimal_impl(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    if type_name(value).as_deref() == Some("Decimal") {
        return Ok(value.into_py(py));
    }

    let decimal_mod = py.import_bound("decimal")?;
    let decimal_cls = decimal_mod.getattr("Decimal")?;

    let coerced = if let Ok(s) = value.extract::<String>() {
        decimal_cls.call1((s,))
    } else if let Ok(b) = value.downcast::<PyBytes>() {
        if let Ok(s) = std::str::from_utf8(b.as_bytes()) {
            decimal_cls.call1((s,))
        } else {
            return Ok(py_none(py));
        }
    } else {
        decimal_cls.call1((value,))
    };

    match coerced {
        Ok(v) => Ok(v.into_py(py)),
        Err(_) => Ok(py_none(py)),
    }
}

pub(crate) fn coerce_scalar_by_kind(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    kind: u8,
) -> PyResult<Py<PyAny>> {
    if matches_kind(value, kind) {
        return Ok(value.into_py(py));
    }

    match kind {
        KIND_STR => coerce_str_impl(py, value),
        KIND_INT => coerce_int_impl(py, value),
        KIND_FLOAT => coerce_float_impl(py, value),
        KIND_BOOL => coerce_bool_impl(py, value),
        KIND_TIME => coerce_time_impl(py, value),
        KIND_DURATION => coerce_duration_impl(py, value),
        KIND_DATE => coerce_date_impl(py, value),
        KIND_DATETIME => coerce_datetime_impl(py, value),
        KIND_DECIMAL => coerce_decimal_impl(py, value),
        _ => Ok(py_none(py)),
    }
}

pub(crate) fn construct_model_from_kwargs(
    py: Python<'_>,
    model_type: &Bound<'_, PyAny>,
    kwargs: &Bound<'_, PyDict>,
) -> PyResult<Option<Py<PyAny>>> {
    if let Ok(builder) = model_type.getattr("_modmex_from_trusted_kwargs") {
        return match builder.call1((kwargs,)) {
            Ok(v) => Ok(Some(v.into_py(py))),
            Err(_) => Ok(None),
        };
    }

    match model_type.call((), Some(kwargs)) {
        Ok(v) => Ok(Some(v.into_py(py))),
        Err(_) => Ok(None),
    }
}

pub(crate) fn coerce_schema_value(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    node: &Bound<'_, PyAny>,
) -> PyResult<Option<Py<PyAny>>> {
    let node_tuple = if let Ok(t) = node.downcast::<PyTuple>() {
        t
    } else {
        return Ok(None);
    };

    if node_tuple.is_empty() {
        return Ok(None);
    }

    let tag = node_tuple.get_item(0)?.extract::<u8>()?;
    match tag {
        KIND_STR | KIND_INT | KIND_FLOAT | KIND_BOOL | KIND_TIME | KIND_DURATION | KIND_DATE
        | KIND_DATETIME | KIND_DECIMAL => {
            let out = coerce_scalar_by_kind(py, value, tag)?;
            if out.bind(py).is_none() {
                Ok(None)
            } else {
                Ok(Some(out))
            }
        }
        NODE_ENUM => {
            if node_tuple.len() < 2 {
                return Ok(None);
            }
            let enum_type = node_tuple.get_item(1)?;
            if value.is_instance(&enum_type)? {
                Ok(Some(value.into_py(py)))
            } else {
                match enum_type.call1((value,)) {
                    Ok(v) => Ok(Some(v.into_py(py))),
                    Err(_) => Ok(None),
                }
            }
        }
        NODE_MODEL => {
            if node_tuple.len() < 3 {
                return Ok(None);
            }
            let model_type = node_tuple.get_item(1)?;
            if value.is_instance(&model_type)? {
                return Ok(Some(value.into_py(py)));
            }
            let source = if let Ok(d) = value.downcast::<PyDict>() {
                d
            } else {
                return Ok(None);
            };
            let sub_schema = node_tuple.get_item(2)?;
            let Some(coerced_kwargs) = coerce_schema_kwargs_internal(py, &source, &sub_schema, 0)?
            else {
                return Ok(None);
            };

            if node_tuple.len() >= 4 {
                let trusted_ctor = node_tuple.get_item(3)?;
                if let Ok(v) = trusted_ctor.call1((coerced_kwargs.bind(py),)) {
                    return Ok(Some(v.into_py(py)));
                }
            }

            match construct_model_from_kwargs(py, &model_type, &coerced_kwargs.bind(py))? {
                Some(v) => Ok(Some(v)),
                None => Ok(None),
            }
        }
        NODE_LIST => {
            if node_tuple.len() < 2 {
                return Ok(None);
            }
            let inner = node_tuple.get_item(1)?;
            let list_obj = if let Ok(l) = value.downcast::<PyList>() {
                l
            } else {
                return Ok(None);
            };
            let out = PyList::empty_bound(py);
            for item in list_obj.iter() {
                if let Some(v) = coerce_schema_value(py, &item, &inner)? {
                    out.append(v.bind(py))?;
                } else {
                    return Ok(None);
                }
            }
            Ok(Some(out.into_py(py)))
        }
        NODE_DICT_STR => {
            if node_tuple.len() < 2 {
                return Ok(None);
            }
            let inner = node_tuple.get_item(1)?;
            let dict_obj = if let Ok(d) = value.downcast::<PyDict>() {
                d
            } else {
                return Ok(None);
            };
            let out = PyDict::new_bound(py);
            for (k, item) in dict_obj.iter() {
                if !k.is_instance_of::<PyString>() {
                    return Ok(None);
                }
                if let Some(v) = coerce_schema_value(py, &item, &inner)? {
                    out.set_item(k, v.bind(py))?;
                } else {
                    return Ok(None);
                }
            }
            Ok(Some(out.into_py(py)))
        }
        NODE_OPTIONAL => {
            if node_tuple.len() < 2 {
                return Ok(None);
            }
            if value.is_none() {
                return Ok(Some(py_none(py)));
            }
            let inner = node_tuple.get_item(1)?;
            coerce_schema_value(py, value, &inner)
        }
        NODE_LITERAL => {
            if node_tuple.len() < 2 {
                return Ok(None);
            }
            let allowed = node_tuple.get_item(1)?;
            let allowed_tuple = if let Ok(t) = allowed.downcast::<PyTuple>() {
                t
            } else {
                return Ok(None);
            };
            for item in allowed_tuple.iter() {
                if value.eq(&item)? {
                    return Ok(Some(value.into_py(py)));
                }
            }
            Ok(None)
        }
        NODE_ANY => Ok(Some(value.into_py(py))),
        _ => Ok(None),
    }
}

pub(crate) fn coerce_schema_kwargs_internal(
    py: Python<'_>,
    kwargs: &Bound<'_, PyDict>,
    schema: &Bound<'_, PyAny>,
    min_fields: usize,
) -> PyResult<Option<Py<PyDict>>> {
    let schema_dict = if let Ok(d) = schema.downcast::<PyDict>() {
        d
    } else {
        return Ok(None);
    };

    if kwargs.len() < min_fields {
        return Ok(None);
    }

    let out = PyDict::new_bound(py);
    let mut coerced_count = 0usize;
    for (key, node) in schema_dict.iter() {
        if let Some(raw) = kwargs.get_item(&key)? {
            if let Some(v) = coerce_schema_value(py, &raw, &node)? {
                out.set_item(key, v.bind(py))?;
                coerced_count += 1;
            } else {
                return Ok(None);
            }
        }
    }

    if coerced_count < min_fields {
        return Ok(None);
    }
    Ok(Some(out.unbind()))
}

#[pyfunction]
pub(crate) fn coerce_values(
    py: Python<'_>,
    values: Vec<Py<PyAny>>,
    kinds: Vec<u8>,
) -> PyResult<Py<PyAny>> {
    if values.len() != kinds.len() {
        return Ok(py_none(py));
    }

    let out = PyList::empty_bound(py);
    for (value, kind) in values.into_iter().zip(kinds.into_iter()) {
        let v = value.bind(py);
        let coerced = coerce_scalar_by_kind(py, &v, kind)?;
        if coerced.bind(py).is_none() {
            return Ok(py_none(py));
        }
        out.append(coerced.bind(py))?;
    }
    Ok(out.into_py(py))
}

#[pyfunction]
pub(crate) fn coerce_kwargs(
    py: Python<'_>,
    kwargs: &Bound<'_, PyDict>,
    names: Vec<String>,
    kinds: Vec<u8>,
    min_mismatches: usize,
) -> PyResult<Py<PyAny>> {
    if names.len() != kinds.len() {
        return Ok(py_none(py));
    }

    let out = PyDict::new_bound(py);
    let mut count = 0usize;

    for (name, kind) in names.iter().zip(kinds.iter()) {
        if let Some(v) = kwargs.get_item(name)? {
            if v.is_none() {
                continue;
            }
            let coerced = coerce_scalar_by_kind(py, &v, *kind)?;
            if coerced.bind(py).is_none() {
                return Ok(py_none(py));
            }
            out.set_item(name, coerced.bind(py))?;
            count += 1;
        }
    }

    if count < min_mismatches {
        return Ok(py_none(py));
    }

    Ok(out.into_py(py))
}

#[pyfunction]
pub(crate) fn coerce_enum_kwargs(
    py: Python<'_>,
    kwargs: &Bound<'_, PyDict>,
    names: Vec<String>,
    enum_types: Vec<Py<PyAny>>,
    min_fields: usize,
) -> PyResult<Py<PyAny>> {
    if names.len() != enum_types.len() {
        return Ok(py_none(py));
    }

    let out = PyDict::new_bound(py);
    let mut count = 0usize;
    for (name, enum_type) in names.into_iter().zip(enum_types.into_iter()) {
        if let Some(value) = kwargs.get_item(&name)? {
            if value.is_none() {
                continue;
            }
            let enum_type = enum_type.bind(py);
            let coerced = if value.is_instance(enum_type)? {
                value.into_py(py)
            } else {
                match enum_type.call1((value,)) {
                    Ok(v) => v.into_py(py),
                    Err(_) => return Ok(py_none(py)),
                }
            };
            out.set_item(name, coerced.bind(py))?;
            count += 1;
        }
    }

    if count < min_fields {
        return Ok(py_none(py));
    }

    Ok(out.into_py(py))
}

#[pyfunction]
pub(crate) fn coerce_model_kwargs(
    py: Python<'_>,
    kwargs: &Bound<'_, PyDict>,
    names: Vec<String>,
    model_types: Vec<Py<PyAny>>,
    min_fields: usize,
) -> PyResult<Py<PyAny>> {
    if names.len() != model_types.len() {
        return Ok(py_none(py));
    }

    let out = PyDict::new_bound(py);
    let mut count = 0usize;

    for (name, model_type) in names.into_iter().zip(model_types.into_iter()) {
        if let Some(value) = kwargs.get_item(&name)? {
            if value.is_none() {
                continue;
            }
            let model_type = model_type.bind(py);
            let coerced = if value.is_instance(model_type)? {
                value.into_py(py)
            } else if let Ok(as_dict) = value.downcast::<PyDict>() {
                match construct_model_from_kwargs(py, &model_type, &as_dict)? {
                    Some(v) => v,
                    None => return Ok(py_none(py)),
                }
            } else {
                match model_type.call1((value,)) {
                    Ok(v) => v.into_py(py),
                    Err(_) => return Ok(py_none(py)),
                }
            };
            out.set_item(name, coerced.bind(py))?;
            count += 1;
        }
    }

    if count < min_fields {
        return Ok(py_none(py));
    }

    Ok(out.into_py(py))
}

pub(crate) fn coerce_construct_kwargs_internal(
    py: Python<'_>,
    kwargs: &Bound<'_, PyDict>,
    scalar_names: &[String],
    scalar_kinds: &[u8],
    enum_names: &[String],
    enum_types: &[Py<PyAny>],
    model_names: &[String],
    model_types: &[Py<PyAny>],
    min_fields: usize,
) -> PyResult<Option<Py<PyDict>>> {
    if scalar_names.len() != scalar_kinds.len() {
        return Ok(None);
    }

    let out = PyDict::new_bound(py);
    let mut count = 0usize;

    for (name, kind) in scalar_names.iter().zip(scalar_kinds.iter()) {
        if let Some(value) = kwargs.get_item(name)? {
            if value.is_none() {
                continue;
            }
            let coerced = coerce_scalar_by_kind(py, &value, *kind)?;
            if coerced.bind(py).is_none() {
                return Ok(None);
            }
            out.set_item(name, coerced.bind(py))?;
            count += 1;
        }
    }

    for (name, enum_type) in enum_names.iter().zip(enum_types.iter()) {
        if let Some(value) = kwargs.get_item(name)? {
            if value.is_none() {
                continue;
            }
            let enum_type = enum_type.bind(py);
            let coerced = if value.is_instance(enum_type)? {
                value.into_py(py)
            } else {
                match enum_type.call1((value,)) {
                    Ok(v) => v.into_py(py),
                    Err(_) => return Ok(None),
                }
            };
            out.set_item(name, coerced.bind(py))?;
            count += 1;
        }
    }

    for (name, model_type) in model_names.iter().zip(model_types.iter()) {
        if let Some(value) = kwargs.get_item(name)? {
            if value.is_none() {
                continue;
            }
            let model_type = model_type.bind(py);
            let coerced = if value.is_instance(model_type)? {
                value.into_py(py)
            } else if let Ok(as_dict) = value.downcast::<PyDict>() {
                match construct_model_from_kwargs(py, &model_type, &as_dict)? {
                    Some(v) => v,
                    None => return Ok(None),
                }
            } else {
                match model_type.call1((value,)) {
                    Ok(v) => v.into_py(py),
                    Err(_) => return Ok(None),
                }
            };
            out.set_item(name, coerced.bind(py))?;
            count += 1;
        }
    }

    if count < min_fields {
        return Ok(None);
    }

    Ok(Some(out.unbind()))
}

#[pyfunction]
pub(crate) fn coerce_construct_kwargs(
    py: Python<'_>,
    kwargs: &Bound<'_, PyDict>,
    scalar_names: Vec<String>,
    scalar_kinds: Vec<u8>,
    enum_names: Vec<String>,
    enum_types: Vec<Py<PyAny>>,
    model_names: Vec<String>,
    model_types: Vec<Py<PyAny>>,
    min_fields: usize,
) -> PyResult<Py<PyAny>> {
    match coerce_construct_kwargs_internal(
        py,
        kwargs,
        &scalar_names,
        &scalar_kinds,
        &enum_names,
        &enum_types,
        &model_names,
        &model_types,
        min_fields,
    )? {
        Some(v) => Ok(v.into_py(py)),
        None => Ok(py_none(py)),
    }
}

#[pyfunction]
pub(crate) fn coerce_schema_kwargs(
    py: Python<'_>,
    kwargs: &Bound<'_, PyDict>,
    schema: &Bound<'_, PyAny>,
    min_fields: usize,
) -> PyResult<Py<PyAny>> {
    if let Some(v) = coerce_schema_kwargs_internal(py, kwargs, schema, min_fields)? {
        Ok(v.into_py(py))
    } else {
        Ok(py_none(py))
    }
}

#[pyfunction]
pub(crate) fn coerce_str(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    coerce_str_impl(py, value)
}

#[pyfunction]
pub(crate) fn coerce_int(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    coerce_int_impl(py, value)
}

#[pyfunction]
pub(crate) fn coerce_float(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    coerce_float_impl(py, value)
}

#[pyfunction]
pub(crate) fn coerce_bool(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    coerce_bool_impl(py, value)
}

#[pyfunction]
pub(crate) fn coerce_time(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    coerce_time_impl(py, value)
}

#[pyfunction]
pub(crate) fn coerce_date(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    coerce_date_impl(py, value)
}

#[pyfunction]
pub(crate) fn coerce_datetime(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    coerce_datetime_impl(py, value)
}
