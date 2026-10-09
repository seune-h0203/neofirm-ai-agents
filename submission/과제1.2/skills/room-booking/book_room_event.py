#!/usr/bin/env python3
"""
book_room_event.py — Codex Custom Skill entry point

Workflow:
  1. GCS-PULSE: check availability → pick room (with fallback) → book
  2. GWS Calendar: create event with room resource → invite attendees
  3. Rollback: cancel GCS-PULSE booking if Calendar creation fails

Usage (CLI):
  python book_room_event.py \
    --title "Q4 Planning" \
    --start "2026-10-15T10:00:00+09:00" \
    --end   "2026-10-15T12:00:00+09:00" \
    --attendees alice@example.com bob@example.com \
    --room-preference "large" \
    --location "Seoul HQ"

Usage (Python API):
  from book_room_event import run
  result = run(title=..., start=..., end=..., attendees=[...])
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Optional

from gcs_pulse import GCSPulseClient, Booking, Room
from gws import GWSCalendarClient, CalendarEvent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("book_room_event")

MAX_FALLBACK_ATTEMPTS = 3


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------
@dataclass
class SkillResult:
    status: str = "failed"          # success | dry_run_ok | partial_failure | failed
    booking_id: str = ""
    event_id: str = ""
    room_id: str = ""
    calendar_link: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status":        self.status,
            "booking_id":    self.booking_id,
            "event_id":      self.event_id,
            "room_id":       self.room_id,
            "calendar_link": self.calendar_link,
            "errors":        self.errors,
        }


# ---------------------------------------------------------------------------
# Core orchestrator
# ---------------------------------------------------------------------------
def run(
    title: str,
    start: str,
    end: str,
    attendees: list[str],
    room_preference: str = "",
    location: str = "Seoul HQ",
    capacity: int = 0,
    dry_run: bool = False,
) -> SkillResult:
    result   = SkillResult()
    gcs      = GCSPulseClient()
    calendar = GWSCalendarClient()

    organizer = attendees[0] if attendees else "unknown@example.com"
    min_cap   = capacity if capacity > 0 else max(1, len(attendees))

    # ------------------------------------------------------------------
    # Step 1: Room availability + booking (with fallback)
    # ------------------------------------------------------------------
    booking: Optional[Booking] = None

    log.info("Step 1 — GCS-PULSE: searching rooms (cap≥%d, location=%r, pref=%r)",
             min_cap, location, room_preference)

    try:
        available = gcs.list_available_rooms(
            check_in=start, check_out=end,
            capacity=min_cap, location=location,
            preference=room_preference,
        )
    except Exception as exc:
        result.errors.append(f"GCS-PULSE list_rooms failed: {exc}")
        log.error("GCS-PULSE list_rooms error: %s", exc)
        return result

    if not available:
        # Fallback: relax preference, keep capacity
        log.warning("No rooms match preference %r — relaxing to any available room", room_preference)
        try:
            available = gcs.list_available_rooms(
                check_in=start, check_out=end,
                capacity=min_cap, location=location,
                preference="",
            )
        except Exception as exc:
            result.errors.append(f"GCS-PULSE fallback list failed: {exc}")
            return result

    if not available:
        result.errors.append(
            f"No rooms available in {location!r} for capacity ≥ {min_cap} "
            f"({start} → {end})"
        )
        log.error("No rooms available — aborting")
        return result

    # Sort: prefer preference match first, then smallest sufficient room
    preferred  = [r for r in available if r.matches_preference(room_preference)]
    candidates = (preferred + [r for r in available if r not in preferred])[:MAX_FALLBACK_ATTEMPTS]

    for attempt, room in enumerate(candidates, 1):
        log.info("  Attempt %d/%d: booking room %s (%s)", attempt, len(candidates), room.id, room.name)
        try:
            booking = gcs.book_room(room.id, start, end, organizer, dry_run=dry_run, room_name=room.name)
            log.info("  Room booked: %s → booking %s", room.id, booking.booking_id)
            result.booking_id = booking.booking_id
            result.room_id    = room.id
            if attempt > 1:
                log.info("  (Used fallback room — primary preference was unavailable)")
            break
        except Exception as exc:
            log.warning("  booking %s failed: %s", room.id, exc)
            result.errors.append(f"Room {room.id} booking failed: {exc}")
            if attempt == len(candidates):
                log.error("All %d candidate rooms failed — aborting", len(candidates))
                return result

    if booking is None:
        result.errors.append("No booking was secured after all fallback attempts")
        return result

    # ------------------------------------------------------------------
    # Step 2: Google Calendar event creation
    # ------------------------------------------------------------------
    log.info("Step 2 — GWS Calendar: creating event %r (room %s)", title, booking.room_id)

    description = (
        f"Room: {booking.room_name} ({booking.room_id})\n"
        f"GCS-PULSE Booking: {booking.booking_id} | Code: {booking.confirmation_code}\n"
        f"Attendees: {', '.join(attendees)}"
    )

    event: Optional[CalendarEvent] = None
    try:
        event = calendar.create_event(
            title=title,
            start=start,
            end=end,
            attendees=attendees,
            room_id=booking.room_id,
            room_name=booking.room_name,
            location=location,
            description=description,
            dry_run=dry_run,
        )
        result.event_id      = event.event_id
        result.calendar_link = event.html_link
        log.info("  Calendar event created: %s", event.event_id)
        log.info("  Notification emails sent to: %s", ", ".join(attendees))
    except Exception as exc:
        log.error("Calendar creation failed: %s — initiating rollback", exc)
        result.errors.append(f"Calendar event creation failed: {exc}")
        _rollback(gcs, booking)
        result.status = "partial_failure"
        return result

    # ------------------------------------------------------------------
    # Done
    # ------------------------------------------------------------------
    result.status = "dry_run_ok" if dry_run else "success"
    _print_summary(result, booking, event, attendees, dry_run)
    return result


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------
def _rollback(gcs: GCSPulseClient, booking: Booking) -> None:
    log.warning("ROLLBACK: cancelling GCS-PULSE booking %s (room %s)", booking.booking_id, booking.room_id)
    try:
        ok = gcs.cancel_booking(booking.booking_id)
        if ok:
            log.info("ROLLBACK: booking %s cancelled, room %s released", booking.booking_id, booking.room_id)
        else:
            log.error("ROLLBACK: cancel returned False — manual cleanup may be required for %s", booking.booking_id)
    except Exception as exc:
        log.error("ROLLBACK FAILED: %s — booking %s may require manual release", exc, booking.booking_id)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
def _print_summary(result: SkillResult, booking: Booking, event: CalendarEvent,
                   attendees: list[str], dry_run: bool) -> None:
    prefix = "[DRY RUN] " if dry_run else ""
    log.info("")
    log.info("=== %sSkill completed: %s ===", prefix, result.status.upper())
    log.info("  Room:          %s (%s)", booking.room_id, booking.room_name)
    log.info("  Booking ID:    %s", booking.booking_id)
    log.info("  Confirm code:  %s", booking.confirmation_code)
    log.info("  Event ID:      %s", event.event_id)
    log.info("  Calendar link: %s", event.html_link)
    log.info("  Attendees (%d): %s", len(attendees), ", ".join(attendees))
    if result.errors:
        log.info("  Warnings:      %s", "; ".join(result.errors))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Book a GCS-PULSE room and create a Google Calendar event."
    )
    p.add_argument("--title",           required=True)
    p.add_argument("--start",           required=True, help="ISO 8601 datetime, e.g. 2026-10-15T10:00:00+09:00")
    p.add_argument("--end",             required=True)
    p.add_argument("--attendees",       nargs="+", required=True, metavar="EMAIL")
    p.add_argument("--room-preference", default="",       dest="room_preference")
    p.add_argument("--location",        default="Seoul HQ")
    p.add_argument("--capacity",        type=int, default=0, help="Min seats (0 = auto from attendee count)")
    p.add_argument("--dry-run",         action="store_true", dest="dry_run")
    p.add_argument("--json",            action="store_true", dest="output_json",
                   help="Print JSON result to stdout instead of human-readable summary")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)

    result = run(
        title=args.title,
        start=args.start,
        end=args.end,
        attendees=args.attendees,
        room_preference=args.room_preference,
        location=args.location,
        capacity=args.capacity,
        dry_run=args.dry_run,
    )

    output = result.to_dict()
    if args.output_json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        status_icon = {"success": "[OK]", "dry_run_ok": "[DRY-RUN]", "partial_failure": "[WARN]", "failed": "[FAIL]"}.get(result.status, "[?]")
        print(f"\n{status_icon} Status: {result.status.upper()}")
        if result.booking_id:
            print(f"   Room:         {result.room_id}")
            print(f"   Booking ID:   {result.booking_id}")
        if result.event_id:
            print(f"   Event ID:     {result.event_id}")
        if result.calendar_link:
            print(f"   Calendar:     {result.calendar_link}")
        if result.errors:
            print(f"   Errors/Warns: {'; '.join(result.errors)}")

    sys.exit(0 if result.status in ("success", "dry_run_ok") else 1)


if __name__ == "__main__":
    main()
