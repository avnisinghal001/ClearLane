import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { TICKET_CATEGORIES, TICKET_KINDS, VEHICLE_TYPES, VIOLATION_LABELS } from "@/lib/constants";
import type { Cell, TicketInput } from "@/lib/types";

export function CreateTicketDialog({
  open,
  onClose,
  station,
  cell,
  onCreate,
}: {
  open: boolean;
  onClose: () => void;
  station: string | null;
  cell?: Cell | null;
  onCreate: (input: TicketInput) => Promise<void>;
}) {
  const [kind, setKind] = useState<"police_ticket" | "chalan">("police_ticket");
  const [category, setCategory] = useState("");
  const [labels, setLabels] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [vehicleType, setVehicleType] = useState("");
  const [vehicleNumber, setVehicleNumber] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setKind("police_ticket");
      setCategory("");
      setLabels([]);
      setNote("");
      setVehicleType("");
      setVehicleNumber("");
      setBusy(false);
    }
  }, [open]);

  const toggleLabel = (l: string) => setLabels((cur) => (cur.includes(l) ? cur.filter((x) => x !== l) : [...cur, l]));

  async function submit() {
    if (!category) return;
    setBusy(true);
    try {
      await onCreate({
        kind,
        category,
        labels,
        station,
        cell: cell?.h3_r10 ?? null,
        lat: cell?.lat ?? null,
        lon: cell?.lon ?? null,
        vehicle_type: vehicleType || null,
        vehicle_number: vehicleNumber.trim().toUpperCase() || null,
        note: note.trim() || null,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create ticket</DialogTitle>
          <DialogDescription>
            {station ?? "Station"} · {cell ? `cell ${cell.h3_r10}` : "no cell pinned"}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Kind</Label>
              <Select value={kind} onValueChange={(v) => setKind(v as "police_ticket" | "chalan")}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TICKET_KINDS.map((k) => (
                    <SelectItem key={k.value} value={k.value}>
                      {k.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Category</Label>
              <Select value={category} onValueChange={setCategory}>
                <SelectTrigger>
                  <SelectValue placeholder="Violation type" />
                </SelectTrigger>
                <SelectContent>
                  {TICKET_CATEGORIES.map((c) => (
                    <SelectItem key={c} value={c}>
                      {c}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>Labels</Label>
            <div className="flex flex-wrap gap-1.5">
              {VIOLATION_LABELS.map((l) => (
                <button
                  key={l}
                  type="button"
                  onClick={() => toggleLabel(l)}
                  className={cn(
                    "rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
                    labels.includes(l) ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent",
                  )}
                >
                  {l}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>
                Vehicle type <span className="text-muted-foreground">(optional)</span>
              </Label>
              <Select value={vehicleType} onValueChange={setVehicleType}>
                <SelectTrigger>
                  <SelectValue placeholder="Select" />
                </SelectTrigger>
                <SelectContent>
                  {VEHICLE_TYPES.map((v) => (
                    <SelectItem key={v} value={v}>
                      {v}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>
                Vehicle no. <span className="text-muted-foreground">(optional)</span>
              </Label>
              <Input value={vehicleNumber} onChange={(e) => setVehicleNumber(e.target.value)} placeholder="KA01AB1234" className="uppercase" />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>Note</Label>
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Context for this ticket (landmark, lane, time)…" />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!category || busy} onClick={submit}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            Create ticket
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
