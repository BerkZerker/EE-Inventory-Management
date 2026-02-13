import { useMemo } from "react";
import { useInvoiceReview } from "@/hooks/useInvoiceReview";
import CostFields from "@/components/CostFields";
import InvoiceItemsTable from "@/components/InvoiceItemsTable";
import NewProductModal from "@/components/NewProductModal";

export default function ReviewPage() {
  const {
    id,
    invoice,
    products,
    loading,
    error,
    acting,
    showNewProduct,
    newProduct,
    setNewProduct,
    editingCosts,
    updateItem,
    approve,
    reject,
    handleProductChange,
    saveNewProduct,
    cancelNewProduct,
    startEditCost,
    changeEditCost,
    commitEditCost,
  } = useInvoiceReview();

  if (loading) return <div className="loading">Loading invoice...</div>;
  if (!invoice) return <div className="error-message">Invoice not found.</div>;

  const isPending = invoice.status === "pending";

  // Compute live preview of allocated cost per unit for pending invoices
  const previewAllocated = useMemo(() => {
    const map = new Map<number, number>();
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
          map.set(
            item.id,
            Math.round((item.unit_cost + extraPerBike) * 100) / 100,
          );
        }
      }
    }
    return map;
  }, [invoice, isPending]);

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

      <CostFields
        invoice={invoice}
        isPending={isPending}
        editingCosts={editingCosts}
        onEditStart={startEditCost}
        onEditChange={changeEditCost}
        onEditCommit={commitEditCost}
      />

      {invoice.items && (
        <InvoiceItemsTable
          items={invoice.items}
          products={products}
          isPending={isPending}
          previewAllocated={previewAllocated}
          onItemUpdate={updateItem}
          onProductChange={handleProductChange}
        />
      )}

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

      <NewProductModal
        show={showNewProduct}
        newProduct={newProduct}
        onChange={setNewProduct}
        onSave={saveNewProduct}
        onCancel={cancelNewProduct}
      />
    </div>
  );
}
