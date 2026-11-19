import json

from django.core.management.base import BaseCommand, CommandError

from apps.reports import jobs


class Command(BaseCommand):
    help = "Run the platform's scheduled jobs (funding expiry, overdue and defaults, claims, consent, fees, reconciliation)."

    def add_arguments(self, parser):
        parser.add_argument("jobs", nargs="*", help=f"Which jobs (default all): {', '.join(jobs.JOBS)}")

    def handle(self, *args, **opts):
        unknown = [j for j in opts["jobs"] if j not in jobs.JOBS]
        if unknown:
            raise CommandError(f"Unknown job(s): {', '.join(unknown)}")
        results = jobs.run(opts["jobs"] or None)
        self.stdout.write(json.dumps(results, indent=2, default=str))
