import { BookOpen, Database, GitBranch, Library, Ruler, Search, Tags } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  getMetadataOverview,
  getMetadataTable,
  listMetadataExamples,
  listMetadataJoins,
  listMetadataMetrics,
  listMetadataTables,
  listMetadataTerms
} from "../api/client";
import type {
  MetadataBusinessTerm,
  MetadataJoin,
  MetadataMetric,
  MetadataOverview,
  MetadataQuestionExample,
  MetadataTable,
  MetadataTableDetail
} from "../types/query";

type TabKey = "tables" | "metrics" | "terms" | "joins" | "examples";
const tabs: Array<{ key: TabKey; label: string; icon: typeof Database }> = [
  { key: "tables", label: "数据表", icon: Database },
  { key: "metrics", label: "指标", icon: Ruler },
  { key: "terms", label: "业务术语", icon: Tags },
  { key: "joins", label: "关联关系", icon: GitBranch },
  { key: "examples", label: "问法样例", icon: Library }
];

export function MetadataPage() {
  const [overview, setOverview] = useState<MetadataOverview | null>(null);
  const [tables, setTables] = useState<MetadataTable[]>([]);
  const [metrics, setMetrics] = useState<MetadataMetric[]>([]);
  const [terms, setTerms] = useState<MetadataBusinessTerm[]>([]);
  const [joins, setJoins] = useState<MetadataJoin[]>([]);
  const [examples, setExamples] = useState<MetadataQuestionExample[]>([]);
  const [tab, setTab] = useState<TabKey>("tables");
  const [search, setSearch] = useState("");
  const [selectedTable, setSelectedTable] = useState<MetadataTableDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      getMetadataOverview(), listMetadataTables(), listMetadataMetrics(), listMetadataTerms(),
      listMetadataJoins(), listMetadataExamples()
    ]).then(([nextOverview, nextTables, nextMetrics, nextTerms, nextJoins, nextExamples]) => {
      setOverview(nextOverview); setTables(nextTables); setMetrics(nextMetrics); setTerms(nextTerms);
      setJoins(nextJoins); setExamples(nextExamples);
    }).catch((reason: Error) => setError(reason.message));
  }, []);

  const filtered = useMemo(() => {
    const normalized = search.trim().toLowerCase();
    if (!normalized) return { tables, metrics, terms };
    const matches = (value: string) => value.toLowerCase().includes(normalized);
    return {
      tables: tables.filter((item) => matches(`${item.table_name} ${item.display_name} ${item.domain} ${item.description}`)),
      metrics: metrics.filter((item) => matches(`${item.metric_code} ${item.metric_name} ${item.description}`)),
      terms: terms.filter((item) => matches(`${item.term} ${item.definition} ${item.synonyms.join(" ")}`))
    };
  }, [metrics, search, tables, terms]);

  async function openTable(table: MetadataTable) {
    try {
      setError("");
      setSelectedTable(await getMetadataTable(table.table_name));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法读取表详情");
    }
  }

  return <div className="min-h-screen bg-surface px-4 py-6 sm:px-6">
    <div className="mx-auto max-w-7xl">
      <header className="border-b border-line pb-5"><h1 className="text-xl font-semibold text-ink">元数据中心</h1><p className="mt-1 text-sm text-muted">业务定义、指标口径与受控关联路径，是 Agent 生成与审核的共同证据源。</p></header>
      <section className="mt-5 grid border-l border-t border-line bg-white sm:grid-cols-3 lg:grid-cols-6">
        {[
          ["数据表", overview?.table_count], ["字段", overview?.column_count], ["指标", overview?.metric_count],
          ["业务术语", overview?.term_count], ["关联路径", overview?.join_count], ["问法样例", overview?.example_count]
        ].map(([label, value]) => <div key={String(label)} className="border-b border-r border-line p-4"><div className="text-2xl font-semibold text-ink">{value ?? "--"}</div><div className="mt-1 text-xs text-muted">{label}</div></div>)}
      </section>
      <section className="mt-5 border border-line bg-white">
        <div className="flex flex-col gap-3 border-b border-line p-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex overflow-x-auto"><div className="flex min-w-max gap-1">{tabs.map((item) => { const Icon = item.icon; return <button key={item.key} type="button" onClick={() => { setTab(item.key); setSelectedTable(null); }} className={`inline-flex h-9 items-center gap-2 px-3 text-sm ${tab === item.key ? "bg-slate-900 text-white" : "text-muted hover:bg-slate-100"}`}><Icon className="h-4 w-4" />{item.label}</button>; })}</div></div>
          {(["tables", "metrics", "terms"] as TabKey[]).includes(tab) && <label className="flex h-9 items-center gap-2 border border-line px-2 text-muted"><Search className="h-4 w-4" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="检索名称、口径或描述" className="w-56 border-0 text-sm text-ink outline-none" /></label>}
        </div>
        {error && <p className="border-b border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">{error}</p>}
        {tab === "tables" && <TableCatalog items={filtered.tables} selected={selectedTable?.table_name} onOpen={openTable} />}
        {tab === "metrics" && <MetricCatalog items={filtered.metrics} />}
        {tab === "terms" && <TermCatalog items={filtered.terms} />}
        {tab === "joins" && <JoinCatalog items={joins} />}
        {tab === "examples" && <ExampleCatalog items={examples} />}
      </section>
      {selectedTable && <TableDetail table={selectedTable} onClose={() => setSelectedTable(null)} />}
    </div>
  </div>;
}

