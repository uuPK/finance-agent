create extension if not exists pgcrypto;

create schema if not exists mart;
create schema if not exists metadata;
create schema if not exists agent;
create schema if not exists evaluation;

-- Customer marketing domain tables.

create table if not exists mart.customer_info (
    customer_id uuid primary key default gen_random_uuid(),
    customer_no varchar(64) not null unique,
    customer_name_masked varchar(128),
    gender varchar(16),
    birth_date date,
    age_band varchar(32),
    customer_level varchar(32),
    risk_level varchar(32),
    open_date date,
    branch_code varchar(64),
    customer_status varchar(32) not null default 'active',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_customer_info_level on mart.customer_info(customer_level);
create index if not exists idx_customer_info_branch on mart.customer_info(branch_code);
create index if not exists idx_customer_info_status on mart.customer_info(customer_status);

create table if not exists mart.service_manager (
    manager_id uuid primary key default gen_random_uuid(),
    manager_no varchar(64) not null unique,
    manager_name_masked varchar(128),
    org_code varchar(64),
    branch_code varchar(64),
    manager_status varchar(32) not null default 'active',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_service_manager_branch on mart.service_manager(branch_code);
create index if not exists idx_service_manager_org on mart.service_manager(org_code);

create table if not exists mart.product_info (
    product_id uuid primary key default gen_random_uuid(),
    product_code varchar(64) not null unique,
    product_name varchar(256) not null,
    product_type varchar(64) not null,
    risk_level varchar(32),
    issuer varchar(128),
    product_status varchar(32) not null default 'active',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_product_info_type on mart.product_info(product_type);
create index if not exists idx_product_info_risk on mart.product_info(risk_level);

create table if not exists mart.public_dimension (
    dimension_id uuid primary key default gen_random_uuid(),
    dimension_type varchar(64) not null,
    dimension_code varchar(64) not null,
    dimension_name varchar(128) not null,
    parent_code varchar(64),
    sort_order integer not null default 0,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint uq_public_dimension unique (dimension_type, dimension_code)
);

create index if not exists idx_public_dimension_type on mart.public_dimension(dimension_type);

create table if not exists mart.service_relationship (
    relationship_id uuid primary key default gen_random_uuid(),
    customer_id uuid not null references mart.customer_info(customer_id),
    manager_id uuid not null references mart.service_manager(manager_id),
    relationship_type varchar(32) not null default 'primary',
    start_date date not null,
    end_date date,
    is_primary boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint ck_service_relationship_date check (end_date is null or end_date >= start_date)
);

create index if not exists idx_service_relationship_customer on mart.service_relationship(customer_id);
create index if not exists idx_service_relationship_manager on mart.service_relationship(manager_id);
create index if not exists idx_service_relationship_primary on mart.service_relationship(is_primary);

create table if not exists mart.customer_asset_daily (
    asset_snapshot_id uuid primary key default gen_random_uuid(),
    customer_id uuid not null references mart.customer_info(customer_id),
    as_of_date date not null,
    total_asset numeric(20, 4) not null default 0,
    cash_asset numeric(20, 4) not null default 0,
    security_market_value numeric(20, 4) not null default 0,
    fund_market_value numeric(20, 4) not null default 0,
    product_market_value numeric(20, 4) not null default 0,
    net_asset numeric(20, 4) not null default 0,
    asset_level varchar(32),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint uq_customer_asset_daily unique (customer_id, as_of_date)
);

create index if not exists idx_customer_asset_daily_date on mart.customer_asset_daily(as_of_date);
create index if not exists idx_customer_asset_daily_total on mart.customer_asset_daily(total_asset);

create table if not exists mart.customer_trade (
    trade_id uuid primary key default gen_random_uuid(),
    customer_id uuid not null references mart.customer_info(customer_id),
    product_id uuid references mart.product_info(product_id),
    trade_date date not null,
    trade_time time,
    trade_type varchar(32) not null,
    market varchar(32),
    security_code varchar(64),
    trade_amount numeric(20, 4) not null default 0,
    trade_quantity numeric(20, 4) not null default 0,
    fee_amount numeric(20, 4) not null default 0,
    realized_profit_loss numeric(20, 4),
    channel varchar(64),
    created_at timestamptz not null default now()
);

create index if not exists idx_customer_trade_customer_date on mart.customer_trade(customer_id, trade_date);
create index if not exists idx_customer_trade_product on mart.customer_trade(product_id);
create index if not exists idx_customer_trade_type on mart.customer_trade(trade_type);

create table if not exists mart.customer_position_daily (
    position_snapshot_id uuid primary key default gen_random_uuid(),
    customer_id uuid not null references mart.customer_info(customer_id),
    product_id uuid not null references mart.product_info(product_id),
    as_of_date date not null,
    position_quantity numeric(20, 4) not null default 0,
    market_value numeric(20, 4) not null default 0,
    cost_amount numeric(20, 4),
    unrealized_profit_loss numeric(20, 4),
    holding_days integer,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint uq_customer_position_daily unique (customer_id, product_id, as_of_date)
);

create index if not exists idx_customer_position_customer_date on mart.customer_position_daily(customer_id, as_of_date);
create index if not exists idx_customer_position_product_date on mart.customer_position_daily(product_id, as_of_date);

create table if not exists mart.customer_asset_flow (
    flow_id uuid primary key default gen_random_uuid(),
    customer_id uuid not null references mart.customer_info(customer_id),
    product_id uuid references mart.product_info(product_id),
    occur_date date not null,
    flow_type varchar(32) not null,
    amount numeric(20, 4) not null,
    channel varchar(64),
    remark varchar(256),
    created_at timestamptz not null default now(),
    constraint ck_customer_asset_flow_type check (flow_type in ('inflow', 'outflow', 'transfer_in', 'transfer_out'))
);

create index if not exists idx_customer_asset_flow_customer_date on mart.customer_asset_flow(customer_id, occur_date);
create index if not exists idx_customer_asset_flow_type on mart.customer_asset_flow(flow_type);

create table if not exists mart.marketing_campaign (
    campaign_id uuid primary key default gen_random_uuid(),
    campaign_code varchar(64) not null unique,
    campaign_name varchar(256) not null,
    campaign_type varchar(64),
    target_product_id uuid references mart.product_info(product_id),
    start_date date,
    end_date date,
    campaign_status varchar(32) not null default 'draft',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint ck_marketing_campaign_date check (end_date is null or start_date is null or end_date >= start_date)
);

create table if not exists mart.marketing_touch (
    touch_id uuid primary key default gen_random_uuid(),
    campaign_id uuid not null references mart.marketing_campaign(campaign_id),
    customer_id uuid not null references mart.customer_info(customer_id),
    manager_id uuid references mart.service_manager(manager_id),
    touch_time timestamptz,
    touch_channel varchar(64),
    touch_status varchar(32) not null default 'planned',
    response_status varchar(32),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_marketing_touch_campaign on mart.marketing_touch(campaign_id);
create index if not exists idx_marketing_touch_customer on mart.marketing_touch(customer_id);
create index if not exists idx_marketing_touch_manager on mart.marketing_touch(manager_id);

-- AI-friendly metadata tables.

create table if not exists metadata.table_metadata (
    id bigserial primary key,
    schema_name varchar(64) not null default 'mart',
    table_name varchar(128) not null,
    display_name varchar(128) not null,
    domain varchar(64) not null,
    description text not null default '',
    grain varchar(128),
    refresh_frequency varchar(64),
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint uq_table_metadata unique (schema_name, table_name)
);

create index if not exists idx_table_metadata_domain on metadata.table_metadata(domain);

create table if not exists metadata.column_metadata (
    id bigserial primary key,
    schema_name varchar(64) not null default 'mart',
    table_name varchar(128) not null,
    column_name varchar(128) not null,
    display_name varchar(128) not null,
    data_type varchar(64) not null,
    description text not null default '',
    semantic_type varchar(64),
    is_dimension boolean not null default false,
    is_metric_source boolean not null default false,
    is_sensitive boolean not null default false,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint uq_column_metadata unique (schema_name, table_name, column_name)
);

create index if not exists idx_column_metadata_table on metadata.column_metadata(schema_name, table_name);
create index if not exists idx_column_metadata_display on metadata.column_metadata(display_name);
create index if not exists idx_column_metadata_sensitive on metadata.column_metadata(is_sensitive);

create table if not exists metadata.metric_metadata (
    id bigserial primary key,
    metric_code varchar(64) not null unique,
    metric_name varchar(128) not null,
    description text not null default '',
    formula text not null,
    default_aggregation varchar(64) not null default '',
    grain varchar(128),
    source_schema varchar(64) not null default 'mart',
    source_tables jsonb not null default '[]'::jsonb,
    required_filters jsonb not null default '[]'::jsonb,
    owner varchar(64) not null default '',
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_metric_metadata_name on metadata.metric_metadata(metric_name);
create index if not exists idx_metric_metadata_source_tables on metadata.metric_metadata using gin(source_tables);

create table if not exists metadata.business_terms (
    id bigserial primary key,
    term varchar(128) not null unique,
    definition text not null,
    synonyms jsonb not null default '[]'::jsonb,
    default_plan_fragment jsonb not null default '{}'::jsonb,
    clarification_required boolean not null default false,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_business_terms_synonyms on metadata.business_terms using gin(synonyms);

create table if not exists metadata.join_relationships (
    id bigserial primary key,
    left_schema varchar(64) not null default 'mart',
    left_table varchar(128) not null,
    left_column varchar(128) not null,
    right_schema varchar(64) not null default 'mart',
    right_table varchar(128) not null,
    right_column varchar(128) not null,
    relationship_type varchar(32) not null default 'many_to_one',
    description text not null default '',
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_join_relationships_left on metadata.join_relationships(left_schema, left_table);
create index if not exists idx_join_relationships_right on metadata.join_relationships(right_schema, right_table);

create table if not exists metadata.question_examples (
    id bigserial primary key,
    question text not null,
    difficulty varchar(32) not null,
    scenario varchar(64) not null default 'customer_marketing',
    expected_query_plan jsonb not null default '{}'::jsonb,
    expected_sql text not null default '',
    expected_result jsonb not null default '{}'::jsonb,
    tags jsonb not null default '[]'::jsonb,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_question_examples_difficulty on metadata.question_examples(difficulty);
create index if not exists idx_question_examples_tags on metadata.question_examples using gin(tags);

create table if not exists metadata.rule_constraints (
    id bigserial primary key,
    rule_code varchar(64) not null unique,
    rule_name varchar(128) not null,
    rule_type varchar(64) not null,
    config jsonb not null default '{}'::jsonb,
    severity varchar(16) not null default 'error',
    description text not null default '',
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_rule_constraints_type on metadata.rule_constraints(rule_type);

-- Agent runtime and audit tables.

create table if not exists agent.query_runs (
    query_id uuid primary key default gen_random_uuid(),
    user_id varchar(128),
    question text not null,
    status varchar(32) not null default 'received',
    final_answer text,
    final_sql text,
    retry_count integer not null default 0,
    elapsed_ms integer,
    error_type varchar(64),
    error_message text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_query_runs_status on agent.query_runs(status);
create index if not exists idx_query_runs_created_at on agent.query_runs(created_at);

create table if not exists agent.query_steps (
    step_id uuid primary key default gen_random_uuid(),
    query_id uuid not null references agent.query_runs(query_id) on delete cascade,
    step_name varchar(64) not null,
    step_status varchar(32) not null,
    summary text not null default '',
    payload jsonb not null default '{}'::jsonb,
    started_at timestamptz not null default now(),
    finished_at timestamptz
);

create index if not exists idx_query_steps_query on agent.query_steps(query_id);
create index if not exists idx_query_steps_name on agent.query_steps(step_name);

create table if not exists agent.guardrail_events (
    event_id uuid primary key default gen_random_uuid(),
    query_id uuid references agent.query_runs(query_id) on delete cascade,
    check_name varchar(128) not null,
    passed boolean not null,
    severity varchar(16) not null default 'info',
    message text not null,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_guardrail_events_query on agent.guardrail_events(query_id);
create index if not exists idx_guardrail_events_passed on agent.guardrail_events(passed);

-- Evaluation tables.

create table if not exists evaluation.eval_cases (
    case_id uuid primary key default gen_random_uuid(),
    case_code varchar(64) not null unique,
    question text not null,
    difficulty varchar(32) not null,
    scenario varchar(64) not null default 'customer_marketing',
    expected_query_plan jsonb not null default '{}'::jsonb,
    expected_sql text,
    expected_result jsonb not null default '{}'::jsonb,
    scoring_config jsonb not null default '{}'::jsonb,
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_eval_cases_difficulty on evaluation.eval_cases(difficulty);
create index if not exists idx_eval_cases_active on evaluation.eval_cases(is_active);

create table if not exists evaluation.eval_runs (
    eval_run_id uuid primary key default gen_random_uuid(),
    run_name varchar(128) not null,
    model_name varchar(128),
    git_commit varchar(64),
    status varchar(32) not null default 'running',
    total_cases integer not null default 0,
    passed_cases integer not null default 0,
    average_elapsed_ms numeric(12, 2),
    started_at timestamptz not null default now(),
    finished_at timestamptz
);

create index if not exists idx_eval_runs_status on evaluation.eval_runs(status);
create index if not exists idx_eval_runs_started_at on evaluation.eval_runs(started_at);

create table if not exists evaluation.eval_results (
    eval_result_id uuid primary key default gen_random_uuid(),
    eval_run_id uuid not null references evaluation.eval_runs(eval_run_id) on delete cascade,
    case_id uuid not null references evaluation.eval_cases(case_id),
    query_id uuid references agent.query_runs(query_id),
    passed boolean not null default false,
    executable boolean not null default false,
    result_correct boolean,
    plan_score numeric(5, 2),
    sql_score numeric(5, 2),
    result_score numeric(5, 2),
    elapsed_ms integer,
    failure_type varchar(64),
    failure_reason text,
    generated_sql text,
    generated_query_plan jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint uq_eval_result unique (eval_run_id, case_id)
);

create index if not exists idx_eval_results_run on evaluation.eval_results(eval_run_id);
create index if not exists idx_eval_results_case on evaluation.eval_results(case_id);
create index if not exists idx_eval_results_passed on evaluation.eval_results(passed);

-- Useful views for metadata and guardrail introspection.

create or replace view metadata.active_tables as
select
    schema_name,
    table_name,
    display_name,
    domain,
    grain,
    description
from metadata.table_metadata
where is_active = true;

create or replace view metadata.sensitive_columns as
select
    schema_name,
    table_name,
    column_name,
    display_name,
    description
from metadata.column_metadata
where is_active = true
  and is_sensitive = true;
