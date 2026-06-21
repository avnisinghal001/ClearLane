import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { Toaster } from "@/components/toast";
import { RoleLanding } from "@/components/RoleLanding";
import { getAuth } from "@/lib/auth";
import type { Role } from "@/lib/types";

// Route-level code splitting: each role (and its heavy deps — leaflet, recharts)
// loads only when entered, keeping the initial bundle lean.
const CitizenApp = lazy(() => import("@/roles/citizen/CitizenApp").then((m) => ({ default: m.CitizenApp })));
const PoliceApp = lazy(() => import("@/roles/police/PoliceApp").then((m) => ({ default: m.PoliceApp })));
const GovtApp = lazy(() => import("@/roles/govt/GovtApp").then((m) => ({ default: m.GovtApp })));

function Splash() {
  return (
    <div className="flex h-[100dvh] items-center justify-center bg-background">
      <Loader2 className="h-7 w-7 animate-spin text-primary" />
    </div>
  );
}

function RequireRole({ role, children }: { role: Role; children: JSX.Element }) {
  const auth = getAuth();
  if (!auth || auth.role !== role) return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <Toaster />
      <Suspense fallback={<Splash />}>
        <Routes>
          <Route path="/" element={<RoleLanding />} />
          <Route path="/citizen" element={<CitizenApp />} />
          <Route
            path="/police"
            element={
              <RequireRole role="station">
                <PoliceApp />
              </RequireRole>
            }
          />
          <Route
            path="/govt"
            element={
              <RequireRole role="govt">
                <GovtApp />
              </RequireRole>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
