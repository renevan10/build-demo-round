-- Lightweight recurrence identity: an opaque, caller-supplied string
-- grouping "meetings like this one" (e.g. a recurring 1:1, a standing
-- team sync). Nothing enforces uniqueness or a fixed cadence -- it only
-- exists so the slot-suggester can look up "how did people rate meetings
-- in this series before" without any real recurrence-scheduling machinery.
ALTER TABLE meetings ADD COLUMN series_key TEXT;

CREATE INDEX IF NOT EXISTS idx_meetings_series_key
    ON meetings (series_key)
    WHERE series_key IS NOT NULL;
