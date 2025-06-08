#!/usr/bin/env python3
"""
AI Appointment Agent – Dynamic & Interactive with API-backed Tools.
Version 2.23: Added quick replies to the initial greeting message.

Features:
- Uses Gemini Function Calling for NLU, dialogue management, and API interaction.
- Enforces validation before registration.
- Handles patient identification, validation (retrieving patientId), and registration.
- Lists available doctors.
- Fetches available appointment slots for a specific doctor and date.
- Schedules and cancels appointments using correct API parameter methods.
- Checks upcoming appointments for a specific patient efficiently.
- Aware of current date for resolving relative date mentions.
- Starts conversation with a defined greeting and initial quick replies.
- Can suggest quick replies and structured UI elements in its responses.
"""

import json
import os
import uuid
import logging
import re  # Added for parsing quick replies and structured data tags
from typing import Dict, Any, List, Optional
from datetime import datetime, date as datetime_date  # For current date

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

import google.generativeai as genai
# Import Tool and FunctionDeclaration from .types
from google.generativeai.types import HarmCategory, HarmBlockThreshold, Tool, FunctionDeclaration

# GenerationConfig is often available at top-level genai.

# ------------------------------------------------------------------------------
# Logging & Dummy Session Store
# ------------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(module)s:%(lineno)d | %(message)s"
)
logger = logging.getLogger("agent")

_MEMORY_SESSION_STORE: Dict[str, Dict[str, Any]] = {}


def _save_session(sid: str, session_data: Dict[str, Any]):
    serializable_history = []
    if "history" in session_data:
        for item in session_data["history"]:
            if isinstance(item, dict):
                serializable_history.append(item)
            else:
                logger.warning(f"Attempting to save non-dict item in history for session {sid}: {type(item)}")
                serializable_history.append(content_to_dict(item))

    session_data_copy = session_data.copy()
    session_data_copy["history"] = serializable_history
    _MEMORY_SESSION_STORE[sid] = session_data_copy
    logger.info(f"Dummy store: Session {sid} saved.")


def _load_session(sid: str) -> Dict[str, Any]:
    if sid not in _MEMORY_SESSION_STORE:
        raise KeyError(f"Session {sid} not found in dummy store.")
    logger.info(f"Dummy store: Session {sid} loaded.")
    return _MEMORY_SESSION_STORE[sid]


# ------------------------------------------------------------------------------
# Env & API Config
# ------------------------------------------------------------------------------
load_dotenv()
GENAI_API_KEY = os.getenv("GEMINI_API_KEY")
PATIENT_SERVICE_API_BASE = os.getenv("PATIENT_SERVICE_URL")
PATIENT_SERVICE_V1_URL = f"{PATIENT_SERVICE_API_BASE}/v1"
APPOINTMENT_SERVICE_API_BASE = os.getenv("APPOINTMENT_SERVICE_URL")  # Matches doctor list API
APPOINTMENT_SERVICE_V1_URL = f"{APPOINTMENT_SERVICE_API_BASE}/v1"

if not GENAI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY missing – set it in .env")

genai.configure(api_key=GENAI_API_KEY)

# ------------------------------------------------------------------------------
# Agent System Prompt
# ------------------------------------------------------------------------------
SYSTEM_PROMPT = f"""You are MedX Hospital's friendly and efficient AI appointment assistant.
Your primary goals are:
1.  Help users book new appointments.
2.  Allow users to check their upcoming appointments.
3.  Allow users to cancel existing appointments.

Initial Interaction:
- Your first response to the user will be a greeting handled by the system (including initial quick replies). After that, engage naturally.

Current Date Awareness:
- You will be provided with the "Current Date" in the context of each turn. Use this to resolve relative date mentions.
- Aim for "YYYY-MM-DD" format for dates.

Suggesting UI Elements:
- Quick Replies: If your response ends with a yes/no question or simple choices, append `[quick_replies: Option1, Option2]`
  Example: "Is this correct? [quick_replies: Yes, No]"
- Required Fields for UI (Form): When you need multiple specific pieces of information (like name, email, phone for identification), append a tag:
  `[required_fields: name|Full Name|text|Enter full name, email|Email Address|email|you@example.com, phone|Phone Number|tel|555-1234]`
  Each field is: `name_attribute|Label Text|input_type|placeholder_text`. Separate fields with a comma.
- Required Input (Single Input Hint): When you need a single specific input like a date, and want to hint the UI to show a date picker, use:
  `[required_input: type|Label Text|submit_message_prefix]`
  Example: "What date would you like? [required_input: date|Select Appointment Date|Date: ]"
  The `submit_message_prefix` is what the UI might prepend to the user's selected value when sending it back.
- Displaying Doctors: After calling `list_available_doctors` and you want the UI to show the list for selection, include the tag `[display_doctors]` in your response. Your text should prompt the user to select from the displayed list.
- Displaying Slots: After calling `get_doctor_available_slots` and you want the UI to show the slots, include `[display_slots]`. Your text should prompt selection.

Key Information & Flow:
- Patient Identification:
  - If `patient_id` is not in session: Ask for name, email, or phone. Use the `[required_fields: ...]` tag.
  - Use `save_patient_details_in_session`.
  - **CRITICAL VALIDATION SEQUENCE**: After saving, if >=2 identifiers are present, *ONLY NEXT ACTION* is to call `validate_or_identify_patient`. Then respond to user based on validation.
  - If `validate_or_identify_patient` is 'found' (and `patient_id` returned): Inform user. Proceed.
  - If 'not_found': Inform user, then ask to register.
- Patient Registration: Only after 'not_found' validation AND user agreement.
- Appointment Booking:
  - Requires `patient_id`.
  - Ask for doctor preference. If none, or user asks, call `list_available_doctors`, then use `[display_doctors]` tag in your response.
  - Once doctor ID is known, ask for date (e.g., using `[required_input: date|Select Date|Date: ]`).
  - Call `get_doctor_available_slots`. Then use `[display_slots]` tag in your response.
  - User selects slot. Ask for `reason`. Confirm. Call `schedule_appointment`.
- Checking/Canceling Appointments: Requires `patient_id`. Use `get_patient_upcoming_appointments` first.

CRITICAL INTERACTION RULE:
- After ANY tool call, you MUST generate a clear, natural language response or question FOR THE USER.
"""


