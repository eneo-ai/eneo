from datetime import datetime, timezone

UTC_MIN_DATETIME = datetime.min.replace(tzinfo=timezone.utc)


def datetime_or_utc_min(value: datetime | None) -> datetime:
    if value is None:
        return UTC_MIN_DATETIME
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
