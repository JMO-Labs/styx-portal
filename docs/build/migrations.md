# Database migrations

The schema is managed by Alembic (`backend/alembic/`). The backend runs
`upgrade head` at startup (`app/db_migrate.py`), on SQLite and on Postgres.
`_run_migrations` in `db_migrate.py` is frozen legacy code for pre-Alembic
SQLite databases: never add to it.

## Add a migration

1. Change the model in `app/models.py`. Datetime fields use
   `Field(sa_type=UTCDateTime)` (a test fails otherwise).
2. Generate a revision against a database at head (an empty SQLite file works):

   ```bash
   cd backend
   rm -f /tmp/styx-mig.db
   DATABASE_URL=sqlite+aiosqlite:////tmp/styx-mig.db .venv/bin/alembic upgrade head
   DATABASE_URL=sqlite+aiosqlite:////tmp/styx-mig.db \
     .venv/bin/alembic revision --autogenerate -m "add foo to users"
   ```

3. Review the file in `alembic/versions/` by hand:
   * On SQLite, `env.py` sets `render_as_batch=True`, so column changes come out as
     `with op.batch_alter_table(...)`. Keep that: SQLite cannot `ALTER`/`DROP`
     columns in place.
   * A new non-null column on a table with rows needs a `server_default`.
   * Constraints get stable names from the metadata naming convention
     (`ix_`, `uq_`, `ck_`, `fk_`, `pk_`). Do not hand-name them differently.
   * Revisions must not import `app.*`; `UTCDateTime` renders as `sa.DateTime()`.
4. Run the suite on both backends (see [Testing](testing.md#backend-pytest)).
   `test_alembic_baseline.py` checks there is one head and that `upgrade head`
   matches the models with no diff.
