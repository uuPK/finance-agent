import { BookOpen, Database, GitBranch, Library, Pencil, Plus, Ruler, Save, Search, ShieldCheck, Tags, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createMetadataRecord, deactivateMetadataRecord, getMetadataOverview, getMetadataTable,
  listMetadataExamples, listMetadataJoins, listMetadataMetrics, listMetadataRules,
  listMetadataTables, listMetadataTerms, updateMetadataRecord
} from "../api/client";
import type {
  MetadataBusinessTerm, MetadataEditableKind, MetadataJoin, MetadataMetric, MetadataOverview,
  MetadataQuestionExample, MetadataRuleConstraint, MetadataTable, MetadataTableDetail
} from "../types/query";

type TabKey = "tables" | MetadataEditableKind;
type EditableRecord = MetadataMetric | MetadataBusinessTerm | MetadataJoin | MetadataQuestionExample | MetadataRuleConstraint;

const tabs: Array<{ key: TabKey; label: string; icon: typeof Database }> = [
  { key: "tables", label: "数据表（只读）", icon: Database }, { key: "metric", label: "指标", icon: Ruler },
  { key: "term", label: "业务术语", icon: Tags }, { key: "join", label: "关联关系", icon: GitBranch },
  { key: "example", label: "问法样例", icon: Library }, { key: "rule", label: "规则约束", icon: ShieldCheck }
];
const endpoint: Record<MetadataEditableKind, string> = { metric: "metrics", term: "terms", join: "joins", example: "examples", rule: "rules" };
const templates: Record<MetadataEditableKind, Record<string, unknown>> = {
  metric: { metric_code: "new_metric", metric_name: "新指标", description: "", formula: "sum(...) ", default_aggregation: "sum", grain: "customer", source_tables: [], required_filters: [], owner: "manual_catalog" },
  term: { term: "新业务术语", definition: "请填写可验证的业务定义。", synonyms: [], default_plan_fragment: {}, clarification_required: false },
  join: { left_schema: "mart", left_table: "", left_column: "", right_schema: "mart", right_table: "", right_column: "", relationship_type: "many_to_one", description: "" },
  example: { question: "", difficulty: "medium", scenario: "customer_marketing", expected_query_plan: {}, expected_sql: "", expected_result: {}, tags: ["manual_catalog"] },
  rule: { rule_code: "new_rule", rule_name: "新规则", rule_type: "semantic_guardrail", config: {}, severity: "error", description: "" }
};

