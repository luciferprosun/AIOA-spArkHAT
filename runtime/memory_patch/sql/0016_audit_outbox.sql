-- Native C5 unit 0016; reviewed source blob 238ad24c2e5c53e1cceae9de39840b1e574fd972.
-- Source namespace/bootstrap is not executed; new native schema and Core context.
CREATE TABLE aioa_memory_patch.audit_events (
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
 CHECK ((record_json::JSONB ->> 'kind' = 'audit') IS TRUE),
 CHECK ((record_json::JSONB ->> 'record_id' = record_id) IS TRUE),
 CHECK (((record_json::JSONB ->> 'revision')::INT8 = revision) IS TRUE),
 CHECK ((record_json::JSONB -> 'scope' ->> 'tenant_id' = tenant_id) IS TRUE),
 CHECK ((record_json::JSONB -> 'scope' ->> 'owner_id' = owner_id) IS TRUE),
 CHECK ((record_json::JSONB -> 'scope' ->> 'space_id' = space_id) IS TRUE),
 CHECK ((record_json::JSONB -> 'scope' ->> 'slot_id' = slot_id) IS TRUE),
 CHECK (record_digest = encode(digest(record_json,'sha256'),'hex'))
 
);
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.audit_events ENABLE ROW LEVEL SECURITY;
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.audit_events FORCE ROW LEVEL SECURITY;
-- C5_STATEMENT
CREATE INDEX audit_events_state_idx ON aioa_memory_patch.audit_events (tenant_id,owner_id,space_id,slot_id,(payload->>'state'),record_id);
-- C5_STATEMENT
CREATE TABLE aioa_memory_patch.outbox (
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
 CHECK ((record_json::JSONB ->> 'kind' = 'outbox') IS TRUE),
 CHECK ((record_json::JSONB ->> 'record_id' = record_id) IS TRUE),
 CHECK (((record_json::JSONB ->> 'revision')::INT8 = revision) IS TRUE),
 CHECK ((record_json::JSONB -> 'scope' ->> 'tenant_id' = tenant_id) IS TRUE),
 CHECK ((record_json::JSONB -> 'scope' ->> 'owner_id' = owner_id) IS TRUE),
 CHECK ((record_json::JSONB -> 'scope' ->> 'space_id' = space_id) IS TRUE),
 CHECK ((record_json::JSONB -> 'scope' ->> 'slot_id' = slot_id) IS TRUE),
 CHECK (record_digest = encode(digest(record_json,'sha256'),'hex'))
 
);
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.outbox ENABLE ROW LEVEL SECURITY;
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.outbox FORCE ROW LEVEL SECURITY;
-- C5_STATEMENT
CREATE INDEX outbox_state_idx ON aioa_memory_patch.outbox (tenant_id,owner_id,space_id,slot_id,(payload->>'state'),record_id);
-- C5_STATEMENT
CREATE UNIQUE INDEX audit_sequence_unique ON aioa_memory_patch.audit_events (tenant_id,owner_id,space_id,slot_id,((payload->>'sequence_number')::INT8));
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.outbox ADD CONSTRAINT outbox_state_closed CHECK(payload->>'state' IN ('PENDING','PUBLISHED'));
