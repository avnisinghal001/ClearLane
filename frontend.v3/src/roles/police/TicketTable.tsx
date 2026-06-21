import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, User, FileText, Receipt } from "lucide-react";
import { DataTable } from "@/components/DataTable";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { relativeTime } from "@/lib/time";
import type { Ticket, TicketKind } from "@/lib/types";

const KIND_META: Record<TicketKind, { label: string; icon: typeof User }> = {
  citizen_complaint: { label: "Citizen", icon: User },
  police_ticket: { label: "Ticket", icon: FileText },
  chalan: { label: "Challan", icon: Receipt },
};

export function TicketTable({
  tickets,
  onResolve,
  onCreate,
  onRowFocus,
}: {
  tickets: Ticket[];
  onResolve: (t: Ticket) => void;
  onCreate: () => void;
  onRowFocus?: (t: Ticket) => void;
}) {
  const [status, setStatus] = useState<"open" | "closed" | "all">("open");

  const filtered = useMemo(() => (status === "all" ? tickets : tickets.filter((t) => t.status === status)), [tickets, status]);

  const counts = useMemo(
    () => ({
      open: tickets.filter((t) => t.status === "open").length,
      closed: tickets.filter((t) => t.status === "closed").length,
    }),
    [tickets],
  );

  const columns = useMemo<ColumnDef<Ticket>[]>(
    () => [
      {
        accessorKey: "created_at",
        header: "When",
        cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{relativeTime(row.original.created_at)}</span>,
      },
      {
        accessorKey: "kind",
        header: "Source",
        cell: ({ row }) => {
          const m = KIND_META[row.original.kind];
          const Icon = m.icon;
          return (
            <Badge variant={row.original.kind === "citizen_complaint" ? "modeled" : "secondary"} className="gap-1">
              <Icon className="h-3 w-3" />
              {m.label}
            </Badge>
          );
        },
      },
      { accessorKey: "category", header: "Category", cell: ({ row }) => <span className="font-medium">{row.original.category ?? "—"}</span> },
      {
        id: "officer",
        header: "Officer",
        cell: ({ row }) =>
          row.original.assigned_badge ? (
            <span className="whitespace-nowrap text-xs">
              <span className="num">{row.original.assigned_badge}</span>
              {row.original.assigned_name ? <span className="text-muted-foreground"> · {row.original.assigned_name}</span> : ""}
            </span>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
      },
      {
        id: "vehicle",
        header: "Vehicle",
        cell: ({ row }) => (
          <span className="whitespace-nowrap text-xs">
            {row.original.vehicle_number ? <span className="font-mono">{row.original.vehicle_number}</span> : "—"}
            {row.original.vehicle_type ? <span className="text-muted-foreground"> · {row.original.vehicle_type}</span> : ""}
          </span>
        ),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => {
          const t = row.original;
          if (t.status === "open") return <Badge variant="warning">Open</Badge>;
          return t.resolution ? <Badge variant="success">Resolved</Badge> : <Badge variant="secondary">Closed</Badge>;
        },
      },
      {
        id: "action",
        header: "",
        cell: ({ row }) =>
          row.original.status === "open" ? (
            <Button
              size="sm"
              variant="outline"
              onClick={(e) => {
                e.stopPropagation();
                onResolve(row.original);
              }}
            >
              Resolve
            </Button>
          ) : (
            <span className="text-xs text-muted-foreground">{row.original.reason ?? "—"}</span>
          ),
      },
    ],
    [onResolve],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Tabs value={status} onValueChange={(v) => setStatus(v as typeof status)}>
          <TabsList>
            <TabsTrigger value="open">Open · {counts.open}</TabsTrigger>
            <TabsTrigger value="closed">Closed · {counts.closed}</TabsTrigger>
            <TabsTrigger value="all">All</TabsTrigger>
          </TabsList>
        </Tabs>
        <Button onClick={onCreate} size="sm">
          <Plus className="h-4 w-4" /> Create ticket
        </Button>
      </div>
      <DataTable
        columns={columns}
        data={filtered}
        searchKey="category"
        searchPlaceholder="Search category…"
        initialSort={[{ id: "created_at", desc: true }]}
        pageSize={9}
        onRowClick={onRowFocus}
        empty={status === "open" ? "No open tickets — queue is clear." : "No tickets."}
      />
    </div>
  );
}
