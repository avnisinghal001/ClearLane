import { Icon } from "./icons.jsx";
import { istToday, istDatePlus, isActive, isRecorded, fmtDate } from "../lib/timeLens.js";

// Global date lens shown above every view. Pick a calendar date (or "All data"):
//  • a date inside the data window  → RECORDED activity that day
//  • a future date                  → PROJECTED expected demand (NOT congestion)
const pad = (n) => String(n).padStart(2, "0");

export default function TimeLensBar({ lens, setLens, daily }) {
  const set = (patch) => setLens({ ...lens, ...patch });
  const today = istToday(), tomorrow = istDatePlus(1);
  const isDate = lens.mode === "date";
  const isPick = isDate && lens.date !== today && lens.date !== tomorrow;

  const seg = (active, label, onClick) => (
    <button className={"seg" + (active ? " active" : "")} onClick={onClick}>{label}</button>
  );

  let status;
  if (lens.mode === "all") {
    status = "Showing all recorded data (Nov 2023 – Apr 2024)";
  } else {
    const when = fmtDate(lens.date) + (lens.hour == null ? "" : ` · ${pad(lens.hour)}:00`);
    status = isRecorded(lens, daily)
      ? `${when} — recorded that day`
      : `${when} — projected demand, not congestion`;
  }

  return (
    <div className="timelens">
      <div className="timelens-title"><Icon name="today" size={15} /> Date lens</div>

      <div className="seg-group">
        {seg(lens.mode === "all", "All data", () => set({ mode: "all", date: null, hour: null }))}
        {seg(isDate && lens.date === today, "Today",
          () => set({ mode: "date", date: today, hour: null }))}
        {seg(isDate && lens.date === tomorrow, "Tomorrow",
          () => set({ mode: "date", date: tomorrow, hour: null }))}
        {seg(isPick, "Pick a date",
          () => set({ mode: "date", date: isPick ? lens.date : today, hour: lens.hour ?? null }))}
      </div>

      {isDate && (
        <div className="timelens-ctrl">
          <input type="date" className="searchbox" style={{ width: "auto" }}
            value={lens.date || today} onChange={(e) => set({ date: e.target.value })} />
          <select className="searchbox" style={{ width: "auto" }}
            value={lens.hour == null ? "" : lens.hour}
            onChange={(e) => set({ hour: e.target.value === "" ? null : +e.target.value })}>
            <option value="">All day</option>
            {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{pad(h)}:00</option>)}
          </select>
          {lens.hour != null && (
            <button className="seg" onClick={() => set({ hour: null })}>clear hour</button>
          )}
        </div>
      )}

      <div className={"timelens-status" + (isActive(lens) ? " on" : "")}>{status}</div>
    </div>
  );
}
