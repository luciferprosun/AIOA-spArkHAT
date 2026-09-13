-- Native C5 unit 0004; reviewed source blob 72ec1f2470ba8f10170555047bfeb816b1764ca9.
-- Source namespace/bootstrap is not executed; new native schema and Core context.
CREATE TABLE aioa_memory_patch.context_grants (
 ticket_hash STRING PRIMARY KEY CHECK(ticket_hash ~ '^[0-9a-f]{64}$'),
 database_principal STRING NOT NULL, backend_pid INT8 NOT NULL,
 tenant_id STRING NOT NULL, owner_id STRING NOT NULL, space_id STRING NOT NULL, slot_id STRING NOT NULL,
 purpose STRING NOT NULL, actor STRING NOT NULL, core_session STRING NOT NULL,
 hat_ids STRING[] NOT NULL, model_ids STRING[] NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL, consumed BOOL NOT NULL DEFAULT false
);
-- C5_STATEMENT
CREATE TABLE aioa_memory_patch.request_contexts (
 database_principal STRING NOT NULL, backend_pid INT8 NOT NULL,
 transaction_started_at TIMESTAMPTZ NOT NULL,
 tenant_id STRING NOT NULL, owner_id STRING NOT NULL, space_id STRING NOT NULL, slot_id STRING NOT NULL,
 purpose STRING NOT NULL, actor STRING NOT NULL, core_session STRING NOT NULL,
 hat_ids STRING[] NOT NULL, model_ids STRING[] NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY(database_principal,backend_pid)
);
-- C5_STATEMENT
CREATE FUNCTION aioa_memory_patch.mint_context_ticket(
 p_hash STRING,p_user STRING,p_pid INT8,p_tenant STRING,p_owner STRING,p_space STRING,p_slot STRING,
 p_purpose STRING,p_actor STRING,p_session STRING,p_hats STRING[],p_models STRING[],p_expires TIMESTAMPTZ
) RETURNS BOOL LANGUAGE PLpgSQL SECURITY DEFINER AS $$
BEGIN
 IF session_user <> '__ROLE_PREFIX___broker' THEN RAISE EXCEPTION 'context broker required' USING ERRCODE='42501'; END IF;
 IF p_hash !~ '^[0-9a-f]{64}$' OR p_pid <= 0 OR p_expires <= statement_timestamp() OR
    length(p_tenant) NOT BETWEEN 1 AND 256 OR length(p_owner) NOT BETWEEN 1 AND 256 OR
    length(p_space) NOT BETWEEN 1 AND 256 OR length(p_slot) NOT BETWEEN 1 AND 256 OR
    length(p_session) NOT BETWEEN 1 AND 256 OR cardinality(p_hats) < 1 OR cardinality(p_models) < 1 THEN
  RAISE EXCEPTION 'invalid context grant' USING ERRCODE='42501'; END IF;
 IF NOT ((p_user='__ROLE_PREFIX___app' AND p_purpose IN ('read','candidate','propose','validate','owner_approval','manage')) OR
         (p_user='__ROLE_PREFIX___commit' AND p_purpose IN ('commit','activate')) OR
         (p_user='__ROLE_PREFIX___reviewer' AND p_purpose='review') OR
         (p_user IN ('__ROLE_PREFIX___publication','__ROLE_PREFIX___ingestion') AND p_purpose='evidence_capture') OR
         (p_user='__ROLE_PREFIX___audit' AND p_purpose='read')) THEN
  RAISE EXCEPTION 'purpose role denied' USING ERRCODE='42501'; END IF;
 IF (p_purpose='owner_approval' AND p_actor <> 'owner_human') OR
    (p_purpose IN ('commit','activate') AND p_actor <> 'commit_service') OR
    (p_purpose='review' AND p_actor <> 'human_reviewer') OR
    (p_actor='critic' AND p_purpose <> 'candidate') THEN
  RAISE EXCEPTION 'actor purpose denied' USING ERRCODE='42501'; END IF;
 INSERT INTO aioa_memory_patch.context_grants VALUES(p_hash,p_user,p_pid,p_tenant,p_owner,p_space,p_slot,p_purpose,p_actor,p_session,p_hats,p_models,least(p_expires,statement_timestamp()+INTERVAL '5 minutes'),false);
 RETURN true;
END $$;
-- C5_STATEMENT
CREATE FUNCTION aioa_memory_patch.set_request_context(p_ticket STRING) RETURNS BOOL
LANGUAGE PLpgSQL SECURITY DEFINER AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM aioa_memory_patch.context_grants
 WHERE ticket_hash=encode(digest(p_ticket,'sha256'),'hex') AND database_principal=session_user
   AND backend_pid=pg_catalog.pg_backend_pid() AND NOT consumed AND expires_at > statement_timestamp()) THEN
  RAISE EXCEPTION 'current Core ticket required' USING ERRCODE='42501'; END IF;
 UPSERT INTO aioa_memory_patch.request_contexts
 SELECT session_user,pg_catalog.pg_backend_pid(),pg_catalog.transaction_timestamp(),g.tenant_id,g.owner_id,g.space_id,g.slot_id,g.purpose,g.actor,g.core_session,g.hat_ids,g.model_ids,g.expires_at
 FROM aioa_memory_patch.context_grants g WHERE g.ticket_hash=encode(digest(p_ticket,'sha256'),'hex')
 AND g.database_principal=session_user AND g.backend_pid=pg_catalog.pg_backend_pid()
 AND NOT g.consumed AND g.expires_at>statement_timestamp();
 UPDATE aioa_memory_patch.context_grants SET consumed=true WHERE ticket_hash=encode(digest(p_ticket,'sha256'),'hex');
 RETURN true;
END $$;
-- C5_STATEMENT
CREATE FUNCTION aioa_memory_patch.clear_request_context() RETURNS BOOL
LANGUAGE PLpgSQL SECURITY DEFINER AS $$
BEGIN
 DELETE FROM aioa_memory_patch.request_contexts WHERE database_principal=session_user AND backend_pid=pg_catalog.pg_backend_pid();
 RETURN true;
END $$;
-- C5_STATEMENT
CREATE FUNCTION aioa_memory_patch.scope_allows(p_tenant STRING,p_owner STRING,p_space STRING,p_slot STRING,p_purposes STRING[]) RETURNS BOOL
LANGUAGE SQL STABLE SECURITY DEFINER AS $$
 SELECT EXISTS(SELECT 1 FROM aioa_memory_patch.request_contexts c WHERE
 c.database_principal=session_user AND c.backend_pid=pg_catalog.pg_backend_pid()
 AND c.transaction_started_at=pg_catalog.transaction_timestamp() AND c.expires_at>statement_timestamp()
 AND c.tenant_id=p_tenant AND c.owner_id=p_owner AND c.space_id=p_space AND c.slot_id=p_slot
 AND (p_purposes IS NULL OR c.purpose=ANY(p_purposes)))
$$;
-- C5_STATEMENT
CREATE FUNCTION aioa_memory_patch.hat_allows(p_hat STRING) RETURNS BOOL
LANGUAGE SQL STABLE SECURITY DEFINER AS $$
 SELECT EXISTS(SELECT 1 FROM aioa_memory_patch.request_contexts c WHERE
 c.database_principal=session_user AND c.backend_pid=pg_catalog.pg_backend_pid()
 AND c.transaction_started_at=pg_catalog.transaction_timestamp() AND c.expires_at>statement_timestamp()
 AND p_hat=ANY(c.hat_ids))
$$;
