-- Native C5 unit 0018; reviewed source blob 9c68d98b816dbf522f83c6425dc0ec07244a80d1.
-- Source namespace/bootstrap is not executed; new native schema and Core context.
REVOKE ALL ON TABLE aioa_memory_patch.context_grants FROM PUBLIC;
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.context_grants OWNER TO __ROLE_PREFIX___security_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.request_contexts FROM PUBLIC;
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.request_contexts OWNER TO __ROLE_PREFIX___security_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.schema_migrations FROM PUBLIC;
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.schema_migrations OWNER TO __ROLE_PREFIX___security_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.schema_certificate FROM PUBLIC;
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.schema_certificate OWNER TO __ROLE_PREFIX___security_owner;
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.source_records OWNER TO __ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.source_records FROM PUBLIC;
-- C5_STATEMENT
GRANT SELECT ON TABLE aioa_memory_patch.source_records TO __ROLE_PREFIX___app,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion;
-- C5_STATEMENT
CREATE POLICY source_records_read ON aioa_memory_patch.source_records FOR SELECT TO __ROLE_PREFIX___app,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL));
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.ingestions OWNER TO __ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.ingestions FROM PUBLIC;
-- C5_STATEMENT
GRANT SELECT ON TABLE aioa_memory_patch.ingestions TO __ROLE_PREFIX___app,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion;
-- C5_STATEMENT
CREATE POLICY ingestions_read ON aioa_memory_patch.ingestions FOR SELECT TO __ROLE_PREFIX___app,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL));
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.operations OWNER TO __ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.operations FROM PUBLIC;
-- C5_STATEMENT
GRANT SELECT ON TABLE aioa_memory_patch.operations TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___reviewer,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___audit;
-- C5_STATEMENT
CREATE POLICY operations_read ON aioa_memory_patch.operations FOR SELECT TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___reviewer,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___audit USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL));
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.spaces OWNER TO __ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.spaces FROM PUBLIC;
-- C5_STATEMENT
GRANT SELECT ON TABLE aioa_memory_patch.spaces TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit;
-- C5_STATEMENT
CREATE POLICY spaces_read ON aioa_memory_patch.spaces FOR SELECT TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL));
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.patches OWNER TO __ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.patches FROM PUBLIC;
-- C5_STATEMENT
GRANT SELECT ON TABLE aioa_memory_patch.patches TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___reviewer;
-- C5_STATEMENT
CREATE POLICY patches_read ON aioa_memory_patch.patches FOR SELECT TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___reviewer USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL) AND aioa_memory_patch.hat_allows(payload->'candidate'->>'hat_id') AND (NOT aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['review']) OR EXISTS(SELECT 1 FROM aioa_memory_patch.reviews r WHERE r.tenant_id=patches.tenant_id AND r.owner_id=patches.owner_id AND r.space_id=patches.space_id AND r.slot_id=patches.slot_id AND r.payload->>'patch_id'=patches.record_id)));
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.sharing_proposals OWNER TO __ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.sharing_proposals FROM PUBLIC;
-- C5_STATEMENT
GRANT SELECT ON TABLE aioa_memory_patch.sharing_proposals TO __ROLE_PREFIX___app;
-- C5_STATEMENT
CREATE POLICY sharing_proposals_read ON aioa_memory_patch.sharing_proposals FOR SELECT TO __ROLE_PREFIX___app USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL));
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.challenges OWNER TO __ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.challenges FROM PUBLIC;
-- C5_STATEMENT
GRANT SELECT ON TABLE aioa_memory_patch.challenges TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit;
-- C5_STATEMENT
CREATE POLICY challenges_read ON aioa_memory_patch.challenges FOR SELECT TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL));
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.approvals OWNER TO __ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.approvals FROM PUBLIC;
-- C5_STATEMENT
GRANT SELECT ON TABLE aioa_memory_patch.approvals TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit;
-- C5_STATEMENT
CREATE POLICY approvals_read ON aioa_memory_patch.approvals FOR SELECT TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL));
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.receipts OWNER TO __ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.receipts FROM PUBLIC;
-- C5_STATEMENT
GRANT SELECT ON TABLE aioa_memory_patch.receipts TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit;
-- C5_STATEMENT
CREATE POLICY receipts_read ON aioa_memory_patch.receipts FOR SELECT TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL));
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.audit_events OWNER TO __ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.audit_events FROM PUBLIC;
-- C5_STATEMENT
GRANT SELECT ON TABLE aioa_memory_patch.audit_events TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___reviewer,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___audit;
-- C5_STATEMENT
CREATE POLICY audit_events_read ON aioa_memory_patch.audit_events FOR SELECT TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___reviewer,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___audit USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL));
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.outbox OWNER TO __ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.outbox FROM PUBLIC;
-- C5_STATEMENT
GRANT SELECT ON TABLE aioa_memory_patch.outbox TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___reviewer,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___audit;
-- C5_STATEMENT
CREATE POLICY outbox_read ON aioa_memory_patch.outbox FOR SELECT TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___reviewer,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___audit USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL));
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.reviews OWNER TO __ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.reviews FROM PUBLIC;
-- C5_STATEMENT
GRANT SELECT ON TABLE aioa_memory_patch.reviews TO __ROLE_PREFIX___app,__ROLE_PREFIX___reviewer;
-- C5_STATEMENT
CREATE POLICY reviews_read ON aioa_memory_patch.reviews FOR SELECT TO __ROLE_PREFIX___app,__ROLE_PREFIX___reviewer USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL));
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.source_lineage OWNER TO __ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.source_lineage FROM PUBLIC;
-- C5_STATEMENT
GRANT SELECT ON TABLE aioa_memory_patch.source_lineage TO __ROLE_PREFIX___app,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion;
-- C5_STATEMENT
CREATE POLICY source_lineage_read ON aioa_memory_patch.source_lineage FOR SELECT TO __ROLE_PREFIX___app,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL));
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.source_publications OWNER TO __ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.source_publications FROM PUBLIC;
-- C5_STATEMENT
GRANT SELECT ON TABLE aioa_memory_patch.source_publications TO __ROLE_PREFIX___app,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion;
-- C5_STATEMENT
CREATE POLICY source_publications_read ON aioa_memory_patch.source_publications FOR SELECT TO __ROLE_PREFIX___app,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL));
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.parsed_chunks OWNER TO __ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.parsed_chunks FROM PUBLIC;
-- C5_STATEMENT
GRANT SELECT ON TABLE aioa_memory_patch.parsed_chunks TO __ROLE_PREFIX___app,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion;
-- C5_STATEMENT
CREATE POLICY parsed_chunks_read ON aioa_memory_patch.parsed_chunks FOR SELECT TO __ROLE_PREFIX___app,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL));
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.source_hat_links OWNER TO __ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.source_hat_links FROM PUBLIC;
-- C5_STATEMENT
GRANT SELECT ON TABLE aioa_memory_patch.source_hat_links TO __ROLE_PREFIX___app,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion;
-- C5_STATEMENT
CREATE POLICY source_hat_links_read ON aioa_memory_patch.source_hat_links FOR SELECT TO __ROLE_PREFIX___app,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL) AND aioa_memory_patch.hat_allows(hat_id));
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.chunk_vectors OWNER TO __ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
REVOKE ALL ON TABLE aioa_memory_patch.chunk_vectors FROM PUBLIC;
-- C5_STATEMENT
GRANT SELECT ON TABLE aioa_memory_patch.chunk_vectors TO __ROLE_PREFIX___app,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion;
-- C5_STATEMENT
CREATE POLICY chunk_vectors_read ON aioa_memory_patch.chunk_vectors FOR SELECT TO __ROLE_PREFIX___app,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL) AND aioa_memory_patch.hat_allows(hat_id));
-- C5_STATEMENT
GRANT INSERT ON TABLE aioa_memory_patch.source_records TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication;
-- C5_STATEMENT
CREATE POLICY source_records_insert ON aioa_memory_patch.source_records FOR INSERT TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['evidence_capture']));
-- C5_STATEMENT
GRANT UPDATE ON TABLE aioa_memory_patch.source_records TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication;
-- C5_STATEMENT
CREATE POLICY source_records_update ON aioa_memory_patch.source_records FOR UPDATE TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['evidence_capture'])) WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['evidence_capture']));
-- C5_STATEMENT
GRANT INSERT ON TABLE aioa_memory_patch.ingestions TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication;
-- C5_STATEMENT
CREATE POLICY ingestions_insert ON aioa_memory_patch.ingestions FOR INSERT TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['evidence_capture']));
-- C5_STATEMENT
GRANT UPDATE ON TABLE aioa_memory_patch.ingestions TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication;
-- C5_STATEMENT
CREATE POLICY ingestions_update ON aioa_memory_patch.ingestions FOR UPDATE TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['evidence_capture'])) WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['evidence_capture']));
-- C5_STATEMENT
GRANT INSERT ON TABLE aioa_memory_patch.operations TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication,__ROLE_PREFIX___reviewer;
-- C5_STATEMENT
CREATE POLICY operations_insert ON aioa_memory_patch.operations FOR INSERT TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication,__ROLE_PREFIX___reviewer WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['candidate','propose','validate','owner_approval','manage','commit','activate','review','evidence_capture']));
-- C5_STATEMENT
GRANT INSERT ON TABLE aioa_memory_patch.spaces TO __ROLE_PREFIX___app;
-- C5_STATEMENT
CREATE POLICY spaces_insert ON aioa_memory_patch.spaces FOR INSERT TO __ROLE_PREFIX___app WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['manage']));
-- C5_STATEMENT
GRANT UPDATE ON TABLE aioa_memory_patch.spaces TO __ROLE_PREFIX___app;
-- C5_STATEMENT
CREATE POLICY spaces_update ON aioa_memory_patch.spaces FOR UPDATE TO __ROLE_PREFIX___app USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['manage'])) WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['manage']));
-- C5_STATEMENT
GRANT INSERT ON TABLE aioa_memory_patch.patches TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit;
-- C5_STATEMENT
CREATE POLICY patches_insert ON aioa_memory_patch.patches FOR INSERT TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['candidate','propose','validate','owner_approval','manage','commit','activate']) AND aioa_memory_patch.hat_allows(payload->'candidate'->>'hat_id') AND ((payload->>'state' IN ('COMMITTED','ACTIVE') AND aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['commit','activate'])) OR payload->>'state' NOT IN ('COMMITTED','ACTIVE')));
-- C5_STATEMENT
GRANT UPDATE ON TABLE aioa_memory_patch.patches TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit;
-- C5_STATEMENT
CREATE POLICY patches_update ON aioa_memory_patch.patches FOR UPDATE TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['candidate','propose','validate','owner_approval','manage','commit','activate'])) WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['candidate','propose','validate','owner_approval','manage','commit','activate']) AND aioa_memory_patch.hat_allows(payload->'candidate'->>'hat_id') AND ((payload->>'state' IN ('COMMITTED','ACTIVE') AND aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['commit','activate'])) OR payload->>'state' NOT IN ('COMMITTED','ACTIVE')));
-- C5_STATEMENT
GRANT INSERT ON TABLE aioa_memory_patch.sharing_proposals TO __ROLE_PREFIX___app;
-- C5_STATEMENT
CREATE POLICY sharing_proposals_insert ON aioa_memory_patch.sharing_proposals FOR INSERT TO __ROLE_PREFIX___app WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['manage']));
-- C5_STATEMENT
GRANT UPDATE ON TABLE aioa_memory_patch.sharing_proposals TO __ROLE_PREFIX___app;
-- C5_STATEMENT
CREATE POLICY sharing_proposals_update ON aioa_memory_patch.sharing_proposals FOR UPDATE TO __ROLE_PREFIX___app USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['manage'])) WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['manage']));
-- C5_STATEMENT
GRANT INSERT ON TABLE aioa_memory_patch.challenges TO __ROLE_PREFIX___app;
-- C5_STATEMENT
CREATE POLICY challenges_insert ON aioa_memory_patch.challenges FOR INSERT TO __ROLE_PREFIX___app WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['owner_approval']));
-- C5_STATEMENT
GRANT UPDATE ON TABLE aioa_memory_patch.challenges TO __ROLE_PREFIX___app;
-- C5_STATEMENT
CREATE POLICY challenges_update ON aioa_memory_patch.challenges FOR UPDATE TO __ROLE_PREFIX___app USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['owner_approval'])) WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['owner_approval']));
-- C5_STATEMENT
GRANT INSERT ON TABLE aioa_memory_patch.approvals TO __ROLE_PREFIX___app;
-- C5_STATEMENT
CREATE POLICY approvals_insert ON aioa_memory_patch.approvals FOR INSERT TO __ROLE_PREFIX___app WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['owner_approval']));
-- C5_STATEMENT
GRANT INSERT ON TABLE aioa_memory_patch.receipts TO __ROLE_PREFIX___commit;
-- C5_STATEMENT
CREATE POLICY receipts_insert ON aioa_memory_patch.receipts FOR INSERT TO __ROLE_PREFIX___commit WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['commit','activate']));
-- C5_STATEMENT
GRANT INSERT ON TABLE aioa_memory_patch.audit_events TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication,__ROLE_PREFIX___reviewer;
-- C5_STATEMENT
CREATE POLICY audit_events_insert ON aioa_memory_patch.audit_events FOR INSERT TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication,__ROLE_PREFIX___reviewer WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['candidate','propose','validate','owner_approval','manage','commit','activate','review','evidence_capture']));
-- C5_STATEMENT
GRANT INSERT ON TABLE aioa_memory_patch.outbox TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication,__ROLE_PREFIX___reviewer;
-- C5_STATEMENT
CREATE POLICY outbox_insert ON aioa_memory_patch.outbox FOR INSERT TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication,__ROLE_PREFIX___reviewer WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['candidate','propose','validate','owner_approval','manage','commit','activate','review','evidence_capture']));
-- C5_STATEMENT
GRANT UPDATE ON TABLE aioa_memory_patch.outbox TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication,__ROLE_PREFIX___reviewer;
-- C5_STATEMENT
CREATE POLICY outbox_update ON aioa_memory_patch.outbox FOR UPDATE TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication,__ROLE_PREFIX___reviewer USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['candidate','propose','validate','owner_approval','manage','commit','activate','review','evidence_capture'])) WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['candidate','propose','validate','owner_approval','manage','commit','activate','review','evidence_capture']));
-- C5_STATEMENT
GRANT INSERT ON TABLE aioa_memory_patch.reviews TO __ROLE_PREFIX___app,__ROLE_PREFIX___reviewer;
-- C5_STATEMENT
CREATE POLICY reviews_insert ON aioa_memory_patch.reviews FOR INSERT TO __ROLE_PREFIX___app,__ROLE_PREFIX___reviewer WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['manage','review']));
-- C5_STATEMENT
GRANT UPDATE ON TABLE aioa_memory_patch.reviews TO __ROLE_PREFIX___app,__ROLE_PREFIX___reviewer;
-- C5_STATEMENT
CREATE POLICY reviews_update ON aioa_memory_patch.reviews FOR UPDATE TO __ROLE_PREFIX___app,__ROLE_PREFIX___reviewer USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['manage','review'])) WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['manage','review']));
-- C5_STATEMENT
GRANT INSERT ON TABLE aioa_memory_patch.source_lineage TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication;
-- C5_STATEMENT
CREATE POLICY source_lineage_insert ON aioa_memory_patch.source_lineage FOR INSERT TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['evidence_capture']));
-- C5_STATEMENT
GRANT INSERT ON TABLE aioa_memory_patch.source_publications TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication;
-- C5_STATEMENT
CREATE POLICY source_publications_insert ON aioa_memory_patch.source_publications FOR INSERT TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['evidence_capture']) AND (source_status <> 'PUBLISHED' OR session_user='__ROLE_PREFIX___publication'));
-- C5_STATEMENT
GRANT UPDATE ON TABLE aioa_memory_patch.source_publications TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication;
-- C5_STATEMENT
CREATE POLICY source_publications_update ON aioa_memory_patch.source_publications FOR UPDATE TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['evidence_capture'])) WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['evidence_capture']) AND (source_status <> 'PUBLISHED' OR session_user='__ROLE_PREFIX___publication'));
-- C5_STATEMENT
GRANT INSERT ON TABLE aioa_memory_patch.parsed_chunks TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication;
-- C5_STATEMENT
CREATE POLICY parsed_chunks_insert ON aioa_memory_patch.parsed_chunks FOR INSERT TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['evidence_capture']));
-- C5_STATEMENT
GRANT INSERT ON TABLE aioa_memory_patch.source_hat_links TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication;
-- C5_STATEMENT
CREATE POLICY source_hat_links_insert ON aioa_memory_patch.source_hat_links FOR INSERT TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['evidence_capture']) AND aioa_memory_patch.hat_allows(hat_id));
-- C5_STATEMENT
GRANT INSERT ON TABLE aioa_memory_patch.chunk_vectors TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication;
-- C5_STATEMENT
CREATE POLICY chunk_vectors_insert ON aioa_memory_patch.chunk_vectors FOR INSERT TO __ROLE_PREFIX___ingestion,__ROLE_PREFIX___publication WITH CHECK(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,ARRAY['evidence_capture']) AND aioa_memory_patch.hat_allows(hat_id));
-- C5_STATEMENT
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
-- C5_STATEMENT
REVOKE ALL ON SCHEMA aioa_memory_patch FROM PUBLIC;
-- C5_STATEMENT
GRANT USAGE ON SCHEMA aioa_memory_patch TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___reviewer,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___audit,__ROLE_PREFIX___broker,__ROLE_PREFIX___schema_owner,__ROLE_PREFIX___security_owner;
-- C5_STATEMENT
GRANT SELECT ON TABLE aioa_memory_patch.schema_certificate,aioa_memory_patch.schema_migrations TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___reviewer,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___audit;
-- C5_STATEMENT
ALTER FUNCTION aioa_memory_patch.mint_context_ticket(STRING,STRING,INT8,STRING,STRING,STRING,STRING,STRING,STRING,STRING,STRING[],STRING[],TIMESTAMPTZ) OWNER TO __ROLE_PREFIX___security_owner;
-- C5_STATEMENT
REVOKE ALL ON FUNCTION aioa_memory_patch.mint_context_ticket(STRING,STRING,INT8,STRING,STRING,STRING,STRING,STRING,STRING,STRING,STRING[],STRING[],TIMESTAMPTZ) FROM PUBLIC;
-- C5_STATEMENT
GRANT EXECUTE ON FUNCTION aioa_memory_patch.mint_context_ticket(STRING,STRING,INT8,STRING,STRING,STRING,STRING,STRING,STRING,STRING,STRING[],STRING[],TIMESTAMPTZ) TO __ROLE_PREFIX___broker;
-- C5_STATEMENT
ALTER FUNCTION aioa_memory_patch.set_request_context(STRING) OWNER TO __ROLE_PREFIX___security_owner;
-- C5_STATEMENT
REVOKE ALL ON FUNCTION aioa_memory_patch.set_request_context(STRING) FROM PUBLIC;
-- C5_STATEMENT
GRANT EXECUTE ON FUNCTION aioa_memory_patch.set_request_context(STRING) TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___reviewer,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___audit;
-- C5_STATEMENT
ALTER FUNCTION aioa_memory_patch.clear_request_context() OWNER TO __ROLE_PREFIX___security_owner;
-- C5_STATEMENT
REVOKE ALL ON FUNCTION aioa_memory_patch.clear_request_context() FROM PUBLIC;
-- C5_STATEMENT
GRANT EXECUTE ON FUNCTION aioa_memory_patch.clear_request_context() TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___reviewer,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___audit;
-- C5_STATEMENT
ALTER FUNCTION aioa_memory_patch.scope_allows(STRING,STRING,STRING,STRING,STRING[]) OWNER TO __ROLE_PREFIX___security_owner;
-- C5_STATEMENT
REVOKE ALL ON FUNCTION aioa_memory_patch.scope_allows(STRING,STRING,STRING,STRING,STRING[]) FROM PUBLIC;
-- C5_STATEMENT
GRANT EXECUTE ON FUNCTION aioa_memory_patch.scope_allows(STRING,STRING,STRING,STRING,STRING[]) TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___reviewer,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___audit,__ROLE_PREFIX___schema_owner;
-- C5_STATEMENT
ALTER FUNCTION aioa_memory_patch.hat_allows(STRING) OWNER TO __ROLE_PREFIX___security_owner;
-- C5_STATEMENT
REVOKE ALL ON FUNCTION aioa_memory_patch.hat_allows(STRING) FROM PUBLIC;
-- C5_STATEMENT
GRANT EXECUTE ON FUNCTION aioa_memory_patch.hat_allows(STRING) TO __ROLE_PREFIX___app,__ROLE_PREFIX___commit,__ROLE_PREFIX___reviewer,__ROLE_PREFIX___publication,__ROLE_PREFIX___ingestion,__ROLE_PREFIX___audit,__ROLE_PREFIX___schema_owner;
