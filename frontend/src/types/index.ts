/** Product master record (one per bike model). */
export interface Product {
  id: number;
  sku: string;
  shopify_product_id: string | null;
  shopify_variant_id: string | null;
  model_name: string;
  color: string | null;
  size: string | null;
  retail_price: number;
  created_at: string;
  updated_at: string;
}

/** Invoice record. */
export interface Invoice {
  id: number;
  invoice_ref: string;
  supplier: string;
  invoice_date: string;
  total_amount: number | null;
  shipping_cost: number;
  discount: number;
  file_path: string | null;
  status: "pending" | "approved" | "rejected";
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
}

/** Parsed invoice line item. */
export interface InvoiceItem {
  id: number;
  invoice_id: number;
  product_id: number | null;
  description: string;
  quantity: number;
  unit_cost: number;
  total_cost: number;
  allocated_cost: number | null;
  created_at: string;
}

/** Individual bike (one per physical unit). */
export interface Bike {
  id: number;
  serial_number: string;
  product_id: number;
  invoice_id: number | null;
  shopify_variant_id: string | null;
  actual_cost: number;
  date_received: string;
  status: "available" | "sold" | "returned" | "damaged";
  date_sold: string | null;
  sale_price: number | null;
  shopify_order_id: string | null;
  notes: string | null;
  created_at: string;
}

/** Aggregated per-product inventory summary. */
export interface InventorySummary {
  product_id: number;
  sku: string;
  model_name: string;
  total: number;
  available: number;
  sold: number;
}
