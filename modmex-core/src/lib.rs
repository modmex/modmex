use pyo3::prelude::*;

mod coerce;
mod model_core;
mod types;

#[pymodule]
fn _modmex_rust(_py: Python<'_>, module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<types::ModelCore>()?;
    Ok(())
}
