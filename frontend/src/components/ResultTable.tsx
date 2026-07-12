import { flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { useMemo } from "react";

export function ResultTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  const columns = useMemo(
    () =>
      Object.keys(rows[0] ?? {}).map((key) => ({
        accessorKey: key,
        header: key,
        cell: ({ getValue }: { getValue: () => unknown }) => formatValue(getValue())
      })),
    [rows]
  );
  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() });

  if (!rows.length) {
    return <div className="border-y border-line py-12 text-center text-sm text-muted">查询没有返回数据</div>;
  }

  return (
    <div className="max-h-[420px] overflow-auto border border-line bg-white">
      <table className="w-full border-collapse text-left text-sm">
        <thead className="sticky top-0 z-10 bg-slate-50">
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id}>
              {group.headers.map((header) => (
                <th key={header.id} className="whitespace-nowrap border-b border-line px-3 py-2.5 font-semibold text-ink">
                  {flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id} className="border-b border-line last:border-0 hover:bg-slate-50/70">
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="max-w-80 whitespace-nowrap px-3 py-2.5 text-slate-700">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 4 }).format(value);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
