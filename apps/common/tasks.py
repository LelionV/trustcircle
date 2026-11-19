from celery import shared_task


@shared_task(name="common.ping")
def ping() -> str:
    """Smoke-test task: `python manage.py shell -c "from apps.common.tasks import ping; print(ping.delay().get(timeout=10))"`."""
    return "pong"
