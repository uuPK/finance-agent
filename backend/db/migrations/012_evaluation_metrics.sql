-- Phase 9: additive, idempotent per-case metrics. Existing scores stay intact.
alter table evaluation.eval_results
    add column if not exists metrics jsonb not null default '{}'::jsonb;
