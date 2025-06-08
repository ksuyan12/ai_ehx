import requests
import json
from typing import Dict, Any, Optional
from config import settings
from logger_config import get_logger

logger = get_logger(__name__)
PATIENT_SERVICE_V1_URL = settings.patient_service_v1_url

def validate_patient(name: Optional[str], email: Optional[str], phone: Optional[str]) -> Dict[str, Any]:
    """Calls the Patient Service to validate patient details."""
    payload = {k: v for k, v in {"name": name, "email": email, "phone": phone}.items() if v}
    logger.info(f"Calling Patient Service: Validate with {payload}")

    if len(payload) < 2:
        return {"status": "error", "message": "Insufficient details. Need at least two of: name, email, or phone."}

    try:
        url = f"{PATIENT_SERVICE_V1_URL}/patients/validate"
        response = requests.post(url, json=payload, timeout=7)
        logger.info(f"Patient Service Validate Response: Status {response.status_code}, Body: {response.text[:200]}")

        if response.status_code == 200:
            try:
                response_data = response.json()
                patient_id = response_data.get("patientId")
                if patient_id:
                    return {"status": "found", "patient_id": patient_id, "message_for_user": "Your details validated."}
                else:
                    logger.error("Validation successful (200 OK) but 'patientId' missing.")
                    return {"status": "error", "message": "Validation service error (missing ID)."}
            except json.JSONDecodeError:
                logger.error("Could not decode JSON from successful validation.")
                return {"status": "error", "message": "Validation service returned unreadable data."}
        elif response.status_code == 404:
            return {"status": "not_found", "message_for_user": "I couldn't find a record."}
        else:
            return {"status": "error", "message": f"Validation service error: {response.status_code}"}
    except requests.RequestException as e:
        logger.error(f"Connection error during validation: {e}")
        return {"status": "error", "message": f"Connection error: {e}"}

def register_patient(name: str, email: str, phone: str, **kwargs) -> Dict[str, Any]:
    """Calls the Patient Service to register a new patient."""
    logger.info(f"Calling Patient Service: Register for {name}")
    patient_fhir = {
        "resourceType": "Patient", "active": True, "name": [{"use": "official", "text": name}],
        "telecom": [
            {"system": "phone", "value": phone, "use": "mobile"},
            {"system": "email", "value": email, "use": "home"}
        ]
    }
    if kwargs.get("gender"): patient_fhir["gender"] = kwargs["gender"].lower()
    if kwargs.get("birthDate"): patient_fhir["birthDate"] = kwargs["birthDate"]
    if kwargs.get("address_line") and kwargs.get("address_city") and kwargs.get("address_country"):
        patient_fhir["address"] = [{"use": "home", "line": [kwargs["address_line"]], "city": kwargs["address_city"], "country": kwargs["address_country"]}]

    try:
        url = f"{PATIENT_SERVICE_V1_URL}/patients"
        response = requests.post(url, json=patient_fhir, timeout=7)
        logger.info(f"Patient Service Register Response: {response.status_code}, Body: {response.text[:200]}")
        if response.status_code == 201:
            reg_data = response.json()
            patient_id = reg_data.get("id")
            return {"status": "registered", "patient_id": patient_id, "message_for_user": f"Registered, {name}."} if patient_id else {"status": "error", "message": "Registration OK but no ID."}
        else: return {"status": "error", "message": f"Registration failed: {response.status_code}"}
    except Exception as e: return {"status": "error", "message": f"Registration exception: {e}"}