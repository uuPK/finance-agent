create table if not exists agent.query_exports (
    export_id uuid primary key default gen_random_uuid(),
    query_id uuid not null references agent.query_runs(query_id) on delete cascade,
    user_id varchar(128) not null,
    export_format varchar(16) not null,
    export_status varchar(32) not null default 'running',
    row_count integer not null default 0,
    truncated boolean not null default false,
    elapsed_ms integer,
    error_type varchar(64),
    error_message text,
    created_at timestamptz not null default now(),
    finished_at timestamptz
);

create index if not exists idx_query_exports_query on agent.query_exports(query_id);
create index if not exists idx_query_exports_user on agent.query_exports(user_id);
create index if not exists idx_query_exports_created_at on agent.query_exports(created_at);
