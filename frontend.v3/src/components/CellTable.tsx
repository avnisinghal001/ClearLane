import { useMemo } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { MapPin, ListChecks, Waypoints, MoonStar } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/DataTable";
import { picColor, num } from "@/lib/format";
import {
  cellTier, isBlindSpot, underObserved, flowImpactTable, priorityScore, type FlowImpactRanked,
} from "@/lib/signals";
import type { Cell } from "@/lib/types";

export type CellTableVariant = "priority" | "flow" | "blind";

const TIER_VARIANT: Record<string, "destructive" | "warning" | "secondary"> = {
  P1: "destructive",
  P2: "warning",
  P3: "secondary",
  P4: "secondary",
};

function ScoreChip({ value }: { value: number }) {
  return (
    <span className="num inline-flex h-7 w-9 items-center justify-center rounded-md text-xs font-bold text-white" style={{ background: picColor(value) }}>
      {Math.round(value)}
    </span>
  );
}

const META: Record<CellTableVariant, { title: string; icon: typeof ListChecks; caption: string }> = {
  priority: {
    title: "Priority queue",
    icon: ListChecks,
    caption: "Ranked by where to act now — chronic pressure plus a short live boost from fresh reports. Estimated from tickets — not measured congestion.",
  },
  flow: {
    title: "Road impact",
    icon: Waypoints,
    caption: "How much a blockage here could disrupt movement — parking pressure weighted by road type and nearby metro/markets. An estimate — not measured congestion.",
  },
  blind: {
    title: "Evening blind spots",
    icon: MoonStar,
    caption: "Busy spots that look lightly patrolled — most likely missed during the evening rush. A lead to check, not a confirmed hotspot.",
  },
};

// One reusable ranked cell table for the Priority-queue, Flow-impact and Blind-spot
// views (single source for govt + police). All cell/station-level; never per officer.
export function CellTable({
  cells,
  variant,
  onFocus,
  title,
}: {
  cells: Cell[];
  variant: CellTableVariant;
  onFocus: (c: Cell) => void;
  title?: string;
}) {
  const flow = useMemo(() => (variant === "flow" ? flowImpactTable(cells) : null), [cells, variant]);

  const rows = useMemo(() => {
    if (variant === "flow" && flow) {
      return [...cells].sort((a, b) => (flow.get(b.h3_r10)?.score ?? 0) - (flow.get(a.h3_r10)?.score ?? 0)).slice(0, 60);
    }
    if (variant === "blind") {
      return cells.filter((c) => isBlindSpot(c) || c.emerging).sort((a, b) => (b.pic_score ?? 0) - (a.pic_score ?? 0)).slice(0, 60);
    }
    return [...cells].sort((a, b) => priorityScore(b) - priorityScore(a)).slice(0, 60);
  }, [cells, variant, flow]);

  const columns = useMemo<ColumnDef<Cell>[]>(() => {
    const idCol: ColumnDef<Cell> = {
      id: "cell",
      header: "Cell",
      cell: ({ row }) => {
        const c = row.original;
        return (
          <div className="min-w-0">
            <div className="truncate text-[13px] font-medium">{c.police_station ?? "Unassigned"}</div>
            <div className="font-mono text-[11px] text-muted-foreground">
              {c.h3_r10.slice(0, 9)}… · {c.road_class ?? "—"}
            </div>
          </div>
        );
      },
    };
    const focusCol: ColumnDef<Cell> = {
      id: "focus",
      header: "",
      cell: ({ row }) => (
        <Button size="icon" variant="ghost" title="Show on map" onClick={() => onFocus(row.original)}>
          <MapPin className="h-4 w-4" />
        </Button>
      ),
    };

    if (variant === "flow") {
      return [
        {
          id: "flow",
          header: "Flow impact",
          accessorFn: (c: Cell) => flow?.get(c.h3_r10)?.score ?? 0,
          cell: ({ row }) => {
            const f = flow?.get(row.original.h3_r10) as FlowImpactRanked | undefined;
            return (
              <div className="flex items-center gap-2">
                <ScoreChip value={f?.score ?? 0} />
                <span className="text-[11px] text-muted-foreground">×{f?.multiplier?.toFixed(2) ?? "—"}</span>
              </div>
            );
          },
        },
        idCol,
        {
          id: "junction",
          header: "Junction",
          cell: ({ row }) => <span className="num text-[12px]">{Math.round((flow?.get(row.original.h3_r10)?.junction ?? 0) * 100)}%</span>,
        },
        { id: "pic", header: "Pressure", cell: ({ row }) => <span className="num text-[12px]">{Math.round(row.original.pic_score)}</span> },
        focusCol,
      ];
    }

    if (variant === "blind") {
      return [
        {
          id: "tier",
          header: "Tier",
          cell: ({ row }) => <Badge variant={TIER_VARIANT[cellTier(row.original)]}>{cellTier(row.original)}</Badge>,
        },
        idCol,
        {
          id: "why",
          header: "Why flagged",
          cell: ({ row }) => {
            const c = row.original;
            return (
              <div className="flex flex-wrap gap-1">
                {isBlindSpot(c) && <Badge variant="warning" className="font-normal">evening blind spot</Badge>}
                {c.emerging && <Badge variant="modeled" className="font-normal">rising</Badge>}
                {underObserved(c) && (c.rank_divergence ?? 0) >= 90 && <Badge variant="secondary" className="font-normal">lightly patrolled</Badge>}
              </div>
            );
          },
        },
        { id: "pic", header: "Pressure", cell: ({ row }) => <span className="num text-[12px] font-semibold">{Math.round(row.original.pic_score)}</span> },
        focusCol,
      ];
    }

    // priority
    return [
      {
        id: "priority",
        header: "Priority",
        accessorFn: (c: Cell) => priorityScore(c),
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <ScoreChip value={priorityScore(row.original)} />
            <Badge variant={TIER_VARIANT[cellTier(row.original)]}>{cellTier(row.original)}</Badge>
          </div>
        ),
      },
      idCol,
      { id: "pic", header: "Pressure", cell: ({ row }) => <span className="num text-[12px]">{Math.round(row.original.pic_score)}</span> },
      {
        id: "peak",
        header: "Peak / wk",
        cell: ({ row }) => (
          <span className="text-[11px] text-muted-foreground">
            {row.original.peak_dow ?? "—"} · {num(row.original.weekly_expected, 0)}/wk
          </span>
        ),
      },
      focusCol,
    ];
  }, [variant, flow, onFocus]);

  const meta = META[variant];
  const Icon = meta.icon;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Icon className="h-4 w-4 text-primary" /> {title ?? meta.title}
          <Badge variant="secondary">{rows.length}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <DataTable columns={columns} data={rows} pageSize={10} dense empty="No cells in scope." />
        <p className="text-[11px] leading-tight text-muted-foreground">{meta.caption} Area-level only — never per officer.</p>
      </CardContent>
    </Card>
  );
}
