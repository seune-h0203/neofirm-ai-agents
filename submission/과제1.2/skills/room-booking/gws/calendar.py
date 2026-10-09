"""
GWS Calendar client.

Uses google-api-python-client with service-account credentials when
GOOGLE_SERVICE_ACCOUNT_JSON is set; falls back to mock mode otherwise.
"""
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

_MOCK_EVENTS: dict[str, dict] = {}


@dataclass
class CalendarEvent:
    event_id: str
    title: str
    start: str
    end: str
    attendees: list[str]
    room_id: str
    room_name: str
    location: str
    html_link: str
    status: str = "confirmed"


class GWSCalendarClient:
    def __init__(self):
        sa_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        self._calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
        self._impersonate  = os.environ.get("GOOGLE_IMPERSONATE_EMAIL", "")
        self._service      = None
        self._use_mock     = True

        if sa_path and os.path.isfile(sa_path):
            self._service  = self._build_service(sa_path)
            self._use_mock = self._service is None
        else:
            log.warning("GWS Calendar: no service account configured — using in-process mock")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def create_event(
        self,
        title: str,
        start: str,
        end: str,
        attendees: list[str],
        room_id: str,
        room_name: str,
        location: str,
        description: str = "",
        dry_run: bool = False,
    ) -> CalendarEvent:
        body = self._build_event_body(title, start, end, attendees, room_id, room_name, location, description)
        if dry_run:
            return self._dry_run_event(body)
        if self._use_mock:
            return self._mock_create(body)
        return self._live_create(body)

    def delete_event(self, event_id: str) -> bool:
        """Called by rollback logic."""
        if self._use_mock:
            removed = _MOCK_EVENTS.pop(event_id, None)
            log.info("mock deleted event %s: %s", event_id, "ok" if removed else "not found")
            return removed is not None
        try:
            self._service.events().delete(calendarId=self._calendar_id, eventId=event_id).execute()
            return True
        except Exception as exc:
            log.error("GWS delete_event failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Event body builder
    # ------------------------------------------------------------------
    def _build_event_body(self, title, start, end, attendees, room_id, room_name, location, description) -> dict:
        body: dict = {
            "summary": title,
            "location": f"{location} / {room_name} ({room_id})",
            "description": description or f"Room: {room_name} ({room_id}) | Booking via GCS-PULSE",
            "start": {"dateTime": start, "timeZone": "Asia/Seoul"},
            "end":   {"dateTime": end,   "timeZone": "Asia/Seoul"},
            "attendees": [{"email": e} for e in attendees],
            "conferenceData": None,
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email",  "minutes": 60},
                    {"method": "popup",  "minutes": 10},
                ],
            },
            "sendUpdates": "all",    # triggers notification emails to all attendees
            "guestsCanModify": False,
        }
        return body

    # ------------------------------------------------------------------
    # Mock implementation
    # ------------------------------------------------------------------
    def _mock_create(self, body: dict) -> CalendarEvent:
        import random, string
        event_id = "evt-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        _MOCK_EVENTS[event_id] = body
        log.info("mock created calendar event %s: %r", event_id, body["summary"])
        attendees = [a["email"] for a in body.get("attendees", [])]
        return CalendarEvent(
            event_id=event_id,
            title=body["summary"],
            start=body["start"]["dateTime"],
            end=body["end"]["dateTime"],
            attendees=attendees,
            room_id=body["location"].split("(")[-1].rstrip(")"),
            room_name=body["location"].split(" / ")[-1].split(" (")[0] if " / " in body["location"] else "",
            location=body["location"].split(" / ")[0] if " / " in body["location"] else body["location"],
            html_link=f"https://calendar.google.com/calendar/event?eid={event_id}",
        )

    def _dry_run_event(self, body: dict) -> CalendarEvent:
        attendees = [a["email"] for a in body.get("attendees", [])]
        return CalendarEvent(
            event_id="DRY-RUN",
            title=body["summary"],
            start=body["start"]["dateTime"],
            end=body["end"]["dateTime"],
            attendees=attendees,
            room_id="DRY-RUN",
            room_name="",
            location=body["location"],
            html_link="",
            status="dry_run",
        )

    # ------------------------------------------------------------------
    # Live Google Calendar API
    # ------------------------------------------------------------------
    def _build_service(self, sa_path: str):
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            scopes = ["https://www.googleapis.com/auth/calendar"]
            creds = service_account.Credentials.from_service_account_file(sa_path, scopes=scopes)
            if self._impersonate:
                creds = creds.with_subject(self._impersonate)
            service = build("calendar", "v3", credentials=creds, cache_discovery=False)
            log.info("GWS Calendar: service account authenticated")
            return service
        except Exception as exc:
            log.error("GWS Calendar: failed to build service — %s", exc)
            return None

    def _live_create(self, body: dict) -> CalendarEvent:
        event = (
            self._service.events()
            .insert(calendarId=self._calendar_id, body=body, sendUpdates="all")
            .execute()
        )
        attendees = [a["email"] for a in body.get("attendees", [])]
        return CalendarEvent(
            event_id=event["id"],
            title=event.get("summary", ""),
            start=event["start"]["dateTime"],
            end=event["end"]["dateTime"],
            attendees=attendees,
            room_id=body["location"].split("(")[-1].rstrip(")"),
            room_name="",
            location=event.get("location", ""),
            html_link=event.get("htmlLink", ""),
        )
