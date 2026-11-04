-- Seed data for composite_1_search_db [ours].
-- One unrelated row so the table is non-empty at the start of a run.
-- The task row (label 'birth_year_grace_hopper') must be absent initially;
-- the agent inserts it during the task.
INSERT INTO public.facts (label, value, source_url) VALUES
    ('sample_fact', 'placeholder_value', 'https://example.org/placeholder');
