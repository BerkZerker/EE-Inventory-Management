import { useState, useEffect } from "react";
import apiClient from "@/api/client";
import type { InventorySummary, Bike } from "@/types";

export default function InventoryPage() {
  const [summary, setSummary] = useState<InventorySummary[]>([]);
  const [bikes, setBikes] = useState<Bike[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [searchSerial, setSearchSerial] = useState("");

  useEffect(() => {
    const load = async () => {
      try {
        const resp = await apiClient.get("/inventory/summary");
        setSummary(resp.data);
      } catch {
        /* ignore */
      }
    };
    load();
  }, []);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const params: Record<string, string> = {};
        if (searchSerial) params.search = searchSerial;
        else if (statusFilter) params.status = statusFilter;
        const resp = await apiClient.get("/bikes", { params });
        setBikes(resp.data);
      } catch {
        /* ignore */
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [statusFilter, searchSerial]);

  const totals = summary.reduce(
    (acc, s) => ({
      total: acc.total + s.total_bikes,
      available: acc.available + s.available,
      sold: acc.sold + s.sold,
    }),
    { total: 0, available: 0, sold: 0 },
  );

  return (
    <div>
      <div className="page-header">
        <h2>Inventory</h2>
        <p>Manage bike inventory and track status.</p>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="label">Total Bikes</div>
          <div className="value">{totals.total}</div>
        </div>
        <div className="stat-card">
          <div className="label">Available</div>
          <div className="value">{totals.available}</div>
        </div>
        <div className="stat-card">
          <div className="label">Sold</div>
          <div className="value">{totals.sold}</div>
        </div>
      </div>

      {summary.length > 0 && (
        <div style={{ marginBottom: "1.5rem" }}>
          <h3>By Product</h3>
          <table>
            <thead>
              <tr>
                <th>SKU</th>
                <th>Model</th>
                <th>Total</th>
                <th>Available</th>
                <th>Sold</th>
                <th>Damaged</th>
                <th>Avg Cost</th>
              </tr>
            </thead>
            <tbody>
              {summary.map((s) => (
                <tr key={s.product_id}>
                  <td>{s.sku}</td>
                  <td>{s.brand} {s.model}</td>
                  <td>{s.total_bikes}</td>
                  <td>{s.available}</td>
                  <td>{s.sold}</td>
                  <td>{s.damaged}</td>
                  <td>
                    {s.avg_cost != null ? `$${s.avg_cost.toFixed(2)}` : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3>All Bikes</h3>
      <div className="toolbar">
        <input
          type="text"
          placeholder="Search serial number..."
          value={searchSerial}
          onChange={(e) => {
            setSearchSerial(e.target.value);
            if (e.target.value) setStatusFilter("");
          }}
        />
        <select
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value);
            setSearchSerial("");
          }}
        >
          <option value="">All statuses</option>
          <option value="available">Available</option>
          <option value="sold">Sold</option>
          <option value="damaged">Damaged</option>
          <option value="returned">Returned</option>
        </select>
      </div>

      {loading ? (
        <div className="loading">Loading...</div>
      ) : bikes.length === 0 ? (
        <div className="empty-state">
          <p>No bikes found.</p>
        </div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Serial</th>
              <th>Model</th>
              <th>Status</th>
              <th>Cost</th>
              <th>Sale Price</th>
              <th>Received</th>
            </tr>
          </thead>
          <tbody>
            {bikes.map((bike) => (
              <tr key={bike.id}>
                <td>{bike.serial_number}</td>
                <td>{bike.brand ?? ""} {bike.model ?? "N/A"}</td>
                <td>
                  <span className={`badge ${bike.status}`}>{bike.status}</span>
                </td>
                <td>${bike.actual_cost.toFixed(2)}</td>
                <td>
                  {bike.sale_price != null
                    ? `$${bike.sale_price.toFixed(2)}`
                    : "-"}
                </td>
                <td>{bike.date_received}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
