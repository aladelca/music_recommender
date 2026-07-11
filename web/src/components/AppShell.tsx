import { Compass, History, LogOut, Settings, SlidersHorizontal } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth/useAuth";

const navigation = [
  { to: "/discover", label: "Discover", icon: Compass },
  { to: "/history", label: "History", icon: History },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function AppShell() {
  const { user, logout } = useAuth();
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <NavLink className="brand" to="/discover" aria-label="Outside the Loop home">
          <span className="brand-mark"><SlidersHorizontal size={19} /></span>
          <span>Outside the Loop</span>
        </NavLink>
        <nav className="primary-nav" aria-label="Primary">
          {navigation.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "active" : "")}>
              <Icon size={18} aria-hidden="true" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="account-summary">
          <span className="avatar" aria-hidden="true">{(user?.display_name ?? "T").slice(0, 1)}</span>
          <span className="account-name">{user?.display_name ?? "Beta tester"}</span>
          <button className="icon-button" type="button" onClick={() => void logout()} title="Log out">
            <LogOut size={17} aria-hidden="true" />
            <span className="sr-only">Log out</span>
          </button>
        </div>
      </aside>
      <main className="main-content"><Outlet /></main>
      <nav className="mobile-nav" aria-label="Primary">
        {navigation.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "active" : "")}>
            <Icon size={19} aria-hidden="true" />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
