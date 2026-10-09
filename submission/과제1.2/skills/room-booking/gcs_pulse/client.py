"""
GCS-PULSE client.

Tries real HTTP first (GCS_PULSE_API_URL + GCS_PULSE_API_KEY).
Falls back to an in-process mock when the server is unreachable,
so the skill runs end-to-end in dev/CI without a live GCS-PULSE instance.
"""
import logging
import os
import random
import string
import uuid
from datetime import datetime, timedelta
from typing import Optional

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

from .models import Booking, Room

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------
_MOCK_ROOMS: list[Room] = [
    Room("R-101", "Standard Room",    floor=1, capacity=4,  rate_krw=150_000, location="Seoul HQ", available=True,  features=["whiteboard", "TV"]),
    Room("R-102", "Standard Room B",  floor=1, capacity=4,  rate_krw=150_000, location="Seoul HQ", available=False, features=["whiteboard"]),
    Room("R-201", "Conference Room",  floor=2, capacity=10, rate_krw=300_000, location="Seoul HQ", available=True,  features=["projector", "video-conf"]),
    Room("R-202", "Board Room",       floor=2, capacity=20, rate_krw=500_000, location="Seoul HQ", available=True,  features=["projector", "video-conf", "catering"]),
    Room("R-301", "Focus Pod",        floor=3, capacity=2,  rate_krw=80_000,  location="Seoul HQ", available=True,  features=["standing-desk"]),
    Room("R-302", "Focus Pod B",      floor=3, capacity=2,  rate_krw=80_000,  location="Seoul HQ", available=True,  features=["standing-desk"]),
]

_active_bookings: dict[str, Booking] = {}


def _mock_booking_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"BK-{datetime.now().strftime('%Y%m%d')}-{suffix}"


