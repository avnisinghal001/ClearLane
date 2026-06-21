import { CheckCircle2, AlertCircle, Clock } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/* eslint-disable @typescript-eslint/no-explicit-any */

export function Scorecard({ evaluation }: { evaluation: any }) {
  const rows: any[] = evaluation?.scorecard ?? [];
  const pending: string[] = evaluation?.pending_live_api ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="success" className="gap-1">
          <CheckCircle2 className="h-3.5 w-3.5" /> {evaluation?.n_pass ?? 0}/{evaluation?.n_capabilities ?? 0} capabilities passed
        </Badge>
        <span className="text-sm text-muted-foreground">Each is an auditable bar — never a claim that ticket data measures congestion.</span>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {rows.map((r) => (
          <Card key={r.capability}>
            <CardHeader className="pb-2">
              <div className="flex items-start justify-between gap-2">
                <CardTitle className="text-sm">{r.capability}</CardTitle>
                <Badge variant={r.status === "PASS" ? "success" : "warning"} className="gap-1">
                  {r.status === "PASS" ? <CheckCircle2 className="h-3 w-3" /> : <AlertCircle className="h-3 w-3" />}
                  {r.status}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-1 pt-0">
              <div className="text-sm font-medium">{r.headline}</div>
              <div className="text-xs text-muted-foreground">Criteria: {r.criteria}</div>
              <div className="font-mono text-[11px] text-muted-foreground">stage {r.stage}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {pending.length > 0 && (
        <Card className="border-dashed">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Clock className="h-4 w-4 text-muted-foreground" /> Pending live API
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <ul className="list-inside list-disc space-y-1 text-sm text-muted-foreground">
              {pending.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
