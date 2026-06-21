// Shared option lists for the citizen report + police ticket/resolution forms.
// These labelled fields are exactly what the police see when verifying a report.

export const COMPLAINT_CATEGORIES = [
  "Footpath / pavement parking",
  "No-parking zone",
  "Double parking",
  "Bus stop blocked",
  "Junction / corner blocked",
  "Wrong-side parking",
  "Driveway / gate blocked",
  "Main-road obstruction",
];

export const TICKET_CATEGORIES = [
  "No Parking",
  "Wrong Parking",
  "Parking In A Main Road",
  "Parking Near Road Crossing",
  "Footpath Parking",
  "Double Parking",
  "Obstructive Parking",
  "Bus Stop / Stand Parking",
];

export const VIOLATION_LABELS = [
  "Obstructs traffic flow",
  "Blocks footpath",
  "Near junction",
  "Repeat offender",
  "Heavy vehicle",
  "Peak-hour",
  "School / hospital zone",
];

export const VEHICLE_TYPES = ["Car", "Two-Wheeler", "Auto", "LCV / Goods", "Bus", "Truck", "Other"];

export const TICKET_KINDS: { value: "police_ticket" | "chalan"; label: string }[] = [
  { value: "police_ticket", label: "Field ticket" },
  { value: "chalan", label: "E-challan" },
];

export const RESOLUTION_REASONS = [
  { value: "verified_obstruction", label: "Verified obstruction — action taken" },
  { value: "towed", label: "Vehicle towed / removed" },
  { value: "warning_issued", label: "Warning issued / moved on" },
  { value: "challan_issued", label: "Challan issued" },
  { value: "false_alarm", label: "False alarm — no violation" },
  { value: "no_obstruction", label: "Parked but not obstructing" },
  { value: "structural_issue", label: "Structural issue (needs civic fix)" },
  { value: "other", label: "Other (specify)" },
];
