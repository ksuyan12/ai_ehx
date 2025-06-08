from typing import Dict, Any, Optional
from logger_config import get_logger
from services import patient_api, appointment_api

logger = get_logger(__name__)


def save_patient_details_in_session(**kwargs) -> Dict[str, Any]:
    """
    Saves or updates details in session. Handles "None" string for clearing.
    """
    logger.info(f"Tool: save_patient_details_in_session with {kwargs}")
    updated_fields = {}
    for k, v in kwargs.items():
        if v == "None" or v is None:
            updated_fields[k] = None
        elif v is not None:
            # Ensure specific ID fields are strings
            if k in ["doctor_id", "selected_slot_id", "appointment_id_to_cancel"]:
                updated_fields[k] = str(v)
            else:
                updated_fields[k] = v
    return {"status": "details_noted_in_session", "updated_fields": updated_fields}


def validate_or_identify_patient(**kwargs) -> Dict[str, Any]:
    logger.info(f"Tool: validate_or_identify_patient with {kwargs}")
    return patient_api.validate_patient(
        kwargs.get("name"), kwargs.get("email"), kwargs.get("phone")
    )

def register_new_patient(name: str, email: str, phone: str, **kwargs) -> Dict[str, Any]:
    logger.info(f"Tool: register_new_patient for {name}")
    return patient_api.register_patient(name, email, phone, **kwargs)

def list_available_doctors() -> Dict[str, Any]:
    logger.info("Tool: list_available_doctors")
    return appointment_api.fetch_doctors()

def get_doctor_available_slots(doctor_id: str, date: str) -> Dict[str, Any]:
    logger.info(f"Tool: get_doctor_available_slots(doctor_id={doctor_id}, date={date})")
    try:
        clean_doctor_id = str(int(float(doctor_id)))
        logger.info(f"Sanitized doctor_id to: {clean_doctor_id}")
        return appointment_api.fetch_slots(clean_doctor_id, date)
    except (ValueError, TypeError) as e:
        logger.error(f"Invalid doctor_id format received: '{doctor_id}' - Error: {e}")
        return {"status": "error", "message": f"Invalid doctor ID format '{doctor_id}' provided."}

def schedule_appointment(patient_id: str, slot_id: str, reason: Optional[str] = "general-checkup") -> Dict[str, Any]:
    logger.info(f"Tool: schedule_appointment(patient_id={patient_id}, slot_id={slot_id}, reason={reason})")
    # Ensure slot_id is int for the API call
    try:
        clean_slot_id = str(int(float(slot_id)))
    except ValueError:
        logger.error(f"Invalid slot_id format for schedule_appointment: {slot_id}")
        return {"status": "error", "message": "Invalid slot ID format."}
    return appointment_api.book_appointment(patient_id, clean_slot_id, reason or "general-checkup")

def get_patient_upcoming_appointments(patient_id: str) -> Dict[str, Any]:
    logger.info(f"Tool: get_patient_upcoming_appointments(patient_id={patient_id})")
    return appointment_api.fetch_upcoming(patient_id)

def cancel_appointment(appointment_id: str) -> Dict[str, Any]:
    logger.info(f"Tool: cancel_appointment(appointment_id={appointment_id})")
    return appointment_api.remove_appointment(appointment_id)

# Mapping of tool names to their implementation functions
AVAILABLE_PYTHON_TOOLS = {
    "save_patient_details_in_session": save_patient_details_in_session,
    "validate_or_identify_patient": validate_or_identify_patient,
    "register_new_patient": register_new_patient,
    "list_available_doctors": list_available_doctors,
    "get_doctor_available_slots": get_doctor_available_slots,
    "schedule_appointment": schedule_appointment,
    "get_patient_upcoming_appointments": get_patient_upcoming_appointments,
    "cancel_appointment": cancel_appointment,
}