import { NavLink } from "react-router-dom";

export default function DashboardPage() {
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
