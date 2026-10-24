import { NavLink, Outlet } from "react-router-dom";
import { NAV } from "../nav";
import { IngestBanner } from "./IngestBanner";
import "./app.css";

export function Shell() {
  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <nav className="sidebar" aria-label="Main">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            L
          </span>
          <span>
            LRAE <span className="muted brand-sub">manager</span>
          </span>
        </div>
        <ul className="nav-list">
          {NAV.map((n) => (
            <li key={n.to}>
              <NavLink to={n.to} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
                {n.label}
                {n.placeholder && <span className="soon">soon</span>}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <div className="content">
        <IngestBanner />
        <main id="main" className="main" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
