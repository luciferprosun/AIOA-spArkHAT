-- Native opt-in learning-v1 unit 0019; no automatic migration.
-- Source namespace/bootstrap is not executed; new native schema and Core context.
CREATE TABLE aioa_memory_patch.learning_records (
 tenant_id STRING NOT NULL CHECK (length(tenant_id) BETWEEN 1 AND 256),
 owner_id STRING NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 256),
 space_id STRING NOT NULL CHECK (length(space_id) BETWEEN 1 AND 256),
 slot_id STRING NOT NULL CHECK (length(slot_id) BETWEEN 1 AND 256),
 record_id STRING NOT NULL CHECK (length(record_id) BETWEEN 1 AND 256),
 revision INT8 NOT NULL CHECK (revision > 0),
 record_json STRING NOT NULL CHECK (octet_length(record_json) <= 4194304),
 payload JSONB AS (record_json::JSONB -> 'payload') STORED,
 record_digest STRING NOT NULL CHECK (record_digest ~ '^[0-9a-f]{64}$'),
 PRIMARY KEY (tenant_id,owner_id,space_id,slot_id,record_id),
 CHECK ((jsonb_typeof(record_json::JSONB) = 'object') IS TRUE),
 CHECK ((jsonb_typeof(record_json::JSONB -> 'payload') = 'object') IS TRUE),
 CHECK ((record_json::JSONB ->> 'kind' = 'learning') IS TRUE),
 CHECK ((record_json::JSONB ->> 'record_id' = record_id) IS TRUE),
 CHECK (((record_json::JSONB ->> 'revision')::INT8 = revision) IS TRUE),
 CHECK ((record_json::JSONB -> 'scope' ->> 'tenant_id' = tenant_id) IS TRUE),
 CHECK ((record_json::JSONB -> 'scope' ->> 'owner_id' = owner_id) IS TRUE),
 CHECK ((record_json::JSONB -> 'scope' ->> 'space_id' = space_id) IS TRUE),
 CHECK ((record_json::JSONB -> 'scope' ->> 'slot_id' = slot_id) IS TRUE),
 CHECK (record_digest = encode(digest(record_json,'sha256'),'hex'))
 
);
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.learning_records ENABLE ROW LEVEL SECURITY;
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.learning_records FORCE ROW LEVEL SECURITY;
-- C5_STATEMENT
CREATE INDEX learning_records_state_idx ON aioa_memory_patch.learning_records (tenant_id,owner_id,space_id,slot_id,(record_json::JSONB->'payload'->>'state'),record_id);
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.learning_records ADD CONSTRAINT learning_advisory_only CHECK ((payload->>'execution_authority'='false' AND payload->>'publication_authority'='false' AND payload->>'privacy_scope'='PRIVATE') IS TRUE);
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.learning_records OWNER TO __ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.learning_records FROM PUBLIC;
-- C5_STATEMENT
GRANT SELECT,INSERT,UPDATE ON TABLE aioa_memory_patch.learning_records TO __ROLE_PREFIX___app;
-- C5_STATEMENT
CREATE POLICY learning_records_read ON aioa_memory_patch.learning_records FOR SELECT TO __ROLE_PREFIX___app USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL) AND aioa_memory_patch.hat_allows(payload->>'domain_hat'));
-- C5_STATEMENT
CREATE POLICY learning_records_insert ON aioa_memory_patch.learning_records FOR INSERT TO __ROLE_PREFIX___app WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['manage']) AND aioa_memory_patch.hat_allows(payload->>'domain_hat'));
-- C5_STATEMENT
CREATE POLICY learning_records_update ON aioa_memory_patch.learning_records FOR UPDATE TO __ROLE_PREFIX___app USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['manage']) AND aioa_memory_patch.hat_allows(payload->>'domain_hat')) WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['manage']) AND aioa_memory_patch.hat_allows(payload->>'domain_hat'));
