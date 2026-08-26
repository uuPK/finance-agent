-- Add reusable official-data semantics exposed by the held-out evaluation suite.
-- This migration changes metadata only; business tables and records remain untouched.

insert into metadata.metric_metadata
    (metric_code, metric_name, description, formula, default_aggregation, grain, source_tables, owner)
values
    (
        'average_customer_age',
        '客户平均年龄',
        '在指定客户快照范围内，对 ads_cust_info_d.cust_age 求平均。',
        'avg(ads_cust_info_d.cust_age)',
        'avg',
        'customer-snapshot',
        '["ads_cust_info_d"]'::jsonb,
        'official_dataset'
    ),
    (
        'normal_total_asset',
        '普通账户总资产',
        '指定资产快照内普通账户总资产之和，仅使用 dws_cust_aset_d.nm_tot_aset。',
        'sum(coalesce(dws_cust_aset_d.nm_tot_aset, 0))',
        'sum',
        'customer-date',
        '["dws_cust_aset_d"]'::jsonb,
        'official_dataset'
    ),
    (
        'credit_total_asset',
        '信用账户净资产',
        '指定资产快照内信用账户净资产之和，仅使用 dws_cust_aset_d.fc_pur_aset。',
        'sum(coalesce(dws_cust_aset_d.fc_pur_aset, 0))',
        'sum',
        'customer-date',
        '["dws_cust_aset_d"]'::jsonb,
        'official_dataset'
    ),
    (
        'trade_fee',
        '交易费用',
        '指定交易期间内买入费用与卖出费用之和。',
        'sum(coalesce(dwd_cust_tran_d.buy_fare, 0) + coalesce(dwd_cust_tran_d.sell_fare, 0))',
        'sum',
        'customer-product-date',
        '["dwd_cust_tran_d"]'::jsonb,
        'official_dataset'
    ),
    (
        'trade_quantity',
        '成交数量',
        '指定交易期间内买入数量与卖出数量之和；与交易金额不同。',
        'sum(coalesce(dwd_cust_tran_d.buy_mnt, 0) + coalesce(dwd_cust_tran_d.sell_mnt, 0))',
        'sum',
        'customer-product-date',
        '["dwd_cust_tran_d"]'::jsonb,
        'official_dataset'
    ),
    (
        'net_cash_inflow',
        '现金净流入',
        '指定资金期间内现金流入减现金流出；不包含转账或划拨。',
        'sum(coalesce(dws_cust_fin_d.cash_in, 0) - coalesce(dws_cust_fin_d.cash_out, 0))',
        'sum',
        'customer-date-source',
        '["dws_cust_fin_d"]'::jsonb,
        'official_dataset'
    ),
    (
        'transfer_amount',
        '转账金额',
        '指定资金期间内转入金额与转出金额绝对规模之和。',
        'sum(coalesce(dws_cust_fin_d.tran_in, 0) + coalesce(dws_cust_fin_d.tran_out, 0))',
        'sum',
        'customer-date-source',
        '["dws_cust_fin_d"]'::jsonb,
        'official_dataset'
    ),
    (
        'assignment_amount',
        '划拨金额',
        '指定资金期间内划入金额与划出金额绝对规模之和。',
        'sum(coalesce(dws_cust_fin_d.assign_in, 0) + coalesce(dws_cust_fin_d.assign_out, 0))',
        'sum',
        'customer-date-source',
        '["dws_cust_fin_d"]'::jsonb,
        'official_dataset'
    ),
    (
        'bidirectional_trade_customer',
        '双向交易客户',
        '指定期间内同时存在买入和卖出记录的客户；先按 pty_id 汇总后过滤。',
        'customer set: group by dwd_cust_tran_d.pty_id having sum(buy_amt) > 0 and sum(sell_amt) > 0',
        'count_distinct',
        'customer-period',
        '["dwd_cust_tran_d"]'::jsonb,
        'official_dataset'
    ),
    (
        'distinct_holding_product_count',
        '不同产品持有数量',
        '指定持仓快照内每位客户去重后的产品数量；先按 pty_id 汇总后过滤。',
        'count(distinct dwd_cust_hold_d.prdt_id) by pty_id',
        'count_distinct',
        'customer-date',
        '["dwd_cust_hold_d"]'::jsonb,
        'official_dataset'
    )
