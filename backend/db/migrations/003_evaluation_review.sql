-- Evaluation, human-review, and dataset-versioning extension.

alter table evaluation.eval_cases
    add column if not exists dataset_version varchar(64) not null default 'synthetic-v1',
    add column if not exists source_type varchar(32) not null default 'synthetic',
    add column if not exists expected_status varchar(32) not null default 'completed',
    add column if not exists tags jsonb not null default '[]'::jsonb;

alter table evaluation.eval_runs
    add column if not exists dataset_version varchar(64),
    add column if not exists metadata_version varchar(64),
    add column if not exists prompt_version varchar(64),
    add column if not exists evaluation_mode varchar(32) not null default 'full',
    add column if not exists review_queued_cases integer not null default 0;

alter table evaluation.eval_results
    add column if not exists generated_response jsonb not null default '{}'::jsonb,
    add column if not exists auto_decision varchar(32) not null default 'pending',
    add column if not exists review_priority varchar(16),
    add column if not exists review_status varchar(32) not null default 'not_required',
    add column if not exists risk_reasons jsonb not null default '[]'::jsonb,
    add column if not exists critic_confidence numeric(5, 4);

create index if not exists idx_eval_results_review_status on evaluation.eval_results(review_status);

create table if not exists evaluation.review_batches (
    review_batch_id uuid primary key default gen_random_uuid(),
    batch_name varchar(128) not null,
    status varchar(32) not null default 'open',
    dataset_version varchar(64),
    created_by varchar(128) not null default 'system',
    exported_at timestamptz,
    imported_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists evaluation.review_items (
    review_item_id uuid primary key default gen_random_uuid(),
    review_batch_id uuid not null references evaluation.review_batches(review_batch_id) on delete cascade,
    eval_result_id uuid not null references evaluation.eval_results(eval_result_id) on delete cascade,
    status varchar(32) not null default 'pending',
    priority varchar(16) not null default 'normal',
    risk_reasons jsonb not null default '[]'::jsonb,
    assigned_to varchar(128),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint uq_review_item_per_batch unique (review_batch_id, eval_result_id)
);

create index if not exists idx_review_items_status on evaluation.review_items(status);
create index if not exists idx_review_items_result on evaluation.review_items(eval_result_id);

create table if not exists evaluation.review_decisions (
    review_decision_id uuid primary key default gen_random_uuid(),
    review_item_id uuid not null references evaluation.review_items(review_item_id) on delete cascade,
    reviewer_id varchar(128) not null,
    verdict varchar(32) not null,
    error_class varchar(64),
    severity varchar(16) not null default 'minor',
    corrected_query_plan jsonb not null default '{}'::jsonb,
    corrected_sql text,
    corrected_result jsonb not null default '{}'::jsonb,
    reviewer_note text,
    confidence numeric(5, 4),
    source_checksum varchar(128),
    created_at timestamptz not null default now()
);

create index if not exists idx_review_decisions_item on evaluation.review_decisions(review_item_id);
