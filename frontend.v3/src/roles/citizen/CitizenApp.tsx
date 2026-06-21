import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Map as MapIcon, Megaphone, ListChecks, Crosshair } from "lucide-react";
import { AppShell, type NavItem } from "@/components/AppShell";
import { ClearLaneMap } from "@/components/map/ClearLaneMap";
import { TimeControl, type TimeValue } from "@/components/TimeControl";
import { CellDrawer } from "@/components/CellDrawer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/toast";
import { ReportSheet } from "./ReportSheet";
import { MyReports } from "./MyReports";
import { useGeolocation } from "@/hooks/useGeolocation";
import { useMapData } from "@/hooks/useMapData";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { getTickets, postComplaint } from "@/lib/api";
import { logout } from "@/lib/auth";
import type { Cell, ComplaintInput, Ticket } from "@/lib/types";

const MY_KEY = "cl_v3_my_reports";
const loadMyIds = (): string[] => {
  try {
    return JSON.parse(localStorage.getItem(MY_KEY) || "[]");
  } catch {
    return [];
  }
};

export function CitizenApp() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const { cityCoords, request } = useGeolocation(true);

  const [tab, setTab] = useState<"map" | "reports">("map");
  const [time, setTime] = useState<TimeValue>({ when: "now", hour: 18 });
  const { data, loading } = useMapData(time.when, time.hour);

  const [selected, setSelected] = useState<Cell | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [pickMode, setPickMode] = useState(false);
  const [reportLoc, setReportLoc] = useState<[number, number] | null>(null);
  const [flyTo, setFlyTo] = useState<[number, number] | null>(null);

  const [myIds, setMyIds] = useState<string[]>(loadMyIds);
  const [allTickets, setAllTickets] = useState<Ticket[]>([]);

  const refreshTickets = useCallback(() => {
    getTickets({ limit: 500 }).then(setAllTickets).catch(() => {});
  }, []);
  useEffect(() => refreshTickets(), [refreshTickets]);

  const myReports = useMemo(() => allTickets.filter((t) => myIds.includes(t.id)), [allTickets, myIds]);

  const openReport = useCallback(
    (loc?: [number, number] | null) => {
      setReportLoc(loc ?? cityCoords ?? (data?.cells[0] ? [data.cells[0].lat, data.cells[0].lon] : null));
      setReportOpen(true);
    },
    [cityCoords, data],
  );

  async function submitReport(input: ComplaintInput) {
    const t = await postComplaint(input);
    const next = [t.id, ...myIds];
    setMyIds(next);
    localStorage.setItem(MY_KEY, JSON.stringify(next));
    refreshTickets();
    setReportOpen(false);
    setPickMode(false);
    toast("Report filed — thank you!", {
      desc: `Routed to ${t.station ?? "the nearest station"}. You're helping clear Bengaluru's lanes.`,
      tone: "success",
    });
  }

  const nav: NavItem[] = [
    { key: "map", label: "Map", icon: <MapIcon className="h-5 w-5" /> },
    { key: "report", label: "Report", icon: <Megaphone className="h-5 w-5" /> },
    { key: "reports", label: "My reports", icon: <ListChecks className="h-5 w-5" /> },
  ];

  function onNav(k: string) {
    if (k === "report") {
      openReport();
      return;
    }
    setTab(k as "map" | "reports");
  }

  return (
    <AppShell
      roleLabel="Citizen"
      nav={nav}
      active={tab}
      onNav={onNav}
      onSwitchRole={() => navigate("/")}
      onLogout={() => {
        logout();
        navigate("/");
      }}
      fill={tab === "map"}
    >
      {tab === "map" ? (
        <div className="absolute inset-0">
          <ClearLaneMap
            cells={data?.cells ?? []}
            source={data?.source ?? "live"}
            userLocation={cityCoords}
            flyTo={flyTo}
            onCellClick={setSelected}
            pickMode={pickMode}
            onPick={(ll) => {
              setReportLoc(ll);
              setPickMode(false);
              setReportOpen(true);
            }}
            defaultZoom={13}
          />

          {/* time lens */}
          <div className="absolute left-2 top-2 z-[500] w-[min(20rem,calc(100%-4.5rem))]">
            <TimeControl value={time} onChange={setTime} />
            <div className="mt-2 flex items-center gap-2">
              <Badge variant={data?.source === "forecast" ? "modeled" : "live"}>
                {data?.source === "forecast" ? "Forecast" : "Live"}
              </Badge>
              {loading && <span className="text-[11px] text-muted-foreground">updating…</span>}
            </div>
          </div>

          {/* pick-mode hint */}
          {pickMode && (
            <div className="absolute left-1/2 top-3 z-[600] -translate-x-1/2 rounded-full border bg-background/95 px-3 py-1.5 text-sm shadow-md backdrop-blur">
              Tap the spot to report
            </div>
          )}

          {/* report CTA — bottom-right FAB, clear of the mobile nav */}
          <Button
            onClick={() => openReport()}
            className="absolute bottom-20 right-4 z-[610] gap-2 rounded-full px-5 shadow-lg md:bottom-6"
          >
            <Megaphone className="h-4 w-4" /> Report incident
          </Button>
        </div>
      ) : (
        <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
          <div>
            <h2 className="text-xl font-bold">My reports</h2>
            <p className="text-sm text-muted-foreground">Track the verification status of parking problems you've reported.</p>
          </div>
          <MyReports tickets={myReports} />
        </div>
      )}

      <CellDrawer cell={selected} side={isMobile ? "bottom" : "right"} onClose={() => setSelected(null)}>
        {selected && (
          <div className="flex gap-2">
            <Button
              className="flex-1"
              onClick={() => {
                openReport([selected.lat, selected.lon]);
                setSelected(null);
              }}
            >
              <Megaphone className="h-4 w-4" /> Report here
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setFlyTo([selected.lat, selected.lon]);
                setSelected(null);
              }}
            >
              <Crosshair className="h-4 w-4" /> Zoom
            </Button>
          </div>
        )}
      </CellDrawer>

      <ReportSheet
        open={reportOpen}
        onClose={() => setReportOpen(false)}
        location={reportLoc}
        onLocateMe={() => {
          request();
          if (cityCoords) setReportLoc(cityCoords);
        }}
        onPickOnMap={() => {
          setReportOpen(false);
          setTab("map");
          setPickMode(true);
        }}
        onSubmit={submitReport}
      />
    </AppShell>
  );
}