def _mock_confirmation_code() -> str:
    return "GCP-" + "".join(random.choices(string.digits, k=4))


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class GCSPulseClient:
    def __init__(self):
        self._base_url = os.environ.get("GCS_PULSE_API_URL", "").rstrip("/")
        self._api_key  = os.environ.get("GCS_PULSE_API_KEY", "")
        self._use_mock = not self._base_url or not _HTTPX_AVAILABLE

        if self._use_mock:
            log.warning("GCS-PULSE: no live server configured — using in-process mock")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def list_available_rooms(
        self,
        check_in: str,
        check_out: str,
        capacity: int = 1,
        location: str = "Seoul HQ",
        preference: str = "",
    ) -> list[Room]:
        if self._use_mock:
            return self._mock_list_rooms(check_in, check_out, capacity, location, preference)
        return self._http_list_rooms(check_in, check_out, capacity, location, preference)

    def book_room(
        self,
        room_id: str,
        check_in: str,
        check_out: str,
        guest_email: str,
        dry_run: bool = False,
        room_name: str = "",
    ) -> Booking:
        if dry_run:
            return self._dry_run_booking(room_id, check_in, check_out, guest_email, room_name)
        if self._use_mock:
            return self._mock_book(room_id, check_in, check_out, guest_email)
        return self._http_book(room_id, check_in, check_out, guest_email)

    def cancel_booking(self, booking_id: str) -> bool:
        """Release a booking — used by rollback logic."""
        if self._use_mock:
            return self._mock_cancel(booking_id)
        return self._http_cancel(booking_id)

    # ------------------------------------------------------------------
    # Mock implementations
    # ------------------------------------------------------------------
    def _mock_list_rooms(self, check_in, check_out, capacity, location, preference) -> list[Room]:
        results = []
        for r in _MOCK_ROOMS:
            if not r.available:
                continue
            if r.capacity < capacity:
                continue
            if location and location.lower() not in r.location.lower():
                continue
            if preference and not r.matches_preference(preference):
                continue
            results.append(r)
        log.debug("mock list_rooms → %d results", len(results))
        return results

    def _mock_book(self, room_id, check_in, check_out, guest_email) -> Booking:
        room = next((r for r in _MOCK_ROOMS if r.id == room_id), None)
        if room is None:
            raise ValueError(f"Room {room_id!r} not found")
        if not room.available:
            raise ValueError(f"Room {room_id!r} is not available for {check_in} → {check_out}")

        # Parse nights
        try:
            d1 = datetime.fromisoformat(check_in.split("T")[0])
            d2 = datetime.fromisoformat(check_out.split("T")[0])
            nights = max(1, (d2 - d1).days)
        except ValueError:
            nights = 1

        booking = Booking(
            booking_id=_mock_booking_id(),
            room_id=room.id,
            room_name=room.name,
            check_in=check_in,
            check_out=check_out,
            guest_email=guest_email,
            nights=nights,
            total_krw=room.rate_krw * nights,
            confirmation_code=_mock_confirmation_code(),
        )
        room.available = False           # mark room as taken in mock state
        _active_bookings[booking.booking_id] = booking
        log.info("mock booked room %s → %s", room_id, booking.booking_id)
        return booking

    def _mock_cancel(self, booking_id: str) -> bool:
        booking = _active_bookings.pop(booking_id, None)
        if booking is None:
            log.warning("mock cancel: booking %s not found", booking_id)
            return False
        room = next((r for r in _MOCK_ROOMS if r.id == booking.room_id), None)
        if room:
            room.available = True
        log.info("mock cancelled booking %s, room %s released", booking_id, booking.room_id)
        return True

    def _dry_run_booking(self, room_id, check_in, check_out, guest_email, room_name: str = "") -> Booking:
        return Booking(
            booking_id="DRY-RUN",
            room_id=str(room_id),
            room_name=room_name or str(room_id),
            check_in=check_in,
            check_out=check_out,
            guest_email=guest_email,
            nights=1,
            total_krw=0,
            confirmation_code="DRY-RUN",
            status="DRY_RUN",
        )

    # ------------------------------------------------------------------
    # HTTP implementations (1000.school live API)
    # /meeting-rooms                          → list rooms
    # /meeting-rooms/{id}/reservations        → list / create reservations
    # /meeting-rooms/reservations/{id}        → cancel reservation
    # ------------------------------------------------------------------
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    def _http_list_rooms(self, check_in, check_out, capacity, location, preference) -> list[Room]:
        with httpx.Client(timeout=10.0) as c:
            resp = c.get(f"{self._base_url}/meeting-rooms", headers=self._headers())
            resp.raise_for_status()
        raw = resp.json()
        rooms_data = raw if isinstance(raw, list) else raw.get("rooms", raw.get("items", []))

        # Parse check_in date for availability check
        check_date = check_in.split("T")[0] if "T" in check_in else check_in

        rooms: list[Room] = []
        for r in rooms_data:
            # capacity may be embedded in description e.g. "최대 4인"
            desc = r.get("description", "")
            import re as _re
            cap_match = _re.search(r"최대\s*(\d+)", desc)
            room_cap = int(cap_match.group(1)) if cap_match else int(r.get("capacity", 99))

            room = Room(
                id=str(r.get("id", r.get("room_id", ""))),
                name=r.get("name", r.get("room_name", "")),
                floor=int(r.get("floor", 0)),
                capacity=room_cap,
                rate_krw=int(r.get("rate_krw", r.get("rate", 0))),
                location=r.get("location", location),
                available=r.get("available", True),
                features=r.get("features", []),
            )
            if room.capacity < capacity:
                continue
            if preference and not room.matches_preference(preference):
                continue
            # Check availability via reservations endpoint
            if self._http_is_room_available(room.id, check_date, check_in, check_out):
                room.available = True
                rooms.append(room)
        log.debug("live list_rooms → %d results", len(rooms))
        return rooms

    def _http_is_room_available(self, room_id: str, date: str, check_in: str, check_out: str) -> bool:
        """Return True if no existing reservation overlaps the requested window."""
        try:
            with httpx.Client(timeout=10.0) as c:
                resp = c.get(
                    f"{self._base_url}/meeting-rooms/{room_id}/reservations",
                    params={"date": date},
                    headers=self._headers(),
                )
                if resp.status_code == 404:
                    return True  # room or endpoint not found → assume available
                resp.raise_for_status()
            existing = resp.json()
            if not isinstance(existing, list):
                existing = existing.get("reservations", existing.get("items", []))
            for res in existing:
                rs = res.get("start_at", res.get("start_time", res.get("start", "")))
                re_ = res.get("end_at", res.get("end_time", res.get("end", "")))
                if rs and re_ and rs < check_out and re_ > check_in:
                    return False  # overlap
            return True
        except Exception as exc:
            log.warning("availability check for room %s failed: %s — assuming available", room_id, exc)
            return True

    def _http_book(self, room_id, check_in, check_out, guest_email) -> Booking:
        payload = {
            "start_at": check_in,
            "end_at": check_out,
            "purpose": f"Booked by {guest_email}",
        }
        with httpx.Client(timeout=15.0) as c:
            resp = c.post(
                f"{self._base_url}/meeting-rooms/{room_id}/reservations",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
        data = resp.json()
        res_id = str(data.get("id", data.get("reservation_id", "")))
        return Booking(
            booking_id=res_id,
            room_id=str(data.get("meeting_room_id", data.get("room_id", room_id))),
            room_name=data.get("reserved_by_name", data.get("room_name", "")),
            check_in=data.get("start_at", data.get("start_time", check_in)),
            check_out=data.get("end_at", data.get("end_time", check_out)),
            guest_email=guest_email,
            nights=1,
            total_krw=int(data.get("total_krw", data.get("price", 0))),
            confirmation_code=res_id,
        )

    def _http_cancel(self, booking_id: str) -> bool:
        with httpx.Client(timeout=10.0) as c:
            resp = c.delete(
                f"{self._base_url}/meeting-rooms/reservations/{booking_id}",
                headers=self._headers(),
            )
            return resp.status_code in (200, 204)
