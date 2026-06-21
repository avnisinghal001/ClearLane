import { useEffect, useState } from "react";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { RESOLUTION_REASONS } from "@/lib/constants";
import type { ResolveInput, Ticket } from "@/lib/types";

export function ResolveDialog({
  ticket,
  onClose,
  onResolve,
}: {
  ticket: Ticket | null;
  onClose: () => void;
  onResolve: (id: string, body: ResolveInput) => Promise<void>;
}) {
  const [resolution, setResolution] = useState(true);
  const [reason, setReason] = useState("");
  const [reasonOther, setReasonOther] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (ticket) {
      setResolution(true);
      setReason("");
      setReasonOther("");
      setBusy(false);
    }
  }, [ticket]);

  async function submit() {
    if (!ticket || !reason) return;
    setBusy(true);
    try {
      await onResolve(ticket.id, {
        status: "closed",
        resolution,
        reason,
        reason_other: reason === "other" ? reasonOther.trim() : undefined,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={Boolean(ticket)} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Resolve ticket</DialogTitle>
          <DialogDescription>
            {ticket?.category ?? "Ticket"} · {ticket?.station ?? "—"}
            {ticket?.vehicle_number ? ` · ${ticket.vehicle_number}` : ""}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <Label>Outcome</Label>
            <div className="mt-1.5 grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setResolution(true)}
                className={cn(
                  "flex items-center justify-center gap-2 rounded-lg border py-2.5 text-sm font-medium transition-colors",
                  resolution ? "border-[hsl(var(--success))] bg-[hsl(var(--success))]/10 text-[hsl(var(--success))]" : "hover:bg-accent",
                )}
              >
                <CheckCircle2 className="h-4 w-4" /> Resolved (true)
              </button>
              <button
                type="button"
                onClick={() => setResolution(false)}
                className={cn(
                  "flex items-center justify-center gap-2 rounded-lg border py-2.5 text-sm font-medium transition-colors",
                  !resolution ? "border-destructive bg-destructive/10 text-destructive" : "hover:bg-accent",
                )}
              >
                <XCircle className="h-4 w-4" /> Not resolved (false)
              </button>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>Reason</Label>
            <Select value={reason} onValueChange={setReason}>
              <SelectTrigger>
                <SelectValue placeholder="Select a reason" />
              </SelectTrigger>
              <SelectContent>
                {RESOLUTION_REASONS.map((r) => (
                  <SelectItem key={r.value} value={r.value}>
                    {r.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {reason === "other" && (
            <div className="space-y-1.5">
              <Label>Other reason</Label>
              <Textarea value={reasonOther} onChange={(e) => setReasonOther(e.target.value)} placeholder="Describe the outcome…" />
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!reason || (reason === "other" && !reasonOther.trim()) || busy} onClick={submit}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            Close ticket
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
