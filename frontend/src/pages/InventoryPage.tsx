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

  // Bike editing
  const [editingBikeId, setEditingBikeId] = useState<number | null>(null);
  const [bikeEditForm, setBikeEditForm] = useState({ actual_cost: 0, status: "available" as string, notes: "" });

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

  const deleteProduct = async (id: number, name: string, bikeCount: number) => {
    const msg = bikeCount > 0
      ? `Delete "${name}" and its ${bikeCount} bike(s)?\n\nThis will also remove Shopify variants.`
      : `Delete "${name}"?`;
    if (!confirm(msg)) return;
    try {
      await productApi.delete(id);
      if (expandedProduct === id) setExpandedProduct(null);
      loadSummary();
      loadProducts();
    } catch {
      setError("Delete failed.");
    }
  };

  const bulkDeleteModel = async (brand: string, modelGroup: ModelGroup) => {
    const totalBikes = modelGroup.variants.reduce((sum, v) => sum + v.total_bikes, 0);
    const msg = totalBikes > 0
      ? `Delete all ${modelGroup.variants.length} variants of "${brand} ${modelGroup.model}" and their ${totalBikes} bike(s)?\n\nThis will also remove Shopify variants.`
      : `Delete all ${modelGroup.variants.length} variants of "${brand} ${modelGroup.model}"?`;
    if (!confirm(msg)) return;
    try {
      const ids = modelGroup.variants.map((v) => v.product_id);
      await productApi.bulkDelete(ids);
      setExpandedProduct(null);
      loadSummary();
      loadProducts();
    } catch (err) {
      setError(extractErrorMessage(err, "Bulk delete failed"));
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

  // Bike editing
  const startEditBike = (bike: Bike) => {
    setEditingBikeId(bike.id);
    setBikeEditForm({
      actual_cost: bike.actual_cost,
      status: bike.status,
      notes: bike.notes ?? "",
    });
  };

  const cancelEditBike = () => {
    setEditingBikeId(null);
  };

  const saveEditBike = async () => {
    if (editingBikeId === null) return;
    setError(null);
    setSaving(true);
    try {
      await bikeApi.update(editingBikeId, {
        actual_cost: bikeEditForm.actual_cost,
        status: bikeEditForm.status as Bike["status"],
        notes: bikeEditForm.notes || null,
      });
      setEditingBikeId(null);
      // Refresh the expanded bikes list
      if (expandedProduct !== null) {
        const resp = await bikeApi.list({ product_id: String(expandedProduct) });
        setProductBikes(resp.data);
      }
      loadSummary();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to update bike"));
    } finally {
      setSaving(false);
    }
  };

  const deleteBike = async (bike: Bike) => {
    if (!confirm(`Delete bike ${bike.serial_number}?\n\nThis will also remove the Shopify variant if one exists.`)) return;
    setError(null);
    try {
      await bikeApi.delete(bike.id);
      // Refresh the expanded bikes list
      if (expandedProduct !== null) {
        const resp = await bikeApi.list({ product_id: String(expandedProduct) });
        setProductBikes(resp.data);
      }
      loadSummary();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to delete bike"));
    }
  };

  const totals = summary.reduce(
    (acc, s) => ({
      total: acc.total + s.total_bikes,
      available: acc.available + s.available,
      inTransit: acc.inTransit + s.in_transit,
      sold: acc.sold + s.sold,
    }),
    { total: 0, available: 0, inTransit: 0, sold: 0 },
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
          <div className="label">In Transit</div>
          <div className="value">{totals.inTransit}</div>
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
            <p style={{ color: "#8a8a8a" }}>No bikes found for "{searchSerial}"</p>
          ) : (
            <div className="table-responsive"><table>
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
                    <td>{bike.date_received ? fmtDateTime(bike.date_received) : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
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
                <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.5rem" }}>
                  <h4 style={{ margin: 0, color: "#525252" }}>{modelGroup.model}</h4>
                  {modelGroup.variants.length > 1 && (
                    <button
                      className="danger sm"
                      onClick={() => bulkDeleteModel(brandGroup.brand, modelGroup)}
                    >
                      Delete All Variants ({modelGroup.variants.length})
                    </button>
                  )}
                </div>
                <div className="table-responsive"><table className="inventory-table">
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
                            {v.in_transit > 0 && <>{" "}<span className="badge in_transit">{v.in_transit} in transit</span></>}
                            {" / "}
                            {v.total_bikes}
                            {v.sold > 0 && <span style={{ color: "#8a8a8a", marginLeft: "0.5rem" }}>({v.sold} sold)</span>}
                          </td>
                          <td>{v.avg_cost != null ? `$${v.avg_cost.toFixed(2)}` : "-"}</td>
                          <td>${v.retail_price.toFixed(2)}</td>
                          <td onClick={(e) => e.stopPropagation()}>
                            <button onClick={() => startEditProduct(v)} style={{ marginRight: "0.5rem" }}>Edit</button>
                            <button className="danger" onClick={() => deleteProduct(v.product_id, `${brandGroup.brand} ${modelGroup.model} ${v.color ?? ""} ${v.size ?? ""}`.trim(), v.total_bikes)}>Delete</button>
                          </td>
                        </tr>
                        {expandedProduct === v.product_id && (
                          <tr key={`${v.product_id}-bikes`}>
                            <td colSpan={6} style={{ padding: "0.5rem 0 0.5rem 2rem", background: "var(--color-surface-alt)" }}>
                              {bikesLoading ? (
                                <div style={{ padding: "0.25rem", color: "var(--color-text-secondary)" }}>Loading bikes...</div>
                              ) : productBikes.length === 0 ? (
                                <div style={{ padding: "0.25rem", color: "var(--color-text-secondary)" }}>No bikes for this product.</div>
                              ) : (
                                <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", padding: "0.25rem 0" }}>
                                  {productBikes.map((bike) => (
                                    <div key={bike.id} style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
                                      <span style={{ fontWeight: 600, minWidth: "7rem" }}>{bike.serial_number}</span>
                                      {editingBikeId === bike.id ? (
                                        <>
                                          <select
                                            value={bikeEditForm.status}
                                            onChange={(e) => setBikeEditForm({ ...bikeEditForm, status: e.target.value })}
                                            style={{ fontSize: "0.8rem" }}
                                          >
                                            <option value="available">Available</option>
                                            <option value="in_transit">In Transit</option>
                                            <option value="sold">Sold</option>
                                            <option value="returned">Returned</option>
                                            <option value="damaged">Damaged</option>
                                          </select>
                                          <span style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}>
                                            <span style={{ color: "var(--color-text-secondary)", fontSize: "0.8rem" }}>Cost:</span>
                                            <input
                                              type="number"
                                              step="0.01"
                                              value={bikeEditForm.actual_cost}
                                              onChange={(e) => setBikeEditForm({ ...bikeEditForm, actual_cost: Number(e.target.value) })}
                                              style={{ width: "6rem", fontSize: "0.8rem" }}
                                            />
                                          </span>
                                          <span style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}>
                                            <span style={{ color: "var(--color-text-secondary)", fontSize: "0.8rem" }}>Notes:</span>
                                            <input
                                              value={bikeEditForm.notes}
                                              onChange={(e) => setBikeEditForm({ ...bikeEditForm, notes: e.target.value })}
                                              placeholder="Notes"
                                              style={{ width: "10rem", fontSize: "0.8rem" }}
                                            />
                                          </span>
                                          <button className="primary sm" onClick={saveEditBike} disabled={saving}>Save</button>
                                          <button className="sm" onClick={cancelEditBike}>Cancel</button>
                                        </>
                                      ) : (
                                        <>
                                          <span className={`badge ${bike.status}`}>{bike.status}</span>
                                          <span><span style={{ color: "var(--color-text-secondary)" }}>Cost:</span> ${bike.actual_cost.toFixed(2)}</span>
                                          <span><span style={{ color: "var(--color-text-secondary)" }}>Received:</span> {bike.date_received ? fmtDateTime(bike.date_received) : "-"}</span>
                                          {bike.notes && <span style={{ color: "var(--color-text-secondary)", fontStyle: "italic" }}>{bike.notes}</span>}
                                          <button className="sm" onClick={() => startEditBike(bike)}>Edit</button>
                                          <button className="danger sm" onClick={() => deleteBike(bike)}>Delete</button>
                                        </>
                                      )}
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
                </table></div>
              </div>
            ))}
          </div>
        ))
      )}
    </div>
  );
}
