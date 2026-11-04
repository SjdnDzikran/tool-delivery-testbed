-- Initial schema for composite_2_db_repo [ours].
-- Restore is idempotent: drops and recreates the task table.
BEGIN;

DROP TABLE IF EXISTS public.product_sales CASCADE;

CREATE TABLE public.product_sales (
    id      bigserial PRIMARY KEY,
    product text NOT NULL,
    region  text NOT NULL,
    units   int NOT NULL,
    revenue numeric(12,2) NOT NULL
);

COMMIT;
