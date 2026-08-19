import { useState } from "react";
import MeetingTimeSection from "./MeetingTimeSection";
import UsefulnessSection from "./UsefulnessSection";

// Wide enough to cover the seeded adversarial dataset (Jan-Aug 2026) out
// of the box; the range is a plain filter, not tied to "today" in any
// particular timezone -- there's no single "today" that's correct for
// every employee at once.
const DEFAULT_START = "2026-01-01";
const DEFAULT_END = "2026-12-31";

export default function DashboardPage({ refreshSignal }: { refreshSignal: number }) {
  const [startDate, setStartDate] = useState(DEFAULT_START);
  const [endDate, setEndDate] = useState(DEFAULT_END);

  // A user filling in "From" and "To" one field at a time can pass through
  // an invalid range for a moment (native date inputs can fire onChange per
  // field). Both sections skip fetching rather than flash an error for a
  // transient state -- they hold their last valid render until both fields
  // agree again, per "refetch keeps the frame."
  const rangeIsValid = startDate !== "" && endDate !== "" && endDate >= startDate;

  return (
    <div>
      {/* One filter row, above everything it scopes -- both sections below
          re-render against the same date range, so the numbers always agree. */}
      <div style={{ display: "flex", gap: "1rem", alignItems: "flex-end", marginBottom: "1.75rem" }}>
        <label style={fieldStyle}>
          From
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </label>
        <label style={fieldStyle}>
          To
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </label>
      </div>

      <MeetingTimeSection
        startDate={startDate}
        endDate={endDate}
        rangeIsValid={rangeIsValid}
        refreshSignal={refreshSignal}
      />

      <hr style={{ border: "none", borderTop: "1px solid var(--border)", margin: "0 0 2rem" }} />

      <UsefulnessSection
        startDate={startDate}
        endDate={endDate}
        rangeIsValid={rangeIsValid}
        refreshSignal={refreshSignal}
      />
    </div>
  );
}

const fieldStyle = { display: "flex", flexDirection: "column" as const, gap: "0.3rem" };
