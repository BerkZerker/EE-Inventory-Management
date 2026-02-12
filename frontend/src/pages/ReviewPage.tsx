import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import apiClient from "@/api/client";
import type { Invoice, InvoiceItem, Product } from "@/types";

interface NewProductForm {
  brand: string;
  model: string;
  retail_price: number;
  color: string;
  size: string;
}

const emptyNewProduct = (): NewProductForm => ({
  brand: "",
  model: "",
  retail_price: 0,
  color: "",
  size: "",
});

export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState(false);

  // New product modal state
  const [showNewProduct, setShowNewProduct] = useState(false);
  const [newProductFor, setNewProductFor] = useState<InvoiceItem | null>(null);
  const [newProduct, setNewProduct] = useState<NewProductForm>(emptyNewProduct());
  const [prevProductId, setPrevProductId] = useState<number | null>(null);

  // Editable cost fields
  const [editingCosts, setEditingCosts] = useState<Record<string, number>>({});

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
      const resp = await apiClient.get(`/invoices/${id}`);
      setInvoice(resp.data);
    } catch {
      setError("Failed to update item.");
    }
  };

  const updateInvoiceCost = async (field: string, value: number) => {
    try {
      await apiClient.put(`/invoices/${id}`, { [field]: value });
      const resp = await apiClient.get(`/invoices/${id}`);
      setInvoice(resp.data);
    } catch {
      setError("Failed to update invoice.");
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

  const handleProductChange = (item: InvoiceItem, value: string) => {
    if (value === "new") {
      setPrevProductId(item.product_id);
      setNewProductFor(item);
      setNewProduct(emptyNewProduct());
      setShowNewProduct(true);
    } else {
      const val = value ? Number(value) : null;
      updateItem(item, "product_id", val);
    }
  };

  const saveNewProduct = async () => {
    setError(null);
    try {
      const resp = await apiClient.post("/products", {
        brand: newProduct.brand,
        model: newProduct.model,
        retail_price: newProduct.retail_price,
        color: newProduct.color || undefined,
        size: newProduct.size || undefined,
      });
      const created: Product = resp.data;
      setProducts((prev) => [...prev, created]);
      // Auto-select the new product for the line item
      if (newProductFor) {
        await updateItem(newProductFor, "product_id", created.id);
      }
      setShowNewProduct(false);
      setNewProductFor(null);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { error?: string } } })?.response?.data
          ?.error ?? "Failed to create product";
      setError(msg);
    }
  };

  const cancelNewProduct = () => {
    setShowNewProduct(false);
    setNewProductFor(null);
  };

  if (loading) return <div className="loading">Loading invoice...</div>;
  if (!invoice) return <div className="error-message">Invoice not found.</div>;

  const isPending = invoice.status === "pending";

  const costFields: { key: string; label: string }[] = [
    { key: "shipping_cost", label: "Shipping" },
    { key: "discount", label: "Discount" },
    { key: "credit_card_fees", label: "CC Fees" },
    { key: "tax", label: "Tax" },
    { key: "other_fees", label: "Other Fees" },
  ];

  // Compute live preview of allocated cost per unit for pending invoices
  const previewAllocated = new Map<number, number>();
  if (isPending && invoice.items && invoice.items.length > 0) {
    const totalBikes = invoice.items.reduce((sum, it) => sum + it.quantity, 0);
    if (totalBikes > 0) {
      const totalExtras =
        (invoice.shipping_cost ?? 0) +
        (invoice.credit_card_fees ?? 0) +
        (invoice.tax ?? 0) +
        (invoice.other_fees ?? 0) -
        (invoice.discount ?? 0);
      const extraPerBike = Math.round((totalExtras / totalBikes) * 100) / 100;
      for (const item of invoice.items) {
        previewAllocated.set(
          item.id,
          Math.round((item.unit_cost + extraPerBike) * 100) / 100,
        );
      }
    }
  }

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
        {costFields.map(({ key, label }) => {
          const fieldValue = (invoice as Record<string, unknown>)[key] as number;
          const isEditing = key in editingCosts;
          return (
            <div className="stat-card" key={key}>
              <div className="label">{label}</div>
              <div className="value">
                {isPending ? (
                  isEditing ? (
                    <input
                      type="number"
                      step="0.01"
                      value={editingCosts[key]}
                      onChange={(e) =>
                        setEditingCosts((prev) => ({
                          ...prev,
                          [key]: Number(e.target.value),
                        }))
                      }
                      onBlur={() => {
                        updateInvoiceCost(key, editingCosts[key]);
                        setEditingCosts((prev) => {
                          const next = { ...prev };
                          delete next[key];
                          return next;
                        });
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          (e.target as HTMLInputElement).blur();
                        }
                      }}
                      autoFocus
                    />
                  ) : (
                    <span
                      style={{ cursor: "pointer" }}
                      title="Click to edit"
                      onClick={() =>
                        setEditingCosts((prev) => ({
                          ...prev,
                          [key]: fieldValue ?? 0,
                        }))
                      }
                    >
                      ${(fieldValue ?? 0).toFixed(2)}
                    </span>
                  )
                ) : (
                  `$${(fieldValue ?? 0).toFixed(2)}`
                )}
              </div>
            </div>
          );
        })}
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
                    onChange={(e) => handleProductChange(item, e.target.value)}
                  >
                    <option value="">-- Select --</option>
                    <option value="new">+ New Product</option>
                    {products.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.brand} {p.model} ({p.sku})
                      </option>
                    ))}
                  </select>
                ) : (
                  (() => {
                    const p = products.find((p) => p.id === item.product_id);
                    return p ? `${p.brand} ${p.model}` : "Unmatched";
                  })()
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
                  : isPending && previewAllocated.has(item.id)
                    ? <span style={{ color: "#6b7280" }}>
                        ~${previewAllocated.get(item.id)!.toFixed(2)}
                      </span>
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

      {/* PDF Preview */}
      {invoice.file_path && (
        <div style={{ marginTop: "2rem" }}>
          <h3>Original Invoice</h3>
          <object
            data={`/api/invoices/${id}/pdf`}
            type="application/pdf"
            width="100%"
            style={{
              height: "600px",
              border: "1px solid #d1d5db",
              borderRadius: "8px",
            }}
          >
            <p>
              PDF preview not available.{" "}
              <a href={`/api/invoices/${id}/pdf`} target="_blank" rel="noreferrer">
                Download PDF
              </a>
            </p>
          </object>
        </div>
      )}

      {/* New Product Modal */}
      {showNewProduct && (
        <div className="modal-overlay" onClick={cancelNewProduct}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>New Product</h3>
            <div className="form-row" style={{ flexWrap: "wrap" }}>
              <div className="form-group">
                <label>Brand</label>
                <input
                  value={newProduct.brand}
                  onChange={(e) =>
                    setNewProduct({ ...newProduct, brand: e.target.value })
                  }
                />
              </div>
              <div className="form-group">
                <label>Model</label>
                <input
                  value={newProduct.model}
                  onChange={(e) =>
                    setNewProduct({ ...newProduct, model: e.target.value })
                  }
                />
              </div>
            </div>
            <div className="form-row" style={{ flexWrap: "wrap" }}>
              <div className="form-group">
                <label>Color</label>
                <input
                  value={newProduct.color}
                  onChange={(e) =>
                    setNewProduct({ ...newProduct, color: e.target.value })
                  }
                />
              </div>
              <div className="form-group">
                <label>Size</label>
                <input
                  value={newProduct.size}
                  onChange={(e) =>
                    setNewProduct({ ...newProduct, size: e.target.value })
                  }
                />
              </div>
              <div className="form-group">
                <label>Retail Price</label>
                <input
                  type="number"
                  step="0.01"
                  value={newProduct.retail_price}
                  onChange={(e) =>
                    setNewProduct({ ...newProduct, retail_price: Number(e.target.value) })
                  }
                />
              </div>
            </div>
            <div className="actions">
              <button
                className="success"
                onClick={saveNewProduct}
                disabled={!newProduct.brand || !newProduct.model}
              >
                Create Product
              </button>
              <button onClick={cancelNewProduct}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
