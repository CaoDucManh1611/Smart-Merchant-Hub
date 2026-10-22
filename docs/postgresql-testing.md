# PostgreSQL test suite

Backend tests use separate PostgreSQL databases derived from the configured application URLs: `*_test` databases are created when missing, and test-owned schemas are removed after the run. The configured PostgreSQL role needs `CREATEDB`, schema creation rights, and the `vector` extension. Runtime databases are never used as test targets.

Run from `backend` with `python -m pytest`. With Docker Compose, the test bootstrap changes the Compose hostname `db` to `127.0.0.1` for a host-side run; inside a container it keeps `db`. Set `SMART_MERCHANT_TEST_DATABASE_HOST` if PostgreSQL is published on another host. Set `RUN_POSTGRES_TESTS=0` only to run the legacy SQLite compatibility mode.

In-memory SQLAlchemy fixtures are mapped to PostgreSQL schemas isolated per engine. Tests that directly exercise SQLite file snapshots or SQLite parsing continue to use SQLite as their input format.
