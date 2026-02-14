import { useState, useEffect, useCallback } from "react";
import { bikeApi } from "@/api/services";
import { extractErrorMessage } from "@/api/errors";
import { fmtDate } from "@/fmt";
import type { Bike } from "@/types";

interface InvoiceGroup {
  invoice_id: number | null;
  invoice_ref: string;
  supplier: string;
  invoice_date: string;
  bikes: Bike[];
}

function groupByInvoice(bikes: Bike[]): InvoiceGroup[] {
  const map = new Map<number | null, InvoiceGroup>();
  for (const bike of bikes) {
    const key = bike.invoice_id;
    if (!map.has(key)) {
      map.set(key, {
        invoice_id: key,
        invoice_ref: bike.invoice_ref ?? "Unknown",
        supplier: bike.supplier ?? "Unknown",
        invoice_date: bike.invoice_date ?? "",
        bikes: [],
      });
    }
    map.get(key)!.bikes.push(bike);
  }
  return Array.from(map.values());
}

export default function InTransitPage() {
  const [bikes, setBikes] = useState<Bike[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [receiving, setReceiving] = useState(false);

  const loadBikes = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await bikeApi.list({ status: "in_transit" });
      setBikes(resp.data);
      setSelected(new Set());
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to load in-transit bikes"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBikes();
  }, [loadBikes]);

  const toggleBike = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleGroup = (groupBikes: Bike[]) => {
    const ids = groupBikes.map((b) => b.id);
    const allSelected = ids.every((id) => selected.has(id));
    setSelected((prev) => {
      const next = new Set(prev);
      if (allSelected) {
        ids.forEach((id) => next.delete(id));
      } else {
        ids.forEach((id) => next.add(id));
      }
      return next;
    });
  };

  const handleReceive = async (ids: number[]) => {
    setReceiving(true);
    setError(null);
    setSuccess(null);
    try {
      const resp = await bikeApi.receive(ids);
      const count = resp.data.bikes.length;
      const warnings = resp.data.shopify_warnings;
      setSuccess(
        `Received ${count} bike${count !== 1 ? "s" : ""}` +
          (warnings.length > 0 ? ` (warnings: ${warnings.join(", ")})` : ""),
      );
      loadBikes();
    } catch (err) {
      setError(extractErrorMessage(err, "Failed to receive bikes"));
    } finally {
      setReceiving(false);
    }
  };

  const groups = groupByInvoice(bikes);

  return (
    <div>
      <div className="page-header">
        <h2>In Transit</h2>
        <p>Bikes ordered but not yet received. Mark them as received to add to inventory and Shopify.</p>
      </div>

      {error && <div className="error-message">{error}</div>}
      {success && <div className="success-message">{success}</div>}

      {!loading && bikes.length > 0 && (
        <div className="toolbar">
          <button
            className="primary"
            disabled={selected.size === 0 || receiving}
            onClick={() => handleReceive(Array.from(selected))}
          >
            {receiving ? "Receiving..." : `Receive Selected (${selected.size})`}
          </button>
          <button
            className="success"
            disabled={receiving}
            onClick={() => handleReceive(bikes.map((b) => b.id))}
          >
            {receiving ? "Receiving..." : `Receive All (${bikes.length})`}
          </button>
        </div>
      )}

      {loading ? (
        <div className="loading">Loading...</div>
      ) : bikes.length === 0 ? (
        <div className="empty-state">
          <p>No bikes in transit. Approve an invoice to create in-transit bikes.</p>
        </div>
      ) : (
        groups.map((group) => {
          const groupIds = group.bikes.map((b) => b.id);
          const allSelected = groupIds.every((id) => selected.has(id));
          return (
            <div key={group.invoice_id ?? "none"} style={{ marginBottom: "1.5rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.5rem" }}>
                <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={() => toggleGroup(group.bikes)}
                  />
                  <strong>Select All</strong>
                </label>
                <h3 style={{ margin: 0 }}>
                  {group.invoice_ref}
                </h3>
                <span style={{ color: "var(--color-text-secondary)" }}>
                  {group.supplier}
                  {group.invoice_date && ` \u2022 ${fmtDate(group.invoice_date)}`}
                  {` \u2022 ${group.bikes.length} bike${group.bikes.length !== 1 ? "s" : ""}`}
                </span>
              </div>
              <div className="table-responsive">
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: "2.5rem" }}></th>
                      <th>Serial #</th>
                      <th>Product</th>
                      <th>Color</th>
                      <th>Size</th>
                      <th>Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.bikes.map((bike) => (
                      <tr key={bike.id}>
                        <td>
                          <input
                            type="checkbox"
                            checked={selected.has(bike.id)}
                            onChange={() => toggleBike(bike.id)}
                          />
                        </td>
                        <td>{bike.serial_number}</td>
                        <td>{bike.brand ?? ""} {bike.model ?? ""}</td>
                        <td>{bike.color ?? "-"}</td>
                        <td>{bike.size ?? "-"}</td>
                        <td>${bike.actual_cost.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}
