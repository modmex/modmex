use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBool, PyFloat, PyInt, PyString};

pub(crate) const KIND_STR: u8 = 1;
pub(crate) const KIND_INT: u8 = 2;
pub(crate) const KIND_FLOAT: u8 = 3;
pub(crate) const KIND_BOOL: u8 = 4;
pub(crate) const KIND_TIME: u8 = 5;
pub(crate) const KIND_DURATION: u8 = 6;
pub(crate) const KIND_DATE: u8 = 7;
pub(crate) const KIND_DATETIME: u8 = 8;
pub(crate) const KIND_DECIMAL: u8 = 9;

pub(crate) const NODE_ENUM: u8 = 10;
pub(crate) const NODE_MODEL: u8 = 11;
pub(crate) const NODE_LIST: u8 = 12;
pub(crate) const NODE_DICT_STR: u8 = 13;
pub(crate) const NODE_OPTIONAL: u8 = 14;
pub(crate) const NODE_LITERAL: u8 = 15;
pub(crate) const NODE_ANY: u8 = 16;

pub(crate) enum Validator {
    Scalar(ScalarValidator),
    Enum(Py<PyAny>),
    Model {
        model_type: Py<PyAny>,
        core: Py<ModelCore>,
    },
    List(Box<Validator>),
    DictStr(Box<Validator>),
    Optional(Box<Validator>),
    Literal(Py<PyAny>),
    Any,
}

pub(crate) struct ScalarValidator {
    pub(crate) kind: u8,
    pub(crate) helper: Option<Py<PyAny>>,
}

pub(crate) struct FieldSpec {
    pub(crate) py_name: Py<PyString>,
    pub(crate) required: bool,
    pub(crate) default: Option<Py<PyAny>>,
    pub(crate) default_factory: Option<Py<PyAny>>,
    pub(crate) validator: Validator,
}

#[pyclass]
pub(crate) struct ModelCore {
    pub(crate) model_type: Py<PyAny>,
    pub(crate) new_func: Py<PyAny>,
    pub(crate) fields: Vec<FieldSpec>,
}

pub(crate) fn py_none(py: Python<'_>) -> Py<PyAny> {
    py.None()
}

pub(crate) fn type_name(value: &Bound<'_, PyAny>) -> Option<String> {
    value.get_type().name().ok().map(|v| v.to_string())
}

pub(crate) fn matches_kind(value: &Bound<'_, PyAny>, kind: u8) -> bool {
    match kind {
        KIND_STR => value.is_instance_of::<PyString>(),
        KIND_INT => value.is_instance_of::<PyInt>() && !value.is_instance_of::<PyBool>(),
        KIND_FLOAT => value.is_instance_of::<PyFloat>(),
        KIND_BOOL => value.is_instance_of::<PyBool>(),
        KIND_TIME => type_name(value).as_deref() == Some("time"),
        KIND_DURATION => type_name(value).as_deref() == Some("timedelta"),
        KIND_DATE => type_name(value).as_deref() == Some("date"),
        KIND_DATETIME => type_name(value).as_deref() == Some("datetime"),
        KIND_DECIMAL => type_name(value).as_deref() == Some("Decimal"),
        _ => false,
    }
}
