-- Native C5 unit 0002; reviewed source blob 7f2a39e25ae00dcdb63071362ecdf21c534658be.
-- Source namespace/bootstrap is not executed; new native schema and Core context.
CREATE TABLE aioa_memory_patch.source_lineage (
 tenant_id STRING NOT NULL CHECK (length(tenant_id) BETWEEN 1 AND 256),
 owner_id STRING NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 256),
 space_id STRING NOT NULL CHECK (length(space_id) BETWEEN 1 AND 256),
 slot_id STRING NOT NULL CHECK (length(slot_id) BETWEEN 1 AND 256),
 source_id STRING NOT NULL,
 version_id STRING NOT NULL,
 record_digest STRING NOT NULL CHECK(record_digest ~ '^[0-9a-f]{64}$'),
 metadata_json STRING NOT NULL,
 PRIMARY KEY(tenant_id,owner_id,space_id,slot_id,source_id,version_id)
 
);
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.source_lineage ENABLE ROW LEVEL SECURITY;
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.source_lineage FORCE ROW LEVEL SECURITY;
