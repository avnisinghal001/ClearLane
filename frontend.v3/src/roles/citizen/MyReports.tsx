import { useMemo } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Inbox } from "lucide-react";
import { DataTable } from "@/components/DataTable";
import { Badge } from "@/components/ui/badge";
import { relativeTime } from "@/lib/time";
import type { Ticket } from "@/lib/types";

export function MyReports({ tickets }: { tickets: Ticket[] }) {
  const columns = useMemo<ColumnDef<Ticket>[]>(
    () => [
      {
        accessorKey: "created_at",
        header: "Filed",
        cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{relativeTime(row.original.created_at)}</span>,
      },
      { accessorKey: "category", header: "Category", cell: ({ row }) => <span className="font-medium">{row.original.category}</span> },
      { accessorKey: "station", header: "Station", cell: ({ row }) => row.original.station ?? "—" },
      {
        accessorKey: "traffic_caused",
        header: "Traffic?",
        cell: ({ row }) =>
          row.original.traffic_caused == null ? (
            "—"
          ) : row.original.traffic_caused ? (
            <Badge variant="warning">Yes</Badge>
          ) : (
            <Badge variant="secondary">No</Badge>
          ),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => {
          const t = row.original;
          if (t.status === "open") return <Badge variant="modeled">Open</Badge>;
          return t.resolution ? <Badge variant="success">Resolved</Badge> : <Badge variant="secondary">Closed</Badge>;
        },
      },
      {
        id: "outcome",
        header: "Outcome",
        cell: ({ row }) => <span className="text-xs text-muted-foreground">{row.original.reason ?? (row.original.status === "open" ? "Awaiting verification" : "—")}</span>,
      },
    ],
    [],
  );

  if (!tickets.length) {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-14 text-center">
        <Inbox className="h-8 w-8 text-muted-foreground" />
        <p className="mt-3 font-medium">No reports yet</p>
        <p className="mt-1 max-w-xs text-sm text-muted-foreground">
          Spotted a vehicle blocking the road? File a report from the map — you'll see its verification status here.
        </p>
      </div>
    );
  }

  return <DataTable columns={columns} data={tickets} initialSort={[{ id: "created_at", desc: true }]} pageSize={8} />;
}
