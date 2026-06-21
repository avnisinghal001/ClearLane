import { useEffect, useState } from "react";
import { Loader2, LocateFixed, MapPin } from "lucide-react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { COMPLAINT_CATEGORIES, VEHICLE_TYPES } from "@/lib/constants";
import type { ComplaintInput } from "@/lib/types";

export function ReportSheet({
  open,
  onClose,
  location,
  onLocateMe,
  onPickOnMap,
  onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  location: [number, number] | null;
  onLocateMe: () => void;
  onPickOnMap: () => void;
  onSubmit: (input: ComplaintInput) => Promise<void>;
}) {
  const [category, setCategory] = useState("");
  const [traffic, setTraffic] = useState(true);
  const [description, setDescription] = useState("");
  const [vehicleType, setVehicleType] = useState("");
  const [vehicleNumber, setVehicleNumber] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setBusy(false);
    }
  }, [open]);

  const canSubmit = Boolean(category) && Boolean(location) && !busy;

  async function submit() {
    if (!location || !category) return;
    setBusy(true);
    try {
      await onSubmit({
        lat: location[0],
        lon: location[1],
        category,
        traffic_caused: traffic,
        description: description.trim(),
        vehicle_type: vehicleType || undefined,
        vehicle_number: vehicleNumber.trim().toUpperCase() || undefined,
      });
      // reset for next time
      setCategory("");
      setDescription("");
      setVehicleType("");
      setVehicleNumber("");
      setTraffic(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="bottom" className="rounded-t-2xl">
        <SheetHeader className="px-5">
          <SheetTitle>Report illegal parking</SheetTitle>
          <SheetDescription>
            These labelled fields are what the police station sees when verifying your report.
          </SheetDescription>
        </SheetHeader>

        <div className="space-y-4 px-5 pb-6 pt-1">
          {/* location */}
          <div className="rounded-lg border bg-muted/30 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-sm">
                <MapPin className="h-4 w-4 text-primary" />
                {location ? (
                  <span className="num">
                    {location[0].toFixed(5)}, {location[1].toFixed(5)}
                  </span>
                ) : (
                  <span className="text-muted-foreground">No location set</span>
                )}
              </div>
              <div className="flex gap-1.5">
                <Button size="sm" variant="outline" onClick={onLocateMe}>
                  <LocateFixed className="h-4 w-4" /> Locate
                </Button>
                <Button size="sm" variant="outline" onClick={onPickOnMap}>
                  Pick on map
                </Button>
              </div>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>Category</Label>
            <Select value={category} onValueChange={setCategory}>
              <SelectTrigger>
                <SelectValue placeholder="What's the problem?" />
              </SelectTrigger>
              <SelectContent>
                {COMPLAINT_CATEGORIES.map((c) => (
                  <SelectItem key={c} value={c}>
                    {c}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center justify-between rounded-lg border p-3">
            <div>
              <Label className="cursor-pointer">Is it blocking / causing traffic?</Label>
              <p className="text-[11px] text-muted-foreground">Helps police prioritise obstruction over minor parking.</p>
            </div>
            <Switch checked={traffic} onCheckedChange={setTraffic} />
          </div>

          <div className="space-y-1.5">
            <Label>Description</Label>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. Cars parked across both lanes near the junction during evening rush."
            />
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
                Vehicle number <span className="text-muted-foreground">(optional)</span>
              </Label>
              <Input
                value={vehicleNumber}
                onChange={(e) => setVehicleNumber(e.target.value)}
                placeholder="KA01AB1234"
                className="uppercase"
              />
            </div>
          </div>

          <Button className="w-full" disabled={!canSubmit} onClick={submit}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            Submit report
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
