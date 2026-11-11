# Move from SQLite to PostgreSQL

Copy an existing Styx SQLite database into PostgreSQL with `app.tools.sqlite_to_pg`. The source file is opened read-only and never changed, so you can always go back.

Exit codes: `0` ok, `2` preflight or usage failure (target untouched), `3` verify mismatch (the copy is rolled back).

## Steps

1. **Stop the app.** No writer may touch the SQLite file during the copy.

2. **Back up the SQLite file.** The default `DATABASE_URL` is `sqlite+aiosqlite:///./data/styx-portal.db`, relative to the backend's working directory: `backend/data/styx-portal.db` in a dev checkout, `/app/data/styx-portal.db` on the `db-data` volume in Docker.

    ```bash
    cp backend/data/styx-portal.db backend/data/styx-portal.db.bak
    ```

3. **Stamp the source.** Start the new release once on SQLite, then stop it again. This migrates the source to the release's Alembic head. The tool refuses an unstamped or older source and never upgrades it.

4. **Prepare the target.** Point `DATABASE_URL` at a dedicated PostgreSQL database with no data you want to keep, start the new release once so it migrates the schema, then stop it. The target must be at the same Alembic head. This first start also seeds default rows (templates, service presets), so the target is not empty. Steps 5 and 7 therefore use `--replace`, which overwrites the target's data with the source's.

5. **Dry run.** Scans the source and writes nothing. Run the commands from `backend/` with the venv Python, or from `/app` inside the backend container; both resolve `data/styx-portal.db`. If your `DATABASE_URL` names another file, adjust `--source` to match.

    ```bash
    cd backend
    .venv/bin/python -m app.tools.sqlite_to_pg --source data/styx-portal.db --target "$DATABASE_URL" --replace --dry-run
    ```

6. **Read the orphan list.** Rows whose foreign key points at a missing parent are findings, and by default they abort the run (exit 2). Review each `finding:` line. If the rows are safe to lose, add `--drop-orphans`; skipped primary keys are printed as `skipped <table> <pk>`. Never add the flag without reading the list.

7. **Run the copy.** It runs in one transaction, resets sequences, verifies, and rolls back on a mismatch.

    ```bash
    .venv/bin/python -m app.tools.sqlite_to_pg --source data/styx-portal.db --target "$DATABASE_URL" --replace
    # add --drop-orphans only after step 6
    ```

8. **Verify again.** Compares per-table row counts and checksums over the full source, writes nothing. Step 7 already verified inside its transaction with skipped rows excluded; this is an extra check.

    ```bash
    .venv/bin/python -m app.tools.sqlite_to_pg --source data/styx-portal.db --target "$DATABASE_URL" --verify-only
    ```

    - **No orphans in step 6:** expect exit `0` and no `MISMATCH` line. Exit `3` is a real failure.
    - **Used `--drop-orphans` in step 7:** pass it again (without it, preflight aborts with exit `2` on the same findings). Expect exit `3` with `MISMATCH` only on the tables named in the `skipped` lines, where `rows_src - rows_dst` equals that table's skipped count. Any other mismatch is a real failure.

9. **Start the app** on PostgreSQL and check logins and instances.

## Why `--replace`

Starting the release on PostgreSQL (step 4) seeds default rows, and without `--replace` the tool aborts with `target ... is not empty ... use --replace`. `--replace` overwrites the target's data with the source's, so only use it on a database holding nothing you want to keep, such as the one prepared in step 4.

## Roll back

Point `DATABASE_URL` back at the SQLite file and restart. The source was never changed. Changes made on PostgreSQL after the cutover are not carried back.
