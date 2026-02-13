import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { productApi, invoiceApi } from "@/api/services";
import { extractErrorMessage } from "@/api/errors";
import type { Invoice, InvoiceItem, Product } from "@/types";

export interface NewProductForm {
  brand: string;
  model: string;
  retail_price: number;
  color: string;
  size: string;
}

const emptyNewProduct = (): NewProductForm => ({
  brand: "",
  model: "",
  retail_price: 0,
  color: "",
  size: "",
});

export function useInvoiceReview() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState(false);

  // New product modal state
  const [showNewProduct, setShowNewProduct] = useState(false);
  const [newProductFor, setNewProductFor] = useState<InvoiceItem | null>(null);
  const [newProduct, setNewProduct] = useState<NewProductForm>(emptyNewProduct());

  // Editable cost fields
  const [editingCosts, setEditingCosts] = useState<Record<string, number>>({});

  useEffect(() => {
    const load = async () => {
      try {
        const [invResp, prodResp] = await Promise.all([
          invoiceApi.get(Number(id)),
          productApi.list(),
        ]);
        setInvoice(invResp.data);
        setProducts(prodResp.data);
      } catch {
        setError("Failed to load invoice.");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [id]);

  const updateItem = async (
    item: InvoiceItem,
    field: string,
    value: string | number | null,
  ) => {
    try {
      await invoiceApi.updateItem(Number(id), item.id, { [field]: value });
      const resp = await invoiceApi.get(Number(id));
      setInvoice(resp.data);
    } catch {
      setError("Failed to update item.");
    }
  };

  const updateInvoiceCost = async (field: string, value: number) => {
    try {
      await invoiceApi.update(Number(id), { [field]: value });
      const resp = await invoiceApi.get(Number(id));
      setInvoice(resp.data);
    } catch {
      setError("Failed to update invoice.");
    }
  };

  const approve = async () => {
    setActing(true);
    setError(null);
    try {
      await invoiceApi.approve(Number(id));
      const resp = await invoiceApi.get(Number(id));
      setInvoice(resp.data);
    } catch (err: unknown) {
      setError(extractErrorMessage(err, "Approval failed"));
    } finally {
      setActing(false);
    }
  };

  const reject = async () => {
    setActing(true);
    setError(null);
    try {
      await invoiceApi.reject(Number(id));
      navigate("/invoices");
    } catch {
      setError("Rejection failed.");
    } finally {
      setActing(false);
    }
  };

  const handleProductChange = (item: InvoiceItem, value: string) => {
    if (value === "new") {
      setNewProductFor(item);
      setNewProduct({
        brand: item.parsed_brand ?? "",
        model: item.parsed_model ?? "",
        color: item.parsed_color ?? "",
        size: item.parsed_size ?? "",
        retail_price: 0,
      });
      setShowNewProduct(true);
    } else {
      const val = value ? Number(value) : null;
      updateItem(item, "product_id", val);
    }
  };

  const saveNewProduct = async () => {
    setError(null);
    try {
      const resp = await productApi.create({
        brand: newProduct.brand,
        model: newProduct.model,
        retail_price: newProduct.retail_price,
        color: newProduct.color || null,
        size: newProduct.size || null,
      });
      const created: Product = resp.data;
      setProducts((prev) => [...prev, created]);
      if (newProductFor) {
        await updateItem(newProductFor, "product_id", created.id);
      }
      setShowNewProduct(false);
      setNewProductFor(null);
    } catch (err: unknown) {
      setError(extractErrorMessage(err, "Failed to create product"));
    }
  };

  const cancelNewProduct = () => {
    setShowNewProduct(false);
    setNewProductFor(null);
  };

  const startEditCost = (key: string, currentValue: number) => {
    setEditingCosts((prev) => ({ ...prev, [key]: currentValue ?? 0 }));
  };

  const changeEditCost = (key: string, value: number) => {
    setEditingCosts((prev) => ({ ...prev, [key]: value }));
  };

  const commitEditCost = (key: string) => {
    updateInvoiceCost(key, editingCosts[key]);
    setEditingCosts((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  return {
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
  };
}
