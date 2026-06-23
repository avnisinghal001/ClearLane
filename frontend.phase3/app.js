/* TraFix Phase 3 dashboard — reads generated Phase 3 outputs (no build step).
   Place the latest outputs in ./data via scripts/build_phase3_dashboard.py, then
   serve this folder (python -m http.server) and open it. Falls back gracefully. */

const SEV_COLORS = { NORMAL: "#2ea043", MODERATE: "#d29922", HIGH: "#db6d28", SEVERE: "#f85149" };
const DATA = "./data";

const map = L.map("map", { zoomControl: true }).setView([12.985, 77.735], 13);
L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution: "&copy; OpenStreetMap &copy; CARTO",
  maxZoom: 19,
}).addTo(map);

function sevColor(label) { return SEV_COLORS[label] || "#6e7681"; }

async function loadJSON(path) {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

function renderLegend() {
  const el = document.getElementById("legend");
  el.innerHTML = "<b>Congestion severity</b>" +
    Object.entries(SEV_COLORS).map(([k, v]) =>
      `<div class="row"><span class="dot" style="background:${v}"></span>${k}</div>`).join("");
}

function kpi(v, l) { return `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`; }

async function main() {
  renderLegend();
  let pic, segments, meta = {}, finalReport = null;
  try {
    const picWrap = await loadJSON(`${DATA}/phase3_whitefield_live_pic.json`);
    meta = picWrap;
    pic = await loadJSON(`${DATA}/phase3_whitefield_live_pic.geojson`);
  } catch (e) {
    document.getElementById("footerMeta").textContent =
      "No Phase 3 PIC outputs found in ./data — run scripts/build_phase3_dashboard.py first. (" + e.message + ")";
    return;
  }
  try { finalReport = await loadJSON(`${DATA}/phase3_latest_final_report.json`); } catch (e) { finalReport = null; }
  try { segments = await loadJSON(`${DATA}/phase3_whitefield_segment_catalog.geojson`); } catch (e) { segments = null; }

  const dataMode = (finalReport?.data_mode || meta.data_mode || "?").toUpperCase();
  const liveCalls = finalReport?.mappls_request_summary?.live_mappls_api_calls_attempted ?? null;
  const modePill = document.getElementById("dataMode");
  modePill.textContent = "DATA MODE: " + dataMode;
  modePill.classList.toggle("is-replay", dataMode === "REPLAY");
  modePill.classList.toggle("is-live", dataMode === "LIVE");

  const banner = document.getElementById("runBanner");
  if (dataMode === "REPLAY") {
    banner.className = "run-banner replay";
    banner.textContent = "Replay fixture output. No live Mappls API calls were made for this displayed run.";
  } else if (liveCalls != null) {
    banner.className = "run-banner live";
    banner.textContent = `Live output. Mappls API calls attempted for this run: ${liveCalls}.`;
  } else {
    banner.className = "run-banner";
    banner.textContent = "Run mode unknown. Rebuild the dashboard after the latest Phase 3 run.";
  }

  // segment lines
  if (segments) {
    L.geoJSON(segments, {
      style: { color: "#58a6ff", weight: 3, opacity: 0.5 },
    }).addTo(map);
  }

  // PIC points
  const feats = (pic.features || []).filter(f => f.properties && f.properties.pic_status === "COMPUTED");
  const layer = L.layerGroup().addTo(map);
  const byH3 = {};
  feats.forEach(f => {
    const p = f.properties;
    const [lng, lat] = f.geometry.coordinates;
    const m = L.circleMarker([lat, lng], {
      radius: 8 + 22 * (p.pic_score || 0),
      color: "#0d1117", weight: 1,
      fillColor: sevColor(p.congestion_label), fillOpacity: 0.85,
    }).bindPopup(
      `<b>PIC #${p.pic_rank}</b> — ${p.h3_res10}<br>` +
      `PIC score: <b>${(p.pic_score ?? 0).toFixed(3)}</b><br>` +
      `Congestion: ${p.congestion_label} (severity ${(p.congestion_severity ?? 0).toFixed(3)})<br>` +
      `Historical propensity: ${(p.normalized_propensity ?? 0).toFixed(3)}<br>` +
      (p.localized_anomaly != null ? `Localized slowdown signal: ${Number(p.localized_anomaly).toFixed(3)}<br>` : "") +
      (p.overall_pic_confidence != null ? `Overall confidence: ${Number(p.overall_pic_confidence).toFixed(2)}` : "") +
      `<br><i>High inspection priority — not a confirmed parked-car detection.</i>`
    );
    m.addTo(layer);
    byH3[p.h3_res10] = m;
  });
  if (feats.length) {
    map.fitBounds(L.geoJSON({ type: "FeatureCollection", features: feats }).getBounds().pad(0.2));
  }

  // KPIs
  const sevs = feats.map(f => f.properties.congestion_severity).filter(v => v != null);
  const maxPic = Math.max(0, ...feats.map(f => f.properties.pic_score || 0));
  const meanSev = sevs.length ? (sevs.reduce((a, b) => a + b, 0) / sevs.length) : 0;
  document.getElementById("kpis").innerHTML =
    kpi(feats.length, "PIC-ranked cells") +
    kpi(maxPic.toFixed(3), "Max PIC") +
    kpi(meanSev.toFixed(2), "Mean severity");
  document.getElementById("cycleInfo").textContent =
    `Poll cycle ${meta.poll_cycle_id || "?"} · observed ${meta.observed_at_ist || "?"}` +
    (finalReport?.run_id ? ` · run ${finalReport.run_id}` : "");

  // table
  const tbody = document.querySelector("#picTable tbody");
  feats.sort((a, b) => a.properties.pic_rank - b.properties.pic_rank).forEach(f => {
    const p = f.properties;
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${p.pic_rank}</td>` +
      `<td>${p.h3_res10.slice(0, 10)}…</td>` +
      `<td>${(p.pic_score ?? 0).toFixed(3)}</td>` +
      `<td><span class="sev ${p.congestion_label}">${p.congestion_label}</span></td>` +
      `<td>${(p.normalized_propensity ?? 0).toFixed(3)}</td>`;
    tr.onclick = () => { const m = byH3[p.h3_res10]; if (m) { map.setView(m.getLatLng(), 15); m.openPopup(); } };
    tbody.appendChild(tr);
  });

  document.getElementById("footerMeta").textContent =
    `TraFix Phase 3 · ${feats.length} monitored Whitefield cells · ${meta.coverage || "LIVE TRAFFIC COVERAGE: WHITEFIELD DEMO REGION"} · PIC = historical propensity × live congestion severity`;
}

main();
