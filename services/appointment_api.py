import requests
import json
from datetime import datetime
from typing import Dict, Any, List
from config import settings
from logger_config import get_logger

logger = get_logger(__name__)
APPOINTMENT_SERVICE_V1_URL = settings.appointment_service_v1_url

def fetch_doctors() -> Dict[str, Any]:
    """Fetches the list of available doctors from the Appointment Service."""
    logger.info("Calling Appointment Service: List Doctors")
    try:
        url = f"{APPOINTMENT_SERVICE_V1_URL}/doctors"
        response = requests.get(url, timeout=7)
        logger.info(f"Appointment Service List Doctors Response: {response.status_code}, Body: {response.text[:300]}")
        if response.status_code == 200:
            doctors = response.json()
            active_doctors = [
                { "id": str(doc.get("id")), "display_text": f"Dr. {doc.get('name')} ({doc.get('specialization')})"}
                for doc in doctors if doc.get("active")
            ]
            if not active_doctors:
                return {"status": "no_doctors_found", "doctors": [], "message_for_user": "No doctors found."}
            return {"status": "success", "doctors": active_doctors}
        else:
            return {"status": "error", "message": f"Failed to get doctors: {response.status_code}"}
    except Exception as e:
        logger.error(f"Error calling list_available_doctors service: {e}")
        return {"status": "error", "message": f"Connection error: {e}"}

def fetch_slots(doctor_id: str, date: str) -> Dict[str, Any]:
    """Fetches available slots for a doctor on a specific date."""
    logger.info(f"Calling Appointment Service: Get Slots (Dr_ID={doctor_id}, Date={date})")
    try: datetime.strptime(date, "%Y-%m-%d")
    except ValueError: return {"status": "error", "message": "Invalid date format (YYYY-MM-DD)."}
    try:
        url = f"{APPOINTMENT_SERVICE_V1_URL}/doctors/{doctor_id}/slots"
        response = requests.get(url, params={"date": date}, timeout=7)
        logger.info(f"Appointment Service Get Slots Response: {response.status_code}, Body: {response.text[:200]}")
        if response.status_code == 200:
            api_slots = response.json()
            available_slots = []
            for slot in api_slots:
                if not slot.get("booked"):
                    try:
                        start = datetime.strptime(slot.get("startTime"), "%H:%M:%S").strftime('%-I:%M %p')
                        end = datetime.strptime(slot.get("endTime"), "%H:%M:%S").strftime('%-I:%M %p')
                        display = f"{start} - {end}"
                    except: display = f"{slot.get('startTime')} - {slot.get('endTime')}"
                    available_slots.append({"id": str(slot.get("id")), "display_text": display})
            if not available_slots: return {"status": "no_slots_found", "slots": [], "message_for_user": "No slots found."}
            return {"status": "success", "slots": available_slots}
        else: return {"status": "error", "message": f"Failed to get slots: {response.status_code}"}
    except Exception as e: return {"status": "error", "message": f"Slot fetch exception: {e}"}

def book_appointment(patient_id: str, slot_id: str, reason: str) -> Dict[str, Any]:
    """Books an appointment using the Appointment Service."""
    logger.info(f"Calling Appointment Service: Schedule (Patient_ID={patient_id}, Slot_ID={slot_id})")
    params = {"patientId": patient_id, "slotId": int(slot_id), "reason": reason or "general-checkup"}
    try:
        url = f"{APPOINTMENT_SERVICE_V1_URL}/appointments"
        response = requests.post(url, params=params, timeout=7)
        logger.info(f"Appointment Service Schedule Response: {response.status_code}, Body: {response.text[:200]}")
        if response.status_code in [200, 201]:
            details = response.json()
            appt_id = str(details.get("id"))
            return {"status": "booked", "appointment_id": appt_id, "details": details, "message_for_user": f"Booked (ID: {appt_id})."}
        else: return {"status": "error", "message": f"Booking failed: {response.status_code}"}
    except Exception as e: return {"status": "error", "message": f"Booking exception: {e}"}

def fetch_upcoming(patient_id: str) -> Dict[str, Any]:
    """Fetches upcoming appointments for a patient."""
    logger.info(f"Calling Appointment Service: Get Upcoming (Patient_ID={patient_id})")
    try:
        url = f"{APPOINTMENT_SERVICE_V1_URL}/upcomingByPatientId"
        response = requests.get(url, params={"patientId": patient_id}, timeout=7)
        logger.info(f"Appointment Service Get Upcoming Response: {response.status_code}, Body: {response.text[:300]}")
        if response.status_code == 200:
            appointments = response.json()
            return {"status": "success", "appointments": appointments} if appointments else {"status": "no_appointments_found", "appointments": []}
        elif response.status_code == 404:
            return {"status": "no_appointments_found", "appointments": []}
        else:
            return {"status": "error", "message": f"Failed to get appointments: {response.status_code}"}
    except Exception as e:
        logger.error(f"Error calling upcoming appointments: {e}")
        return {"status": "error", "message": f"Connection error: {e}"}

def remove_appointment(appointment_id: str) -> Dict[str, Any]:
    """Cancels an appointment using the Appointment Service."""
    logger.info(f"Calling Appointment Service: Cancel (Appt_ID={appointment_id})")
    try:
        clean_id = str(int(float(appointment_id)))
        url = f"{APPOINTMENT_SERVICE_V1_URL}/appointments/{clean_id}"
        response = requests.delete(url, timeout=7)
        logger.info(f"Appointment Service Cancel Response: {response.status_code}")
        if response.status_code in [200, 204]:
            return {"status": "cancelled", "message_for_user": f"Appointment {clean_id} cancelled."}
        else:
            return {"status": "error", "message": f"Cancellation failed: {response.status_code}"}
    except ValueError:
        return {"status": "error", "message": "Invalid appointment ID format."}
    except Exception as e:
        return {"status": "error", "message": f"Cancellation exception: {e}"}