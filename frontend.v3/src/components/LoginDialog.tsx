import { useEffect, useState } from "react";
import { Building2, Shield, Loader2 } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { login } from "@/lib/auth";
import { getStations } from "@/lib/api";
import type { AuthSession, Station } from "@/lib/types";

export function LoginDialog({
  role,
  open,
  onClose,
  onSuccess,
}: {
  role: "govt" | "station" | null;
  open: boolean;
  onClose: () => void;
  onSuccess: (a: AuthSession) => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [stations, setStations] = useState<Station[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open && role === "station") getStations().then(setStations).catch(() => {});
    if (open) {
      setError(null);
      if (role === "govt") {
        setUsername("govt");
        setPassword("govt");
      } else {
        setUsername("");
        setPassword("");
      }
    }
  }, [open, role]);

  if (!role) return null;
  const isGovt = role === "govt";

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const a = await login(role as "govt" | "station", username, password);
      onSuccess(a);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login failed.");
    } finally {
      setBusy(false);
    }
  }

  function pickStation(slug: string) {
    setUsername(slug);
    setPassword(slug); // demo credential convention: slug / slug
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <div className="mb-1 flex h-10 w-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
            {isGovt ? <Building2 className="h-5 w-5" /> : <Shield className="h-5 w-5" />}
          </div>
          <DialogTitle>{isGovt ? "Government Command" : "Police Station Login"}</DialogTitle>
          <DialogDescription>
            {isGovt
              ? "City-wide oversight across all stations. Demo credentials: govt / govt."
              : "Sign in to your station's command view. Demo: pick a station — credentials are slug / slug."}
          </DialogDescription>
        </DialogHeader>

        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          {!isGovt && stations.length > 0 && (
            <div className="space-y-1.5">
              <Label>Quick pick (demo)</Label>
              <Select onValueChange={pickStation}>
                <SelectTrigger>
                  <SelectValue placeholder="Choose a police station…" />
                </SelectTrigger>
                <SelectContent>
                  {stations.slice(0, 40).map((s) => (
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
            <Input id="u" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" placeholder={isGovt ? "govt" : "station-slug"} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="p">Password</Label>
            <Input id="p" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          </div>
          {error && <p className="text-sm font-medium text-destructive">{error}</p>}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            Sign in
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
