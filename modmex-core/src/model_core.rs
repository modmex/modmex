use crate::coerce::coerce_scalar_by_kind;
use crate::types::*;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList, PyString, PyTuple};

pub(crate) fn compile_validator(node: &Bound<'_, PyAny>) -> PyResult<Option<Validator>> {
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
        | KIND_DATETIME | KIND_DECIMAL => Ok(Some(Validator::Scalar(tag))),
        NODE_ENUM => {
            if node_tuple.len() < 2 {
                return Ok(None);
            }
            Ok(Some(Validator::Enum(node_tuple.get_item(1)?.unbind())))
        }
        NODE_MODEL => {
            if node_tuple.len() < 5 {
                return Ok(None);
            }
            Ok(Some(Validator::Model {
                model_type: node_tuple.get_item(1)?.unbind(),
                trusted_ctor: node_tuple.get_item(3)?.unbind(),
                core: node_tuple.get_item(4)?.unbind(),
            }))
        }
        NODE_LIST => {
            if node_tuple.len() < 2 {
                return Ok(None);
            }
            let inner = compile_validator(&node_tuple.get_item(1)?)?;
            Ok(inner.map(|v| Validator::List(Box::new(v))))
        }
        NODE_DICT_STR => {
            if node_tuple.len() < 2 {
                return Ok(None);
            }
            let inner = compile_validator(&node_tuple.get_item(1)?)?;
            Ok(inner.map(|v| Validator::DictStr(Box::new(v))))
        }
        NODE_OPTIONAL => {
            if node_tuple.len() < 2 {
                return Ok(None);
            }
            let inner = compile_validator(&node_tuple.get_item(1)?)?;
            Ok(inner.map(|v| Validator::Optional(Box::new(v))))
        }
        NODE_LITERAL => {
            if node_tuple.len() < 2 {
                return Ok(None);
            }
            Ok(Some(Validator::Literal(node_tuple.get_item(1)?.unbind())))
        }
        NODE_ANY => Ok(Some(Validator::Any)),
        _ => Ok(None),
    }
}

