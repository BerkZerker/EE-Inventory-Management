import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import apiClient from "@/api/client";
import type { Invoice } from "@/types";

export default function InvoiceListPage() {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>("");

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const params = statusFilter ? { status: statusFilter } : {};
        const resp = await apiClient.get("/invoices", { params });
        setInvoices(resp.data);
      } catch {
        /* ignore */
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [statusFilter]);

  return (
    <div>
      <div className="page-header">
        <h2>Invoices</h2>
        <p>View and manage supplier invoices.</p>
      </div>

      <div className="toolbar">
        <Link to="/upload">
          <button className="primary">Upload Invoice</button>
        </Link>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All statuses</option>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
      </div>

      {loading ? (
        <div className="loading">Loading...</div>
      ) : invoices.length === 0 ? (
        <div className="empty-state">
          <p>No invoices found.</p>
        </div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Reference</th>
              <th>Supplier</th>
              <th>Date</th>
              <th>Total</th>
              <th>Status</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((inv) => (
              <tr key={inv.id}>
                <td>
                  <Link to={`/invoices/${inv.id}`}>{inv.invoice_ref}</Link>
                </td>
                <td>{inv.supplier}</td>
                <td>{inv.invoice_date}</td>
                <td>
                  {inv.total_amount != null
                    ? `$${inv.total_amount.toFixed(2)}`
                    : "-"}
                </td>
                <td>
                  <span className={`badge ${inv.status}`}>{inv.status}</span>
                </td>
                <td>{new Date(inv.created_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
