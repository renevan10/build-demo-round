import { useEffect, useMemo, useState, type CSSProperties, type FormEvent } from "react";
import {
  ApiError,
  bookSlot,
  getMeetingRooms,
  suggestMeetingSlots,
  type Employee,
  type Meeting,
  type MeetingRoom,
  type Office,
  type Priority,
  type RankedSlot,
} from "../api";
import { formatInstantInZone, formatRange } from "../format";

const PRIORITIES: Priority[] = ["low", "medium", "high", "critical"];
const DURATIONS = [15, 30, 45, 60, 90, 120];
const GRANULARITIES = [15, 30, 60];

export default function FindTimePage({
  employees,
  offices,
  onBooked,
}: {
  employees: Employee[];
  offices: Office[];
  onBooked: () => void;
}) {
  const [title, setTitle] = useState("");
  const [organizerId, setOrganizerId] = useState<number | "">("");
  const [requiredIds, setRequiredIds] = useState<Set<number>>(new Set());
  const [optionalIds, setOptionalIds] = useState<Set<number>>(new Set());
  const [durationMinutes, setDurationMinutes] = useState(30);
  const [granularityMinutes, setGranularityMinutes] = useState(30);
  const [searchStart, setSearchStart] = useState("");
  const [searchEnd, setSearchEnd] = useState("");
  const [timezone, setTimezone] = useState("");
  const [seriesKey, setSeriesKey] = useState("");
  const [priority, setPriority] = useState<Priority>("medium");
  const [officeId, setOfficeId] = useState<number | "">("");
  const [rooms, setRooms] = useState<MeetingRoom[]>([]);
  const [roomId, setRoomId] = useState<number | "">("");

  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [results, setResults] = useState<RankedSlot[] | null>(null);

  const [bookingKey, setBookingKey] = useState<string | null>(null);
  const [bookError, setBookError] = useState<string | null>(null);
  const [booked, setBooked] = useState<Meeting | null>(null);

  useEffect(() => {
    if (organizerId === "" && employees.length > 0) {
      setOrganizerId(employees[0].id);
      setTimezone(employees[0].timezone);
      setRequiredIds(new Set([employees[0].id]));
    }
  }, [employees, organizerId]);

  useEffect(() => {
    if (officeId === "" && offices.length > 0) setOfficeId(offices[0].id);
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

  const timezoneByEmployeeId = useMemo(
    () => Object.fromEntries(employees.map((e) => [e.id, e.timezone])),
    [employees],
  );

  function toggleRequired(id: number) {
    setRequiredIds((prev) => toggleSet(prev, id));
    setOptionalIds((prev) => removeFromSet(prev, id));
  }

  function toggleOptional(id: number) {
    setOptionalIds((prev) => toggleSet(prev, id));
    setRequiredIds((prev) => removeFromSet(prev, id));
  }

  async function handleSearch(e: FormEvent) {
    e.preventDefault();
    setSearchError(null);
    setResults(null);
    setBooked(null);

    if (requiredIds.size === 0) {
      setSearchError("Pick at least one required attendee.");
      return;
    }
    if (!searchStart || !searchEnd || !timezone) {
      setSearchError("Fill in the search window and timezone.");
      return;
    }
    if (searchEnd <= searchStart) {
      setSearchError("Search end must be after search start.");
      return;
    }

    setSearching(true);
    try {
      const ranked = await suggestMeetingSlots({
        required_ids: Array.from(requiredIds),
        optional_ids: Array.from(optionalIds),
        duration_minutes: durationMinutes,
        search_start_local: searchStart,
        search_end_local: searchEnd,
        timezone,
        granularity_minutes: granularityMinutes,
        series_key: seriesKey.trim() || null,
        max_results: 8,
      });
      setResults(ranked);
    } catch (err) {
      setSearchError(err instanceof ApiError ? err.message : "Failed to find times.");
    } finally {
      setSearching(false);
    }
  }

  async function handleBook(slot: RankedSlot) {
    setBookError(null);
    setBooked(null);
    if (organizerId === "" || !title.trim()) {
      setBookError("Add a title (and make sure an organizer is selected) before booking.");
      return;
    }
    const key = slot.start_utc;
    setBookingKey(key);
    try {
      const meeting = await bookSlot({
        title: title.trim(),
        organizer_id: organizerId,
        // Required vs. optional must stay distinct through booking, not
        // just search: the DB layer only hard-blocks on a required
        // attendee's conflict, matching the suggester's own rule that an
        // optional attendee never blocks a slot.
        participant_ids: Array.from(requiredIds),
        optional_participant_ids: Array.from(optionalIds),
        room_id: roomId === "" ? null : roomId,
        priority,
        start_utc: slot.start_utc,
        end_utc: slot.end_utc,
        idempotency_key: crypto.randomUUID(),
        series_key: seriesKey.trim() || null,
      });
      setBooked(meeting);
      setResults(null);
      onBooked();
    } catch (err) {
      setBookError(err instanceof ApiError ? err.message : "Failed to book that slot.");
    } finally {
      setBookingKey(null);
    }
  }

  return (
    <section>
      <h2 style={{ marginTop: 0 }}>Find a time</h2>
      <p style={{ color: "var(--muted)", marginTop: "-0.5rem" }}>
        Ranks candidate times by inconvenience cost across everyone required, instead of you
        checking each calendar by hand. Equal-cost options are broken by who'd otherwise bear the
        most pain, not just the lowest total.
      </p>

      <form onSubmit={handleSearch} style={{ display: "grid", gap: "0.9rem", maxWidth: 720 }}>
        <label style={fieldStyle}>
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Sprint planning" />
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

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.9rem" }}>
          <fieldset style={{ border: "1px solid var(--border)", borderRadius: 6 }}>
            <legend style={{ padding: "0 0.4rem", color: "var(--muted)" }}>
              Required (must find a slot free for all of these)
            </legend>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem", maxHeight: 140, overflowY: "auto" }}>
              {employees.map((employee) => (
                <label key={employee.id} style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
                  <input type="checkbox" checked={requiredIds.has(employee.id)} onChange={() => toggleRequired(employee.id)} />
                  {employee.name}
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset style={{ border: "1px solid var(--border)", borderRadius: 6 }}>
            <legend style={{ padding: "0 0.4rem", color: "var(--muted)" }}>
              Optional (never blocks a slot, only adds cost if busy)
            </legend>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem", maxHeight: 140, overflowY: "auto" }}>
              {employees.map((employee) => (
                <label key={employee.id} style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
                  <input type="checkbox" checked={optionalIds.has(employee.id)} onChange={() => toggleOptional(employee.id)} />
                  {employee.name}
                </label>
              ))}
            </div>
          </fieldset>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: "0.9rem" }}>
          <label style={fieldStyle}>
            Search from (local)
            <input type="datetime-local" value={searchStart} onChange={(e) => setSearchStart(e.target.value)} required />
          </label>
          <label style={fieldStyle}>
            Search until (local)
            <input type="datetime-local" value={searchEnd} onChange={(e) => setSearchEnd(e.target.value)} required />
          </label>
          <label style={fieldStyle}>
            In timezone
            <select value={timezone} onChange={(e) => setTimezone(e.target.value)}>
              {timezoneOptions.map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
          </label>
          <label style={fieldStyle}>
            Duration
            <select value={durationMinutes} onChange={(e) => setDurationMinutes(Number(e.target.value))}>
              {DURATIONS.map((d) => (
                <option key={d} value={d}>
                  {d} min
                </option>
              ))}
            </select>
          </label>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: "0.9rem" }}>
          <label style={fieldStyle}>
            Search granularity
            <select value={granularityMinutes} onChange={(e) => setGranularityMinutes(Number(e.target.value))}>
              {GRANULARITIES.map((g) => (
                <option key={g} value={g}>
                  every {g} min
                </option>
              ))}
            </select>
          </label>
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
          <label style={fieldStyle}>
            Recurring series (optional)
            <input
              value={seriesKey}
              onChange={(e) => setSeriesKey(e.target.value)}
              placeholder="e.g. weekly-status-review"
            />
          </label>
        </div>

        <div>
          <button type="submit" disabled={searching}>
            {searching ? "Searching…" : "Find times"}
          </button>
        </div>

        {searchError && <p style={{ color: "var(--danger)" }}>{searchError}</p>}
      </form>

      {results && (
        <div style={{ marginTop: "1.5rem" }}>
          <h3>Candidate times, ranked</h3>
          {results.length === 0 && <p style={{ color: "var(--muted)" }}>No feasible slot in that window for everyone required.</p>}
          <div style={{ display: "grid", gap: "0.75rem" }}>
            {results.map((slot) => (
              <div
                key={slot.start_utc}
                style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0.9rem 1.1rem" }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: "0.5rem" }}>
                  <strong>{formatRange(slot.start_utc, slot.end_utc)}</strong>
                  <span style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
                    total cost {slot.total_cost} · worst-case {slot.max_cost}
                  </span>
                  <button type="button" onClick={() => handleBook(slot)} disabled={bookingKey === slot.start_utc}>
                    {bookingKey === slot.start_utc ? "Booking…" : "Book this slot"}
                  </button>
                </div>
                <PersonCostList label="Required" costs={slot.required_costs} slot={slot} tzById={timezoneByEmployeeId} />
                {slot.optional_costs.length > 0 && (
                  <PersonCostList label="Optional (attending)" costs={slot.optional_costs} slot={slot} tzById={timezoneByEmployeeId} />
                )}
              </div>
            ))}
          </div>
          {bookError && <p style={{ color: "var(--danger)" }}>{bookError}</p>}
        </div>
      )}

      {booked && (
        <p style={{ color: "var(--success)", marginTop: "1rem" }}>
          Booked "{booked.title}" for {formatRange(booked.start_utc, booked.end_utc)}.
        </p>
      )}
    </section>
  );
}

function PersonCostList({
  label,
  costs,
  slot,
  tzById,
}: {
  label: string;
  costs: { employee_id: number; employee_name: string; cost: number }[];
  slot: RankedSlot;
  tzById: Record<number, string>;
}) {
  return (
    <div style={{ marginTop: "0.5rem", fontSize: "0.85rem" }}>
      <span style={{ color: "var(--muted)" }}>{label}:</span>{" "}
      {costs
        .map((c) => {
          const tz = tzById[c.employee_id];
          const local = tz ? formatInstantInZone(slot.start_utc, tz) : "";
          return `${c.employee_name} (${local}, cost ${c.cost})`;
        })
        .join("  ·  ")}
    </div>
  );
}

function toggleSet(set: Set<number>, id: number): Set<number> {
  const next = new Set(set);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

function removeFromSet(set: Set<number>, id: number): Set<number> {
  if (!set.has(id)) return set;
  const next = new Set(set);
  next.delete(id);
  return next;
}

const fieldStyle: CSSProperties = { display: "flex", flexDirection: "column", gap: "0.3rem" };
