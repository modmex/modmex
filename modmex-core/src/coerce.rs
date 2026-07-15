use crate::types::*;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBool, PyBytes, PyFloat, PyInt, PyString};

pub(crate) fn coerce_str_impl(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    if value.is_none() {
        return Ok(py_none(py));
    }

    if value.is_instance_of::<PyString>() {
        return Ok(value.into_py(py));
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

    if let Ok(v) = value.downcast::<PyInt>() {
        return Ok(v.extract::<i64>()?.into_py(py));
    }

    if let Ok(s) = value.downcast::<PyString>() {
        if let Ok(v) = s.to_str()?.trim().parse::<i64>() {
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
    if let Ok(v) = value.downcast::<PyFloat>() {
        return Ok(v.extract::<f64>()?.into_py(py));
    }

    if let Ok(v) = value.downcast::<PyInt>() {
        return Ok(v.extract::<f64>()?.into_py(py));
    }

    if let Ok(s) = value.downcast::<PyString>() {
        if let Ok(v) = s.to_str()?.trim().parse::<f64>() {
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
    if let Ok(v) = value.downcast::<PyBool>() {
        let v = v.extract::<bool>()?;
        return Ok(v.into_py(py));
    }

    if let Ok(s) = value.downcast::<PyString>() {
        match s.to_str()?.to_ascii_lowercase().as_str() {
            "1" | "on" | "t" | "true" | "y" | "yes" => return Ok(true.into_py(py)),
            "0" | "off" | "f" | "false" | "n" | "no" => return Ok(false.into_py(py)),
            _ => {}
        }
    }

    Ok(py_none(py))
}

pub(crate) fn coerce_time_with_helper(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    helper: Option<&Bound<'_, PyAny>>,
) -> PyResult<Py<PyAny>> {
    if type_name(value).as_deref() == Some("time") {
        return Ok(value.into_py(py));
    }

    let text = if let Ok(s) = value.downcast::<PyString>() {
        Some(s.to_str()?.to_owned())
    } else if let Ok(b) = value.downcast::<PyBytes>() {
        std::str::from_utf8(b.as_bytes()).ok().map(|s| s.to_owned())
    } else {
        None
    };

    if let Some(s) = text {
        if let Some(v) = parse_time_ascii(py, s.as_bytes())? {
            return Ok(v);
        }
        let callable = if let Some(helper) = helper {
            helper.clone()
        } else {
            py.import_bound("datetime")?
                .getattr("time")?
                .getattr("fromisoformat")?
        };
        if let Ok(v) = callable.call1((s.as_str(),)) {
            return Ok(v.into_py(py));
        }
    }

    Ok(py_none(py))
}

pub(crate) fn coerce_date_with_helper(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    helper: Option<&Bound<'_, PyAny>>,
) -> PyResult<Py<PyAny>> {
    if type_name(value).as_deref() == Some("date") {
        return Ok(value.into_py(py));
    }

    let text = if let Ok(s) = value.downcast::<PyString>() {
        Some(s.to_str()?.to_owned())
    } else if let Ok(b) = value.downcast::<PyBytes>() {
        std::str::from_utf8(b.as_bytes()).ok().map(|s| s.to_owned())
    } else {
        None
    };

    if let Some(s) = text {
        let callable = if let Some(helper) = helper {
            helper.clone()
        } else {
            py.import_bound("datetime")?
                .getattr("date")?
                .getattr("fromisoformat")?
        };
        if let Ok(v) = callable.call1((s.as_str(),)) {
            return Ok(v.into_py(py));
        }
    }

    Ok(py_none(py))
}

pub(crate) fn coerce_datetime_with_helper(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    helper: Option<&Bound<'_, PyAny>>,
) -> PyResult<Py<PyAny>> {
    if type_name(value).as_deref() == Some("datetime") {
        return Ok(value.into_py(py));
    }

    let text = if let Ok(s) = value.downcast::<PyString>() {
        Some(s.to_str()?.to_owned())
    } else if let Ok(b) = value.downcast::<PyBytes>() {
        std::str::from_utf8(b.as_bytes()).ok().map(|s| s.to_owned())
    } else {
        None
    };

    if let Some(s) = text {
        let callable = if let Some(helper) = helper {
            helper.clone()
        } else {
            py.import_bound("datetime")?
                .getattr("datetime")?
                .getattr("fromisoformat")?
        };
        if let Ok(v) = callable.call1((s.as_str(),)) {
            return Ok(v.into_py(py));
        }
    }

    Ok(py_none(py))
}

pub(crate) fn coerce_duration_with_helper(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    helper: Option<&Bound<'_, PyAny>>,
) -> PyResult<Py<PyAny>> {
    if type_name(value).as_deref() == Some("timedelta") {
        return Ok(value.into_py(py));
    }

    let seconds = if let Ok(v) = value.downcast::<PyFloat>() {
        Some(v.extract::<f64>()?)
    } else if let Ok(v) = value.downcast::<PyInt>() {
        Some(v.extract::<f64>()?)
    } else if let Ok(s) = value.downcast::<PyString>() {
        s.to_str()?.trim().parse::<f64>().ok()
    } else if let Ok(b) = value.downcast::<PyBytes>() {
        std::str::from_utf8(b.as_bytes())
            .ok()
            .and_then(|s| s.trim().parse::<f64>().ok())
    } else {
        None
    };

    if let Some(sec) = seconds {
        let whole = sec.trunc();
        let micros = ((sec - whole) * 1_000_000.0).round();
        if whole >= i32::MIN as f64
            && whole <= i32::MAX as f64
            && micros >= i32::MIN as f64
            && micros <= i32::MAX as f64
        {
            let timedelta = py.import_bound("datetime")?.getattr("timedelta")?;
            return Ok(timedelta.call1((0, whole as i32, micros as i32))?.into_py(py));
        }
        let cls = if let Some(helper) = helper {
            helper.clone()
        } else {
            py.import_bound("datetime")?.getattr("timedelta")?
        };
        if let Ok(v) = cls.call1((0, sec)) {
            return Ok(v.into_py(py));
        }
    }

    Ok(py_none(py))
}

fn parse_2_digits(bytes: &[u8], index: usize) -> Option<u8> {
    let tens = *bytes.get(index)?;
    let ones = *bytes.get(index + 1)?;
    if !tens.is_ascii_digit() || !ones.is_ascii_digit() {
        return None;
    }
    Some((tens - b'0') * 10 + (ones - b'0'))
}

fn parse_time_ascii(py: Python<'_>, bytes: &[u8]) -> PyResult<Option<Py<PyAny>>> {
    if bytes.len() < 5 || bytes.get(2) != Some(&b':') {
        return Ok(None);
    }

    let Some(hour) = parse_2_digits(bytes, 0) else {
        return Ok(None);
    };
    let Some(minute) = parse_2_digits(bytes, 3) else {
        return Ok(None);
    };
    let mut second = 0;
    let mut microsecond = 0;

    if bytes.len() >= 8 {
        if bytes.get(5) != Some(&b':') {
            return Ok(None);
        }
        let Some(parsed_second) = parse_2_digits(bytes, 6) else {
            return Ok(None);
        };
        second = parsed_second;
    } else if bytes.len() != 5 {
        return Ok(None);
    }

    if bytes.len() > 8 {
        if bytes.get(8) != Some(&b'.') {
            return Ok(None);
        }
        let fraction = &bytes[9..];
        if fraction.is_empty() || fraction.len() > 6 {
            return Ok(None);
        }
        let mut value = 0u32;
        for digit in fraction {
            if !digit.is_ascii_digit() {
                return Ok(None);
            }
            value = value * 10 + u32::from(digit - b'0');
        }
        for _ in fraction.len()..6 {
            value *= 10;
        }
        microsecond = value;
    }

    if hour > 23 || minute > 59 || second > 59 {
        return Ok(None);
    }

    let time_cls = py.import_bound("datetime")?.getattr("time")?;
    Ok(Some(time_cls.call1((hour, minute, second, microsecond))?.into_py(py)))
}

pub(crate) fn coerce_decimal_with_helper(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    helper: Option<&Bound<'_, PyAny>>,
) -> PyResult<Py<PyAny>> {
    if type_name(value).as_deref() == Some("Decimal") {
        return Ok(value.into_py(py));
    }

    let decimal_cls = if let Some(helper) = helper {
        helper.clone()
    } else {
        py.import_bound("decimal")?.getattr("Decimal")?
    };

    let coerced = if let Ok(s) = value.downcast::<PyString>() {
        decimal_cls.call1((s.to_str()?,))
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

pub(crate) fn coerce_scalar_by_kind_with_helper(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    kind: u8,
    helper: Option<&Bound<'_, PyAny>>,
) -> PyResult<Py<PyAny>> {
    if matches_kind(value, kind) {
        return Ok(value.into_py(py));
    }

    match kind {
        KIND_STR => coerce_str_impl(py, value),
        KIND_INT => coerce_int_impl(py, value),
        KIND_FLOAT => coerce_float_impl(py, value),
        KIND_BOOL => coerce_bool_impl(py, value),
        KIND_TIME => coerce_time_with_helper(py, value, helper),
        KIND_DURATION => coerce_duration_with_helper(py, value, helper),
        KIND_DATE => coerce_date_with_helper(py, value, helper),
        KIND_DATETIME => coerce_datetime_with_helper(py, value, helper),
        KIND_DECIMAL => coerce_decimal_with_helper(py, value, helper),
        _ => Ok(py_none(py)),
    }
}
