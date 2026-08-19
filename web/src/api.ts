// Thin fetch wrapper around the FastAPI backend (proxied at /api and /health
// by vite.config.ts, so no base URL or CORS config needed).

export type HealthResponse = { status: string };

export type Office = { id: number; name: string; city: string; timezone: string };

export type Employee = {
  id: number;
  name: string;
  email: string;
  timezone: string;
  office_id: number;
};

export type MeetingRoom = { id: number; office_id: number; name: string; capacity: number };

export type Priority = "low" | "medium" | "high" | "critical";
export type MeetingStatus = "scheduled" | "cancelled" | "completed";

export type Meeting = {
  id: number;
  title: string;
  organizer_id: number;
  start_utc: string;
  end_utc: string;
  room_id: number | null;
  priority: Priority;
  status: MeetingStatus;
  idempotency_key: string;
  created_at_utc: string;
};

export type MeetingSummary = {
  id: number;
  title: string;
  organizer_id: number;
  organizer_name: string;
  start_utc: string;
  end_utc: string;
  room_id: number | null;
  room_name: string | null;
  priority: Priority;
  status: MeetingStatus;
  participant_names: string[];
};

export type CreateMeetingInput = {
  title: string;
  organizer_id: number;
  participant_ids: number[];
  optional_participant_ids: number[];
  room_id: number | null;
  priority: Priority;
  local_start: string; // "YYYY-MM-DDTHH:MM", wall-clock time in `timezone`
  local_end: string;
  timezone: string;
  idempotency_key: string;
  series_key: string | null;
};

export type SuggestSlotsInput = {
  required_ids: number[];
  optional_ids: number[];
  duration_minutes: number;
  search_start_local: string; // "YYYY-MM-DDTHH:MM", wall-clock time in `timezone`
  search_end_local: string;
  timezone: string;
  granularity_minutes: number;
  series_key: string | null;
  max_results: number;
};

export type SlotCost = { employee_id: number; employee_name: string; cost: number };

export type RankedSlot = {
  start_utc: string;
  end_utc: string;
  total_cost: number;
  max_cost: number;
  required_costs: SlotCost[];
  optional_costs: SlotCost[];
};

export type EmployeeMeetingTime = {
  employee_id: number;
  employee_name: string;
  meeting_count: number;
  total_hours: number;
  avg_hours_per_day: number;
  avg_hours_per_week: number;
  avg_hours_per_month: number;
};

export type BookSlotInput = {
  title: string;
  organizer_id: number;
  participant_ids: number[];
  optional_participant_ids: number[];
  room_id: number | null;
  priority: Priority;
  start_utc: string;
  end_utc: string;
  idempotency_key: string;
  series_key: string | null;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    detail: string,
  ) {
    super(detail);
  }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    throw new ApiError(res.status, await extractDetail(res));
  }
  return res.json();
}

async function extractDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // response body wasn't JSON -- fall through to the generic message
  }
  return `request failed with status ${res.status}`;
}

export function getHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>("/health");
}

export function getOffices(): Promise<Office[]> {
  return getJson<Office[]>("/api/offices");
}

export function getEmployees(): Promise<Employee[]> {
  return getJson<Employee[]>("/api/employees");
}

export function getMeetingRooms(officeId?: number): Promise<MeetingRoom[]> {
  const qs = officeId !== undefined ? `?office_id=${officeId}` : "";
  return getJson<MeetingRoom[]>(`/api/meeting-rooms${qs}`);
}

export function getMeetings(limit = 50, offset = 0): Promise<MeetingSummary[]> {
  return getJson<MeetingSummary[]>(`/api/meetings?limit=${limit}&offset=${offset}`);
}

export function getEmployeeSchedule(
  employeeId: number,
  limit = 50,
  offset = 0,
): Promise<MeetingSummary[]> {
  return getJson<MeetingSummary[]>(
    `/api/employees/${employeeId}/schedule?limit=${limit}&offset=${offset}`,
  );
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new ApiError(res.status, await extractDetail(res));
  }
  return res.json();
}

export function createMeeting(input: CreateMeetingInput): Promise<Meeting> {
  return postJson<Meeting>("/api/meetings", input);
}

export function getMeetingTimeDashboard(
  startDate: string,
  endDate: string,
): Promise<EmployeeMeetingTime[]> {
  return getJson<EmployeeMeetingTime[]>(
    `/api/dashboard/meeting-time?start_date=${startDate}&end_date=${endDate}`,
  );
}

export function suggestMeetingSlots(input: SuggestSlotsInput): Promise<RankedSlot[]> {
  return postJson<RankedSlot[]>("/api/meetings/suggest", input);
}

export function bookSlot(input: BookSlotInput): Promise<Meeting> {
  return postJson<Meeting>("/api/meetings/book-slot", input);
}
