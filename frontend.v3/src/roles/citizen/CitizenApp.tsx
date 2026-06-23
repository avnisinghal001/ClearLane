import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Map as MapIcon, Megaphone, ListChecks, Crosshair } from "lucide-react";
import { AppShell, type NavItem } from "@/components/AppShell";
import { ClearLaneMap, type MapPin } from "@/components/map/ClearLaneMap";
import { TimeControl, type TimeValue } from "@/components/TimeControl";
import { CellDrawer } from "@/components/CellDrawer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/toast";
import { ReportSheet } from "./ReportSheet";
import { MyReports } from "./MyReports";
import { useGeolocation } from "@/hooks/useGeolocation";
import { useMapData } from "@/hooks/useMapData";
import { useMapFocus } from "@/hooks/useMapFocus";
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
  const { data, loading } = useMapData(time.when, time.hour, time.date);

  const [selected, setSelected] = useState<Cell | null>(null);
  const { focus, setFocus } = useMapFocus();
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
  // my filed reports -> blue markers on the map
  const reportPins = useMemo<MapPin[]>(
    () =>
      myReports
        .filter((t) => t.lat != null && t.lon != null)
        .map((t) => ({
          key: t.id,
          lat: t.lat as number,
          lon: t.lon as number,
          color: "#2563eb",
          pulse: true,
          label: `${t.category ?? "Your report"} · ${t.station ?? "nearest station"}`,
        })),
    [myReports],
  );
  const evidence = useMemo<[number, number][]>(
    () => allTickets.filter((t) => t.lat != null && t.lon != null).map((t) => [t.lat as number, t.lon as number]),
    [allTickets],
  );

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
    { key: "reports", label: "Your reports", icon: <ListChecks className="h-5 w-5" /> },
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
      bottomNavOnMobile
    >
      {tab === "map" ? (
        <div className="absolute inset-0">
          <ClearLaneMap
            cells={data?.cells ?? []}
            source={data?.source ?? "live"}
            audience="citizen"
            userLocation={cityCoords}
            flyTo={flyTo}
            focus={focus}
            modalOpen={Boolean(selected)}
            onCellClick={(c) => setFocus({ lat: c.lat, lon: c.lon, h3: c.h3_r10 })}
            onFocusOpen={(c) => setSelected((data?.cells ?? []).find((x) => x.h3_r10 === c.h3_r10) ?? c)}
            pickMode={pickMode}
            onPick={(ll) => {
              setReportLoc(ll);
              setPickMode(false);
              setReportOpen(true);
            }}
            onLongPress={(ll) => openReport(ll)}
            onPickModeChange={setPickMode}
            enableComplaint
            pins={reportPins}
            evidence={evidence}
            bottomSafe
            defaultZoom={13}
            lens={{ badge: data?.badge, nEmerging: data?.n_emerging, nAdjusted: data?.n_adjusted, learningAdjusted: data?.learning_adjusted }}
          />

          {/* time lens */}
          <div className="absolute left-2 top-2 z-[500] w-[min(20rem,calc(100%-4.5rem))]">
            <TimeControl value={time} onChange={setTime} plain />
            <div className="mt-2 flex items-center gap-2">
              <Badge variant={data?.source === "forecast" ? "modeled" : "live"}>
                {data?.source === "forecast" ? "Forecast" : "Now"}
              </Badge>
              {loading && <span className="text-[11px] text-muted-foreground">updating…</span>}
            </div>
          </div>

          {/* report CTA — vertical 90° tab anchored to the RIGHT EDGE (or long-press
              the map anywhere). Shimmer sweep; vertical writing-mode rotates the label. */}
          <button
            onClick={() => openReport()}
            aria-label="Report a parking problem"
            title="Report a parking problem — or long-press the map"
            className="group fixed right-0 top-1/2 z-[610] flex -translate-y-1/2 items-center gap-2 overflow-hidden rounded-l-xl bg-primary py-4 pl-2 pr-1.5 font-semibold text-primary-foreground shadow-lg ring-1 ring-black/10 transition-[padding] hover:pl-2.5 [writing-mode:vertical-rl]"
          >
            <span
              aria-hidden
              className="pointer-events-none absolute inset-0 animate-shimmer bg-gradient-to-b from-transparent via-white/40 to-transparent"
            />
            <Megaphone className="h-4 w-4 rotate-90" />
            <span className="text-sm tracking-wide">Report a problem</span>
          </button>
        </div>
      ) : (
        <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
          <div>
            <h2 className="text-xl font-bold">Your reports</h2>
            <p className="text-sm text-muted-foreground">See what happened to the parking problems you reported.</p>
          </div>
          <MyReports tickets={myReports} />
        </div>
      )}

      <CellDrawer cell={selected} cells={data?.cells ?? []} audience="citizen" side={isMobile ? "bottom" : "right"} onClose={() => setSelected(null)}>
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
