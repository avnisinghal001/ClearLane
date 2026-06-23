import type { ReactNode } from "react";
import { ChevronLeft, LogOut, Repeat } from "lucide-react";
import { Brand, Logo } from "./Brand";
import { cn } from "@/lib/utils";

export interface NavItem {
  key: string;
  label: string;
  icon: ReactNode;
}

// The unified left navigation: a collapsible icon rail on desktop and the body of
// the slide-in drawer on mobile (AppShell wraps it in a sheet). Scope is set by the
// caller (government = all sections; a station = its own).
export function SideNav({
  roleLabel,
  nav,
  active,
  onNav,
  collapsed = false,
  onToggleCollapse,
  onSwitchRole,
  onLogout,
  onItemSelected,
  showCollapse = true,
}: {
  roleLabel: string;
  nav: NavItem[];
  active: string;
  onNav: (k: string) => void;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  onSwitchRole?: () => void;
  onLogout?: () => void;
  onItemSelected?: () => void;
  showCollapse?: boolean;
}) {
  return (
    <aside className={cn("flex h-full flex-col bg-card", collapsed ? "w-[4.25rem]" : "w-60")}>
      <div className={cn("flex h-14 shrink-0 items-center border-b", collapsed ? "justify-center px-2" : "px-3")}>
        {collapsed ? <Logo /> : <Brand subtitle={roleLabel} />}
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto p-2">
        {nav.map((n) => {
          const isActive = active === n.key;
          return (
            <button
              key={n.key}
              title={n.label}
              onClick={() => {
                onNav(n.key);
                onItemSelected?.();
              }}
              className={cn(
                "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground",
                collapsed && "justify-center px-0",
              )}
            >
              <span className="flex h-5 w-5 shrink-0 items-center justify-center">{n.icon}</span>
              {!collapsed && <span className="truncate">{n.label}</span>}
              {isActive && !collapsed && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-primary" />}
            </button>
          );
        })}
      </nav>

      <div className="space-y-1 border-t p-2">
        {onSwitchRole && (
          <FooterButton collapsed={collapsed} icon={<Repeat className="h-4 w-4" />} label="Switch role" onClick={onSwitchRole} />
        )}
        {onLogout && <FooterButton collapsed={collapsed} icon={<LogOut className="h-4 w-4" />} label="Log out" onClick={onLogout} />}
        {showCollapse && onToggleCollapse && (
          <button
            onClick={onToggleCollapse}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className={cn(
              "hidden w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground md:flex",
              collapsed && "justify-center px-0",
            )}
          >
            <ChevronLeft className={cn("h-4 w-4 transition-transform", collapsed && "rotate-180")} />
            {!collapsed && <span>Collapse</span>}
          </button>
        )}
      </div>
    </aside>
  );
}

function FooterButton({ collapsed, icon, label, onClick }: { collapsed: boolean; icon: ReactNode; label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      title={label}
      className={cn(
        "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
        collapsed && "justify-center px-0",
      )}
    >
      <span className="flex h-5 w-5 shrink-0 items-center justify-center">{icon}</span>
      {!collapsed && <span className="truncate">{label}</span>}
    </button>
  );
}
