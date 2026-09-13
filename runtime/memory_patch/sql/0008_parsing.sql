-- Native C5 unit 0008; reviewed source blob 42fa72b36773d25c0fc96625567e8ba6ec11e135.
-- Source namespace/bootstrap is not executed; new native schema and Core context.
CREATE TABLE aioa_memory_patch.parsed_chunks (
 tenant_id STRING NOT NULL CHECK (length(tenant_id) BETWEEN 1 AND 256),
 owner_id STRING NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 256),
 space_id STRING NOT NULL CHECK (length(space_id) BETWEEN 1 AND 256),
 slot_id STRING NOT NULL CHECK (length(slot_id) BETWEEN 1 AND 256),
 chunk_id STRING NOT NULL,
 source_id STRING NOT NULL,
 version_id STRING NOT NULL,
 artifact_digest STRING NOT NULL CHECK(artifact_digest ~ '^[0-9a-f]{64}$'),
 excerpt STRING NOT NULL CHECK(octet_length(excerpt) BETWEEN 1 AND 16384),
 excerpt_digest STRING NOT NULL CHECK(excerpt_digest = encode(digest(excerpt,'sha256'),'hex')),
 PRIMARY KEY(tenant_id,owner_id,space_id,slot_id,chunk_id),
 UNIQUE(tenant_id,owner_id,space_id,slot_id,chunk_id,source_id,version_id),
 FOREIGN KEY(tenant_id,owner_id,space_id,slot_id,source_id,version_id) REFERENCES aioa_memory_patch.source_publications(tenant_id,owner_id,space_id,slot_id,source_id,version_id)
 
);
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.parsed_chunks ENABLE ROW LEVEL SECURITY;
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.parsed_chunks FORCE ROW LEVEL SECURITY;
