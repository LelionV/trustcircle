from django.apps import apps
from django.core.management.base import BaseCommand

from apps.common.constraints import ConditionalUnique


class Command(BaseCommand):
    help = ("Recompute the flag columns behind 'unique while…' rules (one active config, one open offer per "
            "investor, one live guarantee per loan…). Run after loaddata or after moving data between databases.")

    def handle(self, *args, **options):
        for model in apps.get_models():
            if issubclass(model, ConditionalUnique) and not model._meta.abstract:
                model.sync_flags()
                self.stdout.write(f"  {model._meta.label}: flags updated")
        self.stdout.write(self.style.SUCCESS("Done."))
