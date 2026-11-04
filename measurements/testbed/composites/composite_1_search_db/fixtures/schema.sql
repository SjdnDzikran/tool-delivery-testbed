-- Initial schema for composite_1_search_db [ours].
-- Restore is idempotent: drops and recreates the task table.
BEGIN;

DROP TABLE IF EXISTS public.facts CASCADE;

CREATE TABLE public.facts (
    id         bigserial PRIMARY KEY,
    label      text NOT NULL,
    value      text NOT NULL,
    source_url text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

COMMIT;
