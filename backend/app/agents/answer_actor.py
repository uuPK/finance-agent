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
    total_count: int | float | None = None
    total_count_column: str | None = None
    renderer: str = "deterministic_result_renderer"

    def to_dict(self) -> dict[str, object]:
        return {
            "renderer": self.renderer,
            "row_count": self.row_count,
            "preview_row_count": self.preview_row_count,
            "columns": self.columns,
            "grain": self.grain,
            "truncated": self.truncated,
            "total_count": self.total_count,
            "total_count_column": self.total_count_column,
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
            total_count, total_count_column = self._extract_total_count(
                preview_rows=preview_rows,
                columns=columns,
                grain=grain,
            )
            answer = self._success_answer(
                row_count=row_count,
                preview_row_count=preview_row_count,
                columns=columns,
                grain=grain,
                preview_rows=preview_rows,
                truncated=execution_result.truncated,
                total_count=total_count,
                total_count_column=total_count_column,
            )

        return AnswerRenderResult(
            answer=answer,
            row_count=row_count,
            preview_row_count=preview_row_count,
            columns=columns,
            grain=grain,
            truncated=execution_result.truncated,
            total_count=total_count if row_count else None,
            total_count_column=total_count_column if row_count else None,
        )

    def _success_answer(
        self,
        row_count: int,
        preview_row_count: int,
        columns: list[str],
        grain: str | None,
        preview_rows: list[dict[str, Any]],
        truncated: bool,
        total_count: int | float | None,
        total_count_column: str | None,
    ) -> str:
        if total_count is not None:
            return self._count_answer(
                row_count=row_count,
                preview_row_count=preview_row_count,
                columns=columns,
                grain=grain,
                preview_rows=preview_rows,
                truncated=truncated,
                total_count=total_count,
                total_count_column=total_count_column,
            )

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

    def _count_answer(
        self,
        row_count: int,
        preview_row_count: int,
        columns: list[str],
        grain: str | None,
        preview_rows: list[dict[str, Any]],
        truncated: bool,
        total_count: int | float,
        total_count_column: str | None,
    ) -> str:
        label = self._count_label(total_count_column)
        formatted_count = self._format_number(total_count)
        if grain == "aggregate":
            parts = [f"查询已完成，{label}为 {formatted_count}。"]
            single_row_summary = self._single_row_summary(preview_rows, columns)
            if single_row_summary:
                parts.append(f"结果摘要：{single_row_summary}。")
            return "".join(parts)

        parts = [f"查询已完成，共命中 {formatted_count} 条记录。"]
        if row_count:
            parts.append(f"本次查询返回 {row_count} 条记录。")
        if grain:
            parts.append(f"结果粒度为 {self._grain_label(grain)}。")
        if columns:
            parts.append(f"结果字段包括：{', '.join(columns)}。")
        if truncated:
            parts.append(f"结果超过系统最大返回行数，当前仅保留前 {row_count} 条用于安全预览。")
        elif preview_row_count < row_count:
            parts.append(f"当前响应展示前 {preview_row_count} 条预览，明细见 result_preview。")
        elif preview_row_count > 0:
            parts.append("明细见 result_preview。")
        return "".join(parts)

    def _extract_total_count(
        self,
        preview_rows: list[dict[str, Any]],
        columns: list[str],
        grain: str | None,
    ) -> tuple[int | float | None, str | None]:
        if not preview_rows:
            return None, None
        first_row = preview_rows[0]
        aliases = {
            "total_count",
            "customer_count",
            "count",
            "cnt",
            "总数",
            "数量",
            "客户数量",
            "客户数",
        }
        for column in columns:
            if column.lower() in aliases or column in aliases:
                value = first_row.get(column)
                if self._is_number(value):
                    return value, column

        if grain == "aggregate" and len(columns) == 1:
            column = columns[0]
            value = first_row.get(column)
            if self._is_number(value):
                return value, column
        return None, None

    def _is_number(self, value: object) -> bool:
        return isinstance(value, int | float) and not isinstance(value, bool)

    def _count_label(self, column: str | None) -> str:
        if column in {"customer_count", "客户数量", "客户数"}:
            return "客户数量"
        if column in {"total_count", "总数"}:
            return "总数"
        return "数量"

    def _format_number(self, value: int | float) -> str:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

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
