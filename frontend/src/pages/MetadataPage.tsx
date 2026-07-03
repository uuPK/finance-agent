import { Card } from "../components/Card";

const metadataItems = [
  "table_metadata",
  "column_metadata",
  "metric_metadata",
  "business_terms",
  "join_relationships",
  "question_examples"
];

export function MetadataPage() {
  return (
    <div className="space-y-5 p-6">
      <div>
        <h1 className="text-2xl font-semibold">元数据</h1>
        <p className="mt-1 text-sm text-muted">第一版先展示元数据资产类型，下一阶段接入 PostgreSQL 查询。</p>
      </div>
      <Card title="元数据资产">
        <div className="grid grid-cols-3 gap-3">
          {metadataItems.map((item) => (
            <div key={item} className="rounded-md border border-line bg-surface p-4">
              <div className="text-sm font-semibold">{item}</div>
              <div className="mt-1 text-sm text-muted">待接入数据源</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
