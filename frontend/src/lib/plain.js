// Translation layer: technical fields -> plain English an untrained constable
// understands at a glance. Used by the officer view and the map's Simple popups.
// No raw scores / percentiles / Spearman / SHAP ever leave this module's callers.

export function tierLabel(tier) {
  return { P1: "Top priority", P2: "High priority", P3: "Watch", P4: "Low" }[tier] || tier;
}

// red = act now, amber = high, else slate
export function urgencyColor(zone, op) {
  const p = op ? op.operational_priority : zone.priority;
  if (zone.tier === "P1" || p >= 80) return "#E24B4A";
  if (zone.tier === "P2" || p >= 60) return "#EF9F27";
  return "#5b6472";
}

// the individual plain phrases that apply to a zone
export function plainPhrases(z) {
  const out = [];
  if (z.pressure >= 70) out.push("Vehicles block traffic here constantly");
  else if (z.pressure >= 40) out.push("Regular blocking through the day");
  else out.push("Occasional blocking");
  if (z.chronic) out.push("happens almost every day");
  if (z.responsiveness === "resistant")
    out.push("tickets aren't fixing it — needs a barrier or No-Parking board");
  else if (z.responsiveness === "responding") out.push("enforcement is working here");
  if (z.habitual) out.push("the same vehicles park here daily");
  if (z.evening_blind_spot) out.push("never checked in the evening rush (5–9pm), when it's worst");
  if (z.forecast_rising) out.push("and it's getting worse");
  if (z.under_recognized) out.push("patrols keep missing this, but it's serious");
  return out;
}

// one or two plain sentences for a card / popup
export function reasonSentence(z) {
  const p = plainPhrases(z);
  if (p.length === 0) return "";
  // sentence 1: blocking level (+ frequency), sentence 2: the key differentiator
  let s1 = p[0];
  if (p[1] && p[1].startsWith("happens")) s1 += ", " + p[1];
  const rest = p.filter((x) => x !== p[0] && !x.startsWith("happens"));
  const s2 = rest[0];
  let out = s1.charAt(0).toUpperCase() + s1.slice(1) + ".";
  if (s2) out += " " + s2.charAt(0).toUpperCase() + s2.slice(1) + ".";
  return out;
}

// the recommended action as a short plain chip (intervention is already plain)
export function actionChip(z) {
  const t = (z.intervention || "").toLowerCase();
  if (t.includes("tow")) return { icon: "🚛", text: "Tow blocking vehicles" };
  if (t.includes("no-parking") || t.includes("infrastructure") || t.includes("barrier"))
    return { icon: "🚧", text: "Needs a No-Parking board / barrier" };
  if (t.includes("evening sweep") || t.includes("evening")) return { icon: "🌆", text: "Add an evening sweep (5–9pm)" };
  if (t.includes("corridor") || t.includes("barricad")) return { icon: "🚓", text: "Patrol the whole stretch" };
  if (t.includes("board")) return { icon: "🪧", text: "Fix a No-Parking board" };
  return { icon: "📍", text: z.intervention || "Enforce here" };
}

// how long ago (for complaint cards)
export function ago(tsSeconds) {
  if (!tsSeconds) return "";
  const s = Math.max(0, Date.now() / 1000 - tsSeconds);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function km(metres) {
  if (metres == null) return null;
  return metres < 950 ? `${Math.round(metres)} m` : `${(metres / 1000).toFixed(1)} km`;
}

export function haversine(lat1, lon1, lat2, lon2) {
  const R = 6371000, r = Math.PI / 180;
  const dphi = (lat2 - lat1) * r, dl = (lon2 - lon1) * r;
  const a = Math.sin(dphi / 2) ** 2 +
    Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}
