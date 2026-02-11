import { useEffect } from "react";
import { Routes, Route, NavLink } from "react-router-dom";
import "./App.css";
import apiClient from "@/api/client";
import UploadPage from "@/pages/UploadPage";
import InvoiceListPage from "@/pages/InvoiceListPage";
import ReviewPage from "@/pages/ReviewPage";
import InventoryPage from "@/pages/InventoryPage";
import ProductsPage from "@/pages/ProductsPage";
import ReportPage from "@/pages/ReportPage";

function Dashboard() {
  return (
    <div>
      <div className="page-header">
        <h2>Dashboard</h2>
        <p>Welcome to the E-Bike Inventory Management System.</p>
      </div>
      <div className="stats-grid">
        <NavLink to="/inventory" style={{ textDecoration: "none" }}>
          <div className="stat-card">
            <div className="label">Inventory</div>
            <div className="value" style={{ fontSize: "1rem" }}>
              View bikes &rarr;
            </div>
          </div>
        </NavLink>
        <NavLink to="/upload" style={{ textDecoration: "none" }}>
          <div className="stat-card">
            <div className="label">Invoices</div>
            <div className="value" style={{ fontSize: "1rem" }}>
              Upload PDF &rarr;
            </div>
          </div>
        </NavLink>
        <NavLink to="/products" style={{ textDecoration: "none" }}>
          <div className="stat-card">
            <div className="label">Products</div>
            <div className="value" style={{ fontSize: "1rem" }}>
              Manage catalog &rarr;
            </div>
          </div>
        </NavLink>
        <NavLink to="/reports" style={{ textDecoration: "none" }}>
          <div className="stat-card">
            <div className="label">Reports</div>
            <div className="value" style={{ fontSize: "1rem" }}>
              View profits &rarr;
            </div>
          </div>
        </NavLink>
      </div>
    </div>
  );
}

function App() {
  useEffect(() => {
    apiClient.post("/sync/products").catch(() => {});
  }, []);

  return (
    <div className="app">
      <div className="app-layout">
        <aside className="sidebar">
          <div className="sidebar-brand">
            <h1>EE Inventory</h1>
            <p>E-Bike Management</p>
          </div>
          <nav>
            <NavLink to="/" end>
              Dashboard
            </NavLink>
            <NavLink to="/upload">Upload Invoice</NavLink>
            <NavLink to="/invoices">Invoices</NavLink>
            <NavLink to="/inventory">Inventory</NavLink>
            <NavLink to="/products">Products</NavLink>
            <NavLink to="/reports">Reports</NavLink>
          </nav>
        </aside>
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/upload" element={<UploadPage />} />
            <Route path="/invoices" element={<InvoiceListPage />} />
            <Route path="/invoices/:id" element={<ReviewPage />} />
            <Route path="/inventory" element={<InventoryPage />} />
            <Route path="/products" element={<ProductsPage />} />
            <Route path="/reports" element={<ReportPage />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export default App;
