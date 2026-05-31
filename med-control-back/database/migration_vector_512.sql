-- Migration: change document_embeddings.embedding from vector(768) to vector(512)
-- Reason: switched embedding model from nomic-embed-text (768) to voyage-3-lite (512)

DROP INDEX IF EXISTS idx_embeddings_vector;

DELETE FROM document_embeddings;

ALTER TABLE document_embeddings
  ALTER COLUMN embedding TYPE vector(512);

CREATE INDEX idx_embeddings_vector
  ON document_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
