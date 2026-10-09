"""GCS-PULSE data models."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Room:
    id: str
    name: str
    floor: int
    capacity: int
    rate_krw: int
    location: str
    available: bool
    features: list[str] = field(default_factory=list)

    def matches_preference(self, pref: str) -> bool:
        """True if this room matches a keyword preference or exact ID."""
        if not pref:
            return True
        p = pref.lower()
        if p == self.id.lower():
            return True
        if p in ("large", "big") and self.capacity >= 10:
            return True
        if p in ("small", "focus") and self.capacity <= 4:
            return True
        if p in ("medium", "mid") and 5 <= self.capacity <= 9:
            return True
        return p in self.name.lower() or p in self.location.lower()


@dataclass
class Booking:
    booking_id: str
    room_id: str
    room_name: str
    check_in: str
    check_out: str
    guest_email: str
    nights: int
    total_krw: int
    confirmation_code: str
    status: str = "CONFIRMED"
