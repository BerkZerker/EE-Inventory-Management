import type { Invoice } from "@/types";

const COST_FIELDS: { key: string; label: string; op: "+" | "-" }[] = [
  { key: "shipping_cost", label: "Shipping", op: "+" },
  { key: "credit_card_fees", label: "CC Fees", op: "+" },
  { key: "tax", label: "Tax", op: "+" },
  { key: "other_fees", label: "Other Fees", op: "+" },
  { key: "discount", label: "Discount", op: "-" },
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
  const itemSubtotal = (invoice.items ?? []).reduce(
    (sum, item) => sum + item.unit_cost * item.quantity,
    0,
  );

  const grandTotal =
    itemSubtotal +
    (invoice.shipping_cost ?? 0) +
    (invoice.credit_card_fees ?? 0) +
    (invoice.tax ?? 0) +
    (invoice.other_fees ?? 0) -
    (invoice.discount ?? 0);

  return (
    <div className="cost-breakdown">
      <div className="cost-line">
        <span className="cost-label">Subtotal</span>
        <span className="cost-amount">${itemSubtotal.toFixed(2)}</span>
      </div>
      {COST_FIELDS.map(({ key, label, op }) => {
        const fieldValue = getInvoiceCostValue(invoice, key);
        const isEditing = key in editingCosts;
        return (
          <div className="cost-line" key={key}>
            <span className="cost-label">
              {op === "+" ? "+" : "\u2212"} {label}
            </span>
            <span className="cost-amount">
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
                    className="cost-inline-input"
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
            </span>
          </div>
        );
      })}
      <div className="cost-separator" />
      <div className="cost-line cost-total">
        <span className="cost-label">Total</span>
        <span className="cost-amount">${grandTotal.toFixed(2)}</span>
      </div>
    </div>
  );
}
