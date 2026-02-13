import type { Invoice } from "@/types";

const COST_FIELDS: { key: string; label: string }[] = [
  { key: "shipping_cost", label: "Shipping" },
  { key: "discount", label: "Discount" },
  { key: "credit_card_fees", label: "CC Fees" },
  { key: "tax", label: "Tax" },
  { key: "other_fees", label: "Other Fees" },
];

function getInvoiceCostValue(invoice: Invoice, key: string): number {
  const costFields: Record<string, number | undefined> = {
    shipping_cost: invoice.shipping_cost,
    discount: invoice.discount,
    credit_card_fees: invoice.credit_card_fees,
    tax: invoice.tax,
    other_fees: invoice.other_fees,
  };
  return costFields[key] ?? 0;
}

interface Props {
  invoice: Invoice;
  isPending: boolean;
  editingCosts: Record<string, number>;
  onEditStart: (key: string, currentValue: number) => void;
  onEditChange: (key: string, value: number) => void;
  onEditCommit: (key: string) => void;
}

export default function CostFields({
  invoice,
  isPending,
  editingCosts,
  onEditStart,
  onEditChange,
  onEditCommit,
}: Props) {
  return (
    <div className="stats-grid">
      <div className="stat-card">
        <div className="label">Total</div>
        <div className="value">
          ${invoice.total_amount?.toFixed(2) ?? "N/A"}
        </div>
      </div>
      {COST_FIELDS.map(({ key, label }) => {
        const fieldValue = getInvoiceCostValue(invoice, key);
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
                    onChange={(e) => onEditChange(key, Number(e.target.value))}
                    onBlur={() => onEditCommit(key)}
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
                    onClick={() => onEditStart(key, fieldValue ?? 0)}
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
  );
}
