import { Routes, Route, NavLink } from "react-router-dom";
import "./App.css";
import ErrorBoundary from "@/components/ErrorBoundary";
import DashboardPage from "@/pages/DashboardPage";
import InvoiceListPage from "@/pages/InvoiceListPage";
import ReviewPage from "@/pages/ReviewPage";
import InventoryPage from "@/pages/InventoryPage";
import ReportPage from "@/pages/ReportPage";

function App() {
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
