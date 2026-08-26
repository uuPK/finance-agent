-- Add the official contest semantics that are required by the complex Q&A examples.
-- This is intentionally metadata-only: it does not alter or synthesize any business data.

insert into metadata.metric_metadata
    (metric_code, metric_name, description, formula, default_aggregation, grain, source_tables, owner)
values
    (
        'daily_average_asset',
        '日均资产',
        '指定期间内客户每日总资产之和除以该期间自然日天数；官方 2026 年 Q1 口径固定除以 90。',
        'sum(coalesce(dws_cust_aset_d.nm_tot_aset, 0) + coalesce(dws_cust_aset_d.fc_pur_aset, 0)) / (to_date(end_date, ''YYYYMMDD'') - to_date(start_date, ''YYYYMMDD'') + 1)',
        'custom',
        'customer-period',
        '["dws_cust_aset_d"]'::jsonb,
        'official_dataset'
    ),
    (
        'profit_loss',
        '资产盈亏',
        '官方 Q1 参考口径：期末普通资产+期末信用资产-期初普通资产+期初信用资产+期间资产流出-期间资产流入；输出时保留期初资产、期末资产、流入、流出和盈亏。',
        'end_nm_tot_aset + end_fc_pur_aset - begin_nm_tot_aset + begin_fc_pur_aset + period_asset_out - period_asset_in',
        'custom',
        'customer-period',
        '["dws_cust_aset_d", "dws_cust_fin_d"]'::jsonb,
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
        '交易量',
        '官方赛题中“交易量”默认按买入金额与卖出金额之和计算；只有明确要求“数量/份额”时才使用 buy_mnt 与 sell_mnt。',
        '["交易金额", "成交金额"]'::jsonb,
        '{"metric_code": "trade_amount"}'::jsonb,
        false
    ),
    (
        '日均资产',
        '指定日期区间内每日总资产之和除以该区间自然日天数；2026 年 Q1 为 90 天。',
        '["平均资产", "日平均资产"]'::jsonb,
        '{"metric_code": "daily_average_asset"}'::jsonb,
        false
    ),
    (
        '资产盈亏',
        '官方 Q1 参考口径为：期末普通资产+期末信用资产-期初普通资产+期初信用资产+期间资产流出-期间资产流入。期初日为 20260101，期末日为 20260331。',
        '["盈亏", "盈利情况", "资产收益"]'::jsonb,
        '{"metric_code": "profit_loss"}'::jsonb,
        false
    ),
    (
        '股票交易',
        '股票产品大类在 dim_product.up_prdt_type_id=''PT040000''。',
        '["股票类交易"]'::jsonb,
        '{"field_code": "up_prdt_type_id", "value": "PT040000"}'::jsonb,
        false
    ),
    (
        '科创板',
        '产品小类以 dim_product.prdt_type_name=''科创板'' 筛选。',
        '["科创板股票"]'::jsonb,
        '{"field_code": "prdt_type_name", "value": "科创板"}'::jsonb,
        false
    ),
    (
        '不同客户年龄段资产分布',
        '官方参考口径：客户年龄分段使用 ads_cust_info_d.data_dt=''20260531''，资产汇总使用 dws_cust_aset_d.data_dt=''20260331''。',
        '["年龄段资产分布", "客户年龄资产分布"]'::jsonb,
        '{"customer_snapshot_date": "20260531", "asset_snapshot_date": "20260331"}'::jsonb,
        false
    )
on conflict (term) do update set
    definition = excluded.definition,
    synonyms = excluded.synonyms,
    default_plan_fragment = excluded.default_plan_fragment,
    clarification_required = excluded.clarification_required,
    is_active = true,
    updated_at = now();
