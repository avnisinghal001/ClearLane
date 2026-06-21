import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "@/components/toast";
import { RoleLanding } from "@/components/RoleLanding";
import { CitizenApp } from "@/roles/citizen/CitizenApp";
import { PoliceApp } from "@/roles/police/PoliceApp";
import { GovtApp } from "@/roles/govt/GovtApp";
import { getAuth } from "@/lib/auth";
import type { Role } from "@/lib/types";

function RequireRole({ role, children }: { role: Role; children: JSX.Element }) {
  const auth = getAuth();
  if (!auth || auth.role !== role) return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <Toaster />
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
    </BrowserRouter>
  );
}
