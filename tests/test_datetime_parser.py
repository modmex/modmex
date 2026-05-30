from datetime import date, datetime, time, timedelta, timezone

import pytest

from modmex.datetime_parser import (
    get_numeric,
    from_unix_seconds,
    parse_date,
    parse_datetime,
    parse_duration,
    parse_time,
)


def test_get_numeric_handles_strings_and_invalid_types() -> None:
    assert get_numeric("10.5", "date") == 10.5
    assert get_numeric(10, "date") == 10

    with pytest.raises(TypeError):
        get_numeric(None, "date")


def test_from_unix_seconds_supports_milliseconds_and_bounds() -> None:
    dt_from_ms = from_unix_seconds(21_000_000_000)

    assert dt_from_ms.year == 1970
    assert from_unix_seconds(int(4e20)) == datetime.max
    assert from_unix_seconds(-int(4e20)) == datetime.min


def test_parse_date_supports_datetime_string_and_bytes() -> None:
    assert parse_date("2026-05-30T18:10:05") == date(2026, 5, 30)
    assert parse_date(b"2026-05-30") == date(2026, 5, 30)
    assert parse_date(datetime(2026, 5, 30, 18, 10, 5)) == date(2026, 5, 30)
    assert parse_date(0) == date(1970, 1, 1)

    with pytest.raises(ValueError, match="invalid date"):
        parse_date("2026-15-30")

    with pytest.raises(ValueError, match="invalid date"):
        parse_date("no-date")

    with pytest.raises(ValueError, match="invalid date"):
        parse_date("2026-02-30T10:00:00")

    with pytest.raises(ValueError, match="invalid date"):
        parse_date("2026-05-30T25:00:00")


def test_parse_time_supports_offsets_and_rejects_invalid_values() -> None:
    parsed = parse_time("08:30:15.1+0230")
    parsed_negative_offset = parse_time("08:30:00-0230")
    parsed_from_number = parse_time(60)
    parsed_from_bytes = parse_time(b"08:30")

    assert parsed == time(8, 30, 15, 100000, tzinfo=timezone(timedelta(hours=2, minutes=30)))
    assert parsed_negative_offset == time(8, 30, 0, tzinfo=timezone(timedelta(hours=-2, minutes=-30)))
    assert parsed_from_number == time(0, 1)
    assert parsed_from_bytes == time(8, 30)

    with pytest.raises(ValueError, match="invalid time"):
        parse_time(86400)

    with pytest.raises(ValueError, match="invalid time"):
        parse_time("bad-time")

    with pytest.raises(ValueError, match="invalid time"):
        parse_time("25:00:00")

    with pytest.raises(ValueError, match="invalid timezone"):
        parse_time("08:30:00+99:99")


def test_parse_datetime_supports_numeric_and_timezone_values() -> None:
    parsed_from_number = parse_datetime(0)
    parsed_from_str = parse_datetime("2026-05-30 18:10:05Z")
    parsed_from_bytes = parse_datetime(b"2026-05-30T18:10:05.1")

    assert parsed_from_number == datetime(1970, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert parsed_from_str == datetime(2026, 5, 30, 18, 10, 5, tzinfo=timezone.utc)
    assert parsed_from_bytes == datetime(2026, 5, 30, 18, 10, 5, 100000)

    with pytest.raises(ValueError, match="invalid datetime"):
        parse_datetime("bad-datetime")

    with pytest.raises(ValueError, match="invalid datetime"):
        parse_datetime("2026-01-01T25:00:00")


def test_parse_duration_supports_standard_and_iso_formats() -> None:
    assert parse_duration("1 02:03:04.5") == timedelta(days=1, hours=2, minutes=3, seconds=4, microseconds=500000)
    assert parse_duration("PT1H30M") == timedelta(hours=1, minutes=30)
    assert parse_duration(b"10") == timedelta(seconds=10)
    assert parse_duration("-1.5") == timedelta(seconds=-1, microseconds=-500000)

    with pytest.raises(ValueError, match="invalid duration"):
        parse_duration("PX1")

    with pytest.raises(TypeError):
        parse_duration(None)
