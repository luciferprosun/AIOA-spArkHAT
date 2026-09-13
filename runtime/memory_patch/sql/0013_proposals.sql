-- Native C5 unit 0013; reviewed source blob 2da101c466713db4b4891ce1bfa6a1d9c5ce6e5c.
-- Source namespace/bootstrap is not executed; new native schema and Core context.
ALTER TABLE aioa_memory_patch.patches ADD CONSTRAINT patch_candidate_identity CHECK(
 (payload->>'candidate_digest' ~ '^[0-9a-f]{64}$' AND jsonb_typeof(payload->'candidate')='object') IS TRUE
);
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.patches ADD CONSTRAINT patch_proposal_binding CHECK(
 payload->>'state'='DETECTED' OR
 (jsonb_typeof(payload->'proposal')='object' AND payload->'proposal'->>'content_hash' ~ '^[0-9a-f]{64}$'
 AND payload->'proposal'->>'tenant_id'=tenant_id AND payload->'proposal'->>'owner_user_id'=owner_id
 AND payload->'proposal'->>'target_personal_memory_space_id'=space_id) IS TRUE
);
-- C5_STATEMENT
CREATE INDEX patch_candidate_dedup_idx ON aioa_memory_patch.patches (tenant_id,owner_id,space_id,slot_id,(record_json::JSONB->'payload'->>'candidate_digest'));
