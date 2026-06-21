import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, MapPin, Shield, Building2, ShieldCheck } from "lucide-react";
import { Brand } from "./Brand";
import { LoginDialog } from "./LoginDialog";
import { Card } from "@/components/ui/card";
import { enterCitizen } from "@/lib/auth";
import type { AuthSession } from "@/lib/types";
import { cn } from "@/lib/utils";

interface RoleCard {
  key: "citizen" | "station" | "govt";
  title: string;
  blurb: string;
  img: string;
  icon: typeof MapPin;
}

const ROLES: RoleCard[] = [
  {
    key: "citizen",
    title: "Citizen",
    blurb: "See parking-congestion hotspots near you and report illegal parking that blocks traffic.",
    img: "/illustrations/citizen.svg",
    icon: MapPin,
  },
  {
    key: "station",
    title: "Police Station",
    blurb: "Command map, next-day deployment zones, and a live ticket queue for your jurisdiction.",
    img: "/illustrations/police.svg",
    icon: Shield,
  },
  {
    key: "govt",
    title: "Government",
    blurb: "City-wide analytics, per-station performance, and the model evidence scorecard.",
    img: "/illustrations/govt.svg",
    icon: Building2,
  },
];

export function RoleLanding() {
  const navigate = useNavigate();
  const [loginRole, setLoginRole] = useState<"govt" | "station" | null>(null);

  function choose(key: RoleCard["key"]) {
    if (key === "citizen") {
      enterCitizen();
      navigate("/citizen");
    } else {
      setLoginRole(key);
    }
  }

  function onSuccess(a: AuthSession) {
    setLoginRole(null);
    navigate(a.role === "govt" ? "/govt" : "/police");
  }

  return (
    <div className="min-h-[100dvh] bg-background">
      {/* hero */}
      <div className="relative overflow-hidden border-b bg-[#FFF7ED]">
        <div className="mx-auto grid max-w-6xl items-center gap-6 px-5 py-10 md:grid-cols-2 md:py-14">
          <div>
            <Brand subtitle="Bengaluru Parking-Congestion Intelligence" />
            <h1 className="mt-6 text-3xl font-extrabold leading-tight tracking-tight sm:text-4xl">
              Bias-corrected parking enforcement,{" "}
              <span className="text-primary">honestly measured.</span>
            </h1>
            <p className="mt-3 max-w-xl text-muted-foreground">
              Five months of parking-violation tickets, corrected for where police already patrol — turned into a
              ranked, validated deployment plan. We never claim to measure congestion from tickets.
            </p>
            <div className="mt-5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1 rounded-full bg-background px-3 py-1 font-medium">
                <ShieldCheck className="h-3.5 w-3.5 text-[hsl(var(--success))]" /> Honesty contract
              </span>
              <span className="rounded-full bg-background px-3 py-1 font-medium">H3 cell-level</span>
              <span className="rounded-full bg-background px-3 py-1 font-medium">Works offline</span>
            </div>
          </div>
          <img src="/illustrations/hero.svg" alt="" className="w-full max-w-md justify-self-center md:justify-self-end" />
        </div>
      </div>

      {/* role chooser */}
      <div className="mx-auto max-w-6xl px-5 py-10">
        <h2 className="text-lg font-semibold">I am a…</h2>
        <p className="text-sm text-muted-foreground">Choose how you want to use ClearLane.</p>
        <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {ROLES.map((r) => {
            const Icon = r.icon;
            return (
              <Card
                key={r.key}
                onClick={() => choose(r.key)}
                className={cn(
                  "group cursor-pointer overflow-hidden transition-all hover:-translate-y-0.5 hover:shadow-md hover:ring-1 hover:ring-primary/30",
                )}
              >
                <div className="flex items-center gap-4 p-5">
                  <img src={r.img} alt="" className="h-20 w-20 shrink-0 rounded-xl" />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 font-semibold">
                      <Icon className="h-4 w-4 text-primary" />
                      {r.title}
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">{r.blurb}</p>
                    <span className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-primary">
                      Enter
                      <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                    </span>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>

        <p className="mt-8 max-w-3xl text-xs leading-relaxed text-muted-foreground">
          <b>Note on the data.</b> Every record is a parking-enforcement ticket, not a congestion measurement. Ticket
          times track officer shifts (enforcement peaks ~10am). The "evening blind spot" is an enforcement-coverage gap
          versus the city's <i>assumed</i> congestion peaks — not measured evening congestion. We never rank individual
          officers.
        </p>
      </div>

      <LoginDialog role={loginRole} open={Boolean(loginRole)} onClose={() => setLoginRole(null)} onSuccess={onSuccess} />
    </div>
  );
}
