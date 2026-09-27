-- Phase 10: evaluation-only ablation provenance and comparison guardrails.
alter table evaluation.eval_runs
    add column if not exists ablation_variant varchar(64),
    add column if not exists comparison_group varchar(128),
    add column if not exists comparison_manifest jsonb;

create index if not exists idx_eval_runs_comparison_group
    on evaluation.eval_runs(comparison_group)
    where comparison_group is not null;
