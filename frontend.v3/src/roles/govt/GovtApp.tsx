import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { LayoutDashboard, Building2, Map as MapIcon, ShieldCheck } from "lucide-react";
import { AppShell, type NavItem } from "@/components/AppShell";
import { ClearLaneMap } from "@/components/map/ClearLaneMap";
import { TimeControl, type TimeValue } from "@/components/TimeControl";
import { CellDrawer } from "@/components/CellDrawer";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { KpiStrip } from "./KpiStrip";
import { StationTable } from "./StationTable";
import { Analytics } from "./Analytics";
import { Scorecard } from "./Scorecard";
import { GovtPlaybook } from "./GovtPlaybook";
import { useMapData } from "@/hooks/useMapData";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { getCausal, getEvaluation, getKpis, getSim, getStations } from "@/lib/api";
import { logout } from "@/lib/auth";
import type { Cell, Kpis, Station } from "@/lib/types";

/* eslint-disable @typescript-eslint/no-explicit-any */

export function GovtApp() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const [tab, setTab] = useState<"overview" | "stations" | "map" | "evidence">("overview");
  const [time, setTime] = useState<TimeValue>({ when: "now", hour: 18 });
  const { data, refetch } = useMapData(time.when, time.hour);

  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [stations, setStations] = useState<Station[]>([]);
  const [sim, setSim] = useState<any>(null);
  const [causal, setCausal] = useState<any>(null);
  const [evaluation, setEvaluation] = useState<any>(null);
  const [selected, setSelected] = useState<Cell | null>(null);
  const [flyTo, setFlyTo] = useState<[number, number] | null>(null);

  useEffect(() => {
    getKpis().then(setKpis);
    getStations().then(setStations);
    getSim().then(setSim);
    getCausal().then(setCausal);
    getEvaluation().then(setEvaluation);
  }, []);

  const nav: NavItem[] = [
    { key: "overview", label: "Overview", icon: <LayoutDashboard className="h-5 w-5" /> },
    { key: "stations", label: "Stations", icon: <Building2 className="h-5 w-5" /> },
    { key: "map", label: "City map", icon: <MapIcon className="h-5 w-5" /> },
    { key: "evidence", label: "Evidence", icon: <ShieldCheck className="h-5 w-5" /> },
  ];

  function focusStation(s: Station) {
    setFlyTo([s.lat, s.lon]);
    setTab("map");
  }

  return (
    <AppShell
      roleLabel="Government Command"
      nav={nav}
      active={tab}
      onNav={(k) => setTab(k as typeof tab)}
      onSwitchRole={() => navigate("/")}
      onLogout={() => {
        logout();
        navigate("/");
      }}
      userName="City-wide"
      fill={tab === "map"}
    >
      {tab === "overview" && (
        <div className="mx-auto max-w-7xl space-y-5 p-4 sm:p-6">
          <div>
            <h2 className="text-xl font-bold">City overview</h2>
            <p className="text-sm text-muted-foreground">
              Bias-corrected parking-enforcement intelligence across {stations.length} stations. Honest by design — we never claim to measure congestion from tickets.
            </p>
          </div>
          {kpis ? <KpiStrip k={kpis} /> : <div className="h-24 animate-pulse rounded-xl bg-muted" />}
          <GovtPlaybook kpis={kpis} onDone={() => { refetch(); getKpis().then(setKpis); }} />
          {kpis && sim && causal && <Analytics kpis={kpis} sim={sim} causal={causal} />}
        </div>
      )}

      {tab === "stations" && (
        <div className="mx-auto max-w-7xl space-y-4 p-4 sm:p-6">
          <div>
            <h2 className="text-xl font-bold">Per-station performance</h2>
            <p className="text-sm text-muted-foreground">Click a station to locate it on the city map. Aggregated to the zone level only — never per officer.</p>
          </div>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Stations ({stations.length})</CardTitle>
            </CardHeader>
            <CardContent>
              <StationTable stations={stations} onFocus={focusStation} />
            </CardContent>
          </Card>
        </div>
      )}

      {tab === "map" && (
        <div className="absolute inset-0">
          <ClearLaneMap cells={data?.cells ?? []} source={data?.source ?? "live"} flyTo={flyTo} onCellClick={setSelected} defaultHeat defaultZoom={11} />
          <div className="absolute left-2 top-2 z-[500] w-[min(20rem,calc(100%-4.5rem))]">
            <TimeControl value={time} onChange={setTime} />
            <div className="mt-2">
              <Badge variant={data?.source === "forecast" ? "modeled" : "live"}>{data?.source === "forecast" ? "Forecast" : "Live"}</Badge>
            </div>
          </div>
        </div>
      )}

      {tab === "evidence" && (
        <div className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
          <div>
            <h2 className="text-xl font-bold">Model evidence scorecard</h2>
            <p className="text-sm text-muted-foreground">Auditable capability bars from the ML pipeline's self-grading.</p>
          </div>
          {evaluation ? <Scorecard evaluation={evaluation} /> : <div className="h-40 animate-pulse rounded-xl bg-muted" />}
        </div>
      )}

      <CellDrawer cell={selected} side={isMobile ? "bottom" : "right"} onClose={() => setSelected(null)} />
    </AppShell>
  );
}
