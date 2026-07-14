-- Scope evaluation review batches to a run and accept business-user query disputes.

alter table agent.query_runs
    add column if not exists review_status varchar(32) not null default 'not_requested',
    add column if not exists review_reason text,
    add column if not exists review_requested_at timestamptz;

alter table evaluation.review_batches
    add column if not exists eval_run_id uuid references evaluation.eval_runs(eval_run_id) on delete set null,
    add column if not exists batch_type varchar(32) not null default 'legacy_backlog';

create index if not exists idx_review_batches_eval_run
    on evaluation.review_batches(eval_run_id);
create index if not exists idx_review_batches_type
    on evaluation.review_batches(batch_type);

alter table evaluation.review_items
    alter column eval_result_id drop not null,
    add column if not exists query_id uuid references agent.query_runs(query_id) on delete cascade,
    add column if not exists source_type varchar(32) not null default 'evaluation',
    add column if not exists user_reason text;

create index if not exists idx_review_items_query on evaluation.review_items(query_id);
create unique index if not exists uq_review_item_query_feedback
    on evaluation.review_items(query_id)
    where query_id is not null and source_type = 'user_feedback';

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'ck_review_item_single_source'
    ) then
        alter table evaluation.review_items
            add constraint ck_review_item_single_source check (
                (eval_result_id is not null and query_id is null)
                or (eval_result_id is null and query_id is not null)
            );
    end if;
end $$;
