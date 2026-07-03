import { BarChart3, Database, History, MessageSquareText } from "lucide-react";
import { useState } from "react";

import { EvaluationCenter } from "./pages/EvaluationCenter";
import { HistoryPage } from "./pages/HistoryPage";
import { MetadataPage } from "./pages/MetadataPage";
import { QueryWorkbench } from "./pages/QueryWorkbench";

type PageKey = "query" | "metadata" | "evaluation" | "history";

const navItems: Array<{ key: PageKey; label: string; icon: typeof MessageSquareText }> = [
  { key: "query", label: "智能问数", icon: MessageSquareText },
  { key: "metadata", label: "元数据", icon: Database },
  { key: "evaluation", label: "评测中心", icon: BarChart3 },
  { key: "history", label: "查询历史", icon: History }
];

export default function App() {
  const [page, setPage] = useState<PageKey>("query");

  const Page =
    page === "query"
      ? QueryWorkbench
      : page === "metadata"
        ? MetadataPage
        : page === "evaluation"
          ? EvaluationCenter
          : HistoryPage;

  return (
    <div className="min-h-screen bg-surface text-ink">
      <aside className="fixed inset-y-0 left-0 w-64 border-r border-line bg-white">
        <div className="border-b border-line px-6 py-5">
          <div className="text-lg font-semibold">Finance Agent</div>
          <div className="mt-1 text-sm text-muted">可信智能问数工作台</div>
        </div>
        <nav className="space-y-1 p-3">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = page === item.key;
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => setPage(item.key)}
                className={[
                  "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm",
                  active ? "bg-accent text-white" : "text-ink hover:bg-surface"
                ].join(" ")}
              >
                <Icon className="h-4 w-4" />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </aside>
      <main className="ml-64 min-h-screen">
        <Page />
      </main>
    </div>
  );
}
