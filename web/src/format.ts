// Every meeting time crossing this boundary is a UTC ISO string from the
// API. Formatting happens here, once, in the viewer's own browser timezone
// -- never assume which zone the person looking at the screen is in.

export function formatInstant(utcIso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(new Date(utcIso));
}

export function formatTimeOnly(utcIso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(utcIso));
}

export function formatRange(startUtc: string, endUtc: string): string {
  return `${formatInstant(startUtc)} – ${formatTimeOnly(endUtc)}`;
}

// Same as formatInstant, but in a specific person's timezone rather than
// the viewer's own -- used when showing "what time is this for them".
export function formatInstantInZone(utcIso: string, timeZone: string): string {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
    timeZone,
  }).format(new Date(utcIso));
}
