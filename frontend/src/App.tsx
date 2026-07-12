import { BarChart3, Database, History, Menu, MessageSquareText, X } from "lucide-react";
import { useState } from "react";

import { EvaluationCenter } from "./pages/EvaluationCenter";
import { HistoryPage } from "./pages/HistoryPage";
import { MetadataPage } from "./pages/MetadataPage";
import { QueryWorkbench } from "./pages/QueryWorkbench";

type PageKey = "query" | "metadata" | "evaluation" | "history";
const activeRunStorageKey = "finance-agent-active-run-id";

const navItems = [
  { key: "query" as const, label: "智能问数", icon: MessageSquareText },
  { key: "history" as const, label: "查询历史", icon: History },
  { key: "metadata" as const, label: "元数据", icon: Database },
  { key: "evaluation" as const, label: "评测中心", icon: BarChart3 }
];

export default function App() {
  const [page, setPage] = useState<PageKey>("query");
  const [activeRunId, setActiveRunIdState] = useState<string | null>(() =>
    window.localStorage.getItem(activeRunStorageKey)
  );
  const [mobileNav, setMobileNav] = useState(false);

  function navigate(next: PageKey) {
    setPage(next);
    setMobileNav(false);
  }

  function setActiveRunId(queryId: string | null) {
    setActiveRunIdState(queryId);
    if (queryId) window.localStorage.setItem(activeRunStorageKey, queryId);
    else window.localStorage.removeItem(activeRunStorageKey);
  }

  const content = page === "query" ? (
    <QueryWorkbench activeRunId={activeRunId} onRunChange={setActiveRunId} />
  ) : page === "history" ? (
    <HistoryPage onOpen={(queryId) => { setActiveRunId(queryId); navigate("query"); }} />
  ) : page === "metadata" ? <MetadataPage /> : <EvaluationCenter />;

  return (
    <div className="min-h-screen bg-surface text-ink">
      <header className="sticky top-0 z-40 flex h-16 items-center justify-between border-b border-line bg-white px-4 lg:hidden">
        <div><div className="font-semibold">Finance Agent</div><div className="text-xs text-muted">可信问数工作台</div></div>
        <button type="button" title="打开导航" onClick={() => setMobileNav((open) => !open)} className="grid h-9 w-9 place-items-center rounded hover:bg-slate-100">{mobileNav ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}</button>
      </header>
      <aside className={`${mobileNav ? "block" : "hidden"} fixed inset-x-0 top-16 z-30 border-b border-line bg-white lg:inset-y-0 lg:left-0 lg:top-0 lg:block lg:w-56 lg:border-b-0 lg:border-r`}>
        <div className="hidden h-20 border-b border-line px-5 py-4 lg:block"><div className="text-base font-semibold">Finance Agent</div><div className="mt-1 text-xs text-muted">可信智能问数</div></div>
        <nav className="grid grid-cols-2 gap-1 p-3 lg:block lg:space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = page === item.key;
            return <button key={item.key} type="button" onClick={() => navigate(item.key)} className={`flex w-full items-center gap-3 rounded px-3 py-2.5 text-left text-sm ${active ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-100"}`}><Icon className="h-4 w-4" />{item.label}</button>;
          })}
        </nav>
        <div className="absolute bottom-0 hidden w-full border-t border-line p-4 text-xs leading-5 text-muted lg:block">业务查询过程全程可追踪<br />数据结果经过多轮审核</div>
      </aside>
      <main className="min-h-screen lg:ml-56">{content}</main>
    </div>
  );
}
