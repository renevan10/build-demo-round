import { useState, type CSSProperties } from "react";
import type { MeetingSummary } from "../api";
import { formatRange } from "../format";

const PRIORITY_COLORS: Record<string, string> = {
  low: "#6b7280",
  medium: "#2563eb",
  high: "#d97706",
  critical: "#dc2626",
};

const RATING_VALUES = [1, 2, 3, 4, 5];

const cellStyle: CSSProperties = { padding: "0.5rem 0.75rem", verticalAlign: "top" };
const headerStyle: CSSProperties = {
  ...cellStyle,
  textAlign: "left",
  borderBottom: "2px solid #e5e7eb",
};

export default function MeetingTable({
  meetings,
  viewerEmployeeId,
  onRate,
}: {
  meetings: MeetingSummary[];
  // Both optional together: "Your rating" only makes sense from a single
  // employee's own schedule view, not the all-meetings list which spans
  // everyone. Omit both there.
  viewerEmployeeId?: number;
  onRate?: (meetingId: number, score: number) => Promise<void>;
}) {
  if (meetings.length === 0) {
    return <p style={{ color: "#6b7280" }}>No meetings.</p>;
  }

  const showRating = viewerEmployeeId !== undefined && onRate !== undefined;

  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
      <thead>
        <tr>
          <th style={headerStyle}>Title</th>
          <th style={headerStyle}>When</th>
          <th style={headerStyle}>Organizer</th>
          <th style={headerStyle}>Participants</th>
          <th style={headerStyle}>Room</th>
          <th style={headerStyle}>Priority</th>
          <th style={headerStyle}>Status</th>
          {showRating && <th style={headerStyle}>Your rating</th>}
        </tr>
      </thead>
      <tbody>
        {meetings.map((meeting) => (
          <tr key={meeting.id} style={{ borderBottom: "1px solid #f0f0f0" }}>
            <td style={cellStyle}>{meeting.title}</td>
            <td style={cellStyle}>{formatRange(meeting.start_utc, meeting.end_utc)}</td>
            <td style={cellStyle}>{meeting.organizer_name}</td>
            <td style={cellStyle}>{meeting.participant_names.join(", ")}</td>
            <td style={cellStyle}>{meeting.room_name ?? "Virtual"}</td>
            <td style={cellStyle}>
              <span style={{ color: PRIORITY_COLORS[meeting.priority], fontWeight: 600 }}>
                {meeting.priority}
              </span>
            </td>
            <td style={cellStyle}>{meeting.status}</td>
            {showRating && (
              <td style={cellStyle}>
                <RatingCell meeting={meeting} onRate={(score) => onRate!(meeting.id, score)} />
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RatingCell({
  meeting,
  onRate,
}: {
  meeting: MeetingSummary;
  onRate: (score: number) => Promise<void>;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (meeting.status === "cancelled") {
    return <span style={{ color: "var(--muted)" }}>—</span>;
  }
  const hasHappened = new Date(meeting.end_utc).getTime() < Date.now();
  if (!hasHappened) {
    return <span style={{ color: "var(--muted)" }}>Not yet</span>;
  }

  async function handleClick(score: number) {
    setSubmitting(true);
    setError(null);
    try {
      await onRate(score);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit rating.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <div style={{ display: "flex", gap: "0.2rem" }}>
        {RATING_VALUES.map((value) => {
          const active = meeting.my_usefulness_score === value;
          return (
            <button
              key={value}
              type="button"
              disabled={submitting}
              onClick={() => handleClick(value)}
              title={`Rate this meeting's usefulness: ${value}`}
              style={{
                width: 22,
                height: 22,
                padding: 0,
                lineHeight: "20px",
                borderRadius: 4,
                border: "1px solid var(--border)",
                background: active ? "var(--accent)" : "white",
                color: active ? "white" : "inherit",
                fontSize: "0.75rem",
              }}
            >
              {value}
            </button>
          );
        })}
      </div>
      {error && <div style={{ color: "var(--danger)", fontSize: "0.75rem", marginTop: "0.15rem" }}>{error}</div>}
    </div>
  );
}
