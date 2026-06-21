// Shared roster hook: one source of truth for a station's officers across the
// Force Command screens. Live -> backend /api/v3/force/* (auth-scoped to govt or
// the owning station); offline -> deterministic seed (genRoster). Mutations are
// optimistic and persist to the backend when a live session is present.
//
// HONESTY: the roster is an operational record. Nothing here scores, ranks or
// profiles an individual officer; all hotspot/priority signals stay cell-level.
import { useCallback, useEffect, useState } from "react";
import { addOfficer as apiAdd, getRoster, patchOfficer as apiPatch, removeOfficer as apiRemove } from "@/lib/api";
import type { Officer, RosterPayload, RosterSummary } from "@/lib/types";

function recomputeSummary(officers: Officer[], shiftOrder: string[], ranks: string[]): RosterSummary {
  const by_shift: Record<string, number> = Object.fromEntries(shiftOrder.map((s) => [s, 0]));
  const by_rank: Record<string, number> = Object.fromEntries(ranks.map((r) => [r, 0]));
  for (const o of officers) {
    if (o.shift in by_shift) by_shift[o.shift] += 1;
    if (o.rank in by_rank) by_rank[o.rank] += 1;
  }
  return { total: officers.length, by_shift, by_rank };
}

function withOfficers(r: RosterPayload, officers: Officer[]): RosterPayload {
  return {
    ...r,
    officers,
    station: { ...r.station, officers: officers.length },
    summary: recomputeSummary(officers, r.shift_order, r.ranks),
  };
}

function offlineOfficer(r: RosterPayload, name: string, rank: string, shift: string): Officer {
  const prefix = (r.station.slug.replace(/[^a-z0-9]/g, "").toUpperCase().slice(0, 3) || "STN").padEnd(3, "X");
  const maxSeq = r.officers.reduce((m, o) => {
    const n = parseInt((o.badge || "").split("-").pop() || "", 10);
    return Number.isNaN(n) ? m : Math.max(m, n);
  }, 999);
  return {
    id: -(Date.now() % 1_000_000) - 1, // negative => local-only (no live PATCH/DELETE)
    station_slug: r.station.slug,
    name: name.trim(),
    badge: `${prefix}-${maxSeq + 1}`,
    rank,
    shift,
    status: "available",
  };
}

export interface UseRoster {
  roster: RosterPayload | null;
  loading: boolean;
  live: boolean;
  reload: () => void;
  addOfficer: (name: string, rank: string, shift: string) => Promise<void>;
  patchOfficer: (oid: number, patch: { rank?: string; shift?: string; status?: string }) => Promise<void>;
  removeOfficer: (oid: number) => Promise<void>;
}

export function useRoster(
  slug: string | null,
  meta: { name?: string; lat?: number | null; lon?: number | null; nZones?: number } = {},
): UseRoster {
  const { name, lat, lon, nZones } = meta;
  const [roster, setRoster] = useState<RosterPayload | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(() => {
    if (!slug) {
      setRoster(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    getRoster(slug, { name, lat, lon, nZones })
      .then(setRoster)
      .finally(() => setLoading(false));
  }, [slug, name, lat, lon, nZones]);

  useEffect(() => reload(), [reload]);

  const addOfficer = useCallback(
    async (name2: string, rank: string, shift: string) => {
      if (!name2.trim()) return;
      const created = slug ? await apiAdd(slug, name2.trim(), rank, shift) : null;
      setRoster((r) => (r ? withOfficers(r, [...r.officers, created ?? offlineOfficer(r, name2, rank, shift)]) : r));
    },
    [slug],
  );

  const patchOfficer = useCallback(async (oid: number, patch: { rank?: string; shift?: string; status?: string }) => {
    if (oid >= 0) await apiPatch(oid, patch); // positive ids are live-backed
    setRoster((r) => (r ? withOfficers(r, r.officers.map((o) => (o.id === oid ? ({ ...o, ...patch } as Officer) : o))) : r));
  }, []);

  const removeOfficer = useCallback(async (oid: number) => {
    if (oid >= 0) await apiRemove(oid);
    setRoster((r) => (r ? withOfficers(r, r.officers.filter((o) => o.id !== oid)) : r));
  }, []);

  return { roster, loading, live: roster?.live ?? false, reload, addOfficer, patchOfficer, removeOfficer };
}
