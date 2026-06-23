import { cn } from "@/lib/utils";

export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={cn("h-7 w-7", className)} aria-hidden>
      <defs>
        <linearGradient id="tf-logo" x1="32" y1="0" x2="32" y2="64" gradientUnits="userSpaceOnUse">
          <stop stopColor="#FB923C" />
          <stop offset="1" stopColor="#F97316" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="16" fill="url(#tf-logo)" />
      <path d="M19 34l9 9 17-20" stroke="#fff" strokeWidth="6.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <path d="M16 51h32" stroke="#fff" strokeWidth="5" strokeLinecap="round" strokeDasharray="2 8" opacity="0.92" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("font-extrabold tracking-tight", className)}>
      Tra<span className="text-primary">Fix</span>
    </span>
  );
}

export function Brand({ subtitle, className }: { subtitle?: string; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <Logo />
      <div className="leading-tight">
        <Wordmark />
        {subtitle && <div className="text-[11px] font-medium text-muted-foreground">{subtitle}</div>}
      </div>
    </div>
  );
}
