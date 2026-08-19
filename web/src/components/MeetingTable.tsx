import type { CSSProperties } from "react";
import type { MeetingSummary } from "../api";
import { formatRange } from "../format";

const PRIORITY_COLORS: Record<string, string> = {
  low: "#6b7280",
  medium: "#2563eb",
  high: "#d97706",
  critical: "#dc2626",
};

const cellStyle: CSSProperties = { padding: "0.5rem 0.75rem", verticalAlign: "top" };
const headerStyle: CSSProperties = {
  ...cellStyle,
  textAlign: "left",
  borderBottom: "2px solid #e5e7eb",
};

export default function MeetingTable({ meetings }: { meetings: MeetingSummary[] }) {
  if (meetings.length === 0) {
    return <p style={{ color: "#6b7280" }}>No meetings.</p>;
  }

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
          </tr>
        ))}
      </tbody>
    </table>
  );
}