# ------------------------------------------------------------------------------
# Tool Definitions (Python Functions)
# ------------------------------------------------------------------------------
def save_patient_details_in_session(**kwargs) -> Dict[str, Any]:
    logger.info(f"🛠️ Tool Called: save_patient_details_in_session with {kwargs}")
    updated_fields = {k: v for k, v in kwargs.items() if v is not None}
    if "doctor_id" in updated_fields and updated_fields["doctor_id"] is not None:
        updated_fields["doctor_id"] = str(updated_fields["doctor_id"])
    return {"status": "details_noted_in_session", "updated_fields": updated_fields}


def validate_or_identify_patient(**kwargs) -> Dict[str, Any]:
    payload = {k: v for k, v in kwargs.items() if k in ["name", "email", "phone"] and v}
    logger.info(f"🛠️ Tool Called: validate_or_identify_patient with {payload}")
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
                    return {"status": "found", "patient_id": patient_id,
                            "message_for_user": "Your details have been validated and record found."}
                else:
                    logger.error("Validation successful (200 OK) but 'patientId' missing in response.")
                    return {"status": "error",
                            "message": "Validation successful but patient ID not provided by service."}
            except json.JSONDecodeError:
                logger.error("Could not decode JSON from successful validation response.")
                return {"status": "error", "message": "Validation service returned an unreadable success response."}
        elif response.status_code == 404:
            return {"status": "not_found", "message_for_user": "I couldn't find a record with those details."}
        else:
            return {"status": "error",
                    "message": f"Validation service error: {response.status_code} - {response.text[:100]}"}
    except requests.RequestException as e:
        logger.error(f"Connection error during validation: {e}")
        return {"status": "error", "message": f"Connection error: {e}"}


def register_new_patient(name: str, email: str, phone: str, **kwargs) -> Dict[str, Any]:
    logger.info(f"🛠️ Tool Called: register_new_patient for {name}")
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
        patient_fhir["address"] = [{"use": "home", "line": [kwargs["address_line"]], "city": kwargs["address_city"],
                                    "country": kwargs["address_country"]}]

    try:
        url = f"{PATIENT_SERVICE_V1_URL}/patients"
        response = requests.post(url, json=patient_fhir, timeout=7)
        logger.info(f"Patient Service Register Response: {response.status_code}, Body: {response.text[:200]}")
        if response.status_code == 201:
            reg_data = response.json()
            patient_id = reg_data.get("id")
            return {"status": "registered", "patient_id": patient_id,
                    "message_for_user": f"Welcome! You're now registered, {name}."} if patient_id else {
                "status": "error", "message": "Registration OK but no ID returned."}
        else:
            return {"status": "error",
                    "message": f"Registration failed: {response.status_code} - {response.text[:100]}"}
    except Exception as e:
        return {"status": "error", "message": f"Registration exception: {e}"}


def list_available_doctors() -> Dict[str, Any]:
    logger.info("🛠️ Tool Called: list_available_doctors")
    try:
        url = f"{APPOINTMENT_SERVICE_V1_URL}/doctors"
        response = requests.get(url, timeout=7)
        logger.info(
            f"Appointment Service List Doctors Response: Status {response.status_code}, Body: {response.text[:300]}")
        if response.status_code == 200:
            doctors = response.json()
            active_doctors = []
            for doc in doctors:
                if doc.get("active"):
                    active_doctors.append({
                        "id": str(doc.get("id")),
                        "display_text": f"Dr. {doc.get('name')} ({doc.get('specialization')})"
                    })
            logger.info(f"Found {len(active_doctors)} active doctors.")
            if not active_doctors:
                return {"status": "no_doctors_found", "doctors": [],
                        "message_for_user": "Sorry, I couldn't find any doctors available at the moment."}
            return {"status": "success", "doctors": active_doctors}
        else:
            return {"status": "error",
                    "message": f"Failed to get doctor list: {response.status_code} - {response.text[:100]}"}
    except Exception as e:
        logger.error(f"Error calling list_available_doctors service: {e}")
        return {"status": "error", "message": f"Connection error with doctor listing service: {e}"}


