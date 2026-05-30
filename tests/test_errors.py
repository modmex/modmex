from modmex.errors import ValidationError


def test_validation_error_str_formats_all_locations() -> None:
    error = ValidationError(
        errors=[
            {"loc": ["user", "email"], "msg": "invalid format", "type": "value_error"},
            {"loc": ["tags", 1], "msg": "not an integer", "type": "value_error"},
        ]
    )

    assert str(error) == (
        "Error at user.email: invalid format\n"
        "Error at tags.1: not an integer"
    )
