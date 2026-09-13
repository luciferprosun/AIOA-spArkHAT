-- Native C5 unit 0001; reviewed source blob d67fb2a808060dc53ef6a92afb301f600d864f99.
-- Source namespace/bootstrap is not executed; new native schema and Core context.
CREATE SCHEMA aioa_memory_patch;
-- C5_STATEMENT
CREATE TABLE aioa_memory_patch.schema_migrations (
 ordinal INT8 PRIMARY KEY CHECK (ordinal BETWEEN 1 AND 18),
 name STRING UNIQUE NOT NULL,
 checksum STRING NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
 manifest_digest STRING NOT NULL CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
 applied_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp()
);
-- C5_STATEMENT
CREATE TABLE aioa_memory_patch.schema_certificate (
 singleton BOOL PRIMARY KEY CHECK(singleton),
 manifest_digest STRING NOT NULL,
 catalog_fingerprint STRING NOT NULL,
 state STRING NOT NULL CHECK(state IN ('MIGRATING','READY'))
);