function TableCatalog({ items, selected, onOpen }: { items: MetadataTable[]; selected?: string; onOpen: (item: MetadataTable) => void }) {
  return <div className="divide-y divide-line">{items.map((item) => <button key={item.table_name} type="button" onClick={() => void onOpen(item)} className={`grid w-full gap-2 p-4 text-left hover:bg-slate-50 sm:grid-cols-[minmax(200px,1fr)_120px_100px] ${selected === item.table_name ? "bg-slate-50" : ""}`}><div><div className="text-sm font-semibold text-ink">{item.display_name}</div><div className="mt-1 font-mono text-xs text-muted">{item.schema_name}.{item.table_name}</div><p className="mt-2 text-sm text-muted">{item.description}</p></div><span className="self-center text-sm text-muted">{item.domain}</span><span className="self-center text-sm text-muted">{item.column_count} 字段</span></button>)}{!items.length && <Empty />}</div>;
}
function MetricCatalog({ items }: { items: MetadataMetric[] }) { return <div className="divide-y divide-line">{items.map((item) => <div key={item.metric_code} className="grid gap-2 p-4 sm:grid-cols-[minmax(240px,1fr)_180px]"><div><div className="text-sm font-semibold text-ink">{item.metric_name}</div><div className="mt-1 font-mono text-xs text-muted">{item.metric_code}</div><p className="mt-2 text-sm text-muted">{item.description}</p></div><div className="text-xs text-muted"><div>{item.default_aggregation} / {item.grain}</div><div className="mt-2 break-words">{item.formula}</div></div></div>)}{!items.length && <Empty />}</div>; }
function TermCatalog({ items }: { items: MetadataBusinessTerm[] }) { return <div className="divide-y divide-line">{items.map((item) => <div key={item.term} className="p-4"><div className="flex flex-wrap items-center gap-2"><h2 className="text-sm font-semibold text-ink">{item.term}</h2>{item.clarification_required && <span className="bg-amber-100 px-2 py-1 text-xs text-amber-800">需澄清</span>}</div><p className="mt-2 text-sm text-muted">{item.definition}</p><p className="mt-2 text-xs text-muted">同义词：{item.synonyms.join("、") || "--"}</p></div>)}{!items.length && <Empty />}</div>; }
function JoinCatalog({ items }: { items: MetadataJoin[] }) { return <div className="divide-y divide-line">{items.map((item) => <div key={`${item.left_table}:${item.left_column}:${item.right_table}`} className="grid gap-2 p-4 sm:grid-cols-[1fr_auto_1fr]"><span className="font-mono text-xs text-ink">{item.left_table}.{item.left_column}</span><span className="text-xs text-muted">{item.relationship_type}</span><span className="font-mono text-xs text-ink">{item.right_table}.{item.right_column}</span></div>)}{!items.length && <Empty />}</div>; }
function ExampleCatalog({ items }: { items: MetadataQuestionExample[] }) { return <div className="divide-y divide-line">{items.map((item) => <div key={item.question} className="p-4"><div className="flex flex-wrap gap-2"><span className="bg-slate-100 px-2 py-1 text-xs text-slate-700">{item.difficulty}</span><span className="text-xs text-muted">{item.tags.join(" / ")}</span></div><p className="mt-3 text-sm text-ink">{item.question}</p><pre className="mt-3 max-h-36 overflow-auto bg-slate-50 p-2 text-xs text-slate-700">{item.expected_sql}</pre></div>)}{!items.length && <Empty />}</div>; }
function TableDetail({ table, onClose }: { table: MetadataTableDetail; onClose: () => void }) { return <section className="mt-5 border border-line bg-white"><div className="flex items-center justify-between border-b border-line p-4"><div><h2 className="text-sm font-semibold text-ink">{table.display_name}</h2><p className="mt-1 font-mono text-xs text-muted">{table.schema_name}.{table.table_name} / {table.grain}</p></div><button type="button" onClick={onClose} className="h-8 border border-line px-2 text-sm text-ink">关闭</button></div><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead className="bg-slate-50 text-xs text-muted"><tr><th className="p-3">字段</th><th className="p-3">类型</th><th className="p-3">说明</th><th className="p-3">语义</th></tr></thead><tbody>{table.columns.map((column) => <tr key={column.column_name} className="border-t border-line"><td className="p-3 font-mono text-xs text-ink">{column.column_name}<span className="ml-2 font-sans text-muted">{column.display_name}</span></td><td className="p-3 text-muted">{column.data_type}</td><td className="p-3 text-muted">{column.description}</td><td className="p-3 text-muted">{[column.is_dimension && "维度", column.is_metric_source && "指标源", column.is_sensitive && "敏感"].filter(Boolean).join(" / ") || "--"}</td></tr>)}</tbody></table></div></section>; }
function Empty() { return <div className="p-8 text-center text-sm text-muted"><BookOpen className="mx-auto h-5 w-5" /><p className="mt-2">没有匹配的元数据记录。</p></div>; }
