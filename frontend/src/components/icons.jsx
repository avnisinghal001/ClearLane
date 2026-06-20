// Icon set backed by lucide-react (tree-shaken; only these icons are bundled).
// Keeps a stable <Icon name=".." /> API so every call site upgrades at once.
import {
  ShieldCheck, Map, Siren, ListOrdered, Activity, Users, Car, Workflow,
  Clock, TrendingUp, LineChart, LayoutGrid, Building2, BadgeCheck,
  Menu, X, Search, RefreshCw, LogOut, Layers, SlidersHorizontal,
  ChevronRight, MapPin, Shield, Zap, Route, Navigation, Maximize2,
} from "lucide-react";

const MAP = {
  // nav / views
  force: ShieldCheck,
  command: Map,
  today: Siren,
  dispatch: Navigation,
  queue: ListOrdered,
  flow_impact: Activity,
  staffing: Users,
  offenders: Car,
  operations: Workflow,
  timing: Clock,
  coverage: TrendingUp,
  forecast: LineChart,
  typology: LayoutGrid,
  stations: Building2,
  validation: BadgeCheck,
  // ui
  menu: Menu,
  close: X,
  search: Search,
  sync: RefreshCw,
  logout: LogOut,
  layers: Layers,
  settings: SlidersHorizontal,
  chevron: ChevronRight,
  location: MapPin,
  shield: Shield,
  building: Building2,
  pulse: Zap,
  navigate: Navigation,
  expand: Maximize2,
  lane: Route,       // product mark
};

export function Icon({ name, size = 18, className = "", strokeWidth = 1.8 }) {
  const C = MAP[name] || Map;
  return <C size={size} strokeWidth={strokeWidth} className={className} aria-hidden="true" />;
}

export default Icon;
