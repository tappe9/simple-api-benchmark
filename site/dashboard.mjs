export const METRICS = {
  rps: { label: "Requests/s", guidance: "Higher is better", better: "higher" },
  mean: { label: "Mean response", guidance: "Lower is better", better: "lower" },
  memory: { label: "Observed peak memory", guidance: "Lower is better", better: "lower" },
};

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function finite(value, label, { positive = false } = {}) {
  assert(typeof value === "number" && Number.isFinite(value), `${label} must be finite`);
  assert(positive ? value > 0 : value >= 0, `${label} is out of range`);
  return value;
}

export function dashboardRows(model, { endpoint, metric, visibleIds }) {
  assert(model.conditions.endpoints.includes(endpoint), "unsupported endpoint");
  assert(Object.hasOwn(METRICS, metric), "unsupported metric");
  assert(Array.isArray(visibleIds), "visible implementations must be an array");
  assert(new Set(visibleIds).size === visibleIds.length, "duplicate visible implementation");
  assert(visibleIds.every((id) => model.implementations.includes(id)), "unknown visible implementation");

  const order = new Map(model.implementations.map((id, index) => [id, index]));
  const visible = new Set(visibleIds);
  const rows = model.rows.filter((row) => row.endpoint === endpoint && visible.has(row.id));
  if (rows.length === 0) return [];

  const values = rows.map((row) => finite(row[metric], metric, { positive: metric !== "mean" }));
  const maximum = Math.max(...values);
  const bestValue = METRICS[metric].better === "higher" ? maximum : Math.min(...values);

  return rows
    .map((row) => ({
      ...row,
      best: row[metric] === bestValue,
      percent: maximum === 0 ? 0 : (row[metric] / maximum) * 100,
    }))
    .sort((left, right) => {
      const difference = METRICS[metric].better === "higher"
        ? right[metric] - left[metric]
        : left[metric] - right[metric];
      return difference || order.get(left.id) - order.get(right.id);
    });
}