function record(value: unknown): Record<string, unknown> { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function identifier(kind: MetadataEditableKind, item: EditableRecord): string | number { const value = record(item); return kind === "metric" ? String(value.metric_code) : kind === "term" ? String(value.term) : kind === "rule" ? String(value.rule_code) : Number(value.id); }
function payload(item: EditableRecord): Record<string, unknown> { const value = { ...record(item) }; delete value.id; return value; }

export function MetadataPage() {
  const [overview, setOverview] = useState<MetadataOverview | null>(null);
  const [tables, setTables] = useState<MetadataTable[]>([]);
  const [metrics, setMetrics] = useState<MetadataMetric[]>([]);
  const [terms, setTerms] = useState<MetadataBusinessTerm[]>([]);
  const [joins, setJoins] = useState<MetadataJoin[]>([]);
  const [examples, setExamples] = useState<MetadataQuestionExample[]>([]);
  const [rules, setRules] = useState<MetadataRuleConstraint[]>([]);
  const [tab, setTab] = useState<TabKey>("tables");
  const [search, setSearch] = useState("");
  const [selectedTable, setSelectedTable] = useState<MetadataTableDetail | null>(null);
  const [editor, setEditor] = useState<{ kind: MetadataEditableKind; item?: EditableRecord } | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    const results = await Promise.all([getMetadataOverview(), listMetadataTables(), listMetadataMetrics(), listMetadataTerms(), listMetadataJoins(), listMetadataExamples(), listMetadataRules()]);
    setOverview(results[0]); setTables(results[1]); setMetrics(results[2]); setTerms(results[3]); setJoins(results[4]); setExamples(results[5]); setRules(results[6]);
  }, []);
  useEffect(() => { void load().catch((reason: Error) => setError(reason.message)); }, [load]);

  const items = useMemo<EditableRecord[]>(() => tab === "metric" ? metrics : tab === "term" ? terms : tab === "join" ? joins : tab === "example" ? examples : tab === "rule" ? rules : [], [examples, joins, metrics, rules, tab, terms]);
  const matchingItems = useMemo(() => { const text = search.trim().toLowerCase(); return text ? items.filter((item) => JSON.stringify(item).toLowerCase().includes(text)) : items; }, [items, search]);
  const matchingTables = useMemo(() => { const text = search.trim().toLowerCase(); return text ? tables.filter((item) => `${item.table_name} ${item.display_name} ${item.domain} ${item.description}`.toLowerCase().includes(text)) : tables; }, [search, tables]);

  async function openTable(table: MetadataTable) { try { setError(""); setSelectedTable(await getMetadataTable(table.table_name)); } catch (reason) { setError(reason instanceof Error ? reason.message : "无法读取表详情"); } }
  async function save(kind: MetadataEditableKind, value: Record<string, unknown>, item?: EditableRecord) { try { setError(""); if (item) await updateMetadataRecord(endpoint[kind], identifier(kind, item), value); else await createMetadataRecord(endpoint[kind], value); await load(); setEditor(null); setMessage(item ? "元数据已更新，后续问数将使用新口径。" : "元数据已创建，后续问数将检索该定义。"); } catch (reason) { setError(reason instanceof Error ? reason.message : "无法保存元数据"); } }
  async function deactivate(kind: MetadataEditableKind, item: EditableRecord) { if (!window.confirm("确认停用？历史审计保留，但后续检索不会使用此条元数据。")) return; try { await deactivateMetadataRecord(endpoint[kind], identifier(kind, item)); await load(); setMessage("元数据已停用。"); } catch (reason) { setError(reason instanceof Error ? reason.message : "无法停用元数据"); } }

  const editableKind = tab === "tables" ? null : tab;
  return <div className="min-h-screen bg-surface px-4 py-6 sm:px-6"><div className="mx-auto max-w-7xl">
    <header className="border-b border-line pb-5"><h1 className="text-xl font-semibold text-ink">元数据中心</h1><p className="mt-1 text-sm text-muted">官方数据表及字段只能查看；指标、术语、关联、样例和规则可由人工受控维护。</p></header>
    <section className="mt-5 grid border-l border-t border-line bg-white sm:grid-cols-3 lg:grid-cols-6">{[["数据表", overview?.table_count], ["字段", overview?.column_count], ["指标", overview?.metric_count], ["业务术语", overview?.term_count], ["关联路径", overview?.join_count], ["问法样例", overview?.example_count]].map(([label, value]) => <div key={String(label)} className="border-b border-r border-line p-4"><div className="text-2xl font-semibold text-ink">{value ?? "--"}</div><div className="mt-1 text-xs text-muted">{label}</div></div>)}</section>
    <section className="mt-5 border border-line bg-white"><div className="flex flex-col gap-3 border-b border-line p-3 lg:flex-row lg:items-center lg:justify-between"><div className="flex overflow-x-auto"><div className="flex min-w-max gap-1">{tabs.map((entry) => { const Icon = entry.icon; return <button key={entry.key} type="button" onClick={() => { setTab(entry.key); setSelectedTable(null); setEditor(null); }} className={`inline-flex h-9 items-center gap-2 px-3 text-sm ${tab === entry.key ? "bg-slate-900 text-white" : "text-muted hover:bg-slate-100"}`}><Icon className="h-4 w-4" />{entry.label}</button>; })}</div></div><div className="flex gap-2"><label className="flex h-9 items-center gap-2 border border-line px-2 text-muted"><Search className="h-4 w-4" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="检索名称、口径或描述" className="w-48 border-0 text-sm text-ink outline-none" /></label>{editableKind && <button type="button" onClick={() => setEditor({ kind: editableKind })} className="inline-flex h-9 items-center gap-1 bg-slate-900 px-3 text-sm text-white"><Plus className="h-4 w-4" />新增</button>}</div></div>
      {error && <p className="border-b border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">{error}</p>}{message && <p className="border-b border-teal-200 bg-teal-50 px-4 py-2 text-sm text-teal-800">{message}</p>}
      {tab === "tables" ? <TableCatalog items={matchingTables} selected={selectedTable?.table_name} onOpen={openTable} /> : <EditableCatalog kind={tab} items={matchingItems} onEdit={(item) => setEditor({ kind: tab, item })} onDeactivate={(item) => void deactivate(tab, item)} />}
    </section>{selectedTable && <TableDetail table={selectedTable} onClose={() => setSelectedTable(null)} />}{editor && <MetadataEditor kind={editor.kind} item={editor.item} onClose={() => setEditor(null)} onSave={save} />}
  </div></div>;
}

function MetadataEditor({ kind, item, onClose, onSave }: { kind: MetadataEditableKind; item?: EditableRecord; onClose: () => void; onSave: (kind: MetadataEditableKind, value: Record<string, unknown>, item?: EditableRecord) => Promise<void> }) {
  const [value, setValue] = useState(() => JSON.stringify(item ? payload(item) : templates[kind], null, 2));
  const [error, setError] = useState("");
  async function submit() { try { const next = JSON.parse(value); if (!next || typeof next !== "object" || Array.isArray(next)) throw new Error("内容必须是 JSON 对象。"); await onSave(kind, next as Record<string, unknown>, item); } catch (reason) { setError(reason instanceof Error ? reason.message : "JSON 格式不正确"); } }
  const identity = kind === "metric" ? "metric_code" : kind === "term" ? "term" : kind === "rule" ? "rule_code" : "记录 ID";
  return <section className="fixed inset-0 z-50 overflow-auto bg-slate-950/30 p-4"><div className="mx-auto mt-8 max-w-3xl border border-line bg-white shadow-xl"><div className="flex items-start justify-between border-b border-line p-4"><div><h2 className="text-base font-semibold text-ink">{item ? "编辑" : "新增"}{tabs.find((entry) => entry.key === kind)?.label}</h2><p className="mt-1 text-xs leading-5 text-muted">{item ? `${identity} 是稳定标识，编辑时不可改名。` : "保存前会验证关联的数据表与字段均存在于官方 mart schema。"}</p></div><button type="button" onClick={onClose} className="p-1 text-muted"><X className="h-5 w-5" /></button></div><div className="p-4"><label className="text-xs font-medium text-muted">元数据 JSON<textarea value={value} onChange={(event) => setValue(event.target.value)} className="mt-2 min-h-[360px] w-full resize-y border border-line p-3 font-mono text-xs leading-5 text-ink" /></label>{error && <p className="mt-2 text-sm text-rose-700">{error}</p>}<div className="mt-4 flex justify-end gap-2"><button type="button" onClick={onClose} className="h-9 border border-line px-3 text-sm text-ink">取消</button><button type="button" onClick={() => void submit()} className="inline-flex h-9 items-center gap-2 bg-slate-900 px-3 text-sm text-white"><Save className="h-4 w-4" />保存</button></div></div></div></section>;
}

