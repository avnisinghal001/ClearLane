import { useState, type ReactNode } from "react";
import { Menu } from "lucide-react";
import { Brand } from "./Brand";
import { LiveBadge } from "./LiveBadge";
import { SideNav, type NavItem } from "./SideNav";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

export type { NavItem };

const COLLAPSE_KEY = "cl_v3_nav_collapsed";

export function AppShell({
  roleLabel,
  nav,
  active,
  onNav,
  onSwitchRole,
  onLogout,
  userName,
  fill = false,
  headerExtra,
  bottomNavOnMobile = false,
  children,
}: {
  roleLabel: string;
  nav: NavItem[];
  active: string;
  onNav: (k: string) => void;
  onSwitchRole: () => void;
  onLogout?: () => void;
  userName?: string;
  fill?: boolean;
  headerExtra?: ReactNode;
  bottomNavOnMobile?: boolean;
  children: ReactNode;
}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const toggleCollapse = () => {
    setCollapsed((c) => {
      const next = !c;
      try {
        localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
      } catch {
        /* noop */
      }
      return next;
    });
  };

  const activeLabel = nav.find((n) => n.key === active)?.label ?? roleLabel;

  return (
    <div className="flex h-[100dvh] overflow-hidden bg-background">
      {/* desktop left rail */}
      <div className="hidden shrink-0 border-r md:flex">
        <SideNav
          roleLabel={roleLabel}
          nav={nav}
          active={active}
          onNav={onNav}
          collapsed={collapsed}
          onToggleCollapse={toggleCollapse}
          onSwitchRole={onSwitchRole}
          onLogout={onLogout}
        />
      </div>

      {/* mobile drawer */}
      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent side="left" className="w-[16rem] p-0">
          <SideNav
            roleLabel={roleLabel}
            nav={nav}
            active={active}
            onNav={onNav}
            onSwitchRole={onSwitchRole}
            onLogout={onLogout}
            onItemSelected={() => setDrawerOpen(false)}
            showCollapse={false}
          />
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="z-[600] flex h-14 shrink-0 items-center gap-3 border-b bg-background/95 px-3 backdrop-blur sm:px-4">
          {/* mobile: hamburger (drawer) unless a bottom nav is shown */}
          {!bottomNavOnMobile && (
            <button
              onClick={() => setDrawerOpen(true)}
              className="flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground md:hidden"
              aria-label="Open menu"
            >
              <Menu className="h-5 w-5" />
            </button>
          )}
          {/* mobile brand (desktop brand lives in the rail) */}
          <div className="md:hidden">
            <Brand subtitle={roleLabel} />
          </div>
          {/* desktop: active section title */}
          <h1 className="hidden text-lg font-bold md:block">{activeLabel}</h1>

          <div className="ml-auto flex items-center gap-2">
            {headerExtra}
            <LiveBadge />
            {userName && <span className="hidden text-sm font-medium text-muted-foreground lg:inline">{userName}</span>}
          </div>
        </header>

        <main className={cn("relative min-h-0 flex-1", fill ? "overflow-hidden" : "overflow-y-auto", bottomNavOnMobile && "pb-16 md:pb-0")}>
          {children}
        </main>
      </div>

      {/* citizen mobile-first bottom nav */}
      {bottomNavOnMobile && (
        <nav className="fixed inset-x-0 bottom-0 z-[600] flex h-16 items-stretch border-t bg-background/97 backdrop-blur md:hidden">
          {nav.map((n) => (
            <button
              key={n.key}
              onClick={() => onNav(n.key)}
              className={cn(
                "flex flex-1 flex-col items-center justify-center gap-1 text-[11px] font-medium transition-colors",
                active === n.key ? "text-primary" : "text-muted-foreground",
              )}
            >
              <span className={cn("flex h-6 w-6 items-center justify-center", active === n.key && "scale-110")}>{n.icon}</span>
              {n.label}
            </button>
          ))}
        </nav>
      )}
    </div>
  );
}
