import { cn } from "@/lib/utils";

export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={cn("h-7 w-7", className)} aria-hidden>
      <rect width="64" height="64" rx="14" fill="hsl(var(--primary))" />
      <path d="M18 40c0-10 6-18 14-18s14 8 14 18" stroke="#fff" strokeWidth="4.5" strokeLinecap="round" fill="none" />
      <circle cx="32" cy="44" r="4.5" fill="#fff" />
      <path d="M14 50h36" stroke="#fff" strokeWidth="4.5" strokeLinecap="round" strokeDasharray="2 7" />
    </svg>
  );
}

export function Brand({ subtitle, className }: { subtitle?: string; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <Logo />
      <div className="leading-tight">
        <div className="font-extrabold tracking-tight">
          Clear<span className="text-primary">Lane</span>
        </div>
        {subtitle && <div className="text-[11px] font-medium text-muted-foreground">{subtitle}</div>}
      </div>
    </div>
  );
}
