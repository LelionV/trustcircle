"""
python manage.py doctor

Finds what's behind "error 500" pages:
  1. the database connection (and MySQL settings),
  2. model changes without migration files, and migrations not applied,
  3. tables or columns the code expects but the database doesn't have,
  4. every page's data (GET endpoints) called as one user of each role, printing the
     full error for anything that fails.
Read-only: each call runs in a transaction that is rolled back.
"""
import logging
import traceback
from io import StringIO

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor

ENDPOINTS = {
    "everyone": ["accounts/me/", "accounts/me/profile/", "notifications/", "notifications/unread/"],
    "customer": ["wallet/", "wallet/transactions/", "payments/", "chat/", "disputes/", "reports/users/", "kyc/me/"],
    "BORROWER": ["loans/", "loans/products/", "trust/me/", "risk/me/", "pricing/brackets/", "repayments/",
                 "loans/{loan}/", "loans/{loan}/agreement/"],
    "INVESTOR": ["marketplace/", "marketplace/?mode=OFFERS", "portfolio/", "investments/", "offers/"],
    "GUARANTOR": ["guarantees/", "marketplace/", "portfolio/"],
    "ADMIN": ["admin/overview/", "admin/users/", "admin/kyc/", "admin/loans/", "admin/loans/{any_loan}/",
              "admin/audit-logs/", "admin/config/", "admin/config/platform/", "admin/payments/",
              "admin/extensions/", "admin/defaults/", "admin/finance/reconcile/", "admin/finance/revenue/",
              "admin/finance/ledger/", "admin/reports/", "admin/disputes/", "admin/moderation/reports/",
              "admin/support/chats/"],
}


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class Command(BaseCommand):
    help = "Diagnose server errors: database, migrations, missing columns, and every page's data per role."

    def handle(self, *args, **options):
        ok = True
        ok &= self._database()
        ok &= self._migrations()
        ok &= self._columns()
        ok &= self._endpoints()
        self.stdout.write("")
        if ok:
            self.stdout.write(self.style.SUCCESS("No problems found."))
        else:
            self.stdout.write(self.style.ERROR("Problems found (see above). Send this whole output if you need help."))

    def _title(self, text):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n== {text}"))

    def _database(self):
        self._title("Database")
        try:
            connection.ensure_connection()
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(f"  Can't connect: {exc}"))
            return False
        self.stdout.write(f"  {connection.vendor} · {connection.settings_dict.get('NAME')}")
        if connection.vendor == "mysql":
            try:
                call_command("check_mysql", stdout=StringIO())
                self.stdout.write("  MySQL settings OK")
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"  {exc} (run: python manage.py check_mysql)"))
                return False
        return True

    def _migrations(self):
        self._title("Migrations")
        ok = True
        try:
            call_command("makemigrations", "--check", "--dry-run", stdout=StringIO(), stderr=StringIO())
            self.stdout.write("  Migration files match the models")
        except SystemExit:
            ok = False
            self.stdout.write(self.style.ERROR("  The models changed but there are no migration files for it. "
                                               "Run: python manage.py makemigrations"))
        executor = MigrationExecutor(connections[DEFAULT_DB_ALIAS])
        recorded = executor.recorder.applied_migrations()
        on_disk = set(executor.loader.disk_migrations)
        orphans = sorted({app for (app, name) in recorded if (app, name) not in on_disk and app in
                          {c.label for c in apps.get_app_configs() if c.name.startswith("apps.")}})
        if orphans:
            ok = False
            self.stdout.write(self.style.ERROR(
                "  The database has migrations applied that aren't in this folder's migrations/ directories "
                f"({', '.join(orphans)}). This happens when a new download is unzipped into a new folder: the "
                "migration files you generated earlier stay in the old folder.\n"
                "  Fix (best): copy the old folder's apps\\*\\migrations\\0*.py files into this folder, or unzip "
                "updates over your existing project instead of into a new folder.\n"
                "  Fix (if the old folder is gone): python manage.py makemigrations, then python manage.py migrate "
                "--fake-initial, then run doctor again."))
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            ok = False
            names = ", ".join(f"{m.app_label}.{m.name}" for m, _ in plan[:12])
            self.stdout.write(self.style.ERROR(f"  {len(plan)} migration(s) not applied ({names}…). "
                                               "Run: python manage.py migrate"))
        else:
            self.stdout.write("  All migrations applied")
        return ok

    def _columns(self):
        self._title("Tables and columns")
        missing = []
        with connection.cursor() as cursor:
            tables = set(connection.introspection.table_names(cursor))
            for model in apps.get_models():
                if model._meta.proxy or not model._meta.managed:
                    continue
                table = model._meta.db_table
                if table not in tables:
                    missing.append(f"table {table}")
                    continue
                cols = {c.name for c in connection.introspection.get_table_description(cursor, table)}
                for f in model._meta.local_concrete_fields:
                    if f.column not in cols:
                        missing.append(f"{table}.{f.column}")
        if missing:
            self.stdout.write(self.style.ERROR(f"  Missing: {', '.join(missing[:25])}{' …' if len(missing) > 25 else ''}"))
            self.stdout.write(self.style.ERROR("  Run: python manage.py makemigrations, then python manage.py migrate"))
            return False
        self.stdout.write("  Every table and column the code uses exists")
        return True

    def _endpoints(self):
        self._title("Pages (API calls each page makes), per role")
        from rest_framework.test import APIClient

        from apps.accounts.models import Role, User
        from apps.loans.models import Loan

        collector = _Collect()
        log = logging.getLogger("apps.errors")
        log.addHandler(collector)
        ok = True
        try:
            if True:  # each call runs in its own transaction, rolled back afterwards
                users = {}
                for role in (Role.BORROWER, Role.INVESTOR, Role.GUARANTOR):
                    users[role] = User.objects.filter(role=role, is_active=True).order_by("date_joined").first()
                users["ADMIN"] = (User.objects.filter(role=Role.ADMIN, admin_level="SUPER", is_active=True).first()
                                  or User.objects.filter(role=Role.ADMIN, is_active=True).first())
                any_loan = Loan.objects.order_by("-created_at").first()
                for role, user in users.items():
                    if user is None:
                        self.stdout.write(f"  {role}: no user with this role yet (skipped)")
                        continue
                    own_loan = Loan.objects.filter(borrower=user).order_by("-created_at").first()
                    paths = list(ENDPOINTS["everyone"])
                    if role != "ADMIN":
                        paths += ENDPOINTS["customer"]
                    paths += ENDPOINTS[role]
                    client = APIClient()
                    client.force_authenticate(user)
                    failures = 0
                    for path in paths:
                        if "{loan}" in path and not own_loan or "{any_loan}" in path and not any_loan:
                            continue
                        path = path.replace("{loan}", str(own_loan.pk) if own_loan else "") \
                            .replace("{any_loan}", str(any_loan.pk) if any_loan else "")
                        collector.records.clear()
                        try:
                            with transaction.atomic():
                                res = client.get(f"/api/v1/{path}", HTTP_HOST="127.0.0.1")
                                transaction.set_rollback(True)
                            status = res.status_code
                        except Exception:  # noqa: BLE001
                            status, tb = 500, traceback.format_exc()
                        else:
                            tb = ""
                            for r in collector.records:
                                if r.exc_info:
                                    tb = "".join(traceback.format_exception(*r.exc_info))
                        if status >= 500:
                            ok = False
                            failures += 1
                            self.stdout.write(self.style.ERROR(f"  {role} {user.email}: GET /api/v1/{path} → {status}"))
                            if tb:
                                self.stdout.write("    " + tb.strip().replace("\n", "\n    "))
                    if not failures:
                        self.stdout.write(f"  {role} ({user.email}): {len(paths)} calls OK")
        finally:
            log.removeHandler(collector)
        return ok
