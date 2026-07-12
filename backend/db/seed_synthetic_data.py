# ruff: noqa: E501
from __future__ import annotations

import argparse
import math
import os
import random
import uuid
from datetime import date, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import psycopg
from psycopg import Cursor
from psycopg.types.json import Jsonb

NAMESPACE = uuid.UUID("2f7a1a27-67c7-45aa-9e56-9c8366c3359f")
DEFAULT_DATABASE_URL = "postgresql://finance_agent:finance_agent@localhost:5432/finance_agent"


def stable_uuid(kind: str, value: str | int) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{kind}:{value}")


def money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_database_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def get_default_database_url() -> str:
    try:
        from app.core.config import get_settings

        return get_settings().database_url
    except Exception:
        return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def chunks(rows: list[tuple[Any, ...]], size: int = 2000) -> list[list[tuple[Any, ...]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def execute_many(cur: Cursor[Any], sql: str, rows: list[tuple[Any, ...]], size: int = 2000) -> None:
    for batch in chunks(rows, size):
        cur.executemany(sql, batch)


def reset_seed_data(cur: Cursor[Any]) -> None:
    cur.execute(
        """
        truncate table
            mart.marketing_touch,
            mart.marketing_campaign,
            mart.customer_asset_flow,
            mart.customer_position_daily,
            mart.customer_trade,
            mart.customer_asset_daily,
            mart.service_relationship,
            mart.public_dimension,
            mart.product_info,
            mart.service_manager,
            mart.customer_info
        restart identity cascade
        """
    )
    cur.execute(
        """
        truncate table
            metadata.question_examples,
            metadata.rule_constraints,
            metadata.join_relationships,
            metadata.business_terms,
            metadata.metric_metadata,
            metadata.column_metadata,
            metadata.table_metadata
        restart identity cascade
        """
    )


def asset_level(total_asset: float) -> str:
    if total_asset >= 1_000_000:
        return "private"
    if total_asset >= 500_000:
        return "platinum"
    if total_asset >= 200_000:
        return "gold"
    if total_asset >= 50_000:
        return "potential"
    return "standard"


def age_band(age: int) -> str:
    if age <= 30:
        return "20-30"
    if age <= 40:
        return "31-40"
    if age <= 50:
        return "41-50"
    if age <= 60:
        return "51-60"
    return "60+"


def generate_managers(manager_count: int) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for index in range(1, manager_count + 1):
        branch_no = (index - 1) % 8 + 1
        org_no = (index - 1) % 4 + 1
        rows.append(
            (
                stable_uuid("manager", index),
                f"M{index:04d}",
                f"经理{index:03d}",
                f"ORG{org_no:02d}",
                f"BR{branch_no:03d}",
                "active",
            )
        )
    return rows


def generate_products(product_count: int, rng: random.Random) -> list[tuple[Any, ...]]:
    product_types = ["fund", "stock", "bond", "wealth", "cash_management"]
    risk_levels = ["R1", "R2", "R3", "R4", "R5"]
    rows: list[tuple[Any, ...]] = []
    for index in range(1, product_count + 1):
        product_type = product_types[(index - 1) % len(product_types)]
        risk_level = risk_levels[min(len(risk_levels) - 1, (index - 1) % len(risk_levels))]
        issuer_no = rng.randint(1, 12)
        rows.append(
            (
                stable_uuid("product", index),
                f"P{index:04d}",
                f"测试{product_type.upper()}产品{index:03d}",
                product_type,
                risk_level,
                f"发行机构{issuer_no:02d}",
                "active",
            )
        )
    return rows


def generate_dimensions() -> list[tuple[Any, ...]]:
    values = {
        "gender": [("M", "男"), ("F", "女"), ("U", "未知")],
        "customer_level": [
            ("standard", "普通客户"),
            ("potential", "潜力客户"),
            ("gold", "金卡客户"),
            ("platinum", "白金客户"),
            ("private", "私行客户"),
        ],
        "risk_level": [
            ("C1", "保守"),
            ("C2", "稳健"),
            ("C3", "平衡"),
            ("C4", "积极"),
            ("C5", "进取"),
        ],
        "product_type": [
            ("fund", "基金"),
            ("stock", "股票"),
            ("bond", "债券"),
            ("wealth", "理财"),
            ("cash_management", "现金管理"),
        ],
        "trade_type": [
            ("buy", "买入"),
            ("sell", "卖出"),
            ("subscribe", "申购"),
            ("redeem", "赎回"),
        ],
        "channel": [("app", "APP"), ("counter", "柜台"), ("phone", "电话"), ("web", "网页")],
    }
    rows: list[tuple[Any, ...]] = []
    for dimension_type, items in values.items():
        for order, (code, name) in enumerate(items, start=1):
            rows.append(
                (
                    stable_uuid("dimension", f"{dimension_type}:{code}"),
                    dimension_type,
                    code,
                    name,
                    None,
                    order,
                    True,
                )
            )
    return rows


def generate_customers(
    customer_count: int,
    anchor_date: date,
    rng: random.Random,
) -> tuple[list[tuple[Any, ...]], dict[uuid.UUID, dict[str, Any]]]:
    risk_levels = ["C1", "C2", "C3", "C4", "C5"]
    profiles: dict[uuid.UUID, dict[str, Any]] = {}
    rows: list[tuple[Any, ...]] = []

    for index in range(1, customer_count + 1):
        segment_roll = rng.random()
        if segment_roll < 0.08:
            base_asset = rng.uniform(1_000_000, 3_500_000)
        elif segment_roll < 0.22:
            base_asset = rng.uniform(500_000, 1_000_000)
        elif segment_roll < 0.48:
            base_asset = rng.uniform(200_000, 500_000)
        elif segment_roll < 0.82:
            base_asset = rng.uniform(50_000, 200_000)
        else:
            base_asset = rng.uniform(5_000, 50_000)

        customer_id = stable_uuid("customer", index)
        age = rng.randint(22, 72)
        level = asset_level(base_asset)
        risk_level = risk_levels[min(len(risk_levels) - 1, max(0, int(base_asset // 300_000)))]
        branch_no = rng.randint(1, 8)
        behavior_roll = rng.random()
        behavior = "normal"
        if behavior_roll < 0.15:
            behavior = "silent"
        elif behavior_roll < 0.45:
            behavior = "active"
        elif behavior_roll < 0.60:
            behavior = "net_inflow"
        elif behavior_roll < 0.72:
            behavior = "outflow_risk"

        rows.append(
            (
                customer_id,
                f"C{index:06d}",
                f"客户{index:06d}",
                "M" if rng.random() < 0.52 else "F",
                date(anchor_date.year - age, rng.randint(1, 12), rng.randint(1, 28)),
                age_band(age),
                level,
                risk_level,
                anchor_date - timedelta(days=rng.randint(60, 3600)),
                f"BR{branch_no:03d}",
                "active" if rng.random() < 0.97 else "inactive",
            )
        )
        profiles[customer_id] = {
            "index": index,
            "base_asset": base_asset,
            "level": level,
            "behavior": behavior,
            "cash_ratio": rng.uniform(0.08, 0.28),
            "security_ratio": rng.uniform(0.10, 0.36),
            "fund_ratio": rng.uniform(0.05, 0.32),
            "product_ratio": rng.uniform(0.04, 0.22),
            "trend": rng.uniform(-0.16, 0.24),
        }

    return rows, profiles


def generate_relationships(
    customer_profiles: dict[uuid.UUID, dict[str, Any]],
    managers: list[tuple[Any, ...]],
    anchor_date: date,
    rng: random.Random,
) -> list[tuple[Any, ...]]:
    manager_ids = [row[0] for row in managers]
    rows: list[tuple[Any, ...]] = []
    for customer_id, profile in customer_profiles.items():
        manager_id = manager_ids[profile["index"] % len(manager_ids)]
        rows.append(
            (
                stable_uuid("relationship", f"{customer_id}:current"),
                customer_id,
                manager_id,
                "primary",
                anchor_date - timedelta(days=rng.randint(30, 1000)),
                None,
                True,
            )
        )
        if rng.random() < 0.10:
            previous_manager = manager_ids[(profile["index"] + 7) % len(manager_ids)]
            start_date = anchor_date - timedelta(days=rng.randint(800, 1600))
            rows.append(
                (
                    stable_uuid("relationship", f"{customer_id}:history"),
                    customer_id,
                    previous_manager,
                    "primary",
                    start_date,
                    start_date + timedelta(days=rng.randint(180, 600)),
                    False,
                )
            )
    return rows


def generate_asset_daily(
    customer_profiles: dict[uuid.UUID, dict[str, Any]],
    anchor_date: date,
    days: int,
    rng: random.Random,
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    start_date = anchor_date - timedelta(days=days - 1)
    for customer_id, profile in customer_profiles.items():
        for day_index in range(days):
            as_of_date = start_date + timedelta(days=day_index)
            progress = day_index / max(days - 1, 1)
            cycle = 1 + math.sin(day_index / 13) * 0.015
            noise = 1 + rng.uniform(-0.018, 0.018)
            total_asset = max(
                500,
                profile["base_asset"] * (1 + profile["trend"] * progress) * cycle * noise,
            )
            cash_asset = total_asset * profile["cash_ratio"] * rng.uniform(0.92, 1.08)
            security_value = total_asset * profile["security_ratio"] * rng.uniform(0.92, 1.08)
            fund_value = total_asset * profile["fund_ratio"] * rng.uniform(0.90, 1.10)
            product_value = total_asset * profile["product_ratio"] * rng.uniform(0.90, 1.10)
            net_asset = max(total_asset, cash_asset + security_value + fund_value + product_value)
            rows.append(
                (
                    stable_uuid("asset", f"{customer_id}:{as_of_date.isoformat()}"),
                    customer_id,
                    as_of_date,
                    money(total_asset),
                    money(cash_asset),
                    money(security_value),
                    money(fund_value),
                    money(product_value),
                    money(net_asset),
                    asset_level(total_asset),
                )
            )
    return rows


def choose_portfolios(
    customer_profiles: dict[uuid.UUID, dict[str, Any]],
    products: list[tuple[Any, ...]],
    rng: random.Random,
) -> dict[uuid.UUID, list[tuple[Any, ...]]]:
    portfolios: dict[uuid.UUID, list[tuple[Any, ...]]] = {}
    fund_products = [row for row in products if row[3] == "fund"]
    non_cash_products = [row for row in products if row[3] != "cash_management"]
    for customer_id, profile in customer_profiles.items():
        if profile["behavior"] == "silent" and rng.random() < 0.25:
            portfolios[customer_id] = []
            continue
        count = rng.randint(1, 4)
        pool = non_cash_products
        selected = rng.sample(pool, k=min(count, len(pool)))
        if profile["level"] in {"platinum", "private"} and rng.random() < 0.65:
            selected.append(rng.choice(fund_products))
        portfolios[customer_id] = list({row[0]: row for row in selected}.values())
    return portfolios


def generate_positions(
    customer_profiles: dict[uuid.UUID, dict[str, Any]],
    portfolios: dict[uuid.UUID, list[tuple[Any, ...]]],
    anchor_date: date,
    days: int,
    rng: random.Random,
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    start_date = anchor_date - timedelta(days=days - 1)
    snapshot_dates = [start_date + timedelta(days=index) for index in range(0, days, 7)]
    if anchor_date not in snapshot_dates:
        snapshot_dates.append(anchor_date)

    for customer_id, products in portfolios.items():
        if not products:
            continue
        profile = customer_profiles[customer_id]
        allocation_total = profile["base_asset"] * rng.uniform(0.18, 0.62)
        for product in products:
            product_id = product[0]
            base_market_value = allocation_total / len(products) * rng.uniform(0.75, 1.25)
            fake_price = rng.uniform(0.8, 8.5)
            for as_of_date in snapshot_dates:
                drift = 1 + rng.uniform(-0.08, 0.08)
                market_value = max(100, base_market_value * drift)
                quantity = market_value / fake_price
                cost_amount = market_value * rng.uniform(0.86, 1.12)
                rows.append(
                    (
                        stable_uuid("position", f"{customer_id}:{product_id}:{as_of_date}"),
                        customer_id,
                        product_id,
                        as_of_date,
                        money(quantity),
                        money(market_value),
                        money(cost_amount),
                        money(market_value - cost_amount),
                        rng.randint(1, 1200),
                    )
                )
    return rows


def generate_trades(
    customer_profiles: dict[uuid.UUID, dict[str, Any]],
    portfolios: dict[uuid.UUID, list[tuple[Any, ...]]],
    products: list[tuple[Any, ...]],
    anchor_date: date,
    days: int,
    rng: random.Random,
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    trade_types = ["buy", "sell", "subscribe", "redeem"]
    channels = ["app", "web", "counter", "phone"]

    for customer_id, profile in customer_profiles.items():
        behavior = profile["behavior"]
        if behavior == "silent":
            trade_count = rng.randint(0, 4)
            min_days_ago = min(91, days - 1)
        elif behavior == "active":
            trade_count = rng.randint(24, 70)
            min_days_ago = 0
        else:
            trade_count = rng.randint(5, 26)
            min_days_ago = 0

        candidates = portfolios.get(customer_id) or products
        for trade_index in range(trade_count):
            max_days_ago = days - 1
            days_ago = rng.randint(min_days_ago, max_days_ago)
            product = rng.choice(candidates)
            trade_amount = max(100, profile["base_asset"] * rng.uniform(0.002, 0.08))
            trade_id = stable_uuid("trade", f"{customer_id}:{trade_index}")
            rows.append(
                (
                    trade_id,
                    customer_id,
                    product[0],
                    anchor_date - timedelta(days=days_ago),
                    time(hour=rng.randint(9, 15), minute=rng.randint(0, 59)),
                    rng.choice(trade_types),
                    "CN",
                    product[2],
                    money(trade_amount),
                    money(trade_amount / rng.uniform(1.2, 12.0)),
                    money(trade_amount * rng.uniform(0.0002, 0.0025)),
                    money(trade_amount * rng.uniform(-0.08, 0.12)),
                    rng.choice(channels),
                )
            )
    return rows


def generate_flows(
    customer_profiles: dict[uuid.UUID, dict[str, Any]],
    products: list[tuple[Any, ...]],
    anchor_date: date,
    days: int,
    rng: random.Random,
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    channels = ["app", "web", "counter", "phone"]
    for customer_id, profile in customer_profiles.items():
        flow_count = rng.randint(24, 58)
        for flow_index in range(flow_count):
            if profile["behavior"] == "outflow_risk" and rng.random() < 0.55:
                flow_type = "outflow"
                days_ago = rng.randint(0, min(30, days - 1))
                amount = profile["base_asset"] * rng.uniform(0.04, 0.18)
            elif profile["behavior"] == "net_inflow" and rng.random() < 0.65:
                flow_type = "inflow"
                days_ago = rng.randint(0, min(90, days - 1))
                amount = profile["base_asset"] * rng.uniform(0.02, 0.12)
            else:
                flow_type = rng.choice(["inflow", "outflow", "transfer_in", "transfer_out"])
                days_ago = rng.randint(0, days - 1)
                amount = profile["base_asset"] * rng.uniform(0.001, 0.05)
            product_id = rng.choice(products)[0] if rng.random() < 0.35 else None
            rows.append(
                (
                    stable_uuid("flow", f"{customer_id}:{flow_index}"),
                    customer_id,
                    product_id,
                    anchor_date - timedelta(days=days_ago),
                    flow_type,
                    money(max(50, amount)),
                    rng.choice(channels),
                    "synthetic",
                )
            )
    return rows


def generate_campaigns(anchor_date: date) -> tuple[list[tuple[Any, ...]], list[uuid.UUID]]:
    campaigns: list[tuple[Any, ...]] = []
    campaign_ids: list[uuid.UUID] = []
    campaign_types = ["fund_potential", "asset_retention", "wealth_upgrade", "active_trade"]
    for index in range(1, 7):
        campaign_id = stable_uuid("campaign", index)
        campaign_ids.append(campaign_id)
        campaigns.append(
            (
                campaign_id,
                f"CAM{index:04d}",
                f"测试营销活动{index:02d}",
                campaign_types[(index - 1) % len(campaign_types)],
                None,
                anchor_date - timedelta(days=90 - index * 10),
                anchor_date + timedelta(days=index * 7),
                "active",
            )
        )
    return campaigns, campaign_ids


def generate_touches(
    customer_profiles: dict[uuid.UUID, dict[str, Any]],
    relationships: list[tuple[Any, ...]],
    campaign_ids: list[uuid.UUID],
    anchor_date: date,
    rng: random.Random,
) -> list[tuple[Any, ...]]:
    manager_by_customer = {row[1]: row[2] for row in relationships if row[6]}
    customer_ids = list(customer_profiles.keys())
    touch_count = min(1800, len(customer_ids) * 4)
    rows: list[tuple[Any, ...]] = []
    for index in range(touch_count):
        customer_id = rng.choice(customer_ids)
        touch_day = anchor_date - timedelta(days=rng.randint(0, 90))
        status = rng.choice(["planned", "completed", "completed", "completed"])
        response = rng.choice(["none", "interested", "converted", "rejected"])
        rows.append(
            (
                stable_uuid("touch", index),
                rng.choice(campaign_ids),
                customer_id,
                manager_by_customer.get(customer_id),
                f"{touch_day.isoformat()} {rng.randint(9, 18):02d}:{rng.randint(0, 59):02d}:00+08",
                rng.choice(["app", "phone", "sms", "wechat"]),
                status,
                response,
            )
        )
    return rows


def seed_business_data(cur: Cursor[Any], customer_count: int, days: int, anchor_date: date) -> None:
    rng = random.Random(20260706)
    manager_count = max(12, min(60, customer_count // 16))
    product_count = max(40, min(120, customer_count // 6))

    managers = generate_managers(manager_count)
    products = generate_products(product_count, rng)
    dimensions = generate_dimensions()
    customers, customer_profiles = generate_customers(customer_count, anchor_date, rng)
    relationships = generate_relationships(customer_profiles, managers, anchor_date, rng)
    asset_rows = generate_asset_daily(customer_profiles, anchor_date, days, rng)
    portfolios = choose_portfolios(customer_profiles, products, rng)
    position_rows = generate_positions(customer_profiles, portfolios, anchor_date, days, rng)
    trade_rows = generate_trades(customer_profiles, portfolios, products, anchor_date, days, rng)
    flow_rows = generate_flows(customer_profiles, products, anchor_date, days, rng)
    campaigns, campaign_ids = generate_campaigns(anchor_date)
    touches = generate_touches(customer_profiles, relationships, campaign_ids, anchor_date, rng)

    execute_many(
        cur,
        """
        insert into mart.service_manager
            (manager_id, manager_no, manager_name_masked, org_code, branch_code, manager_status)
        values (%s, %s, %s, %s, %s, %s)
        on conflict (manager_no) do update set
            manager_name_masked = excluded.manager_name_masked,
            org_code = excluded.org_code,
            branch_code = excluded.branch_code,
            manager_status = excluded.manager_status,
            updated_at = now()
        """,
        managers,
    )
    execute_many(
        cur,
        """
        insert into mart.product_info
            (product_id, product_code, product_name, product_type, risk_level, issuer, product_status)
        values (%s, %s, %s, %s, %s, %s, %s)
        on conflict (product_code) do update set
            product_name = excluded.product_name,
            product_type = excluded.product_type,
            risk_level = excluded.risk_level,
            issuer = excluded.issuer,
            product_status = excluded.product_status,
            updated_at = now()
        """,
        products,
    )
    execute_many(
        cur,
        """
        insert into mart.public_dimension
            (dimension_id, dimension_type, dimension_code, dimension_name, parent_code, sort_order, is_active)
        values (%s, %s, %s, %s, %s, %s, %s)
        on conflict (dimension_type, dimension_code) do update set
            dimension_name = excluded.dimension_name,
            parent_code = excluded.parent_code,
            sort_order = excluded.sort_order,
            is_active = excluded.is_active,
            updated_at = now()
        """,
        dimensions,
    )
    execute_many(
        cur,
        """
        insert into mart.customer_info
            (
                customer_id, customer_no, customer_name_masked, gender, birth_date, age_band,
                customer_level, risk_level, open_date, branch_code, customer_status
            )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (customer_no) do update set
            customer_name_masked = excluded.customer_name_masked,
            gender = excluded.gender,
            birth_date = excluded.birth_date,
            age_band = excluded.age_band,
            customer_level = excluded.customer_level,
            risk_level = excluded.risk_level,
            open_date = excluded.open_date,
            branch_code = excluded.branch_code,
            customer_status = excluded.customer_status,
            updated_at = now()
        """,
        customers,
    )
    execute_many(
        cur,
        """
        insert into mart.service_relationship
            (
                relationship_id, customer_id, manager_id, relationship_type, start_date,
                end_date, is_primary
            )
        values (%s, %s, %s, %s, %s, %s, %s)
        on conflict (relationship_id) do update set
            manager_id = excluded.manager_id,
            relationship_type = excluded.relationship_type,
            start_date = excluded.start_date,
            end_date = excluded.end_date,
            is_primary = excluded.is_primary,
            updated_at = now()
        """,
        relationships,
    )
    execute_many(
        cur,
        """
        insert into mart.customer_asset_daily
            (
                asset_snapshot_id, customer_id, as_of_date, total_asset, cash_asset,
                security_market_value, fund_market_value, product_market_value,
                net_asset, asset_level
            )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (customer_id, as_of_date) do update set
            total_asset = excluded.total_asset,
            cash_asset = excluded.cash_asset,
            security_market_value = excluded.security_market_value,
            fund_market_value = excluded.fund_market_value,
            product_market_value = excluded.product_market_value,
            net_asset = excluded.net_asset,
            asset_level = excluded.asset_level,
            updated_at = now()
        """,
        asset_rows,
    )
    execute_many(
        cur,
        """
        insert into mart.customer_position_daily
            (
                position_snapshot_id, customer_id, product_id, as_of_date,
                position_quantity, market_value, cost_amount,
                unrealized_profit_loss, holding_days
            )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (customer_id, product_id, as_of_date) do update set
            position_quantity = excluded.position_quantity,
            market_value = excluded.market_value,
            cost_amount = excluded.cost_amount,
            unrealized_profit_loss = excluded.unrealized_profit_loss,
            holding_days = excluded.holding_days,
            updated_at = now()
        """,
        position_rows,
    )
    execute_many(
        cur,
        """
        insert into mart.customer_trade
            (
                trade_id, customer_id, product_id, trade_date, trade_time, trade_type,
                market, security_code, trade_amount, trade_quantity, fee_amount,
                realized_profit_loss, channel
            )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (trade_id) do update set
            customer_id = excluded.customer_id,
            product_id = excluded.product_id,
            trade_date = excluded.trade_date,
            trade_time = excluded.trade_time,
            trade_type = excluded.trade_type,
            market = excluded.market,
            security_code = excluded.security_code,
            trade_amount = excluded.trade_amount,
            trade_quantity = excluded.trade_quantity,
            fee_amount = excluded.fee_amount,
            realized_profit_loss = excluded.realized_profit_loss,
            channel = excluded.channel
        """,
        trade_rows,
    )
    execute_many(
        cur,
        """
        insert into mart.customer_asset_flow
            (flow_id, customer_id, product_id, occur_date, flow_type, amount, channel, remark)
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (flow_id) do update set
            customer_id = excluded.customer_id,
            product_id = excluded.product_id,
            occur_date = excluded.occur_date,
            flow_type = excluded.flow_type,
            amount = excluded.amount,
            channel = excluded.channel,
            remark = excluded.remark
        """,
        flow_rows,
    )
    execute_many(
        cur,
        """
        insert into mart.marketing_campaign
            (
                campaign_id, campaign_code, campaign_name, campaign_type, target_product_id,
                start_date, end_date, campaign_status
            )
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (campaign_code) do update set
            campaign_name = excluded.campaign_name,
            campaign_type = excluded.campaign_type,
            target_product_id = excluded.target_product_id,
            start_date = excluded.start_date,
            end_date = excluded.end_date,
            campaign_status = excluded.campaign_status,
            updated_at = now()
        """,
        campaigns,
    )
    execute_many(
        cur,
        """
        insert into mart.marketing_touch
            (
                touch_id, campaign_id, customer_id, manager_id, touch_time,
                touch_channel, touch_status, response_status
            )
        values (%s, %s, %s, %s, %s::timestamptz, %s, %s, %s)
        on conflict (touch_id) do update set
            campaign_id = excluded.campaign_id,
            customer_id = excluded.customer_id,
            manager_id = excluded.manager_id,
            touch_time = excluded.touch_time,
            touch_channel = excluded.touch_channel,
            touch_status = excluded.touch_status,
            response_status = excluded.response_status,
            updated_at = now()
        """,
        touches,
    )

    print(
        "Seeded business data: "
        f"customers={len(customers)}, managers={len(managers)}, products={len(products)}, "
        f"assets={len(asset_rows)}, positions={len(position_rows)}, trades={len(trade_rows)}, "
        f"flows={len(flow_rows)}, touches={len(touches)}"
    )


def table_metadata_rows() -> list[tuple[Any, ...]]:
    rows = [
        ("mart", "customer_info", "客户信息表", "customer", "客户基础画像与分群字段", "customer"),
        ("mart", "service_manager", "服务经理信息表", "manager", "服务经理与机构信息", "manager"),
        ("mart", "product_info", "产品信息表", "product", "产品类型、风险等级与状态", "product"),
        (
            "mart",
            "service_relationship",
            "服务关系表",
            "customer_manager",
            "客户与服务经理当前及历史关系",
            "customer-manager",
        ),
        ("mart", "public_dimension", "公共维表", "dimension", "通用枚举代码", "code"),
        (
            "mart",
            "customer_asset_daily",
            "客户资产日表",
            "asset",
            "客户每日资产与资产结构",
            "customer-date",
        ),
        (
            "mart",
            "customer_position_daily",
            "客户持仓日表",
            "position",
            "客户产品持仓快照",
            "customer-product-date",
        ),
        ("mart", "customer_trade", "客户交易表", "trade", "客户交易流水", "trade"),
        (
            "mart",
            "customer_asset_flow",
            "客户资产流入流出表",
            "cash_flow",
            "客户资金流入流出流水",
            "customer-date-flow",
        ),
        (
            "mart",
            "customer_current_asset",
            "当前客户资产视图",
            "asset",
            "每个客户最新统计日资产",
            "customer",
        ),
        (
            "mart",
            "customer_trade_90d",
            "近90天客户交易视图",
            "trade",
            "按客户汇总近90天交易次数和金额",
            "customer",
        ),
        (
            "mart",
            "customer_net_flow_90d",
            "近90天客户净流入视图",
            "cash_flow",
            "按客户汇总近90天流入、流出和净流入",
            "customer",
        ),
    ]
    return [(schema, table, display, domain, desc, grain, "daily", True) for rowspec in rows for schema, table, display, domain, desc, grain in [rowspec]]


def column_rows() -> list[tuple[Any, ...]]:
    columns = [
        ("customer_info", "customer_id", "客户ID", "uuid", "脱敏客户主键", "identifier", True, False, False),
        ("customer_info", "customer_no", "客户编号", "varchar", "脱敏客户编号", "identifier", True, False, False),
        ("customer_info", "customer_name_masked", "客户脱敏名称", "varchar", "演示用脱敏名称", "name", True, False, True),
        ("customer_info", "gender", "性别", "varchar", "性别代码", "category", True, False, False),
        ("customer_info", "age_band", "年龄段", "varchar", "年龄段", "category", True, False, False),
        ("customer_info", "customer_level", "客户等级", "varchar", "客户价值等级", "category", True, False, False),
        ("customer_info", "risk_level", "风险等级", "varchar", "客户风险等级", "category", True, False, False),
        ("customer_info", "branch_code", "分支机构", "varchar", "客户所属分支机构", "category", True, False, False),
        ("service_manager", "manager_id", "服务经理ID", "uuid", "服务经理主键", "identifier", True, False, False),
        ("service_manager", "manager_no", "服务经理编号", "varchar", "服务经理编号", "identifier", True, False, False),
        ("service_manager", "manager_name_masked", "服务经理名称", "varchar", "脱敏经理名称", "name", True, False, False),
        ("service_manager", "org_code", "机构编号", "varchar", "所属机构", "category", True, False, False),
        ("product_info", "product_id", "产品ID", "uuid", "产品主键", "identifier", True, False, False),
        ("product_info", "product_code", "产品代码", "varchar", "产品代码", "identifier", True, False, False),
        ("product_info", "product_type", "产品类型", "varchar", "基金、股票、债券等", "category", True, False, False),
        ("product_info", "risk_level", "产品风险等级", "varchar", "产品风险等级", "category", True, False, False),
        ("customer_asset_daily", "as_of_date", "统计日期", "date", "资产统计日期", "date", True, False, False),
        ("customer_asset_daily", "total_asset", "总资产", "numeric", "客户总资产", "amount", False, True, False),
        ("customer_asset_daily", "cash_asset", "现金资产", "numeric", "现金资产", "amount", False, True, False),
        ("customer_asset_daily", "fund_market_value", "基金市值", "numeric", "基金持仓市值", "amount", False, True, False),
        ("customer_asset_daily", "net_asset", "净资产", "numeric", "客户净资产", "amount", False, True, False),
        ("customer_trade", "trade_date", "交易日期", "date", "交易发生日期", "date", True, False, False),
        ("customer_trade", "trade_type", "交易类型", "varchar", "买入、卖出、申购、赎回", "category", True, False, False),
        ("customer_trade", "trade_amount", "交易金额", "numeric", "交易金额", "amount", False, True, False),
        ("customer_asset_flow", "occur_date", "发生日期", "date", "资金流发生日期", "date", True, False, False),
        ("customer_asset_flow", "flow_type", "流向类型", "varchar", "流入、流出、转入、转出", "category", True, False, False),
        ("customer_asset_flow", "amount", "发生金额", "numeric", "流入流出金额", "amount", False, True, False),
        ("customer_current_asset", "total_asset", "当前总资产", "numeric", "最新统计日总资产", "amount", False, True, False),
        ("customer_trade_90d", "trade_count_90d", "近90天交易次数", "integer", "近90天交易次数", "count", False, True, False),
        ("customer_net_flow_90d", "net_flow_amount_90d", "近90天净流入", "numeric", "近90天净流入金额", "amount", False, True, False),
    ]
    return [("mart", *row, True) for row in columns]


def seed_metadata(cur: Cursor[Any]) -> None:
    execute_many(
        cur,
        """
        insert into metadata.table_metadata
            (
                schema_name, table_name, display_name, domain, description, grain,
                refresh_frequency, is_active
            )
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (schema_name, table_name) do update set
            display_name = excluded.display_name,
            domain = excluded.domain,
            description = excluded.description,
            grain = excluded.grain,
            refresh_frequency = excluded.refresh_frequency,
            is_active = excluded.is_active,
            updated_at = now()
        """,
        table_metadata_rows(),
    )
    execute_many(
        cur,
        """
        insert into metadata.column_metadata
            (
                schema_name, table_name, column_name, display_name, data_type, description,
                semantic_type, is_dimension, is_metric_source, is_sensitive, is_active
            )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (schema_name, table_name, column_name) do update set
            display_name = excluded.display_name,
            data_type = excluded.data_type,
            description = excluded.description,
            semantic_type = excluded.semantic_type,
            is_dimension = excluded.is_dimension,
            is_metric_source = excluded.is_metric_source,
            is_sensitive = excluded.is_sensitive,
            is_active = excluded.is_active,
            updated_at = now()
        """,
        column_rows(),
    )

    metrics = [
        (
            "customer_count",
            "客户数量",
            "按当前筛选条件统计去重客户数。",
            "count(distinct mart.customer_info.customer_id)",
            "count_distinct",
            "aggregate",
            Jsonb(["customer_info"]),
            Jsonb([]),
        ),
        (
            "current_total_asset",
            "当前总资产",
            "客户最新统计日总资产。",
            "sum(mart.customer_current_asset.total_asset)",
            "sum",
            "customer",
            Jsonb(["customer_current_asset"]),
            Jsonb([{"field": "as_of_date", "rule": "latest_snapshot"}]),
        ),
        (
            "trade_count_90d",
            "近90天交易次数",
            "客户近90天交易流水数量。",
            "coalesce(mart.customer_trade_90d.trade_count_90d, 0)",
            "sum",
            "customer",
            Jsonb(["customer_trade_90d"]),
            Jsonb([{"field": "trade_date", "rule": "last_90_days"}]),
        ),
        (
            "trade_amount_90d",
            "近90天交易金额",
            "客户近90天交易金额。",
            "coalesce(mart.customer_trade_90d.trade_amount_90d, 0)",
            "sum",
            "customer",
            Jsonb(["customer_trade_90d"]),
            Jsonb([{"field": "trade_date", "rule": "last_90_days"}]),
        ),
        (
            "net_asset_inflow_90d",
            "近90天资产净流入",
            "客户近90天资金流入减流出。",
            "coalesce(mart.customer_net_flow_90d.net_flow_amount_90d, 0)",
            "sum",
            "customer",
            Jsonb(["customer_net_flow_90d"]),
            Jsonb([{"field": "occur_date", "rule": "last_90_days"}]),
        ),
        (
            "fund_holding_amount",
            "基金持仓金额",
            "客户基金产品持仓市值。",
            "sum(case when product_info.product_type = 'fund' then customer_position_daily.market_value else 0 end)",
            "sum",
            "customer-product-date",
            Jsonb(["customer_position_daily", "product_info"]),
            Jsonb([{"field": "as_of_date", "rule": "latest_snapshot"}]),
        ),
        (
            "response_customer_count",
            "Marketing response customer count",
            "Unique customers that responded to a marketing campaign.",
            "count(distinct mart.marketing_touch.customer_id) filter (where response_status = 'responded')",
            "count_distinct",
            "campaign",
            Jsonb(["marketing_touch", "marketing_campaign"]),
            Jsonb([]),
        ),
        (
            "response_rate",
            "Marketing response rate",
            "Ratio of responded touches to all campaign touches.",
            "responded_touch_count / total_touch_count",
            "ratio",
            "campaign",
            Jsonb(["marketing_touch", "marketing_campaign"]),
            Jsonb([]),
        ),
    ]
    execute_many(
        cur,
        """
        insert into metadata.metric_metadata
            (
                metric_code, metric_name, description, formula, default_aggregation,
                grain, source_tables, required_filters, owner, is_active
            )
        values (%s, %s, %s, %s, %s, %s, %s, %s, 'data_team', true)
        on conflict (metric_code) do update set
            metric_name = excluded.metric_name,
            description = excluded.description,
            formula = excluded.formula,
            default_aggregation = excluded.default_aggregation,
            grain = excluded.grain,
            source_tables = excluded.source_tables,
            required_filters = excluded.required_filters,
            updated_at = now()
        """,
        metrics,
    )

    terms = [
        (
            "有效客户",
            "客户状态为 active 的客户，用于存量有效客户统计。",
            Jsonb(["当前有效客户", "存量有效客户"]),
            Jsonb({"field_code": "customer_status", "operator": "=", "value": "active"}),
        ),
        (
            "高净值客户",
            "当前总资产大于等于 500000 的客户。",
            Jsonb(["高资产客户", "高净值", "大客户"]),
            Jsonb({"metric_code": "current_total_asset", "operator": ">=", "value": 500000}),
        ),
        (
            "活跃客户",
            "近90天交易次数大于等于 3 的客户。",
            Jsonb(["交易活跃客户", "活跃交易客户"]),
            Jsonb({"metric_code": "trade_count_90d", "operator": ">=", "value": 3}),
        ),
        (
            "沉默客户",
            "近90天没有交易记录的客户。",
            Jsonb(["不活跃客户", "无交易客户"]),
            Jsonb({"metric_code": "trade_count_90d", "operator": "=", "value": 0}),
        ),
        (
            "资产流入客户",
            "近90天资产净流入大于 0 的客户。",
            Jsonb(["净流入客户", "资金流入客户"]),
            Jsonb({"metric_code": "net_asset_inflow_90d", "operator": ">", "value": 0}),
        ),
        (
            "基金潜客",
            "当前有可用资产或现金资产，但基金持仓较低或为 0 的客户。",
            Jsonb(["基金潜在客户", "基金营销客户"]),
            Jsonb({"metric_code": "fund_holding_amount", "operator": "=", "value": 0}),
        ),
    ]
    term_rows = [(*term, index in {1, 2}) for index, term in enumerate(terms)]
    execute_many(
        cur,
        """
        insert into metadata.business_terms
            (term, definition, synonyms, default_plan_fragment, clarification_required, is_active)
        values (%s, %s, %s, %s, %s, true)
        on conflict (term) do update set
            definition = excluded.definition,
            synonyms = excluded.synonyms,
            default_plan_fragment = excluded.default_plan_fragment,
            clarification_required = excluded.clarification_required,
            updated_at = now()
        """,
        term_rows,
    )

    joins = [
        ("customer_info", "customer_id", "customer_asset_daily", "customer_id", "one_to_many"),
        ("customer_info", "customer_id", "customer_current_asset", "customer_id", "one_to_one"),
        ("customer_info", "customer_id", "customer_trade", "customer_id", "one_to_many"),
        ("customer_info", "customer_id", "customer_trade_90d", "customer_id", "one_to_one"),
        ("customer_info", "customer_id", "customer_net_flow_90d", "customer_id", "one_to_one"),
        ("customer_info", "customer_id", "customer_asset_flow", "customer_id", "one_to_many"),
        ("customer_info", "customer_id", "customer_position_daily", "customer_id", "one_to_many"),
        ("customer_info", "customer_id", "service_relationship", "customer_id", "one_to_many"),
        ("service_manager", "manager_id", "service_relationship", "manager_id", "one_to_many"),
        ("product_info", "product_id", "customer_trade", "product_id", "one_to_many"),
        ("product_info", "product_id", "customer_position_daily", "product_id", "one_to_many"),
    ]
    execute_many(
        cur,
        """
        insert into metadata.join_relationships
            (
                left_schema, left_table, left_column, right_schema, right_table,
                right_column, relationship_type, description, is_active
            )
        values ('mart', %s, %s, 'mart', %s, %s, %s, %s, true)
        """,
        [
            (
                left_table,
                left_column,
                right_table,
                right_column,
                relationship,
                f"{left_table}.{left_column} -> {right_table}.{right_column}",
            )
            for left_table, left_column, right_table, right_column, relationship in joins
        ],
    )

    examples = [
        (
            "Q001",
            "筛选当前资产超过50万且近90天交易次数大于3次的客户",
            "medium",
            Jsonb({"intent": "customer_segmentation"}),
            """
            select c.customer_no, c.customer_level, a.total_asset, t.trade_count_90d
            from mart.customer_info c
            join mart.customer_current_asset a on a.customer_id = c.customer_id
            left join mart.customer_trade_90d t on t.customer_id = c.customer_id
            where a.total_asset >= 500000
              and coalesce(t.trade_count_90d, 0) > 3
            limit 100
            """,
            Jsonb({"min_rows": 1}),
            Jsonb(["高净值客户", "活跃客户"]),
        ),
        (
            "Q002",
            "按服务经理统计当前总资产排名前10",
            "medium",
            Jsonb({"intent": "ranking_query"}),
            """
            select m.manager_no, m.manager_name_masked, sum(a.total_asset) as total_asset
            from mart.service_manager m
            join mart.service_relationship r on r.manager_id = m.manager_id and r.is_primary = true
            join mart.customer_current_asset a on a.customer_id = r.customer_id
            group by m.manager_no, m.manager_name_masked
            order by total_asset desc
            limit 10
            """,
            Jsonb({"limit": 10}),
            Jsonb(["经理汇总", "当前资产"]),
        ),
    ]
    execute_many(
        cur,
        """
        insert into metadata.question_examples
            (
                question, difficulty, scenario, expected_query_plan, expected_sql,
                expected_result, tags, is_active
            )
        values (%s, %s, 'customer_marketing', %s, %s, %s, %s, true)
        """,
        [(question, difficulty, plan, sql.strip(), result, tags) for _, question, difficulty, plan, sql, result, tags in examples],
    )

    rules = [
        (
            "readonly_select_only",
            "SQL只读",
            "sql_safety",
            Jsonb({"allow": ["select"], "deny": ["insert", "update", "delete", "drop", "alter"]}),
            "error",
            "SQL 执行只允许 SELECT。",
        ),
        (
            "sensitive_detail_block",
            "敏感字段禁止明细返回",
            "privacy",
            Jsonb({"sensitive_columns": ["customer_name_masked"], "allow_aggregate": True}),
            "error",
            "脱敏名称仍按敏感展示字段处理，默认不返回大批量明细。",
        ),
        (
            "limit_required",
            "必须限制返回行数",
            "sql_safety",
            Jsonb({"max_limit": 1000}),
            "error",
            "预览查询必须包含 LIMIT。",
        ),
    ]
    execute_many(
        cur,
        """
        insert into metadata.rule_constraints
            (rule_code, rule_name, rule_type, config, severity, description, is_active)
        values (%s, %s, %s, %s, %s, %s, true)
        on conflict (rule_code) do update set
            rule_name = excluded.rule_name,
            rule_type = excluded.rule_type,
            config = excluded.config,
            severity = excluded.severity,
            description = excluded.description,
            updated_at = now()
        """,
        rules,
    )
    print("Seeded metadata: tables, columns, metrics, business terms, joins, examples, rules")


def _evaluation_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _expected_result(cur: Cursor[Any], sql: str) -> Jsonb:
    cur.execute(sql)
    columns = [item.name for item in cur.description]
    rows = [
        {column: _evaluation_jsonable(value) for column, value in zip(columns, row, strict=True)}
        for row in cur.fetchall()
    ]
    return Jsonb({"columns": columns, "rows": rows, "row_count": len(rows), "comparison": "unordered"})


def seed_evaluation_cases(cur: Cursor[Any]) -> None:
    """Create a deterministic, executable benchmark over the seeded business mart."""
    cases: list[dict[str, Any]] = [
        {
            "code": "SYN-001",
            "question": "当前客户有多少",
            "difficulty": "simple",
            "tags": ["customer", "count"],
            "plan": {"intent": "metric_query", "metrics": ["customer_count"]},
            "sql": "select count(*)::integer as customer_count from mart.customer_info",
        },
        {
            "code": "SYN-002",
            "question": "当前资产大于100万的客户有多少",
            "difficulty": "simple",
            "tags": ["asset", "segmentation"],
            "plan": {"intent": "metric_query", "metrics": ["customer_count", "current_total_asset"], "filters": ["total_asset>1000000"]},
            "sql": "select count(*)::integer as customer_count from mart.customer_current_asset where total_asset > 1000000",
        },
        {
            "code": "SYN-003",
            "question": "列出近90天交易次数大于3次的客户，最多20条",
            "difficulty": "simple",
            "tags": ["trade", "customer_list"],
            "plan": {"intent": "customer_segmentation", "metrics": ["trade_count_90d"], "filters": ["trade_count_90d>3"], "limit": 20},
            "sql": "select c.customer_no, t.trade_count_90d from mart.customer_info c join mart.customer_trade_90d t on t.customer_id = c.customer_id where t.trade_count_90d > 3 limit 20",
        },
        {
            "code": "SYN-004",
            "question": "近90天净流入超过10万的客户数",
            "difficulty": "simple",
            "tags": ["asset_flow", "count"],
            "plan": {"intent": "metric_query", "metrics": ["customer_count", "net_asset_inflow_90d"], "filters": ["net_flow_amount_90d>100000"]},
            "sql": "select count(*)::integer as customer_count from mart.customer_net_flow_90d where net_flow_amount_90d > 100000",
        },
        {
            "code": "SYN-005",
            "question": "按客户等级统计当前客户数和总资产",
            "difficulty": "medium",
            "tags": ["asset", "group_by"],
            "plan": {"intent": "metric_query", "metrics": ["customer_count", "current_total_asset"], "dimensions": ["customer_level"]},
            "sql": "select c.customer_level, count(*)::integer as customer_count, round(sum(a.total_asset), 2) as current_total_asset from mart.customer_info c join mart.customer_current_asset a on a.customer_id = c.customer_id group by c.customer_level order by c.customer_level",
        },
        {
            "code": "SYN-006",
            "question": "筛选当前资产超过50万且近90天交易次数超过3次的客户，最多50条",
            "difficulty": "medium",
            "tags": ["asset", "trade", "segmentation"],
            "plan": {"intent": "customer_segmentation", "metrics": ["current_total_asset", "trade_count_90d"], "filters": ["total_asset>500000", "trade_count_90d>3"], "limit": 50},
            "sql": "select c.customer_no, a.total_asset as current_total_asset, t.trade_count_90d from mart.customer_info c join mart.customer_trade_90d t on t.customer_id = c.customer_id join mart.customer_current_asset a on a.customer_id = c.customer_id where a.total_asset > 500000 and t.trade_count_90d > 3 limit 50",
        },
        {
            "code": "SYN-007",
            "question": "当前资产超过20万且未持有基金的客户数",
            "difficulty": "medium",
            "tags": ["asset", "holding", "negative_filter"],
            "plan": {"intent": "metric_query", "metrics": ["customer_count", "fund_holding_amount"], "filters": ["total_asset>200000", "fund_holding=not_exists"]},
            "sql": "select count(*)::integer as customer_count from mart.customer_current_asset a where a.total_asset > 200000 and not exists (select 1 from mart.customer_position_daily p join mart.product_info pi on pi.product_id = p.product_id where p.customer_id = a.customer_id and pi.product_type = 'fund' and p.as_of_date = a.as_of_date)",
        },
        {
            "code": "SYN-008",
            "question": "按服务经理统计当前管理客户数和总资产，取前10名",
            "difficulty": "medium",
            "tags": ["manager", "asset", "ranking"],
            "plan": {"intent": "ranking_query", "metrics": ["customer_count", "current_total_asset"], "dimensions": ["manager"], "limit": 10},
            "sql": "select m.manager_no, count(distinct r.customer_id)::integer as customer_count, round(sum(a.total_asset), 2) as current_total_asset from mart.service_manager m join mart.service_relationship r on r.manager_id = m.manager_id and r.is_primary = true join mart.customer_current_asset a on a.customer_id = r.customer_id group by m.manager_no order by current_total_asset desc, m.manager_no limit 10",
        },
        {
            "code": "SYN-009",
            "question": "近90天净流出金额最高的客户，展示前20名",
            "difficulty": "medium",
            "tags": ["asset_flow", "ranking"],
            "plan": {"intent": "ranking_query", "metrics": ["net_asset_inflow_90d"], "filters": ["net_flow_amount_90d<0"], "limit": 20},
            "sql": "select c.customer_no, round(f.net_flow_amount_90d, 2) as net_flow_amount_90d from mart.customer_info c join mart.customer_net_flow_90d f on f.customer_id = c.customer_id where f.net_flow_amount_90d < 0 order by f.net_flow_amount_90d asc, c.customer_no limit 20",
        },
        {
            "code": "SYN-010",
            "question": "统计各风险等级客户的当前总资产和近90天交易金额",
            "difficulty": "complex",
            "tags": ["asset", "trade", "cross_domain"],
            "plan": {"intent": "metric_query", "metrics": ["current_total_asset", "trade_amount_90d"], "dimensions": ["risk_level"]},
            "sql": "select c.risk_level, round(sum(a.total_asset), 2) as current_total_asset, round(sum(coalesce(t.trade_amount_90d, 0)), 2) as trade_amount_90d from mart.customer_info c join mart.customer_current_asset a on a.customer_id = c.customer_id left join mart.customer_trade_90d t on t.customer_id = c.customer_id group by c.risk_level order by c.risk_level",
        },
        {
            "code": "SYN-011",
            "question": "找出当前资产超过50万、近90天净流入超过10万且持有基金的客户，最多30条",
            "difficulty": "complex",
            "tags": ["asset", "asset_flow", "holding", "cross_domain"],
            "plan": {"intent": "customer_segmentation", "metrics": ["current_total_asset", "net_asset_inflow_90d", "fund_holding_amount"], "filters": ["total_asset>500000", "net_flow_amount_90d>100000", "fund_holding=exists"], "limit": 30},
            "sql": "select distinct c.customer_no, a.total_asset as current_total_asset, round(f.net_flow_amount_90d, 2) as net_asset_inflow_90d from mart.customer_info c join mart.customer_current_asset a on a.customer_id = c.customer_id join mart.customer_net_flow_90d f on f.customer_id = c.customer_id join mart.customer_position_daily p on p.customer_id = c.customer_id and p.as_of_date = a.as_of_date join mart.product_info pi on pi.product_id = p.product_id and pi.product_type = 'fund' where a.total_asset > 500000 and f.net_flow_amount_90d > 100000 limit 30",
        },
        {
            "code": "SYN-012",
            "question": "按产品类型统计近90天交易客户数和交易金额",
            "difficulty": "complex",
            "tags": ["product", "trade", "group_by"],
            "plan": {"intent": "metric_query", "metrics": ["customer_count", "trade_amount_90d"], "dimensions": ["product_type"]},
            "sql": "select p.product_type, count(distinct t.customer_id)::integer as customer_count, round(sum(t.trade_amount), 2) as trade_amount_90d from mart.customer_trade t join mart.product_info p on p.product_id = t.product_id where t.trade_date > (select max(as_of_date) - interval '90 days' from mart.customer_asset_daily) group by p.product_type order by p.product_type",
        },
        {
            "code": "SYN-013",
            "question": "按营销活动统计已响应客户数和响应率",
            "difficulty": "complex",
            "tags": ["marketing", "campaign", "ratio"],
            "plan": {"intent": "marketing_effect_analysis", "metrics": ["response_customer_count", "response_rate"], "dimensions": ["campaign"]},
            "sql": "select c.campaign_code, count(distinct t.customer_id) filter (where t.response_status = 'responded')::integer as response_customer_count, round((count(*) filter (where t.response_status = 'responded'))::numeric / nullif(count(*), 0), 4) as response_rate from mart.marketing_campaign c left join mart.marketing_touch t on t.campaign_id = c.campaign_id group by c.campaign_code order by c.campaign_code",
        },
        {
            "code": "SYN-014",
            "question": "高净值客户有多少",
            "difficulty": "simple",
            "tags": ["clarification", "asset_definition"],
            "plan": {"intent": "metric_query", "clarification_fields": ["高净值客户"]},
            "expected_status": "needs_clarification",
        },
        {
            "code": "SYN-015",
            "question": "给我活跃客户名单",
            "difficulty": "medium",
            "tags": ["clarification", "activity_definition"],
            "plan": {"intent": "customer_segmentation", "clarification_fields": ["活跃客户"]},
            "expected_status": "needs_clarification",
        },
    ]
    for case in cases:
        expected_status = case.get("expected_status", "completed")
        expected_result = (
            _expected_result(cur, case["sql"])
            if expected_status == "completed"
            else Jsonb({"clarification_fields": case["plan"]["clarification_fields"]})
        )
        cur.execute(
            """
            insert into evaluation.eval_cases
                (case_code, question, difficulty, scenario, expected_query_plan, expected_sql,
                 expected_result, scoring_config, dataset_version, source_type, expected_status, tags)
            values
                (%s, %s, %s, 'customer_marketing', %s, %s, %s, %s,
                 'synthetic-v1', 'synthetic', %s, %s)
            on conflict (case_code) do update set
                question = excluded.question,
                difficulty = excluded.difficulty,
                expected_query_plan = excluded.expected_query_plan,
                expected_sql = excluded.expected_sql,
                expected_result = excluded.expected_result,
                scoring_config = excluded.scoring_config,
                dataset_version = excluded.dataset_version,
                source_type = excluded.source_type,
                expected_status = excluded.expected_status,
                tags = excluded.tags,
                updated_at = now()
            """,
            (
                case["code"],
                case["question"],
                case["difficulty"],
                Jsonb(case["plan"]),
                case.get("sql"),
                expected_result,
                Jsonb({"result_comparison": "unordered", "numeric_tolerance": 0.01}),
                expected_status,
                Jsonb(case["tags"]),
            ),
        )
    print(f"Seeded {len(cases)} deterministic evaluation cases with expected results.")


def verify_seed(cur: Cursor[Any]) -> None:
    checks = [
        ("mart.customer_info", "select count(*) from mart.customer_info"),
        ("mart.customer_asset_daily", "select count(*) from mart.customer_asset_daily"),
        ("mart.customer_trade", "select count(*) from mart.customer_trade"),
        ("mart.customer_asset_flow", "select count(*) from mart.customer_asset_flow"),
        ("metadata.metric_metadata", "select count(*) from metadata.metric_metadata"),
        ("mart.customer_current_asset", "select count(*) from mart.customer_current_asset"),
    ]
    for label, sql in checks:
        cur.execute(sql)
        count = cur.fetchone()[0]
        print(f"{label}: {count}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed synthetic finance-agent data.")
    parser.add_argument("--database-url", default=get_default_database_url())
    parser.add_argument("--customers", type=int, default=500)
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--anchor-date", default="2026-06-30")
    parser.add_argument("--reset", action="store_true", help="Truncate synthetic mart/metadata data first.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    anchor_date = date.fromisoformat(args.anchor_date)
    database_url = normalize_database_url(args.database_url)

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            if args.reset:
                reset_seed_data(cur)
                print("Reset existing synthetic mart and metadata data.")
            seed_business_data(cur, args.customers, args.days, anchor_date)
            seed_metadata(cur)
            seed_evaluation_cases(cur)
            verify_seed(cur)
        conn.commit()


if __name__ == "__main__":
    main()
