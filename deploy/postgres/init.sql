-- Runs once, on the first start of an empty data volume.
CREATE EXTENSION IF NOT EXISTS vector;
-- Self-hosted Langfuse keeps its metadata in its own database on this server.
CREATE DATABASE langfuse;
