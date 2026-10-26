# Upgrade notes

## Before deploying (2 minutes)
1. Open the live app > Upload Data > "Database backup" > Create backup file > Download. Keep that .db file.
2. Make sure DATABASE_PATH on your host points at a persistent location (the database must NOT live inside the code folder that gets replaced).
3. Deploy. Do NOT upload or commit any .db file. (.gitignore now prevents that.)

## What happens on first start
- Schema: only missing columns/indexes are ADDED. Nothing is dropped or rewritten.
- Statuses: "Draft" option removed; "Cancelled" and "Completed" ensured. Tenders that were Draft become Planned.
  Each moved tender (id + reference) is listed in Edit Trail. A copy of the database is saved first in <db folder>/backups/ (*.pre-migration.*.bak).
  This runs once only.
- Every import also saves a backup first (newest 10 kept).

## To roll back
Stop the app, replace the .db file with the backup (*.bak is a normal SQLite file; rename to .db), deploy the old code.

## New files
tracker_utils.py (import/diff logic). Everything else is the same set of files. requirements.txt unchanged. Needs Streamlit >= 1.37 (you already use st.dialog).

## Changes in this version
- Upload Data no longer needs a password.
- Deleting a row asks for name AND email (stored in a new `deleted_email` column, shown in Deleted Records and the Edit Trail).
- KPI cards now include Cancelled and Completed.
