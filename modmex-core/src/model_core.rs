use crate::coerce::coerce_scalar_by_kind_with_helper;
use crate::types::*;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList, PyString, PyTuple};

fn compile_validator(py: Python<'_>, node: &Bound<'_, PyAny>) -> PyResult<Option<Validator>> {
    let Ok(node_tuple) = node.downcast::<PyTuple>() else {
        return Ok(None);
    };
    if node_tuple.is_empty() {
        return Ok(None);
    }

    let tag = node_tuple.get_item(0)?.extract::<u8>()?;
    match tag {
        KIND_STR | KIND_INT | KIND_FLOAT | KIND_BOOL | KIND_TIME | KIND_DURATION | KIND_DATE
        | KIND_DATETIME | KIND_DECIMAL => Ok(Some(Validator::Scalar(compile_scalar(py, tag)?))),
        NODE_ENUM => {
            if node_tuple.len() < 2 {
                return Ok(None);
            }
            Ok(Some(Validator::Enum(node_tuple.get_item(1)?.unbind())))
        }
        NODE_MODEL => {
            if node_tuple.len() < 3 {
                return Ok(None);
            }
            Ok(Some(Validator::Model {
                model_type: node_tuple.get_item(1)?.unbind(),
                core: node_tuple.get_item(2)?.extract::<Py<ModelCore>>()?,
            }))
        }
        NODE_LIST => {
            if node_tuple.len() < 2 {
                return Ok(None);
            }
            Ok(compile_validator(py, &node_tuple.get_item(1)?)?
                .map(|v| Validator::List(Box::new(v))))
        }
        NODE_DICT_STR => {
            if node_tuple.len() < 2 {
                return Ok(None);
            }
            Ok(compile_validator(py, &node_tuple.get_item(1)?)?
                .map(|v| Validator::DictStr(Box::new(v))))
        }
        NODE_OPTIONAL => {
            if node_tuple.len() < 2 {
                return Ok(None);
            }
            Ok(compile_validator(py, &node_tuple.get_item(1)?)?
                .map(|v| Validator::Optional(Box::new(v))))
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

fn validate_value(
    py: Python<'_>,
    value: &Bound<'_, PyAny>,
    validator: &Validator,
) -> PyResult<Option<Py<PyAny>>> {
    match validator {
        Validator::Scalar(scalar) => {
            let helper = scalar.helper.as_ref().map(|helper| helper.bind(py));
            let out = coerce_scalar_by_kind_with_helper(py, value, scalar.kind, helper)?;
            if out.bind(py).is_none() {
                Ok(None)
            } else {
                Ok(Some(out))
            }
        }
        Validator::Enum(enum_type) => {
            let enum_type = enum_type.bind(py);
            if value.is_instance(enum_type)? {
                return Ok(Some(value.into_py(py)));
            }
            match enum_type.call1((value,)) {
                Ok(v) => Ok(Some(v.into_py(py))),
                Err(_) => Ok(None),
            }
        }
        Validator::Model { model_type, core } => {
            let model_type = model_type.bind(py);
            if value.is_instance(model_type)? {
                return Ok(Some(value.into_py(py)));
            }
            let Ok(source) = value.downcast::<PyDict>() else {
                return Ok(None);
            };
            core.bind(py).borrow().construct_from_kwargs(py, source)
        }
        Validator::List(inner) => {
            let Ok(list_obj) = value.downcast::<PyList>() else {
                return Ok(None);
            };
            let out = PyList::empty_bound(py);
            for item in list_obj.iter() {
                let Some(validated) = validate_value(py, &item, inner)? else {
                    return Ok(None);
                };
                out.append(validated.bind(py))?;
            }
            Ok(Some(out.into_py(py)))
        }
        Validator::DictStr(inner) => {
            let Ok(dict_obj) = value.downcast::<PyDict>() else {
                return Ok(None);
            };
            let out = PyDict::new_bound(py);
            for (key, item) in dict_obj.iter() {
                if !key.is_instance_of::<PyString>() {
                    return Ok(None);
                }
                let Some(validated) = validate_value(py, &item, inner)? else {
                    return Ok(None);
                };
                out.set_item(key, validated.bind(py))?;
            }
            Ok(Some(out.into_py(py)))
        }
        Validator::Optional(inner) => {
            if value.is_none() {
                Ok(Some(py_none(py)))
            } else {
                validate_value(py, value, inner)
            }
        }
        Validator::Literal(allowed) => {
            let Ok(allowed_tuple) = allowed.bind(py).downcast::<PyTuple>() else {
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

fn compile_scalar(py: Python<'_>, kind: u8) -> PyResult<ScalarValidator> {
    let helper = match kind {
        KIND_TIME => Some(
            py.import_bound("datetime")?
                .getattr("time")?
                .getattr("fromisoformat")?
                .unbind(),
        ),
        KIND_DATE => Some(
            py.import_bound("datetime")?
                .getattr("date")?
                .getattr("fromisoformat")?
                .unbind(),
        ),
        KIND_DATETIME => Some(
            py.import_bound("datetime")?
                .getattr("datetime")?
                .getattr("fromisoformat")?
                .unbind(),
        ),
        KIND_DURATION => Some(py.import_bound("datetime")?.getattr("timedelta")?.unbind()),
        KIND_DECIMAL => Some(py.import_bound("decimal")?.getattr("Decimal")?.unbind()),
        _ => None,
    };
    Ok(ScalarValidator { kind, helper })
}

impl ModelCore {
    fn new_instance(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.new_func
            .bind(py)
            .call1((self.model_type.bind(py),))
            .map(|v| v.into_py(py))
    }

    fn validate_to_state(
        &self,
        py: Python<'_>,
        kwargs: &Bound<'_, PyDict>,
    ) -> PyResult<Option<Py<PyDict>>> {
        let state = PyDict::new_bound(py);

        for field in &self.fields {
            let name = field.py_name.bind(py);
            let value = if let Some(raw) = kwargs.get_item(name)? {
                let Some(validated) = validate_value(py, &raw, &field.validator)? else {
                    return Ok(None);
                };
                validated
            } else if let Some(default) = &field.default {
                default.clone_ref(py)
            } else if let Some(default_factory) = &field.default_factory {
                default_factory.bind(py).call0()?.into_py(py)
            } else if field.required {
                return Ok(None);
            } else {
                py_none(py)
            };
            state.set_item(name, value.bind(py))?;
        }

        Ok(Some(state.unbind()))
    }

    fn install_state(
        &self,
        target: &Bound<'_, PyAny>,
        state: &Bound<'_, PyDict>,
    ) -> PyResult<()> {
        match target.setattr("__dict__", state) {
            Ok(()) => Ok(()),
            Err(_) => {
                let target_dict = target.getattr("__dict__")?;
                let target_dict = target_dict.downcast::<PyDict>()?;
                target_dict.update(state.as_mapping())
            }
        }
    }

    pub(crate) fn construct_from_kwargs(
        &self,
        py: Python<'_>,
        kwargs: &Bound<'_, PyDict>,
    ) -> PyResult<Option<Py<PyAny>>> {
        let Some(state) = self.validate_to_state(py, kwargs)? else {
            return Ok(None);
        };
        let instance = self.new_instance(py)?;
        self.install_state(instance.bind(py), state.bind(py))?;
        Ok(Some(instance))
    }

    pub(crate) fn construct_into_inner(
        &self,
        py: Python<'_>,
        target: &Bound<'_, PyAny>,
        kwargs: &Bound<'_, PyDict>,
    ) -> PyResult<bool> {
        let Some(state) = self.validate_to_state(py, kwargs)? else {
            return Ok(false);
        };
        self.install_state(target, state.bind(py))?;
        Ok(true)
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
        let new_func = model_type.bind(py).getattr("__new__")?.unbind();
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
            let validator = compile_validator(py, &node)?.ok_or_else(|| {
                pyo3::exceptions::PyValueError::new_err("unsupported schema node")
            })?;

            fields.push(FieldSpec {
                py_name: PyString::new_bound(py, name.as_str()).unbind(),
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

        Ok(Self {
            model_type,
            new_func,
            fields,
        })
    }

    fn construct(&self, py: Python<'_>, kwargs: &Bound<'_, PyDict>) -> PyResult<Py<PyAny>> {
        match self.construct_from_kwargs(py, kwargs)? {
            Some(instance) => Ok(instance),
            None => Ok(py_none(py)),
        }
    }

    fn construct_into(
        &self,
        py: Python<'_>,
        target: &Bound<'_, PyAny>,
        kwargs: &Bound<'_, PyDict>,
    ) -> PyResult<bool> {
        self.construct_into_inner(py, target, kwargs)
    }
}
