"""
Celery application.

Windows (development):  celery -A config worker --loglevel=info --pool=solo
Linux (production):     celery -A config worker --loglevel=info
                        celery -A config beat --loglevel=info
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("p2plend")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Scheduled jobs (apps/reports/jobs.py). Times are in TIME_ZONE.
# Without Celery, run `python manage.py run_scheduled_jobs` from cron / Task Scheduler instead.
from celery.schedules import crontab  # noqa: E402

app.conf.beat_schedule = {
    "expire-funding-hourly": {"task": "reports.run_job", "schedule": crontab(minute=5), "args": ("expire_funding",)},
    "consent-hourly": {"task": "reports.run_job", "schedule": crontab(minute=10), "args": ("consent",)},
    "overdue-daily": {"task": "reports.run_job", "schedule": crontab(hour=6, minute=0), "args": ("overdue",)},
    "claims-daily": {"task": "reports.run_job", "schedule": crontab(hour=6, minute=30), "args": ("claims",)},
    "account-fees-monthly": {"task": "reports.run_job", "schedule": crontab(day_of_month=1, hour=7, minute=0),
                             "args": ("account_fees",)},
    "reconcile-nightly": {"task": "reports.run_job", "schedule": crontab(hour=1, minute=0), "args": ("reconcile",)},
}