def get_doctor_available_slots(doctor_id: str, date: str) -> Dict[str, Any]:
    logger.info(f"🛠️ Tool Called: get_doctor_available_slots(doctor_id={doctor_id}, date={date})")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return {"status": "error", "message": "Invalid date format. Please use<y_bin_46>-MM-DD."}
    try:
        url = f"{APPOINTMENT_SERVICE_V1_URL}/doctors/{doctor_id}/slots"
        response = requests.get(url, params={"date": date}, timeout=7)
        logger.info(f"Appointment Service Get Slots Response: {response.status_code}, Body: {response.text[:200]}")
        if response.status_code == 200:
            api_slots = response.json()
            available_slots_for_ui = []
            for slot in api_slots:
                if not slot.get("booked"):
                    try:
                        start_dt = datetime.strptime(slot.get("startTime"), "%H:%M:%S")
                        end_dt = datetime.strptime(slot.get("endTime"), "%H:%M:%S")
                        display_text = f"{start_dt.strftime('%-I:%M %p')} - {end_dt.strftime('%-I:%M %p')}"
                    except:
                        display_text = f"{slot.get('startTime')} - {slot.get('endTime')}"

                    available_slots_for_ui.append({
                        "id": str(slot.get("id")),
                        "display_text": display_text
                    })
            logger.info(f"Found {len(available_slots_for_ui)} available slots for UI.")
            if not available_slots_for_ui: return {"status": "no_slots_found", "slots": [],
                                                   "message_for_user": f"Sorry, no available slots found for Dr. ID {doctor_id} on {date}."}
            return {"status": "success", "slots": available_slots_for_ui}
        else:
            return {"status": "error",
                    "message": f"Failed to get slots: {response.status_code} - {response.text[:100]}"}
    except Exception as e:
        return {"status": "error", "message": f"Slot fetch exception: {e}"}


def schedule_appointment(patient_id: str, slot_id: str, reason: Optional[str] = "general-checkup") -> Dict[str, Any]:
    logger.info(f"🛠️ Tool Called: schedule_appointment(patient_id={patient_id}, slot_id={slot_id}, reason={reason})")
    params = {"patientId": patient_id, "slotId": int(slot_id)}
    if reason:
        params["reason"] = reason
    else:
        params["reason"] = "general-checkup"
    try:
        url = f"{APPOINTMENT_SERVICE_V1_URL}/appointments"
        logger.info(f"📞 Calling Appointment Service: POST {url} with query params: {params}")
        response = requests.post(url, params=params, timeout=7)
        logger.info(f"Appointment Service Schedule Response: {response.status_code}, Body: {response.text[:200]}")
        if response.status_code == 200 or response.status_code == 201:
            try:
                booking_details = response.json()
                appt_id = str(booking_details.get("id"))
                return {"status": "booked", "appointment_id": appt_id, "details": booking_details,
                        "message_for_user": f"Your appointment (ID: {appt_id}) is confirmed!"}
            except json.JSONDecodeError:
                logger.error("Could not decode JSON from successful booking response.")
                return {"status": "booked", "appointment_id": "UNKNOWN_BOOKING_ID",
                        "message_for_user": "Appointment booked, but confirmation details are unclear."}
        else:
            return {"status": "error", "message": f"Booking failed: {response.status_code} - {response.text[:100]}"}
    except Exception as e:
        return {"status": "error", "message": f"Booking exception: {e}"}


def get_patient_upcoming_appointments(patient_id: str) -> Dict[str, Any]:
    logger.info(f"🛠️ Tool Called: get_patient_upcoming_appointments(patient_id={patient_id})")
    try:
        url = f"{APPOINTMENT_SERVICE_V1_URL}/upcomingByPatientId"
        params = {"patientId": patient_id}
        logger.info(f"📞 Calling Appointment Service: GET {url} with params {params}")
        response = requests.get(url, params=params, timeout=7)
        logger.info(
            f"Appointment Service Get Upcoming (by PatientId) Response: {response.status_code}, Body: {response.text[:300]}")
        if response.status_code == 200:
            patient_appointments = response.json()
            if not patient_appointments:
                logger.info(f"No upcoming appointments found for patient {patient_id} via specific endpoint.")
                return {"status": "no_appointments_found", "appointments": []}
            logger.info(f"Found {len(patient_appointments)} upcoming appointments for patient {patient_id}.")
            return {"status": "success", "appointments": patient_appointments}
        elif response.status_code == 404:
            logger.info(f"No upcoming appointments found (404) for patient {patient_id} via specific endpoint.")
            return {"status": "no_appointments_found", "appointments": []}
        else:
            return {"status": "error",
                    "message": f"Failed to get upcoming appointments: {response.status_code} - {response.text[:100]}"}
    except requests.RequestException as e:
        logger.error(f"Connection error calling upcoming appointments service: {e}")
        return {"status": "error", "message": f"Connection error with upcoming appointments service: {e}"}
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from upcoming appointments service: {e}")
        return {"status": "error", "message": "Received invalid data format from upcoming appointments service."}