pub(crate) fn validate_compiled(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    validator: &Validator,
) -> PyResult<Option<Py<PyAny>>> {
    match validator {
        Validator::Scalar(kind) => {
            let out = coerce_scalar_by_kind(py, value, *kind)?;
            if out.bind(py).is_none() {
                Ok(None)
            } else {
                Ok(Some(out))
            }
        }
        Validator::Enum(enum_type) => {
            let enum_type = enum_type.bind(py);
            if value.is_instance(enum_type)? {
                Ok(Some(value.into_py(py)))
            } else {
                match enum_type.call1((value,)) {
                    Ok(v) => Ok(Some(v.into_py(py))),
                    Err(_) => Ok(None),
                }
            }
        }
        Validator::Model {
            model_type,
            trusted_ctor,
            core,
        } => {
            let model_type = model_type.bind(py);
            if value.is_instance(model_type)? {
                return Ok(Some(value.into_py(py)));
            }
            let source = if let Ok(d) = value.downcast::<PyDict>() {
                d
            } else {
                return Ok(None);
            };
            match core.bind(py).call_method1("validate_updates", (source,)) {
                Ok(updates) => {
                    if updates.is_none() {
                        return Ok(None);
                    }
                    let merged = source.copy()?;
                    let updates_dict = if let Ok(d) = updates.downcast::<PyDict>() {
                        d
                    } else {
                        return Ok(None);
                    };
                    for (key, item) in updates_dict.iter() {
                        merged.set_item(key, item)?;
                    }
                    match trusted_ctor.bind(py).call1((merged,)) {
                        Ok(instance) => Ok(Some(instance.into_py(py))),
                        Err(_) => Ok(None),
                    }
                }
                Err(_) => Ok(None),
            }
        }
        Validator::List(inner) => {
            let list_obj = if let Ok(l) = value.downcast::<PyList>() {
                l
            } else {
                return Ok(None);
            };
            let out = PyList::empty_bound(py);
            for item in list_obj.iter() {
                if let Some(v) = validate_compiled(py, &item, inner)? {
                    out.append(v.bind(py))?;
                } else {
                    return Ok(None);
                }
            }
            Ok(Some(out.into_py(py)))
        }
        Validator::DictStr(inner) => {
            let dict_obj = if let Ok(d) = value.downcast::<PyDict>() {
                d
            } else {
                return Ok(None);
            };
            let out = PyDict::new_bound(py);
            for (key, item) in dict_obj.iter() {
                if !key.is_instance_of::<PyString>() {
                    return Ok(None);
                }
                if let Some(v) = validate_compiled(py, &item, inner)? {
                    out.set_item(key, v.bind(py))?;
                } else {
                    return Ok(None);
                }
            }
            Ok(Some(out.into_py(py)))
        }
        Validator::Optional(inner) => {
            if value.is_none() {
                Ok(Some(py_none(py)))
            } else {
                validate_compiled(py, value, inner)
            }
        }
        Validator::Literal(allowed) => {
            let allowed_tuple = if let Ok(t) = allowed.bind(py).downcast::<PyTuple>() {
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
        Validator::Any => Ok(Some(value.into_py(py))),
    }
}

#[pymethods]
impl ModelCore {
    #[new]
    fn new(
        py: Python<'_>,
        model_type: Py<PyAny>,
        descriptors: &Bound<'_, PyAny>,
    ) -> PyResult<Self> {
        let mut fields = Vec::new();
        for descriptor in descriptors.iter()? {
            let descriptor = descriptor?;
            let descriptor = descriptor.downcast::<PyTuple>()?;
            if descriptor.len() != 5 {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "invalid field descriptor",
                ));
            }

            let name = descriptor.get_item(0)?.extract::<String>()?;
            let node = descriptor.get_item(1)?;
            let required = descriptor.get_item(2)?.extract::<bool>()?;
            let default_obj = descriptor.get_item(3)?;
            let default_factory_obj = descriptor.get_item(4)?;
            let validator = compile_validator(&node)?.ok_or_else(|| {
                pyo3::exceptions::PyValueError::new_err("unsupported schema node")
            })?;

            fields.push(FieldSpec {
                name,
                required,
                default: if default_obj.is_none() {
                    None
                } else {
                    Some(default_obj.into_py(py))
                },
                default_factory: if default_factory_obj.is_none() {
                    None
                } else {
                    Some(default_factory_obj.into_py(py))
                },
                validator,
            });
        }
        Ok(Self { model_type, fields })
    }

    fn construct(&self, py: Python<'_>, kwargs: &Bound<'_, PyDict>) -> PyResult<Py<PyAny>> {
        let instance = self.model_type.bind(py).call_method0("__new__")?;
        if self.construct_into(py, &instance, kwargs)? {
            Ok(instance.into_py(py))
        } else {
            Ok(py_none(py))
        }
    }

    fn validate_kwargs(&self, py: Python<'_>, kwargs: &Bound<'_, PyDict>) -> PyResult<Py<PyAny>> {
        let out = PyDict::new_bound(py);
        for field in &self.fields {
            let value = if let Some(raw) = kwargs.get_item(field.name.as_str())? {
                match validate_compiled(py, &raw, &field.validator)? {
                    Some(v) => v,
                    None => return Ok(py_none(py)),
                }
            } else if let Some(default) = &field.default {
                default.clone_ref(py)
            } else if let Some(default_factory) = &field.default_factory {
                default_factory.bind(py).call0()?.into_py(py)
            } else if field.required {
                return Ok(py_none(py));
            } else {
                py_none(py)
            };
            out.set_item(field.name.as_str(), value.bind(py))?;
        }
        Ok(out.into_py(py))
    }

    fn validate_updates(&self, py: Python<'_>, kwargs: &Bound<'_, PyDict>) -> PyResult<Py<PyAny>> {
        let out = PyDict::new_bound(py);
        for field in &self.fields {
            if let Some(raw) = kwargs.get_item(field.name.as_str())? {
                match validate_compiled(py, &raw, &field.validator)? {
                    Some(v) => out.set_item(field.name.as_str(), v.bind(py))?,
                    None => return Ok(py_none(py)),
                }
            } else if field.required {
                return Ok(py_none(py));
            }
        }
        Ok(out.into_py(py))
    }

    fn construct_into(
        &self,
        py: Python<'_>,
        target: &Bound<'_, PyAny>,
        kwargs: &Bound<'_, PyDict>,
    ) -> PyResult<bool> {
        for field in &self.fields {
            let value = if let Some(raw) = kwargs.get_item(field.name.as_str())? {
                match validate_compiled(py, &raw, &field.validator)? {
                    Some(v) => v,
                    None => return Ok(false),
                }
            } else if let Some(default) = &field.default {
                default.clone_ref(py)
            } else if let Some(default_factory) = &field.default_factory {
                default_factory.bind(py).call0()?.into_py(py)
            } else if field.required {
                return Ok(false);
            } else {
                py_none(py)
            };
            target.setattr(field.name.as_str(), value.bind(py))?;
        }
        Ok(true)
    }
}
