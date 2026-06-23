import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Loader2, MapPin, Shield, ShieldCheck } from "lucide-react";
import { Logo } from "./Brand";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { enterCitizen, login } from "@/lib/auth";
import { getStations } from "@/lib/api";
import type { Station } from "@/lib/types";
import { cn } from "@/lib/utils";

type RoleKey = "citizen" | "station" | "govt";

const ROLES: { key: RoleKey; label: string; icon: typeof MapPin; blurb: string; hero: string }[] = [
  {
    key: "citizen",
    label: "Citizen",
    icon: MapPin,
    blurb: "See parking-congestion hotspots near you and report illegal parking that blocks a lane.",
    hero: "/illustrations/hero-citizen.png",
  },
  {
    key: "station",
    label: "Police",
    icon: Shield,
    blurb: "A command map, next-day deployment zones, and your jurisdiction's ticket queue.",
    hero: "/illustrations/hero-police.png",
  },
  // Government sign-in is hidden for now (the role + routes still exist).
];

export function RoleLanding() {
  const navigate = useNavigate();
  const [role, setRole] = useState<RoleKey>("citizen");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [stations, setStations] = useState<Station[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getStations()
      .then(setStations)
      .catch(() => {});
  }, []);

  const active = ROLES.find((r) => r.key === role)!;
  const stationChips = useMemo(() => stations.slice(0, 4).map((s) => s.slug).filter(Boolean), [stations]);

  function selectRole(r: RoleKey) {
    setRole(r);
    setError(null);
    if (r === "govt") {
      setUsername("govt");
      setPassword("govt");
    } else {
      setUsername("");
      setPassword("");
    }
  }

  function pick(slug: string) {
    setUsername(slug);
    setPassword(slug);
  }

  async function submit(e?: React.FormEvent) {
    e?.preventDefault();
    if (role === "citizen") {
      enterCitizen();
      navigate("/citizen");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const a = await login(role, username, password);
      navigate(a.role === "govt" ? "/govt" : "/police");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-[100dvh] w-full bg-background md:grid md:grid-cols-[1.05fr_1fr]">
      {/* Visual hero — top banner on mobile, left panel on desktop */}
      <div className="relative h-[34vh] min-h-[260px] w-full overflow-hidden md:h-auto">
        {ROLES.map((r) => (
          <img
            key={r.key}
            src={r.hero}
            alt=""
            aria-hidden
            className={cn(
              "absolute inset-0 h-full w-full object-cover transition-opacity duration-700",
              r.key === role ? "opacity-100" : "opacity-0",
            )}
          />
        ))}
        <div className="absolute inset-0 bg-gradient-to-t from-[#070b16] via-[#070b16]/70 to-[#070b16]/20 md:bg-gradient-to-tr md:from-[#070b16] md:via-[#070b16]/55 md:to-transparent" />

        {/* brand */}
        <div className="absolute left-5 top-5 flex items-center gap-2.5 text-white sm:left-8 sm:top-8">
          <Logo className="h-8 w-8 drop-shadow" />
          <div className="text-lg font-extrabold tracking-tight drop-shadow">
            Tra<span className="text-primary">Fix</span>
          </div>
        </div>

        {/* headline */}
        <div className="absolute inset-x-0 bottom-0 p-5 text-white sm:p-8 md:p-10">
          <h1 className="max-w-md text-2xl font-extrabold leading-tight tracking-tight drop-shadow-sm sm:text-3xl">
            Parking enforcement that clears the lane.
          </h1>
          <p className="mt-2 max-w-md text-sm text-white/80 sm:text-[15px]">
            Bengaluru's parking-violation data, bias-corrected into a ranked, hour-aware deployment plan.
          </p>
          <div className="mt-4 hidden flex-wrap items-center gap-2 text-xs text-white/85 sm:flex">
            <span className="inline-flex items-center gap-1 rounded-full bg-white/10 px-3 py-1 font-medium backdrop-blur-sm">
              <ShieldCheck className="h-3.5 w-3.5 text-[hsl(var(--live))]" /> Honesty contract
            </span>
            <span className="rounded-full bg-white/10 px-3 py-1 font-medium backdrop-blur-sm">H3 cell-level</span>
            <span className="rounded-full bg-white/10 px-3 py-1 font-medium backdrop-blur-sm">Works offline</span>
          </div>
        </div>
      </div>

      {/* Sign-in panel */}
      <div className="flex flex-1 items-center justify-center px-5 py-8 sm:px-8">
        <form onSubmit={submit} className="w-full max-w-sm">
          <h2 className="text-2xl font-bold tracking-tight">Welcome</h2>
          <p className="mt-1 text-sm text-muted-foreground">Choose how you'll use TraFix.</p>

          {/* role segmented control */}
          <div className="mt-5 grid grid-cols-2 gap-1 rounded-xl bg-muted p-1">
            {ROLES.map((r) => {
              const Icon = r.icon;
              return (
                <button
                  key={r.key}
                  type="button"
                  onClick={() => selectRole(r.key)}
                  className={cn(
                    "flex items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-sm font-medium transition-colors",
                    role === r.key ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {r.label}
                </button>
              );
            })}
          </div>

          <p className="mt-3 text-sm text-muted-foreground">{active.blurb}</p>

          {/* credentials for police / government */}
          {role !== "citizen" && (
            <div className="mt-4 space-y-3">
              {role === "station" && stations.length > 0 && (
                <div className="space-y-1.5">
                  <Label>Your station</Label>
                  <Select onValueChange={pick}>
                    <SelectTrigger>
                      <SelectValue placeholder="Choose a police station…" />
                    </SelectTrigger>
                    <SelectContent>
                      {stations.slice(0, 60).map((s) => (
                        <SelectItem key={s.slug} value={s.slug}>
                          {s.station}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
              <div className="space-y-1.5">
                <Label htmlFor="u">Username</Label>
                <Input
                  id="u"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  placeholder={role === "govt" ? "govt" : "station ID"}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="p">Password</Label>
                <Input
                  id="p"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  placeholder="••••••"
                />
              </div>
            </div>
          )}

          {error && <p className="mt-3 text-sm font-medium text-destructive">{error}</p>}

          <Button type="submit" className="mt-5 w-full gap-2" disabled={busy}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            {role === "citizen" ? "Continue as citizen" : "Sign in"}
            {!busy && <ArrowRight className="h-4 w-4" />}
          </Button>

          {/* quick sign-in chips */}
          {role !== "citizen" && (
            <div className="mt-4 flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-muted-foreground">Quick sign-in:</span>
              {role === "govt" ? (
                <button type="button" onClick={() => pick("govt")} className={chipCls}>
                  govt
                </button>
              ) : (
                (stationChips.length ? stationChips : ["shivajinagar", "hal-old-airport", "whitefield"]).map((slug) => (
                  <button key={slug} type="button" onClick={() => pick(slug)} className={chipCls}>
                    {slug}
                  </button>
                ))
              )}
            </div>
          )}

          <p className="mt-8 text-xs leading-relaxed text-muted-foreground">
            Bias-corrected from parking-violation data — we never claim to measure congestion. We never rank individual
            officers.
          </p>
        </form>
      </div>
    </div>
  );
}

const chipCls =
  "rounded-full border bg-background px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:border-primary/40 hover:bg-accent hover:text-accent-foreground";
