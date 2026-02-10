import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import apiClient from "@/api/client";
import type { Invoice, InvoiceItem, Product } from "@/types";

export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState(false);

  useEffect(() => {
    const load = async () => {
      try {
        const [invResp, prodResp] = await Promise.all([
          apiClient.get(`/invoices/${id}`),
          apiClient.get("/products"),
        ]);
        setInvoice(invResp.data);
        setProducts(prodResp.data);
      } catch {
        setError("Failed to load invoice.");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [id]);

  const updateItem = async (
    item: InvoiceItem,
    field: string,
    value: string | number | null,
  ) => {
    try {
      await apiClient.put(`/invoices/${id}/items/${item.id}`, {
        [field]: value,
      });
      // Reload invoice to reflect changes
      const resp = await apiClient.get(`/invoices/${id}`);
      setInvoice(resp.data);
    } catch {
      setError("Failed to update item.");
    }
  };

  const approve = async () => {
    setActing(true);
    setError(null);
    try {
      await apiClient.post(`/invoices/${id}/approve`);
      const resp = await apiClient.get(`/invoices/${id}`);
      setInvoice(resp.data);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { error?: string } } })?.response?.data
          ?.error ?? "Approval failed";
      setError(msg);
    } finally {
      setActing(false);
    }
  };

  const reject = async () => {
    setActing(true);
    setError(null);
    try {
      await apiClient.post(`/invoices/${id}/reject`);
      navigate("/invoices");
    } catch {
      setError("Rejection failed.");
    } finally {
      setActing(false);
    }
  };

  if (loading) return <div className="loading">Loading invoice...</div>;
  if (!invoice) return <div className="error-message">Invoice not found.</div>;

  const isPending = invoice.status === "pending";

  return (
    <div>
      <div className="page-header">
        <h2>
          Invoice {invoice.invoice_ref}{" "}
          <span className={`badge ${invoice.status}`}>{invoice.status}</span>
        </h2>
        <p>
          {invoice.supplier} &mdash; {invoice.invoice_date}
        </p>
      </div>

      {error && <div className="error-message">{error}</div>}

      <div className="stats-grid">
        <div className="stat-card">
          <div className="label">Total</div>
          <div className="value">
            ${invoice.total_amount?.toFixed(2) ?? "N/A"}
          </div>
        </div>
        <div className="stat-card">
          <div className="label">Shipping</div>
          <div className="value">${invoice.shipping_cost.toFixed(2)}</div>
        </div>
        <div className="stat-card">
          <div className="label">Discount</div>
          <div className="value">${invoice.discount.toFixed(2)}</div>
        </div>
      </div>

      <table>
        <thead>
          <tr>
            <th>Description</th>
            <th>Product</th>
            <th>Qty</th>
            <th>Unit Cost</th>
            <th>Total Cost</th>
            <th>Allocated</th>
          </tr>
        </thead>
        <tbody>
          {invoice.items?.map((item) => (
            <tr key={item.id}>
              <td>{item.description}</td>
              <td>
                {isPending ? (
                  <select
                    value={item.product_id ?? ""}
                    onChange={(e) => {
                      const val = e.target.value
                        ? Number(e.target.value)
                        : null;
                      updateItem(item, "product_id", val);
                    }}
                  >
                    <option value="">-- Select --</option>
                    {products.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.model_name} ({p.sku})
                      </option>
                    ))}
                  </select>
                ) : (
                  products.find((p) => p.id === item.product_id)?.model_name ??
                  "Unmatched"
                )}
              </td>
              <td>
                {isPending ? (
                  <input
                    type="number"
                    value={item.quantity}
                    style={{ width: "4rem" }}
                    min={1}
                    onChange={(e) =>
                      updateItem(item, "quantity", Number(e.target.value))
                    }
                  />
                ) : (
                  item.quantity
                )}
              </td>
              <td>
                {isPending ? (
                  <input
                    type="number"
                    value={item.unit_cost}
                    style={{ width: "6rem" }}
                    step="0.01"
                    onChange={(e) =>
                      updateItem(item, "unit_cost", Number(e.target.value))
                    }
                  />
                ) : (
                  `$${item.unit_cost.toFixed(2)}`
                )}
              </td>
              <td>${item.total_cost.toFixed(2)}</td>
              <td>
                {item.allocated_cost != null
                  ? `$${item.allocated_cost.toFixed(2)}`
                  : "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {isPending && invoice.preview_serials && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <strong>Preview serials:</strong>{" "}
          {invoice.preview_serials.join(", ")}
        </div>
      )}

      {isPending && (
        <div className="actions">
          <button className="success" disabled={acting} onClick={approve}>
            {acting ? "Processing..." : "Approve"}
          </button>
          <button className="danger" disabled={acting} onClick={reject}>
            Reject
          </button>
        </div>
      )}
    </div>
  );
}
