from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.schemas.query_plan import QueryPlan
from app.services.sql_executor import SQLExecutionResult


@dataclass(slots=True)
class AnswerRenderResult:
    answer: str
    row_count: int
    preview_row_count: int
    columns: list[str]
    grain: str | None
    truncated: bool
    renderer: str = "deterministic_result_renderer"

    def to_dict(self) -> dict[str, object]:
        return {
            "renderer": self.renderer,
            "row_count": self.row_count,
            "preview_row_count": self.preview_row_count,
            "columns": self.columns,
            "grain": self.grain,
            "truncated": self.truncated,
        }


class AnswerActor:
    """Render a concise user-facing answer from reviewed database results."""

    def render(
        self,
        question: str,
        query_plan: QueryPlan,
        execution_result: SQLExecutionResult,
        preview_rows: list[dict[str, Any]],
    ) -> AnswerRenderResult:
        columns = list(execution_result.columns)
        grain = query_plan.grain.level if query_plan.grain else None
        row_count = max(0, execution_result.row_count)
        preview_row_count = len(preview_rows)

        if execution_result.status != "success":
            answer = execution_result.error_message or "查询执行失败，未生成可用结果。"
            return AnswerRenderResult(
                answer=answer,
                row_count=0,
                preview_row_count=0,
                columns=columns,
                grain=grain,
                truncated=execution_result.truncated,
            )

        if row_count == 0:
            answer = "查询已完成，未找到满足条件的数据。"
        else:
            answer = self._success_answer(
                row_count=row_count,
                preview_row_count=preview_row_count,
                columns=columns,
                grain=grain,
                preview_rows=preview_rows,
                truncated=execution_result.truncated,
            )

        return AnswerRenderResult(
            answer=answer,
            row_count=row_count,
            preview_row_count=preview_row_count,
            columns=columns,
            grain=grain,
            truncated=execution_result.truncated,
        )

    def _success_answer(
        self,
        row_count: int,
        preview_row_count: int,
        columns: list[str],
        grain: str | None,
        preview_rows: list[dict[str, Any]],
        truncated: bool,
    ) -> str:
        parts = [f"查询已完成，本次查询返回 {row_count} 条记录。"]
        if grain:
            parts.append(f"结果粒度为 {self._grain_label(grain)}。")
        if columns:
            parts.append(f"结果字段包括：{', '.join(columns)}。")

        single_row_summary = self._single_row_summary(preview_rows, columns)
        if single_row_summary:
            parts.append(f"结果摘要：{single_row_summary}。")

        if truncated:
            parts.append(
                f"结果超过系统最大返回行数，当前仅保留前 {row_count} 条用于安全预览。"
            )
        elif preview_row_count < row_count:
            parts.append(f"当前响应展示前 {preview_row_count} 条预览，明细见 result_preview。")
        elif preview_row_count > 0:
            parts.append("明细见 result_preview。")
        return "".join(parts)

    def _single_row_summary(
        self, preview_rows: list[dict[str, Any]], columns: list[str]
    ) -> str | None:
        if len(preview_rows) != 1 or len(columns) > 5:
            return None
        row = preview_rows[0]
        items = []
        for column in columns:
            value = row.get(column)
            if value is None:
                continue
            items.append(f"{column}={value}")
        return "，".join(items[:5]) if items else None

    def _grain_label(self, grain: str) -> str:
        labels = {
            "customer": "客户级",
            "manager": "服务经理级",
            "product": "产品级",
            "campaign": "营销活动级",
            "aggregate": "汇总级",
        }
        return labels.get(grain, grain)
