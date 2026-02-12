import { useState } from "react";
import apiClient from "@/api/client";
import type { ProfitSummary, ProfitByProduct } from "@/types";

export default function ReportPage() {
  const today = new Date().toISOString().slice(0, 10);
  const thirtyDaysAgo = new Date(Date.now() - 30 * 86400000)
    .toISOString()
    .slice(0, 10);

  const [start, setStart] = useState(thirtyDaysAgo);
  const [end, setEnd] = useState(today);
  const [summary, setSummary] = useState<ProfitSummary | null>(null);
  const [byProduct, setByProduct] = useState<ProfitByProduct[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await apiClient.get("/reports/profit", {
        params: { start, end },
      });
      setSummary(resp.data.summary);
      setByProduct(resp.data.by_product);
    } catch {
      setError("Failed to load report.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <h2>Profit Report</h2>
        <p>Analyze revenue, costs, and margins by date range.</p>
      </div>

      {error && <div className="error-message">{error}</div>}

      <div className="toolbar">
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label>Start Date</label>
          <input
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </div>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label>End Date</label>
          <input
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </div>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label>&nbsp;</label>
          <button className="primary" onClick={load} disabled={loading}>
            {loading ? "Loading..." : "Generate Report"}
          </button>
        </div>
      </div>

      {summary && (
        <>
          <div className="stats-grid">
            <div className="stat-card">
              <div className="label">Units Sold</div>
              <div className="value">{summary.units_sold}</div>
            </div>
            <div className="stat-card">
              <div className="label">Revenue</div>
              <div className="value">${summary.total_revenue.toFixed(2)}</div>
            </div>
            <div className="stat-card">
              <div className="label">Cost</div>
              <div className="value">${summary.total_cost.toFixed(2)}</div>
            </div>
            <div className="stat-card">
              <div className="label">Profit</div>
              <div className="value">${summary.total_profit.toFixed(2)}</div>
            </div>
            <div className="stat-card">
              <div className="label">Margin</div>
              <div className="value">{summary.margin_pct.toFixed(1)}%</div>
            </div>
          </div>

          {byProduct.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>SKU</th>
                  <th>Model</th>
                  <th>Units</th>
                  <th>Revenue</th>
                  <th>Cost</th>
                  <th>Profit</th>
                  <th>Margin</th>
                </tr>
              </thead>
              <tbody>
                {byProduct.map((row) => (
                  <tr key={row.product_id}>
                    <td>{row.sku}</td>
                    <td>{row.brand} {row.model}</td>
                    <td>{row.units_sold}</td>
                    <td>${row.total_revenue.toFixed(2)}</td>
                    <td>${row.total_cost.toFixed(2)}</td>
                    <td>${row.total_profit.toFixed(2)}</td>
                    <td>{row.margin_pct.toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty-state">
              <p>No sales in this date range.</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
