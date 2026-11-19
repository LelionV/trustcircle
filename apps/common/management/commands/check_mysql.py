"""python manage.py check_mysql — confirms the MySQL server and settings suit the platform."""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Check the MySQL version, storage engine, character set and strict mode."

    def handle(self, *args, **options):
        if connection.vendor != "mysql":
            raise CommandError(f"The database is {connection.vendor}, not MySQL (check DB_ENGINE in .env).")
        problems = []
        with connection.cursor() as c:
            c.execute("SELECT VERSION(), @@SESSION.sql_mode, @@character_set_database, @@default_storage_engine")
            version, sql_mode, charset, engine = c.fetchone()
        self.stdout.write(f"Server:        {version}")
        self.stdout.write(f"Engine:        {engine}")
        self.stdout.write(f"Character set: {charset}")
        self.stdout.write(f"SQL mode:      {sql_mode}")
        is_maria = "mariadb" in version.lower()
        major_minor = tuple(int(x) for x in version.split("-")[0].split(".")[:2])
        if is_maria and major_minor < (10, 5):
            problems.append("MariaDB 10.5 or newer is required (XAMPP's MariaDB 10.4 is too old).")
        if not is_maria and major_minor < (8, 0):
            problems.append("MySQL 8.0 or newer is required.")
        if engine.upper() != "INNODB":
            problems.append("The default storage engine must be InnoDB (row locks and transactions).")
        if charset != "utf8mb4":
            problems.append("Create the database with CHARACTER SET utf8mb4 (see README).")
        if "STRICT_TRANS_TABLES" not in sql_mode:
            problems.append("Strict mode is off; check OPTIONS.init_command in settings.")
        if problems:
            for p in problems:
                self.stdout.write(self.style.ERROR(f"  ✗ {p}"))
            raise CommandError("MySQL isn't set up correctly yet.")
        self.stdout.write(self.style.SUCCESS("MySQL is ready."))
