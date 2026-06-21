import { useMemo, useState } from "react";
import { Plus, X, Users } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { Officer, RosterPayload } from "@/lib/types";

// Light/orange-theme shift palette (mirrors the patrol-board status hues' siblings).
const SHIFT_COLOR: Record<string, string> = {
  A: "#2563eb",
  B: "#f59e0b",
  C: "#ea580c",
  D: "#7c3aed",
};

const RANK_HEADING: Record<string, string> = {
  Inspector: "Inspector · Station House Officer",
  "Police Sub-Inspector": "Sub-Inspectors",
  "Assistant Sub-Inspector": "Assistant Sub-Inspectors",
  "Head Constable": "Head Constables",
  Constable: "Constables",
};

// Members & hierarchy view for one station. Ranks top-down (Inspector/SHO → Constables),
// each officer with a rank badge, shift chip + station-prefixed badge id. Add / edit
// (rank + shift) / remove when the viewer is in scope (canManage). Per-officer click
// surfaces that officer's tickets. Operational record only — never a performance score.
export function RosterPanel({
  roster,
  canManage,
  loading,
  onAdd,
  onPatch,
  onRemove,
  onSelectOfficer,
  selectedOfficerId,
}: {
  roster: RosterPayload | null;
  canManage: boolean;
  loading?: boolean;
  onAdd: (name: string, rank: string, shift: string) => void;
  onPatch?: (oid: number, patch: { rank?: string; shift?: string }) => void;
  onRemove: (oid: number) => void;
  onSelectOfficer?: (o: Officer) => void;
  selectedOfficerId?: number | null;
}) {
  const ranks = roster?.ranks ?? [];
  const shiftOrder = roster?.shift_order ?? ["A", "B", "C", "D"];
  const shifts = roster?.shifts ?? {};
  const abbr = roster?.rank_abbr ?? {};
  const officers = roster?.officers ?? [];

  const [name, setName] = useState("");
  const [rank, setRank] = useState("Constable");
  const [shift, setShift] = useState("A");

  const byRank = useMemo(() => {
    const g: Record<string, Officer[]> = {};
    ranks.forEach((r) => (g[r] = []));
    officers.forEach((o) => (g[o.rank] ?? (g[o.rank] = [])).push(o));
    return g;
  }, [officers, ranks]);

  const summary = roster?.summary;

  function submit() {
    if (!name.trim()) return;
    onAdd(name, rank, shift);
    setName("");
    setRank("Constable");
    setShift("A");
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Users className="h-4 w-4 text-primary" /> Members &amp; hierarchy
            <Badge variant="secondary">{summary?.total ?? officers.length}</Badge>
          </CardTitle>
          <Badge variant={roster?.live ? "live" : "modeled"}>{roster?.live ? "Live roster" : "Offline seed"}</Badge>
        </div>
        {/* per-shift roster summary */}
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          {shiftOrder.map((s) => (
            <span
              key={s}
              className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium"
              style={{ borderColor: SHIFT_COLOR[s], color: SHIFT_COLOR[s] }}
            >
              {s} {shifts[s]?.label ?? ""} <span className="num font-semibold">{summary?.by_shift?.[s] ?? 0}</span>
            </span>
          ))}
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* add-officer row (name + rank + shift) */}
        {canManage && (
          <div className="flex flex-wrap items-end gap-2 rounded-lg border bg-muted/30 p-2.5">
            <div className="min-w-[9rem] flex-1">
              <label className="mb-1 block text-[11px] font-medium text-muted-foreground">Officer name</label>
              <Input value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submit()} placeholder="e.g. Kiran Gowda" />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-muted-foreground">Rank</label>
              <select aria-label="Rank" value={rank} onChange={(e) => setRank(e.target.value)} className="h-9 rounded-md border bg-background px-2 text-sm">
                {ranks.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-muted-foreground">Shift</label>
              <select aria-label="Shift" value={shift} onChange={(e) => setShift(e.target.value)} className="h-9 rounded-md border bg-background px-2 text-sm">
                {shiftOrder.map((s) => (
                  <option key={s} value={s}>
                    {s} · {shifts[s]?.label ?? s}
                  </option>
                ))}
              </select>
            </div>
            <Button onClick={submit} disabled={!name.trim()} className="gap-1.5">
              <Plus className="h-4 w-4" /> Add
            </Button>
          </div>
        )}

        {/* ranked hierarchy */}
        <div className="space-y-3">
          {loading && <div className="text-sm text-muted-foreground">Loading roster…</div>}
          {!loading &&
            ranks.map((r) => {
              const list = byRank[r] ?? [];
              if (!list.length) return null;
              return (
                <div key={r}>
                  <div className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {RANK_HEADING[r] ?? r}
                    <span className="num font-bold text-foreground">{list.length}</span>
                  </div>
                  <div className="space-y-1">
                    {list.map((o) => (
                      <div
                        key={o.id}
                        className={cn(
                          "flex items-center gap-2 rounded-lg border bg-card px-2.5 py-1.5",
                          onSelectOfficer && "cursor-pointer hover:bg-accent",
                          selectedOfficerId === o.id && "ring-1 ring-primary",
                        )}
                        onClick={() => onSelectOfficer?.(o)}
                      >
                        <span className="inline-flex h-6 min-w-[2.4rem] items-center justify-center rounded bg-muted px-1 text-[10px] font-bold text-muted-foreground" title={o.rank}>
                          {abbr[o.rank] ?? "PC"}
                        </span>
                        <span className="min-w-0 flex-1 truncate text-sm font-medium">{o.name}</span>
                        {canManage && onPatch ? (
                          <select
                            aria-label={`Shift for ${o.name}`}
                            value={o.shift}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => onPatch(o.id, { shift: e.target.value })}
                            className="h-7 rounded-md border bg-background px-1 text-xs font-semibold"
                            style={{ color: SHIFT_COLOR[o.shift] }}
                          >
                            {shiftOrder.map((s) => (
                              <option key={s} value={s}>
                                {s}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="rounded-full border px-2 py-0.5 text-[11px] font-semibold" style={{ borderColor: SHIFT_COLOR[o.shift], color: SHIFT_COLOR[o.shift] }}>
                            {o.shift}
                          </span>
                        )}
                        <span className="num hidden w-[5.5rem] text-right text-xs text-muted-foreground sm:inline">{o.badge}</span>
                        {canManage && (
                          <button
                            title="Remove officer"
                            onClick={(e) => {
                              e.stopPropagation();
                              onRemove(o.id);
                            }}
                            className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                          >
                            <X className="h-4 w-4" />
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          {!loading && !officers.length && <div className="text-sm text-muted-foreground">No officers on strength.</div>}
        </div>

        <p className="text-[11px] leading-tight text-muted-foreground">
          Roster is an operational record (rank · shift · badge). ClearLane never scores, ranks or profiles an individual officer —
          all hotspot/priority signals stay zone/cell-level.
        </p>
      </CardContent>
    </Card>
  );
}