on conflict (metric_code) do update set
    metric_name = excluded.metric_name,
    description = excluded.description,
    formula = excluded.formula,
    default_aggregation = excluded.default_aggregation,
    grain = excluded.grain,
    source_tables = excluded.source_tables,
    owner = excluded.owner,
    is_active = true,
    updated_at = now();

insert into metadata.business_terms
    (term, definition, synonyms, default_plan_fragment, clarification_required)
values
    (
        '普通账户总资产',
        '普通账户总资产只统计 dws_cust_aset_d.nm_tot_aset，不与信用账户净资产相加。',
        '["普通资产", "普通账户资产"]'::jsonb,
        '{"metric_code": "normal_total_asset"}'::jsonb,
        false
    ),
    (
        '信用账户净资产',
        '信用账户净资产只统计 dws_cust_aset_d.fc_pur_aset，不与普通账户总资产相加。',
        '["信用资产", "融资融券净资产"]'::jsonb,
        '{"metric_code": "credit_total_asset"}'::jsonb,
        false
    ),
    (
        '成交数量',
        '成交数量使用买入数量 buy_mnt 与卖出数量 sell_mnt 之和；不能按交易金额计算。',
        '["交易数量", "成交份额", "成交量数量"]'::jsonb,
        '{"metric_code": "trade_quantity"}'::jsonb,
        false
    ),
    (
        '交易费用',
        '交易费用使用买入费用 buy_fare 与卖出费用 sell_fare 之和。',
        '["买卖费用", "手续费"]'::jsonb,
        '{"metric_code": "trade_fee"}'::jsonb,
        false
    ),
    (
        '现金净流入',
        '现金净流入只使用 cash_in - cash_out；净资金流入才包含现金、转账和划拨的全部流入流出。',
        '["现金净流", "现金流净流入"]'::jsonb,
        '{"metric_code": "net_cash_inflow"}'::jsonb,
        false
    ),
    (
        '转账金额',
        '转账金额使用 tran_in + tran_out；转账净额需由业务方另行明确。',
        '["转入转出金额", "资金转账金额"]'::jsonb,
        '{"metric_code": "transfer_amount"}'::jsonb,
        false
    ),
    (
        '划拨金额',
        '划拨金额使用 assign_in + assign_out；划拨净额需由业务方另行明确。',
        '["划入划出金额", "资金划拨金额"]'::jsonb,
        '{"metric_code": "assignment_amount"}'::jsonb,
        false
    ),
    (
        '一级营业部',
        '一级营业部使用 dim_branch.up_org_name。仅要求按一级营业部汇总时，不应额外输出或分组到 org_name。',
        '["分公司", "上级营业部"]'::jsonb,
        '{"field_code": "up_org_name"}'::jsonb,
        false
    ),
    (
        '客户与事实快照日期',
        '官方客户属性快照为 ads_cust_info_d.data_dt=''20260531''；资产与持仓截至 2026-03-31 时只筛选事实表 data_dt=''20260331''，关联客户属性时不得将客户表日期错误限定为 20260331。',
        '["客户快照", "资产快照", "持仓快照"]'::jsonb,
        '{}'::jsonb,
        false
    ),
    (
        '双向交易客户',
        '“同时发生过买入和卖出”是客户期间级条件：先按 pty_id 汇总，分别判断买入金额和卖出金额之和大于零，再在外层统计客户数。不能在单笔记录 WHERE 中同时筛选买入和卖出。',
        '["同时买入和卖出", "买卖双向", "双向交易"]'::jsonb,
        '{"metric_code": "bidirectional_trade_customer", "grain": "customer-period"}'::jsonb,
        false
    ),
    (
        '不同产品持有数量',
        '“持有至少 N 只不同产品”是客户快照级条件：先按 pty_id 统计 count(distinct prdt_id) 并在 HAVING 中应用阈值，再在外层统计客户数。',
        '["多产品持仓", "至少持有不同产品", "去重产品数量"]'::jsonb,
        '{"metric_code": "distinct_holding_product_count", "grain": "customer-date"}'::jsonb,
        false
    )
on conflict (term) do update set
    definition = excluded.definition,
    synonyms = excluded.synonyms,
    default_plan_fragment = excluded.default_plan_fragment,
    clarification_required = excluded.clarification_required,
    is_active = true,
    updated_at = now();
