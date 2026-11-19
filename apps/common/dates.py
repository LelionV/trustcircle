"""Date-range filters that work the same on every database.

`created_at__date__gte=...` makes MySQL convert time zones in SQL, which needs
MySQL's time-zone tables (often not installed, especially on Windows) and
silently matches nothing without them. These helpers turn local dates into
aware datetimes instead.
"""
from datetime import datetime, time, timedelta

from django.utils import timezone


def start_of(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def date_range_filter(field, start=None, end=None):
    """{field__gte: start 00:00 local, field__lt: day after end 00:00 local}."""
    q = {}
    if start:
        q[f"{field}__gte"] = start_of(start)
    if end:
        q[f"{field}__lt"] = start_of(end + timedelta(days=1))
    return q
