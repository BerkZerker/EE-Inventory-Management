import { useState, useEffect } from "react";
import apiClient from "@/api/client";
import type { Product } from "@/types";

function emptyProduct() {
  return { brand: "", model: "", retail_price: 0, color: "", size: "" };
}

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyProduct());

  const load = async () => {
    setLoading(true);
    try {
      const resp = await apiClient.get("/products");
      setProducts(resp.data);
    } catch {
      setError("Failed to load products.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const save = async () => {
    setError(null);
    try {
      if (editId) {
        await apiClient.put(`/products/${editId}`, form);
      } else {
        await apiClient.post("/products", form);
      }
      setShowForm(false);
      setEditId(null);
      setForm(emptyProduct());
      load();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { error?: string } } })?.response?.data
          ?.error ?? "Save failed";
      setError(msg);
    }
  };

  const startEdit = (p: Product) => {
    setEditId(p.id);
    setForm({
      brand: p.brand,
      model: p.model,
      retail_price: p.retail_price,
      color: p.color ?? "",
      size: p.size ?? "",
    });
    setShowForm(true);
  };

  const deleteProduct = async (id: number) => {
    if (!confirm("Delete this product?")) return;
    try {
      await apiClient.delete(`/products/${id}`);
      load();
    } catch {
      setError("Delete failed.");
    }
  };

  return (
    <div>
      <div className="page-header">
        <h2>Products</h2>
        <p>Manage the product catalog.</p>
      </div>

      {error && <div className="error-message">{error}</div>}

      <div className="toolbar">
        <button
          className="primary"
          onClick={() => {
            setEditId(null);
            setForm(emptyProduct());
            setShowForm(!showForm);
          }}
        >
          {showForm ? "Cancel" : "Add Product"}
        </button>
      </div>

      {showForm && (
        <div className="card" style={{ marginBottom: "1.5rem" }}>
          <h3>{editId ? "Edit Product" : "New Product"}</h3>
          <div className="form-row" style={{ flexWrap: "wrap" }}>
            <div className="form-group">
              <label>Brand</label>
              <input
                value={form.brand}
                onChange={(e) => setForm({ ...form, brand: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>Model</label>
              <input
                value={form.model}
                onChange={(e) => setForm({ ...form, model: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>Color</label>
              <input
                value={form.color}
                onChange={(e) => setForm({ ...form, color: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>Size</label>
              <input
                value={form.size}
                onChange={(e) => setForm({ ...form, size: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>Retail Price</label>
              <input
                type="number"
                step="0.01"
                value={form.retail_price}
                onChange={(e) =>
                  setForm({ ...form, retail_price: Number(e.target.value) })
                }
              />
            </div>
            <div className="form-group">
              <label>&nbsp;</label>
              <button className="success" onClick={save}>
                {editId ? "Update" : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="loading">Loading...</div>
      ) : products.length === 0 ? (
        <div className="empty-state">
          <p>No products yet.</p>
        </div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Brand</th>
              <th>Model</th>
              <th>Color</th>
              <th>Size</th>
              <th>SKU</th>
              <th>Price</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {products.map((p) => (
              <tr key={p.id}>
                <td>{p.brand}</td>
                <td>{p.model}</td>
                <td>{p.color ?? "-"}</td>
                <td>{p.size ?? "-"}</td>
                <td>{p.sku}</td>
                <td>${p.retail_price.toFixed(2)}</td>
                <td>
                  <button
                    onClick={() => startEdit(p)}
                    style={{ marginRight: "0.5rem" }}
                  >
                    Edit
                  </button>
                  <button className="danger" onClick={() => deleteProduct(p.id)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
