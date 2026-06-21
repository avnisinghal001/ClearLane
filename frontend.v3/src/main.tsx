import ReactDOM from "react-dom/client";
import "leaflet/dist/leaflet.css";
import "./index.css";
import App from "./App";

// NOTE: StrictMode's double-invoke of effects fights the imperative,
// single-instance map engines (Leaflet/Mappls bind to one container). Disabled so
// the map initialises cleanly; production never double-invokes anyway.
ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
