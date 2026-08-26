-- Register the reusable average-total-asset metric without changing official business data.
-- Kept separate from 007 so existing local databases can apply it exactly once.

insert into metadata.metric_metadata
    (metric_code, metric_name, description, formula, default_aggregation, grain, source_tables, owner)
values
    (
        'average_total_asset',
        '客户平均总资产',
        '指定客户范围和快照内每位客户总资产的平均值；总资产为普通账户总资产与信用账户净资产之和。',
        'avg(coalesce(dws_cust_aset_d.nm_tot_aset, 0) + coalesce(dws_cust_aset_d.fc_pur_aset, 0))',
        'avg',
        'customer-date',
        '["dws_cust_aset_d"]'::jsonb,
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
        '平均总资产',
        '在用户指定的客户范围和资产快照中，先计算每位客户的总资产（普通账户总资产+信用账户净资产），再对客户取平均；它不是跨日期日均资产。',
        '["平均资产", "客户平均资产"]'::jsonb,
        '{"metric_code": "average_total_asset"}'::jsonb,
        false
    )
on conflict (term) do update set
    definition = excluded.definition,
    synonyms = excluded.synonyms,
    default_plan_fragment = excluded.default_plan_fragment,
    clarification_required = excluded.clarification_required,
    is_active = true,
    updated_at = now();
