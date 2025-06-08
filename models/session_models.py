from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional


class SessionData(BaseModel):
    """Defines the structure for data stored within a session."""
    patient_id: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    gender: Optional[str] = None
    birthDate: Optional[str] = None
    address_line: Optional[str] = None
    address_city: Optional[str] = None
    address_country: Optional[str] = None

    # Booking process fields
    doctor_id: Optional[str] = None
    doctor_name_display: Optional[str] = None  # <-- NEW: To store doctor's display name
    preferred_date: Optional[str] = None
    selected_slot_id: Optional[str] = None  # <-- NEW
    selected_slot_text: Optional[str] = None  # <-- NEW (e.g., "10:00 AM - 10:30 AM")
    visit_reason: Optional[str] = None  # <-- NEW

    # Cancellation process field
    appointment_id_to_cancel: Optional[str] = None

    # Contextual data from tool calls
    last_validation_status: Optional[str] = None
    last_doctors_list: Optional[List[Dict[str, str]]] = None
    last_slots_list: Optional[List[Dict[str, str]]] = None
    last_upcoming_appointments: Optional[List[Dict[str, Any]]] = None

    # Overall state
    conversation_state: str = "initial_greeting"
    current_intent: Optional[str] = None


class Session(BaseModel):
    """Represents a full session, including data and history."""
    data: SessionData = Field(default_factory=SessionData)
    history: List[Dict[str, Any]] = Field(default_factory=list)