import { useState, useEffect, useCallback } from "react";
import { bikeApi, productApi, serialApi } from "@/api/services";
import { extractErrorMessage } from "@/api/errors";
import { useForm } from "@/hooks/useForm";
import { fmtDateTime } from "@/fmt";
import type { InventorySummary, Bike, Product } from "@/types";

const EMPTY_PRODUCT = { brand: "", model: "", retail_price: 0, color: "", size: "" };

interface BrandGroup {
  brand: string;
  models: ModelGroup[];
}
interface ModelGroup {
  model: string;
  variants: InventorySummary[];
}

function groupByBrand(summary: InventorySummary[]): BrandGroup[] {
  const brandMap = new Map<string, Map<string, InventorySummary[]>>();
  for (const s of summary) {
    const brand = s.brand || "Unknown";
    const model = s.model || "Unknown";
    if (!brandMap.has(brand)) brandMap.set(brand, new Map());
    const modelMap = brandMap.get(brand)!;
    if (!modelMap.has(model)) modelMap.set(model, []);
    modelMap.get(model)!.push(s);
  }
  const groups: BrandGroup[] = [];
  for (const [brand, modelMap] of brandMap) {
    const models: ModelGroup[] = [];
    for (const [model, variants] of modelMap) {
      models.push({ model, variants });
    }
    groups.push({ brand, models });
  }
  return groups;
}

