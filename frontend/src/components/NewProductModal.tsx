import type { NewProductForm } from "@/hooks/useInvoiceReview";

interface Props {
  show: boolean;
  newProduct: NewProductForm;
  onChange: (updated: NewProductForm) => void;
  onSave: () => void;
  onCancel: () => void;
}

export default function NewProductModal({ show, newProduct, onChange, onSave, onCancel }: Props) {
  if (!show) return null;

  return (
    <div className="modal-overlay" role="presentation" onClick={onCancel} onKeyDown={(e) => { if (e.key === "Escape") onCancel(); }}>
      <div className="modal-content" role="dialog" aria-modal="true" aria-labelledby="new-product-title" onClick={(e) => e.stopPropagation()}>
        <h3 id="new-product-title">New Product</h3>
        <div className="form-row" style={{ flexWrap: "wrap" }}>
          <div className="form-group">
            <label>Brand</label>
            <input
              value={newProduct.brand}
              onChange={(e) => onChange({ ...newProduct, brand: e.target.value })}
            />
          </div>
          <div className="form-group">
            <label>Model</label>
            <input
              value={newProduct.model}
              onChange={(e) => onChange({ ...newProduct, model: e.target.value })}
            />
          </div>
        </div>
        <div className="form-row" style={{ flexWrap: "wrap" }}>
          <div className="form-group">
            <label>Color</label>
            <input
              value={newProduct.color}
              onChange={(e) => onChange({ ...newProduct, color: e.target.value })}
            />
          </div>
          <div className="form-group">
            <label>Size</label>
            <input
              value={newProduct.size}
              onChange={(e) => onChange({ ...newProduct, size: e.target.value })}
            />
          </div>
          <div className="form-group">
            <label>Retail Price</label>
            <input
              type="number"
              step="0.01"
              value={newProduct.retail_price}
              onChange={(e) => onChange({ ...newProduct, retail_price: Number(e.target.value) })}
            />
          </div>
        </div>
        <div className="actions">
          <button
            className="success"
            onClick={onSave}
            disabled={!newProduct.brand || !newProduct.model}
          >
            Create Product
          </button>
          <button onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
