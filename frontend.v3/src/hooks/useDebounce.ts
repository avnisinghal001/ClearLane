import { useEffect, useState } from "react";

// Returns a debounced copy of `value` that only updates `delayMs` after the last
// change. Used to debounce the TimeControl hour scrubber so dragging it doesn't
// fire a /api/v3/map request on every intermediate value (the slider UI stays
// responsive; only the settled value triggers the fetch).
export function useDebounce<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);
  return debounced;
}
