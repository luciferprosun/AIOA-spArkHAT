-- Native C5 unit 0006; reviewed source blob 12a5dcbbc50ae91fcf97d58dd820410a475ec20f.
-- Source namespace/bootstrap is not executed; new native schema and Core context.
CREATE TABLE aioa_memory_patch.source_publications (
 tenant_id STRING NOT NULL CHECK (length(tenant_id) BETWEEN 1 AND 256),
 owner_id STRING NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 256),
 space_id STRING NOT NULL CHECK (length(space_id) BETWEEN 1 AND 256),
 slot_id STRING NOT NULL CHECK (length(slot_id) BETWEEN 1 AND 256),
 source_id STRING NOT NULL,
 version_id STRING NOT NULL,
 artifact_digest STRING NOT NULL CHECK(artifact_digest ~ '^[0-9a-f]{64}$'),
 source_status STRING NOT NULL CHECK(source_status IN ('REVIEWED','PUBLISHED','WITHDRAWN','QUARANTINED')),
 reviewed_license BOOL NOT NULL,
 publication_proof_id STRING,
 effective_from TIMESTAMPTZ NOT NULL,
 effective_to TIMESTAMPTZ,
 observed_at TIMESTAMPTZ NOT NULL,
 conflicts_with STRING[],
 supersedes STRING,
 PRIMARY KEY(tenant_id,owner_id,space_id,slot_id,source_id,version_id),
 FOREIGN KEY(tenant_id,owner_id,space_id,slot_id,source_id,version_id) REFERENCES aioa_memory_patch.source_lineage(tenant_id,owner_id,space_id,slot_id,source_id,version_id),
 CHECK(effective_to IS NULL OR effective_from < effective_to),
 CHECK(source_status <> 'PUBLISHED' OR (reviewed_license AND publication_proof_id IS NOT NULL))
 
);
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.source_publications ENABLE ROW LEVEL SECURITY;
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.source_publications FORCE ROW LEVEL SECURITY;
