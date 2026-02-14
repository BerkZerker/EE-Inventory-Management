import { useState } from "react";
import { scrapeApi } from "@/api/services";
import { extractErrorMessage } from "@/api/errors";
import type { ScrapedProduct, ScrapeResult, ScrapeImportResult } from "@/types";

export default function ScrapeImportPage() {
  const [url, setUrl] = useState("");
  const [brandName, setBrandName] = useState("");
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [scrapeResult, setScrapeResult] = useState<ScrapeResult | null>(null);
  const [editableProducts, setEditableProducts] = useState<ScrapedProduct[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [importResult, setImportResult] = useState<ScrapeImportResult | null>(null);

  const handleScrape = async () => {
    if (!url.trim() || !brandName.trim()) return;
    setError(null);
    setLoading(true);
    setScrapeResult(null);
    setEditableProducts([]);
    setSelected(new Set());
    setImportResult(null);

    try {
      const resp = await scrapeApi.scrape({ url: url.trim(), brand_name: brandName.trim() });
      setScrapeResult(resp.data);
      setEditableProducts(resp.data.products.map((p) => ({ ...p })));
      setSelected(new Set(resp.data.products.map((_, i) => i)));
    } catch (err) {
      setError(extractErrorMessage(err, "Scraping failed"));
    } finally {
      setLoading(false);
    }
  };

  const handleImport = async () => {
    const toImport = editableProducts.filter((_, i) => selected.has(i));
    if (toImport.length === 0) return;
    setError(null);
    setImporting(true);

    try {
      const resp = await scrapeApi.import(toImport);
      setImportResult(resp.data);
    } catch (err) {
      setError(extractErrorMessage(err, "Import failed"));
    } finally {
      setImporting(false);
    }
  };

  const toggleSelect = (index: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === editableProducts.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(editableProducts.map((_, i) => i)));
    }
  };

  const updateProduct = (index: number, field: keyof ScrapedProduct, value: string) => {
    setEditableProducts((prev) => {
      const copy = [...prev];
      copy[index] = {
        ...copy[index],
        [field]: field === "retail_price" ? Number(value) || 0 : value || null,
      };
      return copy;
    });
  };

  const selectedCount = selected.size;

  return (
    <div>
      <div className="page-header">
        <h2>Brand Scraper</h2>
        <p>Scrape a brand's website to extract their product catalog, then import selected products.</p>
      </div>

      {error && <div className="error-message">{error}</div>}

      {/* Input Form */}
      <div className="card" style={{ marginBottom: "1.5rem" }}>
        <h3>Scrape Brand Website</h3>
        <div className="form-row" style={{ flexWrap: "wrap" }}>
          <div className="form-group">
            <label>Brand Name</label>
            <input
              value={brandName}
              onChange={(e) => setBrandName(e.target.value)}
              placeholder="e.g. Velotric"
            />
          </div>
          <div className="form-group" style={{ flex: 2 }}>
            <label>Website URL</label>
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="e.g. https://www.velotric.com"
              onKeyDown={(e) => e.key === "Enter" && handleScrape()}
            />
          </div>
          <div className="form-group">
            <label>&nbsp;</label>
            <button
              className="primary"
              onClick={handleScrape}
              disabled={loading || !url.trim() || !brandName.trim()}
            >
              {loading ? "Scraping..." : "Scrape Website"}
            </button>
          </div>
        </div>
      </div>

      {loading && <div className="loading">Scraping website... This may take a moment.</div>}

      {/* Scrape Results */}
      {scrapeResult && !loading && (
        <div className="card" style={{ marginBottom: "1.5rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem", flexWrap: "wrap", gap: "0.5rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
              <h3 style={{ margin: 0 }}>Scraped Products</h3>
              <span className={`badge ${scrapeResult.strategy === "shopify json" ? "available" : "pending"}`}>
                {scrapeResult.strategy}
              </span>
            </div>
            <span style={{ color: "var(--color-text-secondary)" }}>
              {editableProducts.length} product{editableProducts.length !== 1 ? "s" : ""} found
            </span>
          </div>

          {scrapeResult.errors.length > 0 && (
            <div className="error-message" style={{ marginBottom: "1rem" }}>
              {scrapeResult.errors.map((e, i) => (
                <div key={i}>{e}</div>
              ))}
            </div>
          )}

          {editableProducts.length === 0 ? (
            <div className="empty-state">
              <p>No products found on this website.</p>
            </div>
          ) : (
            <>
              <div className="toolbar" style={{ marginBottom: "0.75rem" }}>
                <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={selected.size === editableProducts.length}
                    onChange={toggleAll}
                  />
                  {selected.size === editableProducts.length ? "Deselect All" : "Select All"}
                </label>
                <div style={{ flex: 1 }} />
                <button
                  className="success"
                  onClick={handleImport}
                  disabled={importing || selectedCount === 0}
                >
                  {importing ? "Importing..." : `Import Selected (${selectedCount})`}
                </button>
              </div>

              <div className="table-responsive">
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: "3rem" }}></th>
                      <th>Model</th>
                      <th>Color</th>
                      <th>Size</th>
                      <th>Price</th>
                    </tr>
                  </thead>
                  <tbody>
                    {editableProducts.map((product, i) => (
                      <tr key={i} style={{ opacity: selected.has(i) ? 1 : 0.5 }}>
                        <td>
                          <input
                            type="checkbox"
                            checked={selected.has(i)}
                            onChange={() => toggleSelect(i)}
                          />
                        </td>
                        <td>
                          <input
                            value={product.model}
                            onChange={(e) => updateProduct(i, "model", e.target.value)}
                            style={{ width: "100%", border: "1px solid var(--color-border)", borderRadius: "4px", padding: "0.25rem 0.5rem" }}
                          />
                        </td>
                        <td>
                          <input
                            value={product.color ?? ""}
                            onChange={(e) => updateProduct(i, "color", e.target.value)}
                            style={{ width: "100%", border: "1px solid var(--color-border)", borderRadius: "4px", padding: "0.25rem 0.5rem" }}
                          />
                        </td>
                        <td>
                          <input
                            value={product.size ?? ""}
                            onChange={(e) => updateProduct(i, "size", e.target.value)}
                            style={{ width: "100%", border: "1px solid var(--color-border)", borderRadius: "4px", padding: "0.25rem 0.5rem" }}
                          />
                        </td>
                        <td>
                          <input
                            type="number"
                            step="0.01"
                            value={product.retail_price}
                            onChange={(e) => updateProduct(i, "retail_price", e.target.value)}
                            style={{ width: "7rem", border: "1px solid var(--color-border)", borderRadius: "4px", padding: "0.25rem 0.5rem" }}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}

      {/* Import Results */}
      {importResult && (
        <div className="card">
          <h3>Import Results</h3>
          <div className="stats-grid" style={{ marginBottom: "1rem" }}>
            <div className="stat-card">
              <div className="label">Created</div>
              <div className="value">{importResult.created_count}</div>
            </div>
            <div className="stat-card">
              <div className="label">Skipped</div>
              <div className="value">{importResult.skipped_count}</div>
            </div>
          </div>

          {importResult.skipped.length > 0 && (
            <>
              <h4 style={{ marginBottom: "0.5rem" }}>Skipped Products</h4>
              <div className="table-responsive">
                <table>
                  <thead>
                    <tr>
                      <th>Model</th>
                      <th>Color</th>
                      <th>Size</th>
                      <th>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {importResult.skipped.map((item, i) => (
                      <tr key={i}>
                        <td>{item.model}</td>
                        <td>{item.color ?? "-"}</td>
                        <td>{item.size ?? "-"}</td>
                        <td>{item.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
