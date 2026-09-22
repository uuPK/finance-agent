insert into metadata.metric_metadata
    (metric_code, metric_name, description, formula, default_aggregation, grain, source_tables, owner, is_active)
values
    (
        'cash_in_amount',
        '现金流入金额',
        '指定资金期间内现金流入金额，只汇总 cash_in，不扣减现金流出、转账或划拨。',
        'sum(coalesce(dws_cust_fin_d.cash_in, 0))',
        'sum',
        'customer-date-source',
        '["dws_cust_fin_d"]'::jsonb,
        'official_dataset',
        true
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
    (term, definition, synonyms, default_plan_fragment, clarification_required, is_active)
values
    (
        '现金流入',
        '现金流入金额只使用 dws_cust_fin_d.cash_in；不应扣减 cash_out，也不包含转账或划拨。',
        '["现金流入金额", "现金入账"]'::jsonb,
        '{}'::jsonb,
        false,
        true
    ),
    (
        '女性',
        '客户性别“女”在 dim_public 中对应 code_type_id=''500'' 且 code=''5000003''；查询客户表时使用 gender_cd=''5000003''。',
        '["女", "女性客户"]'::jsonb,
        '{}'::jsonb,
        false,
        true
    )
on conflict (term) do update set
    definition = excluded.definition,
    synonyms = excluded.synonyms,
    clarification_required = false,
    is_active = true,
    updated_at = now();
