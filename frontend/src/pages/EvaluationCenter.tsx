import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Card } from "../components/Card";

const data = [
  { name: "SQL可执行率", value: 0 },
  { name: "一次通过率", value: 0 },
  { name: "修复后通过率", value: 0 },
  { name: "结果准确率", value: 0 }
];

export function EvaluationCenter() {
  return (
    <div className="space-y-5 p-6">
      <div>
        <h1 className="text-2xl font-semibold">评测中心</h1>
        <p className="mt-1 text-sm text-muted">后续展示问答集自动评测、失败原因和修复收益。</p>
      </div>
      <Card title="核心指标">
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="value" fill="#0f766e" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </div>
  );
}
