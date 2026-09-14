-- Native C5 unit 0010; reviewed source blob 30e652dfe4a405e6d7c927c0e66c0818dec92a98.
-- Source namespace/bootstrap is not executed; new native schema and Core context.
CREATE TABLE aioa_memory_patch.chunk_vectors (
 tenant_id STRING NOT NULL CHECK (length(tenant_id) BETWEEN 1 AND 256),
 owner_id STRING NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 256),
 space_id STRING NOT NULL CHECK (length(space_id) BETWEEN 1 AND 256),
 slot_id STRING NOT NULL CHECK (length(slot_id) BETWEEN 1 AND 256),
 chunk_id STRING NOT NULL,
 source_id STRING NOT NULL,
 version_id STRING NOT NULL,
 hat_id STRING NOT NULL,
 embedding_model_id STRING NOT NULL CHECK(embedding_model_id='intfloat/multilingual-e5-small'),
 embedding_model_revision STRING NOT NULL CHECK(embedding_model_revision='fd1525a9fd15316a2d503bf26ab031a61d056e98'),
 embedding_model_digest STRING NOT NULL CHECK(embedding_model_digest='aa68fc625f243f0e9c5f97aa9a7d3b7963c7dfdd10ca645d0782f3d8e8c77070'),
 embedding_bytes_digest STRING NOT NULL CHECK(embedding_bytes_digest ~ '^[0-9a-f]{64}$'),
 embedding VECTOR(384) NOT NULL,
 PRIMARY KEY(tenant_id,owner_id,space_id,slot_id,chunk_id,embedding_model_digest),
 FOREIGN KEY(tenant_id,owner_id,space_id,slot_id,chunk_id,source_id,version_id) REFERENCES aioa_memory_patch.parsed_chunks(tenant_id,owner_id,space_id,slot_id,chunk_id,source_id,version_id),
 FOREIGN KEY(tenant_id,owner_id,space_id,slot_id,source_id,version_id,hat_id) REFERENCES aioa_memory_patch.source_hat_links(tenant_id,owner_id,space_id,slot_id,source_id,version_id,hat_id),
 CHECK(vector_dims(embedding)=384),
 CHECK(embedding::STRING !~ '(NaN|Infinity|Inf)')
 
);
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.chunk_vectors ENABLE ROW LEVEL SECURITY;
-- C5_STATEMENT
ALTER TABLE aioa_memory_patch.chunk_vectors FORCE ROW LEVEL SECURITY;
-- C5_STATEMENT
CREATE VECTOR INDEX scoped_vector_l2_idx ON aioa_memory_patch.chunk_vectors (tenant_id,owner_id,space_id,slot_id,hat_id,embedding_model_digest,embedding vector_l2_ops);
