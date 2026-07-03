import { Card } from "../components/Card";

export function HistoryPage() {
  return (
    <div className="space-y-5 p-6">
      <div>
        <h1 className="text-2xl font-semibold">查询历史</h1>
        <p className="mt-1 text-sm text-muted">后续记录问题、QueryPlan、SQL、修复次数、耗时和状态。</p>
      </div>
      <Card title="历史记录">
        <div className="rounded-md border border-dashed border-line p-8 text-center text-sm text-muted">
          暂无查询历史
        </div>
      </Card>
    </div>
  );
}
