-- Phase 5.0: preserve the legacy attempt for display, but never use its sum as
-- the stage identity. Old rows cannot be reliably separated into rounds, so
-- they are version 1 with unknown (NULL) coordinates and retain attempt.
-- Re-applying this migration does not change any already-migrated/new rows.

begin;

alter table agent.query_events
    add column if not exists clarification_round integer,
    add column if not exists stage_attempt integer,
    add column if not exists schema_version integer,
    add column if not exists span_id uuid,
    add column if not exists parent_span_id uuid,
    add column if not exists duration_ms integer;

alter table agent.query_events
    alter column clarification_round drop not null,
    alter column stage_attempt drop not null;

update agent.query_events
set schema_version = 1
where schema_version is null;

update agent.query_events
set clarification_round = null, stage_attempt = null
where schema_version = 1
  and (clarification_round is not null or stage_attempt is not null);

alter table agent.query_events
    alter column clarification_round set default 0,
    alter column stage_attempt set default 0,
    alter column schema_version set default 2,
    alter column schema_version set not null;

alter table agent.query_steps
    add column if not exists clarification_round integer,
    add column if not exists stage_attempt integer,
    add column if not exists schema_version integer,
    add column if not exists span_id uuid,
    add column if not exists parent_span_id uuid,
    add column if not exists duration_ms integer;

alter table agent.query_steps
    alter column clarification_round drop not null,
    alter column stage_attempt drop not null;

update agent.query_steps
set schema_version = 1
where schema_version is null;

update agent.query_steps
set clarification_round = null, stage_attempt = null
where schema_version = 1
  and (clarification_round is not null or stage_attempt is not null);

alter table agent.query_steps
    alter column clarification_round set default 0,
    alter column stage_attempt set default 0,
    alter column schema_version set default 2,
    alter column schema_version set not null;

create unique index if not exists uq_query_steps_run_round_stage_attempt
    on agent.query_steps(query_id, clarification_round, step_name, stage_attempt);
drop index if exists agent.uq_query_steps_run_stage_attempt;

commit;
