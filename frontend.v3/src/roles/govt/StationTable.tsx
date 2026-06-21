import { useMemo } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { DataTable } from "@/components/DataTable";
import { Badge } from "@/components/ui/badge";
import { num } from "@/lib/format";
import { picColor } from "@/lib/format";
import type { Station } from "@/lib/types";

function PicCell({ v }: { v: number }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: picColor(v) }} />
      <span className="num font-medium">{Math.round(v)}</span>
    </span>
  );
}

export function StationTable({ stations, onFocus }: { stations: Station[]; onFocus: (s: Station) => void }) {
  const columns = useMemo<ColumnDef<Station>[]>(
    () => [
      { accessorKey: "station", header: "Station", cell: ({ row }) => <span className="font-medium">{row.original.station}</span> },
      { accessorKey: "n_tickets", header: "Tickets", cell: ({ row }) => <span className="num">{num(row.original.n_tickets)}</span> },
      { accessorKey: "n_cells", header: "Cells", cell: ({ row }) => <span className="num">{num(row.original.n_cells)}</span> },
      { accessorKey: "max_pic", header: "Max PIC", cell: ({ row }) => <PicCell v={row.original.max_pic} /> },
      { accessorKey: "mean_pic", header: "Mean PIC", cell: ({ row }) => <span className="num">{row.original.mean_pic.toFixed(1)}</span> },
      {
        accessorKey: "n_sig_hot",
        header: "Sig. hot",
        cell: ({ row }) => <span className="num">{row.original.n_sig_hot}</span>,
      },
      {
        accessorKey: "n_emerging",
        header: "Emerging",
        cell: ({ row }) => (row.original.n_emerging > 0 ? <Badge variant="warning">{row.original.n_emerging}</Badge> : <span className="text-muted-foreground">0</span>),
      },
      {
        accessorKey: "weekly_expected",
        header: "Expected/wk",
        cell: ({ row }) => <span className="num">{num(row.original.weekly_expected)}</span>,
      },
      {
        accessorKey: "dispatch_stops",
        header: "Route",
        cell: ({ row }) =>
          row.original.dispatch_stops > 0 ? (
            <span className="num text-xs text-muted-foreground">
              {row.original.dispatch_stops} stops · {row.original.route_km} km
            </span>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
      },
    ],
    [],
  );

  return (
    <DataTable
      columns={columns}
      data={stations}
      searchKey="station"
      searchPlaceholder="Search station…"
      initialSort={[{ id: "max_pic", desc: true }]}
      pageSize={12}
      onRowClick={onFocus}
    />
  );
}
