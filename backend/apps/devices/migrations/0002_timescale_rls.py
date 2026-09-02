"""feature_values hypertable, compression, continuous aggregates and isolation (docs/03).

TimescaleDB refuses row-level security on a hypertable that uses compression
("columnstore cannot be used on table with row security"). Compression is essential for the
history volume, so isolation of feature_values (and the 1h/1d aggregates) is enforced with
`security_barrier` views carrying exactly the RLS predicate (tenant / operator / system) and
`WITH CHECK OPTION` for inserts; the runtime role can only reach the views, never the base
tables. Every other table with tenant_id keeps regular RLS.

Non-atomic: continuous aggregates cannot be created inside a transaction block.
"""

from django.conf import settings
from django.db import migrations

from apps.tenants.dbrole import ensure_app_role
from apps.tenants.rls import RLS_PREDICATE, rls_operations

APP = settings.DB_APP_USER

CREATE_FEATURE_VALUES = f"""
CREATE TABLE feature_values (
    device_id uuid NOT NULL,
    feature_name text NOT NULL,
    property_name text NOT NULL,
    ts_polled timestamptz NOT NULL,
    ts_device timestamptz NULL,
    value_num double precision NULL,
    value_bool boolean NULL,
    value_text text NULL,
    tenant_id uuid NOT NULL
);
SELECT create_hypertable('feature_values', 'ts_polled', chunk_time_interval => interval '7 days');
CREATE INDEX feature_values_series_ts ON feature_values
    (device_id, feature_name, property_name, ts_polled DESC);
CREATE INDEX feature_values_tenant_ts ON feature_values (tenant_id, ts_polled DESC);
ALTER TABLE feature_values SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'device_id, feature_name, property_name',
    timescaledb.compress_orderby = 'ts_polled DESC'
);
SELECT add_compression_policy('feature_values', interval '7 days');

CREATE VIEW feature_values_rls WITH (security_barrier = true) AS
    SELECT device_id, feature_name, property_name, ts_polled, ts_device,
           value_num, value_bool, value_text, tenant_id
    FROM feature_values
    WHERE {RLS_PREDICATE}
    WITH CHECK OPTION;
"""

DROP_FEATURE_VALUES = """
DROP VIEW IF EXISTS feature_values_rls;
DROP TABLE IF EXISTS feature_values CASCADE;
"""

# Continuous aggregates over numeric values (docs/03): 1 h refreshed every 15 min (4 h window),
# 1 d refreshed hourly (3 d window) — Timescale requires the window to span >= 2 buckets.
CREATE_AGG_1H = """
CREATE MATERIALIZED VIEW feature_values_1h
WITH (timescaledb.continuous) AS
SELECT tenant_id, device_id, feature_name, property_name,
       time_bucket(interval '1 hour', ts_polled) AS bucket,
       min(value_num) AS min, avg(value_num) AS avg, max(value_num) AS max,
       last(value_num, ts_polled) AS last, count(value_num) AS count
FROM feature_values
WHERE value_num IS NOT NULL
GROUP BY tenant_id, device_id, feature_name, property_name, bucket
WITH NO DATA;
SELECT add_continuous_aggregate_policy('feature_values_1h',
    start_offset => interval '4 hours', end_offset => interval '10 minutes',
    schedule_interval => interval '15 minutes');
"""

CREATE_AGG_1D = """
CREATE MATERIALIZED VIEW feature_values_1d
WITH (timescaledb.continuous) AS
SELECT tenant_id, device_id, feature_name, property_name,
       time_bucket(interval '1 day', ts_polled) AS bucket,
       min(value_num) AS min, avg(value_num) AS avg, max(value_num) AS max,
       last(value_num, ts_polled) AS last, count(value_num) AS count
FROM feature_values
WHERE value_num IS NOT NULL
GROUP BY tenant_id, device_id, feature_name, property_name, bucket
WITH NO DATA;
SELECT add_continuous_aggregate_policy('feature_values_1d',
    start_offset => interval '3 days', end_offset => interval '1 hour',
    schedule_interval => interval '1 hour');
"""

CREATE_AGG_VIEWS = f"""
CREATE VIEW feature_values_1h_rls WITH (security_barrier = true) AS
    SELECT * FROM feature_values_1h WHERE {RLS_PREDICATE};
CREATE VIEW feature_values_1d_rls WITH (security_barrier = true) AS
    SELECT * FROM feature_values_1d WHERE {RLS_PREDICATE};
"""

DROP_AGGS = """
DROP VIEW IF EXISTS feature_values_1d_rls;
DROP VIEW IF EXISTS feature_values_1h_rls;
DROP MATERIALIZED VIEW IF EXISTS feature_values_1d;
DROP MATERIALIZED VIEW IF EXISTS feature_values_1h;
"""

RLS_TABLES = {
    "devices": False,
    "feature_definitions": False,
    "feature_latest": False,
    "feature_json_history": False,
    "device_status_history": False,
    "discovered_devices": False,
}


def apply_app_role_grants(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Grants + the REVOKEs for view-isolated tables (also re-applied on every start)."""
    with schema_editor.connection.cursor() as cursor:
        ensure_app_role(cursor, schema_editor.connection.connection)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("devices", "0001_initial"),
        ("tenants", "0004_rls_user_sessions"),
    ]

    operations = [
        migrations.RunSQL(CREATE_FEATURE_VALUES, DROP_FEATURE_VALUES),
        migrations.RunSQL(CREATE_AGG_1H, DROP_AGGS),
        migrations.RunSQL(CREATE_AGG_1D, migrations.RunSQL.noop),
        migrations.RunSQL(CREATE_AGG_VIEWS, migrations.RunSQL.noop),
        *[
            op
            for table, nullable in RLS_TABLES.items()
            for op in rls_operations(table, tenant_nullable=nullable)
        ],
        migrations.RunPython(apply_app_role_grants, migrations.RunPython.noop),
    ]
