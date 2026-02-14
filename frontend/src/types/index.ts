/** Product master record (one per bike model/color/size combo). */
export interface Product {
  id: number;
  sku: string;
  shopify_product_id: string | null;
  brand: string;
  model: string;
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
  credit_card_fees: number;
  tax: number;
  other_fees: number;
  file_path: string | null;
  status: "pending" | "approved" | "rejected";
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  items?: InvoiceItem[];
  preview_serials?: string[];
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
  parsed_brand: string | null;
  parsed_model: string | null;
  parsed_color: string | null;
  parsed_size: string | null;
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
  /* joined fields from list_bikes */
  sku?: string;
  brand?: string;
  model?: string;
  color?: string;
  size?: string;
  retail_price?: number;
}

/** Aggregated per-product inventory summary. */
export interface InventorySummary {
  product_id: number;
  sku: string;
  brand: string;
  model: string;
  color: string | null;
  size: string | null;
  retail_price: number;
  total_bikes: number;
  available: number;
  sold: number;
  returned: number;
  damaged: number;
  avg_cost: number | null;
}

/** Profit report summary. */
export interface ProfitSummary {
  units_sold: number;
  total_revenue: number;
  total_cost: number;
  total_profit: number;
  margin_pct: number;
}

/** Per-product profit breakdown. */
export interface ProfitByProduct {
  product_id: number;
  sku: string;
  brand: string;
  model: string;
  units_sold: number;
  total_revenue: number;
  total_cost: number;
  total_profit: number;
  margin_pct: number;
}

/** Scraped product from brand website. */
export interface ScrapedProduct {
  brand: string;
  model: string;
  color: string | null;
  size: string | null;
  retail_price: number;
}

/** Result from scraping a brand website. */
export interface ScrapeResult {
  brand_name: string;
  source_url: string;
  strategy: string;
  products: ScrapedProduct[];
  errors: string[];
}

/** Result from importing scraped products. */
export interface ScrapeImportResult {
  created: Array<{ brand: string; model: string; color?: string; size?: string }>;
  created_count: number;
  skipped: Array<{ brand: string; model: string; color?: string; size?: string; reason: string }>;
  skipped_count: number;
}
