import { useEffect, useMemo, useState, type CSSProperties, type FormEvent } from "react";
import {
  ApiError,
  createMeeting,
  getMeetingRooms,
  type Employee,
  type Meeting,
  type MeetingRoom,
  type Office,
  type Priority,
} from "../api";
import { formatRange } from "../format";

const PRIORITIES: Priority[] = ["low", "medium", "high", "critical"];

export default function ScheduleMeetingForm({
  employees,
  offices,
  onCreated,
}: {
  employees: Employee[];
  offices: Office[];
  onCreated: () => void;
}) {
  const [title, setTitle] = useState("");
  const [organizerId, setOrganizerId] = useState<number | "">("");
  const [participantIds, setParticipantIds] = useState<Set<number>>(new Set());
  const [officeId, setOfficeId] = useState<number | "">("");
  const [rooms, setRooms] = useState<MeetingRoom[]>([]);
  const [roomId, setRoomId] = useState<number | "">("");
  const [priority, setPriority] = useState<Priority>("medium");
  const [localStart, setLocalStart] = useState("");
  const [localEnd, setLocalEnd] = useState("");
  const [timezone, setTimezone] = useState("");
  const [seriesKey, setSeriesKey] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Meeting | null>(null);

  // Default the organizer/office once the directory loads, and re-derive
  // the timezone field whenever the organizer changes -- a meeting is
  // scheduled *in* someone's local time, and the organizer's is the least
  // surprising default (still user-editable for e.g. "book this in the
  // Bangalore office's time").
  useEffect(() => {
    if (organizerId === "" && employees.length > 0) {
      setOrganizerId(employees[0].id);
      setTimezone(employees[0].timezone);
    }
  }, [employees, organizerId]);

  useEffect(() => {
    if (officeId === "" && offices.length > 0) {
      setOfficeId(offices[0].id);
    }
  }, [offices, officeId]);

  useEffect(() => {
    if (officeId === "") return;
    getMeetingRooms(officeId).then((fetched) => {
      setRooms(fetched);
      setRoomId("");
    });
  }, [officeId]);

  const timezoneOptions = useMemo(() => {
    const zones = new Set<string>();
    employees.forEach((e) => zones.add(e.timezone));
    offices.forEach((o) => zones.add(o.timezone));
    return Array.from(zones).sort();
  }, [employees, offices]);

  function toggleParticipant(id: number) {
    setParticipantIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setCreated(null);

    if (organizerId === "" || !title.trim() || !localStart || !localEnd || !timezone) {
      setError("Fill in a title, organizer, start, end, and timezone.");
      return;
    }
    if (localEnd <= localStart) {
      setError("End time must be after start time.");
      return;
    }

    setSubmitting(true);
    try {
      const meeting = await createMeeting({
        title: title.trim(),
        organizer_id: organizerId,
        participant_ids: Array.from(participantIds),
        optional_participant_ids: [],
        room_id: roomId === "" ? null : roomId,
        priority,
        local_start: localStart,
        local_end: localEnd,
        timezone,
        idempotency_key: crypto.randomUUID(),
        series_key: seriesKey.trim() || null,
      });
      setCreated(meeting);
      setTitle("");
      setParticipantIds(new Set());
      setLocalStart("");
      setLocalEnd("");
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to schedule the meeting.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section>
      <h2 style={{ marginTop: 0 }}>Schedule a meeting</h2>
      <form onSubmit={handleSubmit} style={{ display: "grid", gap: "0.9rem", maxWidth: 640 }}>
        <label style={fieldStyle}>
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} required />
        </label>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.9rem" }}>
          <label style={fieldStyle}>
            Organizer
            <select
              value={organizerId}
              onChange={(e) => {
                const id = Number(e.target.value);
                setOrganizerId(id);
                const employee = employees.find((emp) => emp.id === id);
                if (employee) setTimezone(employee.timezone);
              }}
            >
              {employees.map((employee) => (
                <option key={employee.id} value={employee.id}>
                  {employee.name}
                </option>
              ))}
            </select>
          </label>

          <label style={fieldStyle}>
            Priority
            <select value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
        </div>

        <fieldset style={{ border: "1px solid var(--border)", borderRadius: 6 }}>
          <legend style={{ padding: "0 0.4rem", color: "var(--muted)" }}>
            Participants (organizer is included automatically)
          </legend>
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: "0.6rem 1rem",
              maxHeight: 140,
              overflowY: "auto",
            }}
          >
            {employees
              .filter((employee) => employee.id !== organizerId)
              .map((employee) => (
                <label key={employee.id} style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={participantIds.has(employee.id)}
                    onChange={() => toggleParticipant(employee.id)}
                  />
                  {employee.name}
                </label>
              ))}
          </div>
        </fieldset>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.9rem" }}>
          <label style={fieldStyle}>
            Office (for room selection)
            <select value={officeId} onChange={(e) => setOfficeId(Number(e.target.value))}>
              {offices.map((office) => (
                <option key={office.id} value={office.id}>
                  {office.name}
                </option>
              ))}
            </select>
          </label>

          <label style={fieldStyle}>
            Room
            <select value={roomId} onChange={(e) => setRoomId(e.target.value ? Number(e.target.value) : "")}>
              <option value="">No room (virtual)</option>
              {rooms.map((room) => (
                <option key={room.id} value={room.id}>
                  {room.name} (cap {room.capacity})
                </option>
              ))}
            </select>
          </label>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "0.9rem" }}>
          <label style={fieldStyle}>
            Start (local)
            <input
              type="datetime-local"
              value={localStart}
              onChange={(e) => setLocalStart(e.target.value)}
              required
            />
          </label>
          <label style={fieldStyle}>
            End (local)
            <input
              type="datetime-local"
              value={localEnd}
              onChange={(e) => setLocalEnd(e.target.value)}
              required
            />
          </label>
          <label style={fieldStyle}>
            Timezone
            <select value={timezone} onChange={(e) => setTimezone(e.target.value)}>
              {timezoneOptions.map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label style={fieldStyle}>
          Recurring series (optional)
          <input
            value={seriesKey}
            onChange={(e) => setSeriesKey(e.target.value)}
            placeholder="e.g. weekly-status-review -- ties usefulness feedback to future scheduling"
          />
        </label>

        <div>
          <button type="submit" disabled={submitting}>
            {submitting ? "Scheduling…" : "Schedule meeting"}
          </button>
        </div>

        {error && <p style={{ color: "var(--danger)" }}>{error}</p>}
        {created && (
          <p style={{ color: "var(--success)" }}>
            Scheduled "{created.title}" for {formatRange(created.start_utc, created.end_utc)}.
          </p>
        )}
      </form>
    </section>
  );
}

const fieldStyle: CSSProperties = { display: "flex", flexDirection: "column", gap: "0.3rem" };
