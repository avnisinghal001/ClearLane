import { forwardRef, useImperativeHandle, useState } from "react";
import { Megaphone } from "lucide-react";
import { toast } from "@/components/toast";
import { ReportSheet } from "@/roles/citizen/ReportSheet";
import { postComplaint } from "@/lib/api";
import type { ComplaintInput, Ticket } from "@/lib/types";

export interface IncidentReporterHandle {
  /** Open the report sheet pre-located at (lat, lon) — used by map long-press. */
  openAt: (loc: [number, number] | null) => void;
}

/**
 * Shared "report an incident" flow for ALL roles (citizen / police / government).
 * Renders a bottom-right FAB (5vh above the safe area) AND exposes openAt() so a
 * long-press / right-click on the map can drop a report at that point. Files a
 * citizen-style complaint via postComplaint (offline-first), shows it on the map as
 * a blue marker, and calls onFiled so the host can refresh its pins/list.
 */
export const IncidentReporter = forwardRef<IncidentReporterHandle, {
  label?: string;
  defaultLoc?: [number, number] | null;
  onFiled?: (t: Ticket) => void;
  onPickOnMap?: () => void;
  onLocateMe?: () => void;
  showFab?: boolean; // false when the host already has a primary FAB (e.g. police "Create ticket")
}>(function IncidentReporter({ label = "Report incident", defaultLoc, onFiled, onPickOnMap, onLocateMe, showFab = true }, ref) {
  const [open, setOpen] = useState(false);
  const [loc, setLoc] = useState<[number, number] | null>(null);

  useImperativeHandle(ref, () => ({
    openAt: (l) => {
      setLoc(l ?? defaultLoc ?? null);
      setOpen(true);
    },
  }));

  async function submit(input: ComplaintInput) {
    const t = await postComplaint(input);
    setOpen(false);
    toast("Report filed — thank you!", {
      desc: `Routed to ${t.station ?? "the nearest station"}.`,
      tone: "success",
    });
    onFiled?.(t);
  }

  return (
    <>
      {showFab && (
        <button
          onClick={() => {
            setLoc(defaultLoc ?? null);
            setOpen(true);
          }}
          aria-label={label}
          title={`${label} — or long-press the map`}
          className="group fixed right-0 top-1/2 z-[610] flex -translate-y-1/2 items-center gap-2 overflow-hidden rounded-l-xl bg-primary py-4 pl-2 pr-1.5 font-semibold text-primary-foreground shadow-lg ring-1 ring-black/10 transition-[padding] hover:pl-2.5 [writing-mode:vertical-rl]"
        >
          <span aria-hidden className="pointer-events-none absolute inset-0 animate-shimmer bg-gradient-to-b from-transparent via-white/40 to-transparent" />
          <Megaphone className="h-4 w-4 rotate-90" />
          <span className="text-sm tracking-wide">{label}</span>
        </button>
      )}

      <ReportSheet
        open={open}
        location={loc}
        onClose={() => setOpen(false)}
        onLocateMe={onLocateMe ?? (() => {})}
        onPickOnMap={onPickOnMap ?? (() => setOpen(false))}
        onSubmit={submit}
      />
    </>
  );
});
