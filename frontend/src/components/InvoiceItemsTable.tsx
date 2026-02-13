import type { InvoiceItem, Product } from "@/types";

interface Props {
  items: InvoiceItem[];
  products: Product[];
  isPending: boolean;
  previewAllocated: Map<number, number>;
  onItemUpdate: (item: InvoiceItem, field: string, value: string | number | null) => void;
  onProductChange: (item: InvoiceItem, value: string) => void;
}

export default function InvoiceItemsTable({
  items,
  products,
  isPending,
  previewAllocated,
  onItemUpdate,
  onProductChange,
}: Props) {
  return (
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
        {items.map((item) => (
          <tr key={item.id}>
            <td>{item.description}</td>
            <td>
              {isPending ? (
                <select
                  value={item.product_id ?? ""}
                  onChange={(e) => onProductChange(item, e.target.value)}
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
                  const p = products.find((pr) => pr.id === item.product_id);
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
                    onItemUpdate(item, "quantity", Number(e.target.value))
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
                    onItemUpdate(item, "unit_cost", Number(e.target.value))
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
                      ~${(previewAllocated.get(item.id) ?? 0).toFixed(2)}
                    </span>
                  : "-"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
