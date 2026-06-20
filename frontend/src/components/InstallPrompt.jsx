import { useEffect, useState } from "react";
import { Icon } from "./icons.jsx";

const isStandalone = () =>
  window.matchMedia?.("(display-mode: standalone)").matches || window.navigator.standalone === true;
const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;

// Beautiful white/blue "Install app" prompt. Shows on every visit (until the app
// is actually installed) to drive accessibility for police + citizens in the field.
export default function InstallPrompt() {
  const [evt, setEvt] = useState(null);
  const [show, setShow] = useState(false);
  const [ios, setIos] = useState(false);

  useEffect(() => {
    if (isStandalone()) return; // already installed → never nag
    const onPrompt = (e) => { e.preventDefault(); setEvt(e); setShow(true); };
    const onInstalled = () => setShow(false);
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    // iOS Safari has no beforeinstallprompt — surface the manual hint instead
    if (isIOS()) { setIos(true); const t = setTimeout(() => setShow(true), 1200); return () => clearTimeout(t); }
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  if (!show) return null;

  const install = async () => {
    if (!evt) return;
    evt.prompt();
    try { await evt.userChoice; } catch { /* ignore */ }
    setEvt(null); setShow(false);
  };

  return (
    <div className="install-card" role="dialog" aria-label="Install ClearLane">
      <span className="install-ic"><Icon name="lane" size={22} strokeWidth={2} /></span>
      <div className="install-txt">
        <b>Install ClearLane</b>
        <span>{ios
          ? "Tap Share, then “Add to Home Screen” for instant offline access."
          : "Add the app to your device — instant, offline access in the field."}</span>
      </div>
      {!ios && <button className="install-btn" onClick={install}>
        <Icon name="navigate" size={15} /> Install</button>}
      <button className="install-x" onClick={() => setShow(false)} aria-label="Not now">
        <Icon name="close" size={16} />
      </button>
    </div>
  );
}
