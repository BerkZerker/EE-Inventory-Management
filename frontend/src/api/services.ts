import apiClient from "./client";
import type { Product, Invoice, Bike, InventorySummary, ProfitSummary, ProfitByProduct } from "@/types";

export const productApi = {
  list: () => apiClient.get<Product[]>("/products"),
  create: (data: Omit<Product, "id" | "sku" | "shopify_product_id" | "created_at" | "updated_at">) =>
    apiClient.post<Product>("/products", data),
  update: (id: number, data: Partial<Product>) => apiClient.put<Product>(`/products/${id}`, data),
  delete: (id: number) => apiClient.delete(`/products/${id}`),
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
};

export const reportApi = {
  profit: (start: string, end: string) =>
    apiClient.get<{ summary: ProfitSummary; by_product: ProfitByProduct[] }>("/reports/profit", {
      params: { start, end },
    }),
};
