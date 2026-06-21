import type { ReactNode } from "react";
import { LogOut, Repeat } from "lucide-react";
import { Brand } from "./Brand";
import { LiveBadge } from "./LiveBadge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface NavItem {
  key: string;
  label: string;
  icon: ReactNode;
}

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
  children: ReactNode;
}) {
  return (
    <div className="flex h-[100dvh] flex-col bg-background">
      <header className="z-[600] flex h-14 shrink-0 items-center gap-3 border-b bg-background/95 px-3 backdrop-blur sm:px-4">
        <Brand subtitle={roleLabel} />
        {/* desktop nav */}
        <nav className="ml-4 hidden items-center gap-1 md:flex">
          {nav.map((n) => (
            <button
              key={n.key}
              onClick={() => onNav(n.key)}
              className={cn(
                "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                active === n.key ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {n.icon}
              {n.label}
            </button>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          {headerExtra}
          <LiveBadge />
          {userName && <span className="hidden text-sm font-medium text-muted-foreground lg:inline">{userName}</span>}
          <Button variant="ghost" size="icon" title="Switch role" onClick={onSwitchRole}>
            <Repeat className="h-4 w-4" />
          </Button>
          {onLogout && (
            <Button variant="ghost" size="icon" title="Log out" onClick={onLogout}>
              <LogOut className="h-4 w-4" />
            </Button>
          )}
        </div>
      </header>

      <main className={cn("relative min-h-0 flex-1", fill ? "overflow-hidden" : "overflow-y-auto", "pb-16 md:pb-0")}>
        {children}
      </main>

      {/* mobile bottom nav */}
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
    </div>
  );
}
