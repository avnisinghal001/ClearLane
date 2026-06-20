import { useState } from "react";
import { Icon } from "./icons.jsx";

const SLIDES = [
  {
    img: "/img/onboard-1.png",
    title: "See the real hotspots",
    text: "Five months of parking tickets, turned into bias-corrected obstruction intelligence — not just a map of where police already patrol.",
  },
  {
    img: "/img/onboard-2.png",
    title: "Command your force",
    text: "Government oversees every station; each station deploys patrols with shift-aware, auto-allocated coverage across its area.",
  },
  {
    img: "/img/onboard-3.png",
    title: "Close the loop with citizens",
    text: "Anyone can report an obstruction, check today's predicted risk, and plan a cleaner route — live, even offline.",
  },
];

export default function Onboarding({ onDone }) {
  const [i, setI] = useState(0);
  const [touch, setTouch] = useState(null);
  const last = i === SLIDES.length - 1;
  const finish = () => { try { localStorage.setItem("cl_onboarded", "1"); } catch { /* ignore */ } onDone(); };
  const next = () => (last ? finish() : setI((x) => x + 1));

  const onTouchStart = (e) => setTouch(e.touches[0].clientX);
  const onTouchEnd = (e) => {
    if (touch == null) return;
    const dx = e.changedTouches[0].clientX - touch;
    if (dx < -45 && !last) setI((x) => x + 1);
    else if (dx > 45 && i > 0) setI((x) => x - 1);
    setTouch(null);
  };

  const s = SLIDES[i];
  return (
    <div className="onboard" onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
      <button className="onboard-skip" onClick={finish}>Skip</button>

      <div className="onboard-media">
        {SLIDES.map((sl, idx) => (
          <img key={idx} src={sl.img} alt="" loading={idx === 0 ? "eager" : "lazy"}
            className={"onboard-img" + (idx === i ? " on" : "")} />
        ))}
        <div className="onboard-fade" />
        <div className="onboard-brand">
          <span className="brand-mark hdr-mark"><Icon name="lane" size={28} strokeWidth={2} /></span>
          Clear<span className="lane">Lane</span>
        </div>
      </div>

      <div className="onboard-body">
        <div className="onboard-dots">
          {SLIDES.map((_, idx) => (
            <span key={idx} className={"onboard-dot" + (idx === i ? " on" : "")}
              onClick={() => setI(idx)} />
          ))}
        </div>
        <h1 className="onboard-title">{s.title}</h1>
        <p className="onboard-text">{s.text}</p>
        <button className="btn accent big block onboard-next" onClick={next}>
          {last ? "Get started" : "Next"} <Icon name="chevron" size={16} />
        </button>
        <div className="onboard-note">Bias-corrected from parking-violation data — never measured congestion.</div>
      </div>
    </div>
  );
}
