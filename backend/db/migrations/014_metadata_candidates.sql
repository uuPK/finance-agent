-- Phase 13: review corrections remain isolated until approval and regression.
create table if not exists metadata.metadata_candidates (
    candidate_id uuid primary key default gen_random_uuid(),
    metadata_version uuid not null default gen_random_uuid(),
    kind varchar(32) not null,
    action varchar(16) not null,
    entity_key text not null,
    payload jsonb not null,
    source_review_item_id uuid not null references evaluation.review_items(review_item_id),
    source_query_id uuid references agent.query_runs(query_id),
    reviewer_id varchar(128) not null,
    supersedes uuid references metadata.metadata_candidates(candidate_id),
    status varchar(24) not null default 'candidate',
    approved_by varchar(128),
    approved_at timestamptz,
    baseline_eval_run_id uuid references evaluation.eval_runs(eval_run_id),
    regression_eval_run_id uuid references evaluation.eval_runs(eval_run_id),
    regression_report jsonb,
    rollback_payload jsonb,
    promoted_entity_id text,
    created_at timestamptz not null default now(),
    promoted_at timestamptz,
    rolled_back_at timestamptz,
    constraint ck_metadata_candidate_status check (
        status in ('candidate', 'approved', 'evaluating', 'ready', 'rejected',
                   'promoted', 'rolled_back')
    ),
    constraint ck_metadata_candidate_action check (action in ('create', 'update'))
);

create index if not exists idx_metadata_candidates_status
    on metadata.metadata_candidates(status, created_at desc);
create index if not exists idx_metadata_candidates_entity
    on metadata.metadata_candidates(kind, entity_key, promoted_at desc);
create unique index if not exists uq_metadata_candidate_review_change
    on metadata.metadata_candidates(source_review_item_id, kind, entity_key);

alter table evaluation.eval_runs
    add column if not exists metadata_candidate_id uuid
        references metadata.metadata_candidates(candidate_id);
