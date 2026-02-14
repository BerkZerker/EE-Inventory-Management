import { useState, useEffect } from "react";
import { Routes, Route, NavLink, useLocation } from "react-router-dom";
import "./App.css";
import ErrorBoundary from "@/components/ErrorBoundary";
import DashboardPage from "@/pages/DashboardPage";
import InvoiceListPage from "@/pages/InvoiceListPage";
import ReviewPage from "@/pages/ReviewPage";
import InventoryPage from "@/pages/InventoryPage";
import ReportPage from "@/pages/ReportPage";

function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  return (
    <div className="app">
      <div className="mobile-header">
        <button className="hamburger-btn" onClick={() => setSidebarOpen(!sidebarOpen)}>
          &#9776;
        </button>
        <img src="/ee-logo-smol.png" alt="EE" />
      </div>
      <div className={`sidebar-overlay${sidebarOpen ? " open" : ""}`} onClick={() => setSidebarOpen(false)} />
      <div className="app-layout">
        <aside className={`sidebar${sidebarOpen ? " open" : ""}`}>
          <div className="sidebar-brand">
            <img src="/ee-logo-hd.svg" alt="EE" className="sidebar-logo" />
            <h1>EE Inventory</h1>
            <p>E-Bike Management</p>
          </div>
          <nav>
            <NavLink to="/" end>Dashboard</NavLink>
            <NavLink to="/invoices">Invoices</NavLink>
            <NavLink to="/inventory">Inventory</NavLink>
            <NavLink to="/reports">Reports</NavLink>
          </nav>
        </aside>
        <main className="main-content">
          <ErrorBoundary>
            <Routes>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/invoices" element={<InvoiceListPage />} />
              <Route path="/invoices/:id" element={<ReviewPage />} />
              <Route path="/inventory" element={<InventoryPage />} />
              <Route path="/reports" element={<ReportPage />} />
            </Routes>
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}

export default App;