def cancel_appointment(appointment_id: str) -> Dict[str, Any]:
    logger.info(f"🛠️ Tool Called: cancel_appointment(appointment_id={appointment_id})")
    try:
        clean_appointment_id = str(int(float(str(appointment_id))))
        url = f"{APPOINTMENT_SERVICE_V1_URL}/appointments/{clean_appointment_id}"
        response = requests.delete(url, timeout=7)
        logger.info(f"Appointment Service Cancel Response: {response.status_code}")
        if response.status_code in [200, 204]:
            return {"status": "cancelled",
                    "message_for_user": f"Appointment ID {clean_appointment_id} has been cancelled."}
        else:
            return {"status": "error",
                    "message": f"Cancellation failed: {response.status_code} - {response.text[:100]}"}
    except ValueError:
        logger.error(f"Invalid appointment_id format for cancellation: {appointment_id}")
        return {"status": "error", "message": "Invalid appointment ID format."}
    except Exception as e:
        return {"status": "error", "message": f"Cancellation exception: {e}"}


# ------------------------------------------------------------------------------
# Gemini Tool Configuration
# ------------------------------------------------------------------------------
TOOLS_CONFIG_LIST = Tool(
    function_declarations=[
        FunctionDeclaration(name="save_patient_details_in_session",
                            description="Saves patient details (name, email, phone, gender, birthDate, address, doctor_id, preferred_date) to session.",
                            parameters={"type": "OBJECT",
                                        "properties": {"name": {"type": "STRING"}, "email": {"type": "STRING"},
                                                       "phone": {"type": "STRING"}, "gender": {"type": "STRING"},
                                                       "birthDate": {"type": "STRING"},
                                                       "address_line": {"type": "STRING"},
                                                       "address_city": {"type": "STRING"},
                                                       "address_country": {"type": "STRING"},
                                                       "doctor_id": {"type": "STRING"},
                                                       "preferred_date": {"type": "STRING"}}}),
        FunctionDeclaration(name="validate_or_identify_patient",
                            description="Validates patient with name, email, or phone (needs at least two). Returns patientId if found.",
                            parameters={"type": "OBJECT",
                                        "properties": {"name": {"type": "STRING"}, "email": {"type": "STRING"},
                                                       "phone": {"type": "STRING"}}}),
        FunctionDeclaration(name="register_new_patient",
                            description="Registers a new patient. Requires name, email, phone. Optional: gender, birthDate, address.",
                            parameters={"type": "OBJECT",
                                        "properties": {"name": {"type": "STRING"}, "email": {"type": "STRING"},
                                                       "phone": {"type": "STRING"}, "gender": {"type": "STRING"},
                                                       "birthDate": {"type": "STRING"},
                                                       "address_line": {"type": "STRING"},
                                                       "address_city": {"type": "STRING"},
                                                       "address_country": {"type": "STRING"}},
                                        "required": ["name", "email", "phone"]}),
        FunctionDeclaration(name="list_available_doctors",
                            description="Lists available doctors. Use if the user doesn't specify a doctor or asks for options.",
                            parameters={"type": "OBJECT", "properties": {}}),
        FunctionDeclaration(name="get_doctor_available_slots",
                            description="Gets available slots for a doctor_id and date (YYYY-MM-DD).",
                            parameters={"type": "OBJECT", "properties": {"doctor_id": {"type": "STRING"},
                                                                         "date": {"type": "STRING",
                                                                                  "description": "Date in<y_bin_46>-MM-DD format."}},
                                        "required": ["doctor_id", "date"]}),
        FunctionDeclaration(name="schedule_appointment",
                            description="Schedules an appointment. Requires patient_id, slot_id, and reason for visit.",
                            parameters={"type": "OBJECT",
                                        "properties": {"patient_id": {"type": "STRING"}, "slot_id": {"type": "STRING"},
                                                       "reason": {"type": "STRING",
                                                                  "description": "Reason for the visit, e.g., general-checkup, follow-up."}},
                                        "required": ["patient_id", "slot_id", "reason"]}),
        FunctionDeclaration(name="get_patient_upcoming_appointments",
                            description="Gets upcoming appointments for an identified patient. Requires patient_id.",
                            parameters={"type": "OBJECT", "properties": {"patient_id": {"type": "STRING"}},
                                        "required": ["patient_id"]}),
        FunctionDeclaration(name="cancel_appointment",
                            description="Cancels an existing appointment using its ID. Requires appointment_id.",
                            parameters={"type": "OBJECT", "properties": {"appointment_id": {"type": "STRING"}},
                                        "required": ["appointment_id"]}),
    ]
)

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

MODEL_CONFIG = genai.GenerationConfig(temperature=0.5)
SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
}

gemini_model = genai.GenerativeModel(
    model_name="gemini-1.5-flash-latest",
    system_instruction=SYSTEM_PROMPT,
    generation_config=MODEL_CONFIG,
    safety_settings=SAFETY_SETTINGS,
    tools=[TOOLS_CONFIG_LIST]
)


