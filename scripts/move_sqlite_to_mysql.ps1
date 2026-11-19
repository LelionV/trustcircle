# Copy everything from backend\db.sqlite3 into the MySQL database set in .env.
# Run from the backend folder with the virtual environment active:
#     powershell -ExecutionPolicy Bypass -File scripts\move_sqlite_to_mysql.ps1
# The MySQL database must exist and be EMPTY (no tables yet). db.sqlite3 only gets its tables updated; no records change.
$ErrorActionPreference = "Stop"

Write-Host "1/5  Bringing db.sqlite3 up to date with the current code..."
$env:DB_ENGINE = "sqlite"
python manage.py migrate
if ($LASTEXITCODE -ne 0) { throw "migrate on SQLite failed" }

Write-Host "2/5  Exporting the data to sqlite-export.json..."
python -X utf8 manage.py dumpdata --exclude contenttypes --exclude auth.permission --exclude admin.logentry `
    --exclude sessions --exclude token_blacklist --indent 1 -o sqlite-export.json
if ($LASTEXITCODE -ne 0) { throw "dumpdata failed" }

Write-Host "3/5  Creating the tables in MySQL..."
Remove-Item Env:\DB_ENGINE
python manage.py check_mysql
if ($LASTEXITCODE -ne 0) { throw "MySQL isn't ready (see the messages above)" }
python manage.py migrate
if ($LASTEXITCODE -ne 0) { throw "migrate on MySQL failed" }

Write-Host "4/5  Loading the data into MySQL..."
python -X utf8 manage.py loaddata sqlite-export.json
if ($LASTEXITCODE -ne 0) { throw "loaddata failed: the MySQL database must be empty before step 3" }

Write-Host "5/5  Rebuilding the 'unique while...' flags and checking the books..."
python manage.py sync_unique_flags
python manage.py run_scheduled_jobs reconcile

Write-Host ""
Write-Host "Done. Keep db.sqlite3 and sqlite-export.json as a backup until you've checked the app."
