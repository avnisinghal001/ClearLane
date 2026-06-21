import { useEffect, useState } from "react";
import { CheckCircle2, Info, AlertTriangle, X } from "lucide-react";
import { cn } from "@/lib/utils";

export type ToastTone = "success" | "info" | "warning";
interface Toast {
  id: number;
  title: string;
  desc?: string;
  tone: ToastTone;
}

let _id = 1;
let _toasts: Toast[] = [];
const listeners = new Set<(t: Toast[]) => void>();
const emit = () => listeners.forEach((l) => l(_toasts.slice()));

export function toast(title: string, opts: { desc?: string; tone?: ToastTone; ttl?: number } = {}) {
  const t: Toast = { id: _id++, title, desc: opts.desc, tone: opts.tone ?? "success" };
  _toasts = [..._toasts, t];
  emit();
  setTimeout(() => {
    _toasts = _toasts.filter((x) => x.id !== t.id);
    emit();
  }, opts.ttl ?? 4200);
}

const ICON = { success: CheckCircle2, info: Info, warning: AlertTriangle };
const TONE = {
  success: "text-[hsl(var(--success))]",
  info: "text-primary",
  warning: "text-[hsl(var(--warning))]",
};

export function Toaster() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => {
    listeners.add(setItems);
    return () => {
      listeners.delete(setItems);
    };
  }, []);
  return (
    <div className="pointer-events-none fixed inset-x-0 top-3 z-[2000] flex flex-col items-center gap-2 px-3">
      {items.map((t) => {
        const Icon = ICON[t.tone];
        return (
          <div
            key={t.id}
            className="pointer-events-auto flex w-full max-w-sm animate-slide-up items-start gap-2.5 rounded-xl border bg-background/97 p-3 shadow-lg backdrop-blur"
          >
            <Icon className={cn("mt-0.5 h-5 w-5 shrink-0", TONE[t.tone])} />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold">{t.title}</div>
              {t.desc && <div className="mt-0.5 text-xs text-muted-foreground">{t.desc}</div>}
            </div>
            <button
              onClick={() => {
                _toasts = _toasts.filter((x) => x.id !== t.id);
                emit();
              }}
              className="text-muted-foreground hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
