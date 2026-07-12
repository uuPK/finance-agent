import { Database, GitBranch, Library, Rows3, Ruler, Tags } from "lucide-react";

const metadataItems = [
  { name: "数据表", code: "table_metadata", icon: Database, description: "业务域、粒度与用途" },
  { name: "字段", code: "column_metadata", icon: Rows3, description: "类型、释义与敏感级别" },
  { name: "指标", code: "metric_metadata", icon: Ruler, description: "口径、公式与时间窗口" },
  { name: "业务词", code: "business_terms", icon: Tags, description: "同义词与默认解释" },
  { name: "关联关系", code: "join_relationships", icon: GitBranch, description: "受控表关联路径" },
  { name: "问法样例", code: "question_examples", icon: Library, description: "业务问题与标准计划" }
];

export function MetadataPage() {
  return (
    <div className="min-h-screen bg-surface px-4 py-6 sm:px-6">
      <div className="mx-auto max-w-6xl">
        <header><h1 className="text-xl font-semibold text-ink">元数据</h1><p className="mt-1 text-sm text-muted">Agent 生成和审核查询时使用的业务证据</p></header>
        <div className="mt-5 border-y border-line bg-white">
          {metadataItems.map((item) => {
            const Icon = item.icon;
            return (
              <div key={item.code} className="grid gap-3 border-b border-line px-4 py-4 last:border-0 sm:grid-cols-[36px_180px_1fr_auto] sm:items-center">
                <span className="grid h-9 w-9 place-items-center rounded bg-slate-100 text-slate-700"><Icon className="h-4 w-4" /></span>
                <div><div className="text-sm font-semibold text-ink">{item.name}</div><div className="mt-0.5 font-mono text-xs text-muted">{item.code}</div></div>
                <p className="text-sm text-muted">{item.description}</p>
                <span className="w-fit rounded bg-slate-100 px-2 py-1 text-xs text-slate-600">接口待接入</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
