from celery import shared_task

from . import jobs


@shared_task(name="reports.run_job")
def run_job(name):
    return jobs.run([name])
