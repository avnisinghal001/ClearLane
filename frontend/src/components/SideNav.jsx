import { Icon } from "./icons.jsx";
import SearchBox from "./SearchBox.jsx";

// Unified navigation: a collapsible icon rail on desktop, a slide-in drawer on
// mobile (toggled by the header hamburger). The collapse control sits top-right.
// On mobile the search lives at the top of this drawer.
export default function SideNav({ views, view, onSelect, collapsed, onToggleCollapse,
                                 mobileOpen, onCloseMobile, role, scopeName, onSearchPick, onLogout }) {
  const pick = (k) => { onSelect(k); onCloseMobile?.(); };
  const roleName = role === "govt" ? "Government" : (scopeName || "Force");
  return (
    <>
      <div className={"sidenav-backdrop" + (mobileOpen ? " show" : "")} onClick={onCloseMobile} />
      <aside className={"sidenav" + (collapsed ? " collapsed" : "") + (mobileOpen ? " mobile-open" : "")}>
        <div className="sidenav-top">
          <div className="sidenav-role">
            <span className="sidenav-role-ic"><Icon name="lane" size={18} strokeWidth={2} /></span>
            <div className="sidenav-role-text">
              <div className="sidenav-role-name" title={roleName}>{roleName}</div>
              <div className="sidenav-role-sub">{role === "govt" ? "Government · Command" : "Station · Command"}</div>
            </div>
          </div>
          <button className="sidenav-collapse-btn hide-mobile" onClick={onToggleCollapse}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-label="toggle sidebar">
            <Icon name="chevron" size={16} />
          </button>
          <button className="sidenav-x show-mobile" onClick={onCloseMobile} aria-label="close menu">
            <Icon name="close" size={18} />
          </button>
        </div>

        <div className="sidenav-search show-mobile">
          <SearchBox onPick={(id) => { onSearchPick?.(id); onCloseMobile?.(); }}
            placeholder="Search junction / zone…" />
        </div>

        <nav className="sidenav-list">
          {views.map(([k, label]) => (
            <button key={k} title={label}
              className={"sidenav-item" + (view === k ? " active" : "")}
              onClick={() => pick(k)}>
              <span className="sidenav-ic"><Icon name={k} size={18} /></span>
              <span className="sidenav-label">{label}</span>
              {view === k && <span className="sidenav-active-dot" />}
            </button>
          ))}
        </nav>

        <button className="sidenav-logout" onClick={onLogout} title="Sign out">
          <span className="sidenav-ic"><Icon name="logout" size={18} /></span>
          <span className="sidenav-label">Logout</span>
        </button>
      </aside>
    </>
  );
}
