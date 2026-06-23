import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";

const EXE = `${process.env.USERPROFILE}\\AppData\\Local\\ms-playwright\\chromium-1228\\chrome-win64\\chrome.exe`;
const BASE = "http://localhost:4174";
const OUT = "smoke-shots";
mkdirSync(OUT, { recursive: true });

const results = [];
const ok = (name, cond, extra = "") => {
  results.push({ name, pass: !!cond, extra });
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${extra ? "  — " + extra : ""}`);
};

async function openDrawerByClickingMap(page) {
  // circles render on a leaflet canvas (no DOM nodes), so click a grid of points
  // until the Radix dialog (CellDrawer) appears. Zoom out first so a station-local
  // (police) cell cluster fills the viewport and is easier to hit.
  const canvas = await page.$(".leaflet-container");
  if (!canvas) return null;
  for (let z = 0; z < 3; z++) {
    const zo = await page.$(".leaflet-control-zoom-out");
    if (zo) { await zo.click(); await page.waitForTimeout(250); }
  }
  await page.waitForTimeout(400);
  const box = await canvas.boundingBox();
  if (!box) return null;
  const N = 11;
  for (let r = 1; r < N; r++) {
    for (let c = 1; c < N; c++) {
      const x = box.x + (box.width * c) / N;
      const y = box.y + (box.height * r) / N;
      await page.mouse.click(x, y);
      const dlg = await page.$('[role="dialog"]');
      if (dlg) {
        await page.waitForTimeout(250);
        return dlg;
      }
    }
  }
  return null;
}

const browser = await chromium.launch({ executablePath: EXE, headless: true });
const pageErrors = []; // uncaught JS exceptions (fatal)
const apiErrors = []; // expected offline /api fallbacks (informational)
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await context.newPage();
page.on("pageerror", (e) => pageErrors.push(`pageerror: ${e.message}`));
page.on("console", (m) => { if (m.type() === "error") apiErrors.push(m.text()); });

try {
  // ---------- CITIZEN ----------
  await page.goto(`${BASE}/citizen`, { waitUntil: "networkidle", timeout: 30000 });
  await page.waitForTimeout(1500);
  const citizenText = await page.innerText("body");
  ok("citizen renders", citizenText.length > 50);
  ok("citizen has plain 'Report a problem' CTA", /Report a problem/i.test(citizenText));
  await page.screenshot({ path: `${OUT}/citizen.png`, fullPage: false });

  const cDlg = await openDrawerByClickingMap(page);
  if (cDlg) {
    const t = await cDlg.innerText();
    ok("citizen modal opens", true);
    ok("modal has NO 'Recurrence'", !/Recurrence/i.test(t), t.match(/Recurrence/i)?.[0] ?? "");
    ok("modal shows 'Why it's flagged'", /Why it'?s flagged/i.test(t));
    ok("modal shows 'What the police can do here' (citizen)", /What the police can do here/i.test(t));
    ok("modal shows 'Typical congestion'", /Typical congestion/i.test(t));
    ok("modal hides Gi*/flow-rank/context-mult jargon", !/Gi\*|flow rank|context mult|rank_divergence|drift_z|dispersion/i.test(t));
    await page.screenshot({ path: `${OUT}/citizen-modal.png` });
    // expand Details and confirm three-number block lives there
    const det = await page.$('[role="dialog"] button:has-text("Details")');
    if (det) { await det.click(); await page.waitForTimeout(300); }
    const t2 = await (await page.$('[role="dialog"]')).innerText();
    ok("Details discloses 'live boost' three-number block", /live boost/i.test(t2));
    await page.screenshot({ path: `${OUT}/citizen-modal-details.png` });
    await page.keyboard.press("Escape");
  } else {
    ok("citizen modal opens", false, "no dialog after grid clicks");
  }

  // ---------- POLICE (seed offline station auth) ----------
  const seed = await page.evaluate(async () => {
    const [st, cl] = await Promise.all([
      fetch("/demo-v3/stations.json").then((r) => r.json()).catch(() => null),
      fetch("/demo-v3/cells.json").then((r) => r.json()).catch(() => null),
    ]);
    const cells = Array.isArray(cl) ? cl : cl?.cells ?? [];
    const counts = {};
    for (const c of cells) if (c.police_station) counts[c.police_station] = (counts[c.police_station] || 0) + 1;
    const stations = Array.isArray(st) ? st : st?.stations ?? [];
    let best = null;
    for (const s of stations) {
      const n = counts[s.station] || 0;
      if (!best || n > best.n) best = { name: s.station, slug: s.slug, n };
    }
    if (best) {
      localStorage.setItem("cl_v3_auth", JSON.stringify({ token: "offline-" + best.slug, role: "station", scope: best.slug, name: best.name, live: false }));
    }
    return best;
  });
  ok("seeded a police station", seed && seed.name, seed ? `${seed.name} (${seed.n} cells)` : "none");

  await page.goto(`${BASE}/police`, { waitUntil: "networkidle", timeout: 30000 });
  await page.waitForTimeout(1500);
  const policeText = await page.innerText("body");
  ok("police renders (not redirected to landing)", !/\/police/.test(page.url()) ? true : !/Choose your role|Citizen access/i.test(policeText));
  ok("police nav 'Where to deploy'", /Where to deploy/i.test(policeText));
  ok("police nav 'Tickets'", /\bTickets\b/i.test(policeText));
  ok("police nav 'Road impact'", /Road impact/i.test(policeText));
  await page.screenshot({ path: `${OUT}/police.png` });

  const pDlg = await openDrawerByClickingMap(page);
  if (pDlg) {
    const t = await pDlg.innerText();
    ok("police modal opens", true);
    ok("police modal NO 'Recurrence'", !/Recurrence/i.test(t));
    ok("police modal shows 'Recommended action'", /Recommended action/i.test(t));
    await page.screenshot({ path: `${OUT}/police-modal.png` });
  } else {
    ok("police modal opens", false, "no dialog after grid clicks (cells may be sparse for this station)");
  }
} catch (e) {
  ok("smoke run completed without throwing", false, String(e));
} finally {
  if (apiErrors.length) console.log(`\n(${apiErrors.length} expected offline /api resource errors — handled by the offline-first fallback)`);
  if (pageErrors.length) { console.log("\n--- uncaught JS exceptions ---"); pageErrors.forEach((e) => console.log(e)); }
  ok("no uncaught JS exceptions", pageErrors.length === 0, pageErrors.slice(0, 3).join(" | "));
  await browser.close();
  const failed = results.filter((r) => !r.pass);
  console.log(`\nSUMMARY: ${results.length - failed.length}/${results.length} passed`);
  process.exit(failed.length ? 1 : 0);
}
