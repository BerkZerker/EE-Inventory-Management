import { useState, useEffect } from "react";
import { NavLink } from "react-router-dom";
import { bikeApi, invoiceApi, productApi } from "@/api/services";
import { fmtDate } from "@/fmt";
import type { InventorySummary, Invoice } from "@/types";

export default function DashboardPage() {
  const [stats, setStats] = useState({ totalBikes: 0, available: 0, inTransit: 0, sold: 0, totalProducts: 0 });
  const [recentInvoices, setRecentInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [summaryResp, invoicesResp, productsResp] = await Promise.all([
          bikeApi.summary(),
          invoiceApi.list(),
          productApi.list(),
        ]);
        const summary: InventorySummary[] = summaryResp.data;
        const totals = summary.reduce(
          (acc, s) => ({
            totalBikes: acc.totalBikes + s.total_bikes,
            available: acc.available + s.available,
            inTransit: acc.inTransit + s.in_transit,
            sold: acc.sold + s.sold,
          }),
          { totalBikes: 0, available: 0, inTransit: 0, sold: 0 },
        );
        setStats({ ...totals, totalProducts: productsResp.data.length });
        setRecentInvoices(invoicesResp.data.slice(0, 5));
      } catch {
        // silent — dashboard is best-effort
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  return (
    <div>
      <div className="page-header" style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
        <img src="/ee-icon-hd.svg" alt="" style={{ width: 40, height: 40 }} />
        <div>
          <h2>Dashboard</h2>
          <p>Welcome to the E-Bike Inventory Management System.</p>
        </div>
      </div>

      <div className="stats-grid">
        <NavLink to="/inventory" style={{ textDecoration: "none" }}>
          <div className="stat-card stat-card-link">
            <div className="label">Total Bikes</div>
            <div className="value">{loading ? "-" : stats.totalBikes}</div>
          </div>
        </NavLink>
        <NavLink to="/inventory" style={{ textDecoration: "none" }}>
          <div className="stat-card stat-card-link">
            <div className="label">Available</div>
            <div className="value">{loading ? "-" : stats.available}</div>
          </div>
        </NavLink>
        <NavLink to="/in-transit" style={{ textDecoration: "none" }}>
          <div className="stat-card stat-card-link">
            <div className="label">In Transit</div>
            <div className="value">{loading ? "-" : stats.inTransit}</div>
          </div>
        </NavLink>
        <NavLink to="/inventory" style={{ textDecoration: "none" }}>
          <div className="stat-card stat-card-link">
            <div className="label">Sold</div>
            <div className="value">{loading ? "-" : stats.sold}</div>
          </div>
        </NavLink>
        <NavLink to="/inventory" style={{ textDecoration: "none" }}>
          <div className="stat-card stat-card-link">
            <div className="label">Products</div>
            <div className="value">{loading ? "-" : stats.totalProducts}</div>
          </div>
        </NavLink>
      </div>

      <div className="stats-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
        <NavLink to="/invoices" style={{ textDecoration: "none" }}>
          <div className="stat-card stat-card-link">
            <div className="label">Invoices</div>
            <div className="value" style={{ fontSize: "1rem" }}>View invoices &rarr;</div>
          </div>
        </NavLink>
        <NavLink to="/reports" style={{ textDecoration: "none" }}>
          <div className="stat-card stat-card-link">
            <div className="label">Reports</div>
            <div className="value" style={{ fontSize: "1rem" }}>View profits &rarr;</div>
          </div>
        </NavLink>
      </div>

      {recentInvoices.length > 0 && (
        <div style={{ marginTop: "0.5rem" }}>
          <h3>Recent Invoices</h3>
          <div className="table-responsive"><table>
            <thead>
              <tr>
                <th>Invoice #</th>
                <th>Supplier</th>
                <th>Date</th>
                <th>Status</th>
                <th>Total</th>
              </tr>
            </thead>
            <tbody>
              {recentInvoices.map((inv) => (
                <tr key={inv.id}>
                  <td>
                    <NavLink to={`/invoices/${inv.id}`}>{inv.invoice_ref}</NavLink>
                  </td>
                  <td>{inv.supplier}</td>
                  <td>{fmtDate(inv.invoice_date)}</td>
                  <td><span className={`badge ${inv.status}`}>{inv.status}</span></td>
                  <td>{inv.total_amount != null ? `$${inv.total_amount.toFixed(2)}` : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </div>
      )}
    </div>
  );
}