export default function InventoryPage() {
  const [summary, setSummary] = useState<InventorySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchSerial, setSearchSerial] = useState("");
  const [searchResults, setSearchResults] = useState<Bike[] | null>(null);
  const [expandedProduct, setExpandedProduct] = useState<number | null>(null);
  const [productBikes, setProductBikes] = useState<Bike[]>([]);
  const [bikesLoading, setBikesLoading] = useState(false);
  const [collapsedBrands, setCollapsedBrands] = useState<Set<string>>(new Set());

  // Product form
  const [showProductForm, setShowProductForm] = useState(false);
  const [editProductId, setEditProductId] = useState<number | null>(null);
  const { values: productForm, setValues: setProductForm, reset: resetProductForm } = useForm(EMPTY_PRODUCT);

  // Add Stock modal
  const [showAddStock, setShowAddStock] = useState(false);
  const [products, setProducts] = useState<Product[]>([]);
  const [stockForm, setStockForm] = useState({ product_id: 0, quantity: 1, cost_per_bike: 0, notes: "" });
  const [saving, setSaving] = useState(false);

  // Serial counter
  const [nextSerial, setNextSerial] = useState<string>("");
  const [serialValue, setSerialValue] = useState<number>(1);
  const [showSerialEdit, setShowSerialEdit] = useState(false);

  const loadSummary = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [summaryResp, serialResp] = await Promise.all([
        bikeApi.summary(),
        serialApi.get(),
      ]);
      setSummary(summaryResp.data);
      setNextSerial(serialResp.data.formatted);
      setSerialValue(serialResp.data.next_serial);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to load inventory"));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadProducts = useCallback(async () => {
    try {
      const resp = await productApi.list();
      setProducts(resp.data);
    } catch {
      // silent
    }
  }, []);

  useEffect(() => {
    loadSummary();
    loadProducts();
  }, [loadSummary, loadProducts]);

  const handleSearch = async () => {
    if (!searchSerial.trim()) {
      setSearchResults(null);
      return;
    }
    try {
      const resp = await bikeApi.list({ search: searchSerial.trim() });
      setSearchResults(resp.data);
    } catch {
      setSearchResults([]);
    }
  };

  const expandProduct = async (productId: number) => {
    if (expandedProduct === productId) {
      setExpandedProduct(null);
      return;
    }
    setExpandedProduct(productId);
    setBikesLoading(true);
    try {
      const resp = await bikeApi.list({ product_id: String(productId) });
      setProductBikes(resp.data);
    } catch {
      setProductBikes([]);
    } finally {
      setBikesLoading(false);
    }
  };

  const toggleBrand = (brand: string) => {
    setCollapsedBrands(prev => {
      const next = new Set(prev);
      if (next.has(brand)) next.delete(brand);
      else next.add(brand);
      return next;
    });
  };

  // Product CRUD
  const saveProduct = async () => {
    setError(null);
    setSaving(true);
    try {
      if (editProductId) {
        await productApi.update(editProductId, productForm);
      } else {
        await productApi.create(productForm);
      }
      setShowProductForm(false);
      setEditProductId(null);
      resetProductForm();
      loadSummary();
      loadProducts();
    } catch (err) {
      setError(extractErrorMessage(err, "Save failed"));
    } finally {
      setSaving(false);
    }
  };

  const startEditProduct = (s: InventorySummary) => {
    setEditProductId(s.product_id);
    setProductForm({
      brand: s.brand,
      model: s.model,
      retail_price: s.retail_price,
      color: s.color ?? "",
      size: s.size ?? "",
    });
    setShowProductForm(true);
  };

  const deleteProduct = async (id: number) => {
    if (!confirm("Delete this product and all its bikes?")) return;
    try {
      await productApi.delete(id);
      loadSummary();
      loadProducts();
    } catch {
      setError("Delete failed.");
    }
  };

  // Add Stock
  const submitAddStock = async () => {
    setError(null);
    setSaving(true);
    try {
      await bikeApi.createManual({
        product_id: stockForm.product_id,
        quantity: stockForm.quantity,
        cost_per_bike: stockForm.cost_per_bike,
        notes: stockForm.notes || undefined,
      });
      setShowAddStock(false);
      setStockForm({ product_id: 0, quantity: 1, cost_per_bike: 0, notes: "" });
      loadSummary();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to add stock"));
    } finally {
      setSaving(false);
    }
  };

  // Serial counter
  const saveSerialCounter = async () => {
    try {
      const resp = await serialApi.set(serialValue);
      setNextSerial(resp.data.formatted);
      setShowSerialEdit(false);
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to set serial counter"));
    }
  };

  const totals = summary.reduce(
    (acc, s) => ({
      total: acc.total + s.total_bikes,
      available: acc.available + s.available,
      sold: acc.sold + s.sold,
    }),
    { total: 0, available: 0, sold: 0 },
  );

  const brandGroups = groupByBrand(summary);

  return (
    <div>
      <div className="page-header">
        <h2>Inventory</h2>
        <p>Manage products, stock, and bike inventory.</p>
      </div>

      {error && <div className="error-message">{error}</div>}

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
        <div className="stat-card">
          <div className="label">Next Bike #</div>
          <div className="value" style={{ fontSize: "1rem" }}>
            {nextSerial}
            <button
              style={{ marginLeft: "0.5rem", fontSize: "0.75rem" }}
              onClick={() => setShowSerialEdit(!showSerialEdit)}
            >
              Edit
            </button>
          </div>
          {showSerialEdit && (
            <div style={{ marginTop: "0.5rem", display: "flex", gap: "0.5rem" }}>
              <input
                type="number"
                value={serialValue}
                onChange={(e) => setSerialValue(Number(e.target.value))}
                style={{ width: "5rem" }}
                min={1}
              />
              <button className="primary" onClick={saveSerialCounter} style={{ fontSize: "0.75rem" }}>
                Save
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="toolbar">
        <button className="primary" onClick={() => { setEditProductId(null); resetProductForm(); setShowProductForm(!showProductForm); }}>
          {showProductForm ? "Cancel" : "Add Product"}
        </button>
        <button className="success" onClick={() => { setShowAddStock(!showAddStock); }}>
          {showAddStock ? "Cancel" : "Add Stock"}
        </button>
        <div style={{ flex: 1 }} />
        <input
          type="text"
          placeholder="Search bike #..."
          value={searchSerial}
          onChange={(e) => setSearchSerial(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
        />
        <button onClick={handleSearch}>Search</button>
      </div>

      {/* Add Product Form */}
      {showProductForm && (
        <div className="card" style={{ marginBottom: "1.5rem" }}>
          <h3>{editProductId ? "Edit Product" : "New Product"}</h3>
          <div className="form-row" style={{ flexWrap: "wrap" }}>
            <div className="form-group">
              <label>Brand</label>
              <input value={productForm.brand} onChange={(e) => setProductForm({ ...productForm, brand: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Model</label>
              <input value={productForm.model} onChange={(e) => setProductForm({ ...productForm, model: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Color</label>
              <input value={productForm.color} onChange={(e) => setProductForm({ ...productForm, color: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Size</label>
              <input value={productForm.size} onChange={(e) => setProductForm({ ...productForm, size: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Retail Price</label>
              <input type="number" step="0.01" value={productForm.retail_price} onChange={(e) => setProductForm({ ...productForm, retail_price: Number(e.target.value) })} />
            </div>
            <div className="form-group">
              <label>&nbsp;</label>
              <button className="success" onClick={saveProduct} disabled={saving}>
                {saving ? "Saving..." : editProductId ? "Update" : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Stock Modal */}
      {showAddStock && (
        <div className="card" style={{ marginBottom: "1.5rem" }}>
          <h3>Add Stock</h3>
          <div className="form-row" style={{ flexWrap: "wrap" }}>
            <div className="form-group">
              <label>Product</label>
              <select value={stockForm.product_id} onChange={(e) => setStockForm({ ...stockForm, product_id: Number(e.target.value) })}>
                <option value={0}>-- Select Product --</option>
                {products.map((p) => (
                  <option key={p.id} value={p.id}>{p.brand} {p.model} {p.color ? `- ${p.color}` : ""} {p.size ? `(${p.size})` : ""}</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label>Quantity</label>
              <input type="number" min={1} value={stockForm.quantity} onChange={(e) => setStockForm({ ...stockForm, quantity: Number(e.target.value) })} style={{ width: "5rem" }} />
            </div>
            <div className="form-group">
              <label>Cost Per Bike</label>
              <input type="number" step="0.01" value={stockForm.cost_per_bike} onChange={(e) => setStockForm({ ...stockForm, cost_per_bike: Number(e.target.value) })} style={{ width: "7rem" }} />
            </div>
            <div className="form-group">
              <label>Notes</label>
              <input value={stockForm.notes} onChange={(e) => setStockForm({ ...stockForm, notes: e.target.value })} placeholder="Optional" />
            </div>
            <div className="form-group">
              <label>&nbsp;</label>
              <button className="success" onClick={submitAddStock} disabled={saving || !stockForm.product_id}>
                {saving ? "Adding..." : "Add Bikes"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Search Results */}
      {searchResults !== null && (
        <div style={{ marginBottom: "1.5rem" }}>
          <h3>Search Results</h3>
          {searchResults.length === 0 ? (
            <p style={{ color: "#6b7280" }}>No bikes found for "{searchSerial}"</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Bike #</th>
                  <th>Product</th>
                  <th>Status</th>
                  <th>Cost</th>
                  <th>Received</th>
                </tr>
              </thead>
              <tbody>
                {searchResults.map((bike) => (
                  <tr key={bike.id}>
                    <td>{bike.serial_number}</td>
                    <td>{bike.brand ?? ""} {bike.model ?? ""}</td>
                    <td><span className={`badge ${bike.status}`}>{bike.status}</span></td>
                    <td>${bike.actual_cost.toFixed(2)}</td>
                    <td>{fmtDateTime(bike.date_received)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <button onClick={() => { setSearchResults(null); setSearchSerial(""); }} style={{ marginTop: "0.5rem" }}>
            Clear Search
          </button>
        </div>
      )}

      {/* Main Inventory View - Grouped by Brand */}
      {loading ? (
        <div className="loading">Loading...</div>
      ) : searchResults !== null ? null : brandGroups.length === 0 ? (
        <div className="empty-state">
          <p>No products yet. Add a product to get started.</p>
        </div>
      ) : (
        brandGroups.map((brandGroup) => (
          <div key={brandGroup.brand} style={{ marginBottom: "1.5rem" }}>
            <h3
              style={{ cursor: "pointer", userSelect: "none", display: "flex", alignItems: "center", gap: "0.5rem" }}
              onClick={() => toggleBrand(brandGroup.brand)}
            >
              <span style={{ fontSize: "0.75rem" }}>{collapsedBrands.has(brandGroup.brand) ? "\u25B6" : "\u25BC"}</span>
              {brandGroup.brand}
            </h3>
            {!collapsedBrands.has(brandGroup.brand) && brandGroup.models.map((modelGroup) => (
              <div key={modelGroup.model} style={{ marginLeft: "1rem", marginBottom: "1rem" }}>
                <h4 style={{ marginBottom: "0.5rem", color: "#374151" }}>{modelGroup.model}</h4>
                <table className="inventory-table">
                  <colgroup>
                    <col style={{ width: "20%" }} />
                    <col style={{ width: "15%" }} />
                    <col style={{ width: "15%" }} />
                    <col style={{ width: "18%" }} />
                    <col style={{ width: "14%" }} />
                    <col style={{ width: "18%" }} />
                  </colgroup>
                  <thead>
                    <tr>
                      <th>Color</th>
                      <th>Size</th>
                      <th>Stock</th>
                      <th>Avg Wholesale</th>
                      <th>Retail</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {modelGroup.variants.map((v) => (
                      <>
                        <tr
                          key={v.product_id}
                          style={{ cursor: "pointer" }}
                          onClick={() => expandProduct(v.product_id)}
                        >
                          <td>{v.color ?? "-"}</td>
                          <td>{v.size ?? "-"}</td>
                          <td>
                            <span className="badge available">{v.available}</span>
                            {" / "}
                            {v.total_bikes}
                            {v.sold > 0 && <span style={{ color: "#6b7280", marginLeft: "0.5rem" }}>({v.sold} sold)</span>}
                          </td>
                          <td>{v.avg_cost != null ? `$${v.avg_cost.toFixed(2)}` : "-"}</td>
                          <td>${v.retail_price.toFixed(2)}</td>
                          <td onClick={(e) => e.stopPropagation()}>
                            <button onClick={() => startEditProduct(v)} style={{ marginRight: "0.5rem" }}>Edit</button>
                            <button className="danger" onClick={() => deleteProduct(v.product_id)}>Delete</button>
                          </td>
                        </tr>
                        {expandedProduct === v.product_id && (
                          <tr key={`${v.product_id}-bikes`}>
                            <td colSpan={6} style={{ padding: "0.5rem 0 0.5rem 2rem", background: "#eef2ff" }}>
                              {bikesLoading ? (
                                <div style={{ padding: "0.25rem", color: "#6b7280" }}>Loading bikes...</div>
                              ) : productBikes.length === 0 ? (
                                <div style={{ padding: "0.25rem", color: "#6b7280" }}>No bikes for this product.</div>
                              ) : (
                                <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", padding: "0.25rem 0" }}>
                                  {productBikes.map((bike) => (
                                    <div key={bike.id} style={{ display: "flex", alignItems: "center", gap: "1.25rem", flexWrap: "wrap" }}>
                                      <span style={{ fontWeight: 600 }}>{bike.serial_number}</span>
                                      <span className={`badge ${bike.status}`}>{bike.status}</span>
                                      <span><span style={{ color: "#6b7280" }}>Cost:</span> ${bike.actual_cost.toFixed(2)}</span>
                                      <span><span style={{ color: "#6b7280" }}>Received:</span> {fmtDateTime(bike.date_received)}</span>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </td>
                          </tr>
                        )}
                      </>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        ))
      )}
    </div>
  );
}
