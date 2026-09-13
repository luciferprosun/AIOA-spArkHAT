-- Native C5 unit 0009; reviewed source blob d82aae60c0db64f21cf4b520bc3a2a93e2d5eaf2.
-- Source namespace/bootstrap is not executed; new native schema and Core context.
CREATE TABLE aioa_memory_patch.source_hat_links (
 tenant_id STRING NOT NULL CHECK (length(tenant_id) BETWEEN 1 AND 256),
 owner_id STRING NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 256),
 space_id STRING NOT NULL CHECK (length(space_id) BETWEEN 1 AND 256),
 slot_id STRING NOT NULL CHECK (length(slot_id) BETWEEN 1 AND 256),
 source_id STRING NOT NULL,
 version_id STRING NOT NULL,
 hat_id STRING NOT NULL,
 core_manifest_digest STRING NOT NULL CHECK(core_manifest_digest ~ '^[0-9a-f]{64}$'),
 PRIMARY KEY(tenant_id,owner_id,space_id,slot_id,source_id,version_id,hat_id),
 FOREIGN KEY(tenant_id,owner_id,space_id,slot_id,source_id,version_id) REFERENCES aioa_memory_patch.source_publications(tenant_id,owner_id,space_id,slot_id,source_id,version_id)
 
);
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.source_hat_links ENABLE ROW LEVEL SECURITY;
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.source_hat_links FORCE ROW LEVEL SECURITY;
