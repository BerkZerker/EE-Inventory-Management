import { Routes, Route } from "react-router-dom";
import "./App.css";

function Home() {
  return (
    <div>
      <h2>Dashboard</h2>
      <p>Welcome to the E-Bike Inventory Management System.</p>
    </div>
  );
}

function App() {
  return (
    <div className="app">
      <header>
        <h1>E-Bike Inventory</h1>
        <nav>{/* Navigation links will be added in Phase 6 */}</nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Home />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
