use pyo3::prelude::*;

mod coerce;
mod construct;
mod model_core;
mod profile;
mod serialize;
mod types;

#[pymodule]
fn _modmex_rust(_py: Python<'_>, module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(coerce::coerce_str, module)?)?;
    module.add_function(wrap_pyfunction!(coerce::coerce_int, module)?)?;
    module.add_function(wrap_pyfunction!(coerce::coerce_float, module)?)?;
    module.add_function(wrap_pyfunction!(coerce::coerce_bool, module)?)?;
    module.add_function(wrap_pyfunction!(coerce::coerce_time, module)?)?;
    module.add_function(wrap_pyfunction!(coerce::coerce_date, module)?)?;
    module.add_function(wrap_pyfunction!(coerce::coerce_datetime, module)?)?;

    module.add_function(wrap_pyfunction!(serialize::serialize_scalar, module)?)?;
    module.add_function(wrap_pyfunction!(serialize::serialize_tree, module)?)?;
    module.add_function(wrap_pyfunction!(serialize::serialize_model_fields, module)?)?;
    module.add_class::<types::ModelCore>()?;

    module.add_function(wrap_pyfunction!(coerce::coerce_values, module)?)?;
    module.add_function(wrap_pyfunction!(coerce::coerce_kwargs, module)?)?;
    module.add_function(wrap_pyfunction!(coerce::coerce_enum_kwargs, module)?)?;
    module.add_function(wrap_pyfunction!(coerce::coerce_model_kwargs, module)?)?;
    module.add_function(wrap_pyfunction!(coerce::coerce_construct_kwargs, module)?)?;
    module.add_function(wrap_pyfunction!(coerce::coerce_schema_kwargs, module)?)?;
    module.add_function(wrap_pyfunction!(
        construct::construct_model_from_schema,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(
        construct::construct_model_runtime,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(profile::reset_construct_profile, module)?)?;
    module.add_function(wrap_pyfunction!(profile::get_construct_profile, module)?)?;
    Ok(())
}
