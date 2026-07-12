alter table agent.query_runs
    add column if not exists current_stage varchar(64),
    add column if not exists clarification_context jsonb not null default '{}'::jsonb,
    add column if not exists final_response jsonb;

alter table agent.query_steps
    add column if not exists attempt integer not null default 0;

create unique index if not exists uq_query_steps_run_stage_attempt
    on agent.query_steps(query_id, step_name, attempt);

create table if not exists agent.query_events (
    event_id bigint generated always as identity primary key,
    query_id uuid not null references agent.query_runs(query_id) on delete cascade,
    event_type varchar(64) not null,
    stage_name varchar(64) not null,
    step_status varchar(32) not null,
    attempt integer not null default 0,
    summary text not null default '',
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_query_events_run_event
    on agent.query_events(query_id, event_id);
