import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./icons.jsx";

// Reusable "expand to full screen" card. Renders content in place with an expand
// button; clicking pops the SAME content into an animated full-screen modal
// (slides up on open, slides back down on close). Drop it around any table.
export default function Expandable({ title, subtitle, right, children,
                                    className = "", bodyClassName = "" }) {
  const [open, setOpen] = useState(false);
  const [closing, setClosing] = useState(false);

  const close = () => {
    setClosing(true);
    setTimeout(() => { setClosing(false); setOpen(false); }, 270);   // match expDown
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open]);

  const head = (inModal) => (
    <div className="exp-head">
      <div className="exp-title">
        <span className="exp-t">{title}</span>
        {subtitle && <span className="exp-sub">{subtitle}</span>}
      </div>
      <div className="exp-actions">
        {right}
        <button className="exp-btn"
          title={inModal ? "Close (Esc)" : "Expand to full screen"}
          onClick={inModal ? close : () => setOpen(true)}>
          <Icon name={inModal ? "close" : "expand"} size={inModal ? 17 : 15} />
        </button>
      </div>
    </div>
  );

  return (
    <section className={"exp " + className}>
      {head(false)}
      <div className={"exp-content " + bodyClassName}>{children}</div>

      {open && createPortal(
        <div className={"exp-backdrop" + (closing ? " closing" : "")} onMouseDown={close}>
          <div className={"exp-modal" + (closing ? " closing" : "")}
            onMouseDown={(e) => e.stopPropagation()}>
            {head(true)}
            <div className={"exp-content exp-modal-body " + bodyClassName}>{children}</div>
          </div>
        </div>, document.body)}
    </section>
  );
}