function TableCatalog({ items, selected, onOpen }: { items: MetadataTable[]; selected?: string; onOpen: (item: MetadataTable) => void }) { return <div className="divide-y divide-line">{items.map((item) => <button key={item.table_name} type="button" onClick={() => void onOpen(item)} className={`grid w-full gap-2 p-4 text-left hover:bg-slate-50 sm:grid-cols-[minmax(200px,1fr)_120px_100px] ${selected === item.table_name ? "bg-slate-50" : ""}`}><div><div className="text-sm font-semibold text-ink">{item.display_name}</div><div className="mt-1 font-mono text-xs text-muted">{item.schema_name}.{item.table_name}</div><p className="mt-2 text-sm text-muted">{item.description}</p></div><span className="self-center text-sm text-muted">{item.domain}</span><span className="self-center text-sm text-muted">{item.column_count} 字段</span></button>)}{!items.length && <Empty />}</div>; }
function EditableCatalog({ kind, items, onEdit, onDeactivate }: { kind: MetadataEditableKind; items: EditableRecord[]; onEdit: (item: EditableRecord) => void; onDeactivate: (item: EditableRecord) => void }) { return <div className="divide-y divide-line">{items.map((item) => { const value = record(item); const title = String(value.metric_name ?? value.term ?? value.rule_name ?? value.question ?? `${value.left_table}.${value.left_column} → ${value.right_table}.${value.right_column}`); const subtitle = String(value.metric_code ?? value.rule_code ?? value.relationship_type ?? value.difficulty ?? ""); const description = String(value.description ?? value.definition ?? ""); return <div key={`${kind}-${identifier(kind, item)}`} className="flex gap-4 p-4"><div className="min-w-0 flex-1"><h2 className="truncate text-sm font-semibold text-ink">{title}</h2><p className="mt-1 font-mono text-xs text-muted">{subtitle}</p>{description && <p className="mt-2 line-clamp-2 text-sm text-muted">{description}</p>}</div><div className="flex shrink-0 items-start gap-1"><button type="button" onClick={() => onEdit(item)} className="inline-flex h-8 items-center gap-1 border border-line px-2 text-xs text-ink"><Pencil className="h-3.5 w-3.5" />编辑</button><button type="button" onClick={() => onDeactivate(item)} className="inline-flex h-8 items-center gap-1 border border-rose-200 px-2 text-xs text-rose-700"><Trash2 className="h-3.5 w-3.5" />停用</button></div></div>; })}{!items.length && <Empty />}</div>; }
function TableDetail({ table, onClose }: { table: MetadataTableDetail; onClose: () => void }) { return <section className="mt-5 border border-line bg-white"><div className="flex items-center justify-between border-b border-line p-4"><div><h2 className="text-sm font-semibold text-ink">{table.display_name}</h2><p className="mt-1 font-mono text-xs text-muted">{table.schema_name}.{table.table_name} / {table.grain}</p></div><button type="button" onClick={onClose} className="h-8 border border-line px-2 text-sm text-ink">关闭</button></div><div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead className="bg-slate-50 text-xs text-muted"><tr><th className="p-3">字段</th><th className="p-3">类型</th><th className="p-3">说明</th><th className="p-3">语义</th></tr></thead><tbody>{table.columns.map((column) => <tr key={column.column_name} className="border-t border-line"><td className="p-3 font-mono text-xs text-ink">{column.column_name}<span className="ml-2 font-sans text-muted">{column.display_name}</span></td><td className="p-3 text-muted">{column.data_type}</td><td className="p-3 text-muted">{column.description}</td><td className="p-3 text-muted">{[column.is_dimension && "维度", column.is_metric_source && "指标源", column.is_sensitive && "敏感"].filter(Boolean).join(" / ") || "--"}</td></tr>)}</tbody></table></div></section>; }
function Empty() { return <div className="p-8 text-center text-sm text-muted"><BookOpen className="mx-auto h-5 w-5" /><p className="mt-2">没有匹配的元数据记录。</p></div>; }
