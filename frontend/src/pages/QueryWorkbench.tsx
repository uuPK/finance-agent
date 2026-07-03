import { Play, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { runQuery } from "../api/client";
import { Card } from "../components/Card";
import type { QueryResponse } from "../types/query";

const examples = [
  "查询当前资产大于50万的客户数量",
  "查询近三个月交易次数超过3次且当前资产大于50万的客户列表",
  "找出近三个月资产净流入明显但尚未持有基金产品的客户"
];

export function QueryWorkbench() {
  const [question, setQuestion] = useState(examples[0]);
  const [response, setResponse] = useState<QueryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleRun() {
    setLoading(true);
    setError(null);
    try {
      const result = await runQuery({ question, include_debug: true });
      setResponse(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "查询失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5 p-6">
      <div>
        <h1 className="text-2xl font-semibold">智能问数</h1>
        <p className="mt-1 text-sm text-muted">自然语言到 QueryPlan、SQL、Guardrail 和结果预览。</p>
      </div>

      <Card title="问题输入" description="先用样例问题验证端到端链路，后续接入真实元数据和 LLM。">
        <div className="flex flex-wrap gap-2">
          {examples.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setQuestion(item)}
              className="rounded-md border border-line px-3 py-2 text-sm hover:bg-surface"
            >
              {item}
            </button>
          ))}
        </div>
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          className="mt-4 min-h-28 w-full rounded-md border border-line p-3 outline-none focus:border-accent"
        />
        <div className="mt-4 flex items-center gap-3">
          <button
            type="button"
            onClick={handleRun}
            disabled={loading || question.trim().length === 0}
            className="inline-flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Play className="h-4 w-4" />
            {loading ? "查询中" : "运行查询"}
          </button>
          {error ? <span className="text-sm text-red-600">{error}</span> : null}
        </div>
      </Card>

      {response ? (
        <div className="grid grid-cols-2 gap-5">
          <Card title="QueryPlan" description="用于约束 SQL 生成的中间表示。">
            <pre className="max-h-80 overflow-auto rounded-md bg-surface p-3 text-xs">
              {JSON.stringify(response.query_plan, null, 2)}
            </pre>
          </Card>

          <Card title="SQL" description="初始化阶段返回占位 SQL，后续接入真实 SQLActor。">
            <pre className="max-h-80 overflow-auto rounded-md bg-surface p-3 text-xs">
              {response.sql}
            </pre>
          </Card>

          <Card title="Guardrail" description="展示安全和合法性检查。">
            <div className="space-y-3">
              {response.guardrail_checks.map((item) => (
                <div key={item.name} className="flex gap-3 rounded-md border border-line p-3">
                  <ShieldCheck className="mt-0.5 h-4 w-4 text-accent" />
                  <div>
                    <div className="text-sm font-medium">{item.name}</div>
                    <div className="text-sm text-muted">{item.message}</div>
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card title="结果预览" description={`耗时 ${response.elapsed_ms} ms，状态 ${response.status}`}>
            <div className="overflow-auto rounded-md border border-line">
              <table className="w-full border-collapse text-sm">
                <tbody>
                  {response.result_preview.map((row, index) => (
                    <tr key={index} className="border-b border-line last:border-0">
                      {Object.entries(row).map(([key, value]) => (
                        <td key={key} className="px-3 py-2">
                          <span className="text-muted">{key}: </span>
                          {String(value)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-4 text-sm text-muted">{response.answer}</p>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