# ------------------------------------------------------------------------------
# Helper Function to Convert Gemini Content to Dict
# ------------------------------------------------------------------------------
def content_to_dict(content_obj) -> Dict[str, Any]:
    if isinstance(content_obj, dict):
        if "parts" in content_obj and isinstance(content_obj["parts"], list):
            new_parts = []
            for p_item in content_obj["parts"]:
                if isinstance(p_item, dict):
                    new_parts.append(p_item)
                else:
                    part_conv = {}
                    if hasattr(p_item, 'text') and p_item.text is not None:
                        part_conv["text"] = p_item.text
                    elif hasattr(p_item, 'function_call'):
                        part_conv["function_call"] = {"name": p_item.function_call.name,
                                                      "args": dict(p_item.function_call.args)}
                    elif hasattr(p_item, 'function_response'):
                        part_conv["function_response"] = {"name": p_item.function_response.name,
                                                          "response": dict(p_item.function_response.response)}
                    if part_conv: new_parts.append(part_conv)
            content_obj["parts"] = new_parts
        return content_obj

    role = getattr(content_obj, 'role', "model")
    parts_list = []
    if hasattr(content_obj, 'parts'):
        for part_content in content_obj.parts:
            part_dict = {}
            if hasattr(part_content, 'function_call') and part_content.function_call:
                part_dict["function_call"] = {"name": part_content.function_call.name,
                                              "args": dict(part_content.function_call.args)}
            elif hasattr(part_content, 'function_response') and part_content.function_response:
                part_dict["function_response"] = {"name": part_content.function_response.name,
                                                  "response": dict(part_content.function_response.response)}
            elif hasattr(part_content, 'text') and part_content.text is not None:
                part_dict["text"] = part_content.text

            if part_dict:
                parts_list.append(part_dict)
            elif isinstance(part_content, dict):
                parts_list.append(part_content)
            else:
                logger.debug(
                    f"content_to_dict: Part had no extractable content: {type(part_content)}, content: {part_content}")
    return {"role": role, "parts": parts_list}


# ------------------------------------------------------------------------------
# FastAPI App & Endpoints
# ------------------------------------------------------------------------------
app = FastAPI(title="AI Appointment Agent - MedX Dynamic (Greeting with Quick Replies)", version="2.23")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"],
                   allow_headers=["*"])


class StartSessionResponse(BaseModel): session_id: str


class MessageRequest(BaseModel): message: str


class MessageResponse(BaseModel):
    reply: str
    quick_replies: Optional[List[str]] = None
    required_fields: Optional[List[Dict[str, str]]] = None
    appointment_slots: Optional[List[Dict[str, str]]] = None
    available_doctors: Optional[List[Dict[str, str]]] = None
    required_input: Optional[Dict[str, str]] = None
    session_data_debug: Optional[Dict] = None


@app.get("/health")
async def health(): return {"status": "ok", "patient_v1": PATIENT_SERVICE_V1_URL,
                            "appointment_v1": APPOINTMENT_SERVICE_V1_URL}


@app.post("/session/start", response_model=StartSessionResponse)
async def start_session_endpoint():
    sid = str(uuid.uuid4())
    _save_session(sid, {"data": {"conversation_state": "initial_greeting"}, "history": []})
    logger.info(f"🚀 Session {sid} started, state set to initial_greeting")
    return {"session_id": sid}


