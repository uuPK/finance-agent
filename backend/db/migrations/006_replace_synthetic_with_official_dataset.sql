-- This migration intentionally removes the previous business mart and all
-- legacy metadata, runtime history, evaluations, and review records.
begin;

drop schema if exists mart cascade;
create schema mart;

create table mart.dim_product (
    prdt_id varchar(12),
    prdt_name varchar(100),
    sor_prdt_id varchar(12),
    market_id varchar(50),
    prdt_type_id varchar(12),
    prdt_type_name varchar(40),
    up_prdt_type_id varchar(12),
    up_prdt_type_name varchar(40)
);

create table mart.ads_cust_info_d (
    data_dt varchar(8),
    pty_id varchar(32),
    sor_pty_id varchar(32),
    cust_lvl_cd varchar(12),
    cust_status varchar(12),
    cust_type varchar(1),
    prov_name varchar(50),
    city_name varchar(50),
    birth_dt varchar(8),
    cust_age numeric(20, 0),
    name varchar(40),
    gender_cd varchar(12),
    edu_cd varchar(32),
    prof_cd varchar(100),
    org_id varchar(100)
);

create table mart.dws_cust_fin_d (
    data_dt varchar(8) not null,
    pty_id varchar(32) not null,
    sys_source varchar(20) not null,
    cash_in numeric(20, 4),
    cash_out numeric(20, 4),
    tran_in numeric(20, 4),
    tran_out numeric(20, 4),
    assign_in numeric(20, 4),
    assign_out numeric(20, 4)
);

create table mart.dwd_cust_hold_d (
    data_dt varchar(8) not null,
    pty_id varchar(32) not null,
    prdt_id varchar(12) not null,
    sys_source varchar(20) not null,
    ccy varchar(12) not null,
    hold_cnt numeric(20, 4),
    mkt_val numeric(20, 4)
);

create table mart.dwd_cust_tran_d (
    data_dt varchar(8) not null,
    pty_id varchar(32) not null,
    prdt_id varchar(12) not null,
    sys_source varchar(20) not null,
    ccy varchar(12) not null,
    buy_cnt integer,
    buy_mnt numeric(20, 4),
    buy_rake numeric(20, 4),
    buy_amt numeric(20, 4),
    buy_fare numeric(20, 4),
    sell_cnt integer,
    sell_mnt numeric(20, 4),
    sell_rake numeric(20, 4),
    sell_amt numeric(20, 4),
    sell_fare numeric(20, 4)
);

create table mart.dws_cust_aset_d (
    data_dt varchar(8) not null,
    pty_id varchar(32) not null,
    nm_tot_aset numeric(20, 4),
    nm_bal numeric(20, 4),
    fc_pur_aset numeric(20, 4),
    fc_bal numeric(20, 4)
);

create table mart.dim_public (
    code varchar(12) not null,
    code_type_id varchar(6) not null,
    describe varchar(50) not null
);

create table mart.dim_branch (
    data_dt varchar(8) not null,
    org_id varchar(50) not null,
    org_name varchar(100) not null,
    up_org_id varchar(50) not null,
    up_org_name varchar(100) not null
);

create index idx_official_customer_date on mart.ads_cust_info_d (pty_id, data_dt);
create index idx_official_customer_org on mart.ads_cust_info_d (org_id);
create index idx_official_asset_customer_date on mart.dws_cust_aset_d (pty_id, data_dt);
create index idx_official_fin_customer_date on mart.dws_cust_fin_d (pty_id, data_dt);
create index idx_official_hold_customer_date on mart.dwd_cust_hold_d (pty_id, data_dt);
create index idx_official_hold_product on mart.dwd_cust_hold_d (prdt_id);
create index idx_official_trade_customer_date on mart.dwd_cust_tran_d (pty_id, data_dt);
create index idx_official_trade_product on mart.dwd_cust_tran_d (prdt_id);
create index idx_official_product_id on mart.dim_product (prdt_id);
create index idx_official_public_code on mart.dim_public (code_type_id, code);
create index idx_official_branch_org on mart.dim_branch (org_id, data_dt);

truncate table metadata.question_examples, metadata.rule_constraints, metadata.join_relationships,
    metadata.business_terms, metadata.metric_metadata, metadata.column_metadata,
    metadata.table_metadata restart identity cascade;
truncate table evaluation.eval_cases, evaluation.eval_runs restart identity cascade;
truncate table agent.query_runs restart identity cascade;

alter table evaluation.eval_cases
    alter column dataset_version set default 'official-v1',
    alter column source_type set default 'official';

commit;
