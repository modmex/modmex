
"""Exception types raised by modmex."""


class UnsupportedJsonSchemaTypeError(TypeError):
    """Raised when a field type has no explicit JSON Schema representation."""


class ValidationError(Exception):
    def __init__(self, errors: list[dict], message: str = "Validation errors occurred"):
        super().__init__(message)
        self.errors = errors

    def _format_error_message(self) -> str:
        return "\n".join(
            f"Error at {'.'.join(map(str, error['loc']))}: {error['msg']}" for error in self.errors
        )

    def __str__(self) -> str:
        return self._format_error_message()