@app.post("/session/{sid}/message", response_model=MessageResponse)
async def chat_endpoint(sid: str, msg: MessageRequest):
    logger.info(f"← User ({sid}): {msg.message}")
    try:
        sess = _load_session(sid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")

    current_session_data: Dict[str, Any] = sess.get("data", {})
    chat_history: List[Dict[str, Any]] = sess.get("history", [])

    if current_session_data.get("conversation_state") == "initial_greeting":
        final_reply_to_user = "Hi, I am MedX AI assistant. How can I help you today?"
        initial_quick_replies = ["Book new appointment", "Check upcoming appointments", "Cancel appointment"]
        logger.info(f" saluto Bot ({sid}): {final_reply_to_user} with QRs: {initial_quick_replies}")

        chat_history.append(content_to_dict({"role": "user", "parts": [{"text": msg.message}]}))
        chat_history.append(content_to_dict({"role": "model", "parts": [{"text": final_reply_to_user}]}))
        current_session_data["conversation_state"] = "active_conversation"
        _save_session(sid, {"data": current_session_data, "history": chat_history})

        # No LLM tags to parse for this hardcoded greeting, so other UI fields are None
        return MessageResponse(
            reply=final_reply_to_user,
            quick_replies=initial_quick_replies,  # Directly set quick replies
            required_fields=None,
            appointment_slots=None,
            available_doctors=None,
            required_input=None,
            session_data_debug=current_session_data if os.getenv("DEBUG_MODE") == "true" else None
        )

    chat_history.append(content_to_dict({"role": "user", "parts": [{"text": msg.message}]}))

    MAX_TURNS, turn_count = 8, 0
    final_reply_to_user = ""
    current_date_str = datetime_date.today().strftime("%Y-%m-%d")

    while turn_count < MAX_TURNS:
        turn_count += 1
        logger.info(
            f"🔄 Turn {turn_count} for {sid}. History items: {len(chat_history)}. Session Data: {current_session_data}. Today is: {current_date_str}")

        temp_history_for_this_turn = [content_to_dict(item) for item in chat_history]

        directive_prompt_text = ""
        last_tool_name_called_by_llm = None
        last_tool_status = None

        if len(chat_history) >= 2:
            for i in range(len(chat_history) - 1, 0, -1):
                current_hist_item = chat_history[i]
                prev_hist_item = chat_history[i - 1]
                if current_hist_item.get("role") == "tool" and \
                        prev_hist_item.get("role") == "model" and \
                        prev_hist_item.get("parts") and prev_hist_item["parts"][0].get("function_call"):
                    last_tool_name_called_by_llm = prev_hist_item["parts"][0]["function_call"].get("name")
                    tool_response_part = current_hist_item.get("parts", [{}])[0].get("function_response", {})
                    last_tool_status = tool_response_part.get("response", {}).get("status")
                    if last_tool_name_called_by_llm == "list_available_doctors" and last_tool_status == "success":
                        current_session_data["last_doctors_list"] = tool_response_part.get("response", {}).get(
                            "doctors")
                    elif last_tool_name_called_by_llm == "get_doctor_available_slots" and last_tool_status == "success":
                        current_session_data["last_slots_list"] = tool_response_part.get("response", {}).get("slots")
                    break

        logger.info(f"Last tool called by LLM: {last_tool_name_called_by_llm}, status: {last_tool_status}")

        if last_tool_name_called_by_llm == "save_patient_details_in_session" and last_tool_status == "details_noted_in_session":
            identifiers_present = {k: v for k, v in current_session_data.items() if
                                   k in ["name", "email", "phone"] and v}
            if len(identifiers_present) >= 2:
                directive_prompt_text = (
                    f"Current session data (after saving): {json.dumps(current_session_data)}. Today's date is {current_date_str}. "
                    "You have just successfully saved patient details. "
                    f"The following identifiers are now available: {json.dumps(identifiers_present)}. "
                    "As per your CRITICAL VALIDATION SEQUENCE, your ONLY NEXT ACTION is to call the `validate_or_identify_patient` tool using these details. "
                    "Do not ask any questions. Call `validate_or_identify_patient` now."
                )
            else:
                directive_prompt_text = (
                    f"Current session data (after saving): {json.dumps(current_session_data)}. Today's date is {current_date_str}. "
                    "You have saved some patient details, but not enough for validation yet (need at least two of name, email, phone). "
                    "Please ask the user for the specific missing information required for validation. Use the [required_fields:...] tag."
                )
        elif last_tool_name_called_by_llm == "validate_or_identify_patient":
            if last_tool_status == "found":
                directive_prompt_text = (
                    f"Current session data (after validation 'found', patient_id is '{current_session_data.get('patient_id')}'): {json.dumps(current_session_data)}. Today's date is {current_date_str}. "
                    "Patient validation was successful and record found. Inform the user. "
                    "Now, proceed with the original appointment booking intent (e.g., ask about preferred doctor or date)."
                )
            elif last_tool_status == "not_found":
                directive_prompt_text = (
                    f"Current session data (after validation 'not_found'): {json.dumps(current_session_data)}. Today's date is {current_date_str}. "
                    "Patient validation indicated the record was not found. Inform the user. "
                    "Now, ask the user if they would like to register as a new patient. You can suggest quick replies [quick_replies: Yes, register me, No, not now]."
                )
            else:
                directive_prompt_text = (
                    f"Current session data (after validation attempt with status '{last_tool_status}'): {json.dumps(current_session_data)}. Today's date is {current_date_str}. "
                    "Inform the user about the validation outcome and ask how they'd like to proceed or if they want to try again."
                )
        elif "cancel" in msg.message.lower() and "patient_id" in current_session_data and current_session_data.get(
                "patient_id"):
            directive_prompt_text = (
                f"Current session data: {json.dumps(current_session_data)}. Today's date is {current_date_str}. "
                "The user wants to cancel an appointment and their patient_id is known. "
                "Your next action is to call `get_patient_upcoming_appointments` to fetch their appointments before asking for an appointment ID."
            )
        else:
            directive_prompt_text = (
                f"Current session data: {json.dumps(current_session_data)}. Today's date is {current_date_str}. "
                "Considering this data and the full conversation history, what is your next user-facing response, "
                "or which tool should you call next according to your instructions in the system prompt? "
                "If a tool was just called, analyze its result and formulate the next user message or tool call. "
                "Ensure you always provide a textual response to the user eventually."
            )

        temp_history_for_this_turn.append({"role": "user", "parts": [{"text": directive_prompt_text}]})
        logger.debug(f"History for Gemini (Turn {turn_count}): {json.dumps(temp_history_for_this_turn, indent=2)}")

        try:
            chat_session = gemini_model.start_chat(history=temp_history_for_this_turn)
            response = chat_session.send_message(" ")

            if not response.candidates:
                logger.error(f"🚨 Gemini returned no candidates for {sid} on turn {turn_count}.")
                final_reply_to_user = "I'm having trouble processing. Could you try again?"
                chat_history.append(content_to_dict({"role": "model", "parts": [{"text": final_reply_to_user}]}))
                break

            candidate = response.candidates[0]
            logger.debug(
                f"Gemini candidate for {sid} (Turn {turn_count}): Finish: {candidate.finish_reason.name}, Content: {candidate.content}")

            gemini_response_content_dict = content_to_dict(candidate.content)
            chat_history.append(gemini_response_content_dict)

            tool_call_executed_this_turn = False
            tool_results_for_history = []

            if gemini_response_content_dict.get("parts"):
                for part_data_dict in gemini_response_content_dict["parts"]:
                    if "function_call" in part_data_dict:
                        tool_call_executed_this_turn = True
                        fc_dict = part_data_dict["function_call"]
                        func_name, args = fc_dict["name"], fc_dict["args"]
                        logger.info(f"🤖 Gemini wants to call: {func_name}({args})")

                        if func_name == "cancel_appointment" and "appointment_id" in args:
                            try:
                                args["appointment_id"] = str(int(float(str(args["appointment_id"]))))
                                logger.info(f"Sanitized appointment_id for cancel: {args['appointment_id']}")
                            except ValueError:
                                logger.error(
                                    f"Could not convert appointment_id '{args['appointment_id']}' to int/str for cancellation.")
                                result = {"status": "error",
                                          "message": "Invalid appointment ID format for cancellation."}
                                tool_results_for_history.append(
                                    {"function_response": {"name": func_name, "response": result}})
                                continue

                        if func_name in AVAILABLE_PYTHON_TOOLS:
                            python_func = AVAILABLE_PYTHON_TOOLS[func_name]
                            if "patient_id" in python_func.__code__.co_varnames and \
                                    "patient_id" not in args and \
                                    "patient_id" in current_session_data and \
                                    current_session_data["patient_id"] is not None:
                                args["patient_id"] = current_session_data["patient_id"]

                            result = python_func(**args)
                            logger.info(f"🛠️ Tool {func_name} result: {result}")

                            if func_name == "save_patient_details_in_session":
                                current_session_data.update(result.get("updated_fields", {}))
                            elif func_name == "validate_or_identify_patient":
                                current_session_data["last_validation_status"] = result.get("status")
                                if result.get("status") == "found" and result.get("patient_id"):
                                    current_session_data["patient_id"] = result.get("patient_id")
                                    logger.info(
                                        f"Patient ID {result.get('patient_id')} stored in session from validation.")
                            elif func_name == "register_new_patient" and result.get("status") == "registered":
                                current_session_data["patient_id"] = result.get("patient_id")
                                logger.info(
                                    f"Patient ID {result.get('patient_id')} stored in session from registration.")

                            if func_name == "list_available_doctors" and result.get("status") == "success":
                                current_session_data["last_doctors_list"] = result.get("doctors")
                            elif func_name == "get_doctor_available_slots" and result.get("status") == "success":
                                current_session_data["last_slots_list"] = result.get("slots")

                            tool_results_for_history.append(
                                {"function_response": {"name": func_name, "response": result}})
                        else:
                            logger.error(f"Tool {func_name} not found.")
                            tool_results_for_history.append({"function_response": {"name": func_name,
                                                                                   "response": {"status": "error",
                                                                                                "message": "Tool not found."}}})

            if tool_call_executed_this_turn:
                if tool_results_for_history:
                    chat_history.append({"role": "tool", "parts": tool_results_for_history})
                continue

            if candidate.finish_reason.name in ["STOP", "MAX_TOKENS"]:
                text_reply_found = False
                if gemini_response_content_dict.get("parts"):
                    parts_list = gemini_response_content_dict["parts"]
                    if parts_list and isinstance(parts_list, list) and len(parts_list) > 0:
                        first_part = parts_list[0]
                        if isinstance(first_part, dict) and first_part.get("text") and first_part["text"].strip():
                            final_reply_to_user = first_part["text"].strip()
                            text_reply_found = True

                if text_reply_found:
                    logger.info(f"🤖 Gemini final text reply for {sid}: {final_reply_to_user}")
                else:
                    final_reply_to_user = "Okay, I've processed that. How else can I assist you today?"
                    logger.warning(
                        f"Gemini STOP/MAX_TOKENS but no usable text in parts for {sid}. Raw Content: {candidate.content}, Dict: {gemini_response_content_dict}")
                break
            elif candidate.finish_reason.name == "TOOL_CALLS" and not tool_call_executed_this_turn:
                logger.warning(
                    f"Gemini indicated TOOL_CALLS but no function_call was processed for {sid}. Content: {candidate.content}")
                final_reply_to_user = "I tried to perform an action but encountered an issue. Could you please try again?"
                break
            else:
                logger.error(
                    f"🚨 Unhandled finish: {candidate.finish_reason.name} for {sid}. Content: {candidate.content}")
                final_reply_to_user = "I'm not sure how to proceed from here. Can you clarify?"
                break

        except Exception as e:
            logger.exception(f"💥 Exception in chat loop for {sid} (Turn {turn_count}): {e}")
            final_reply_to_user = "An internal error occurred. Please try again later."
            chat_history.append(
                content_to_dict({"role": "model", "parts": [{"text": "Internal error during processing."}]}))
            break

    if not final_reply_to_user:
        if turn_count >= MAX_TURNS:
            logger.warning(f"Max turns reached for session {sid}.")
            final_reply_to_user = "We seem to be going in circles. Could you please restate your request clearly?"
        else:
            logger.warning(f"Loop for {sid} ended with no final reply. Fallback.")
            final_reply_to_user = "Is there anything else I can assist with?"

        needs_fallback_in_history = True
        if chat_history:
            last_history_item = chat_history[-1]
            if last_history_item.get("role") == "model":
                if last_history_item.get("parts") and last_history_item["parts"][0].get("text", "").strip():
                    needs_fallback_in_history = False

        if needs_fallback_in_history:
            chat_history.append(content_to_dict({"role": "model", "parts": [{"text": final_reply_to_user}]}))

    # Parse all UI tags from the final_reply_to_user
    quick_replies_list, required_fields_list, display_doctors_flag, display_slots_flag, required_input_dict, final_reply_to_user = parse_ui_tags(
        final_reply_to_user)

    response_payload = MessageResponse(reply=final_reply_to_user)
    if quick_replies_list: response_payload.quick_replies = quick_replies_list
    if required_fields_list: response_payload.required_fields = required_fields_list
    if required_input_dict: response_payload.required_input = required_input_dict

    if display_doctors_flag and current_session_data.get("last_doctors_list"):
        response_payload.available_doctors = current_session_data.get("last_doctors_list")
    if display_slots_flag and current_session_data.get("last_slots_list"):
        response_payload.appointment_slots = current_session_data.get("last_slots_list")

    if os.getenv("DEBUG_MODE") == "true":
        response_payload.session_data_debug = current_session_data

    logger.info(f"→ Bot ({sid}): {response_payload.reply}")
    if response_payload.quick_replies: logger.info(f"  Quick Replies: {response_payload.quick_replies}")
    if response_payload.required_fields: logger.info(f"  Required Fields: {response_payload.required_fields}")
    if response_payload.required_input: logger.info(f"  Required Input: {response_payload.required_input}")
    if response_payload.available_doctors: logger.info(
        f"  Available Doctors: {len(response_payload.available_doctors)} to display")
    if response_payload.appointment_slots: logger.info(
        f"  Appointment Slots: {len(response_payload.appointment_slots)} to display")

    _save_session(sid, {"data": current_session_data, "history": chat_history})
    return response_payload


def parse_ui_tags(text: str) -> (
Optional[List[str]], Optional[List[Dict[str, str]]], bool, bool, Optional[Dict[str, str]], str):
    """Parses all UI tags from text and returns them + cleaned text."""
    cleaned_text = text

    quick_reply_list = None
    qr_match = re.search(r"\[quick_replies:\s*(.+?)\s*\]", cleaned_text)
    if qr_match:
        suggestions_str = qr_match.group(1)
        quick_reply_list = [s.strip() for s in suggestions_str.split(',')]
        cleaned_text = re.sub(r"\[quick_replies:\s*(.+?)\s*\]", "", cleaned_text).strip()

    required_fields_list = None
    rf_match = re.search(r"\[required_fields:\s*(.+?)\s*\]", cleaned_text)
    if rf_match:
        fields_str = rf_match.group(1)
        required_fields_list = []
        field_definitions = [f.strip() for f in fields_str.split(',')]
        for fd_str in field_definitions:
            parts = [p.strip() for p in fd_str.split('|')]
            if len(parts) == 4:
                required_fields_list.append(
                    {"name": parts[0], "label": parts[1], "type": parts[2], "placeholder": parts[3]})
            else:
                logger.warning(f"Malformed required_field definition: {fd_str}")
        cleaned_text = re.sub(r"\[required_fields:\s*(.+?)\s*\]", "", cleaned_text).strip()

    required_input_dict = None
    ri_match = re.search(r"\[required_input:\s*(.+?)\s*\]", cleaned_text)
    if ri_match:
        input_str = ri_match.group(1)
        parts = [p.strip() for p in input_str.split('|')]
        if len(parts) == 3:
            required_input_dict = {"type": parts[0], "label": parts[1], "submit_message_prefix": parts[2]}
        else:
            logger.warning(f"Malformed required_input definition: {input_str}")
        cleaned_text = re.sub(r"\[required_input:\s*(.+?)\s*\]", "", cleaned_text).strip()

    display_doctors_flag = False
    if "[display_doctors]" in cleaned_text:
        display_doctors_flag = True
        cleaned_text = cleaned_text.replace("[display_doctors]", "").strip()

    display_slots_flag = False
    if "[display_slots]" in cleaned_text:
        display_slots_flag = True
        cleaned_text = cleaned_text.replace("[display_slots]", "").strip()

    return quick_reply_list, required_fields_list, display_doctors_flag, display_slots_flag, required_input_dict, cleaned_text.strip()


if __name__ == "__main__":
    import uvicorn

    logger.info(f"AI Agent (MedX Dynamic v2.22 - Required Input UI Hint) starting on port 8083.")
    uvicorn.run(app, host="0.0.0.0", port=8083)

