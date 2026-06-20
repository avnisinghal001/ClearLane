import { useState } from "react";
import { login } from "../lib/auth.js";
import { Icon } from "./icons.jsx";

// RBAC login gate. govt/govt = Government (all areas). Each station logs in with
// its slug as BOTH username and password (e.g. HAL Old Airport -> hal-old-airport).
export default function Login({ onAuthed }) {
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e?.preventDefault();
    setBusy(true); setErr(null);
    try {
      const a = await login(u, p);
      onAuthed(a);
    } catch (e2) {
      setErr(e2.message || "Login failed.");
    } finally { setBusy(false); }
  }
  const quick = (user) => { setU(user); setP(user); };

  return (
    <div className="login-wrap">
      <div className="login-bg" />
      <form className="login-card" onSubmit={submit}>
        <div className="wordmark" style={{ fontSize: 24 }}>
          <span className="brand-mark hdr-mark"><Icon name="lane" size={17} strokeWidth={2} /></span>
          Clear<span className="lane">Lane</span>
          <span className="muted" style={{ fontSize: 13, fontWeight: 600 }}>Force Command</span>
        </div>
        <p className="muted" style={{ marginTop: 4, fontSize: 13 }}>
          Role-based access — Government command oversees every station; each station
          command sees and deploys only its own area.
        </p>

        <label className="login-lab">Username</label>
        <input className="searchbox" style={{ width: "100%" }} autoFocus
          placeholder="govt  or  station-slug (e.g. hal-old-airport)"
          value={u} onChange={(e) => setU(e.target.value)} />
        <label className="login-lab">Password</label>
        <input className="searchbox" style={{ width: "100%" }} type="password"
          placeholder="same as username for this demo"
          value={p} onChange={(e) => setP(e.target.value)} />

        {err && <div className="login-err">{err}</div>}

        <button className="btn accent" style={{ width: "100%", marginTop: 12, padding: 9 }}
          disabled={busy} type="submit">{busy ? "Signing in…" : "Sign in"}</button>

        <div className="login-quick">
          <span className="muted">Quick demo logins:</span>
          <button type="button" className="chip" onClick={() => quick("govt")}>govt</button>
          <button type="button" className="chip" onClick={() => quick("shivajinagar")}>shivajinagar</button>
          <button type="button" className="chip" onClick={() => quick("hal-old-airport")}>hal-old-airport</button>
          <button type="button" className="chip" onClick={() => quick("whitefield")}>whitefield</button>
        </div>
        <div className="muted" style={{ fontSize: 11, marginTop: 10 }}>
          Troop positions shown after login are a deployment <b>simulation</b> for
          planning — not real GPS or measured traffic.
        </div>

        <div className="login-citizen">
          <span className="muted">Not police?</span>
          <a className="btn" href="#/citizen" onClick={() => { window.location.hash = "#/citizen"; }}>
            Open the Citizen app →</a>
        </div>
      </form>
    </div>
  );
}
