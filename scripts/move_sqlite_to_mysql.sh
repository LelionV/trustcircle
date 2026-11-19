#!/usr/bin/env bash
# Linux/macOS version of move_sqlite_to_mysql.ps1. Run from backend/ with the venv active.
set -euo pipefail
echo "1/5 Updating db.sqlite3";  DB_ENGINE=sqlite python manage.py migrate
echo "2/5 Exporting";            DB_ENGINE=sqlite python -X utf8 manage.py dumpdata --exclude contenttypes --exclude auth.permission \
                                   --exclude admin.logentry --exclude sessions --exclude token_blacklist --indent 1 -o sqlite-export.json
echo "3/5 Creating MySQL tables"; python manage.py check_mysql; python manage.py migrate
echo "4/5 Loading";              python -X utf8 manage.py loaddata sqlite-export.json
echo "5/5 Flags and books";      python manage.py sync_unique_flags; python manage.py run_scheduled_jobs reconcile
echo "Done. Keep db.sqlite3 and sqlite-export.json as a backup."
