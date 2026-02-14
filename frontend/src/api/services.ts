import apiClient from "./client";
import type { Product, Invoice, Bike, InventorySummary, ProfitSummary, ProfitByProduct, ScrapedProduct, ScrapeResult, ScrapeImportResult } from "@/types";

export const productApi = {
  list: () => apiClient.get<Product[]>("/products"),
  create: (data: Omit<Product, "id" | "sku" | "shopify_product_id" | "created_at" | "updated_at">) =>
    apiClient.post<Product>("/products", data),
  update: (id: number, data: Partial<Product>) => apiClient.put<Product>(`/products/${id}`, data),
  delete: (id: number) => apiClient.delete(`/products/${id}`),
  bulkDelete: (productIds: number[]) =>
    apiClient.delete<{ message: string; deleted_count: number; bikes_deleted: number; shopify_warnings?: string[] }>(
      "/products/bulk",
      { data: { product_ids: productIds } },
    ),
};

export const invoiceApi = {
  list: (status?: string) =>
    apiClient.get<Invoice[]>("/invoices", { params: status ? { status } : {} }),
  get: (id: number) => apiClient.get<Invoice>(`/invoices/${id}`),
  upload: (data: FormData) =>
    apiClient.post<Invoice>("/invoices/upload", data, {
      headers: { "Content-Type": "multipart/form-data" },
    }),
  update: (id: number, data: Record<string, number>) =>
    apiClient.put<Invoice>(`/invoices/${id}`, data),
  updateItem: (invoiceId: number, itemId: number, data: Record<string, unknown>) =>
    apiClient.put(`/invoices/${invoiceId}/items/${itemId}`, data),
  approve: (id: number) => apiClient.post(`/invoices/${id}/approve`),
  reject: (id: number) => apiClient.post(`/invoices/${id}/reject`),
};

export const bikeApi = {
  list: (params?: Record<string, string>) => apiClient.get<Bike[]>("/bikes", { params }),
  summary: () => apiClient.get<InventorySummary[]>("/inventory/summary"),
  createManual: (data: { product_id: number; quantity: number; cost_per_bike?: number; notes?: string }) =>
    apiClient.post<{ bikes: Bike[]; count: number; shopify_warnings?: string[] }>("/bikes/manual", data),
  update: (id: number, data: Partial<Pick<Bike, "actual_cost" | "status" | "notes" | "date_received">>) =>
    apiClient.put<Bike>(`/bikes/${id}`, data),
  delete: (id: number) => apiClient.delete(`/bikes/${id}`),
};

export const serialApi = {
  get: () => apiClient.get<{ next_serial: number; formatted: string }>("/serial-counter"),
  set: (next_serial: number) =>
    apiClient.put<{ next_serial: number; formatted: string }>("/serial-counter", { next_serial }),
};

export const reportApi = {
  profit: (start: string, end: string) =>
    apiClient.get<{ summary: ProfitSummary; by_product: ProfitByProduct[] }>("/reports/profit", {
      params: { start, end },
    }),
};

export const scrapeApi = {
  scrape: (data: { url: string; brand_name: string }) =>
    apiClient.post<ScrapeResult>("/scrape/brand", data),
  import: (products: ScrapedProduct[]) =>
    apiClient.post<ScrapeImportResult>("/scrape/import", { products }),
};
