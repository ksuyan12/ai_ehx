import json
from datetime import date
from typing import Dict, Any, List, Optional, Tuple
import re

try:
    from models.session_models import SessionData
except ImportError:
    SessionData = dict

STANDARD_QUICK_REPLIES = "[quick_replies: Book new appointment, Check upcoming appointments, Cancel appointment, No thanks]"
POST_NO_APPOINTMENTS_TO_CANCEL_QUICK_REPLIES = "[quick_replies: Book new appointment, Check upcoming appointments, No thanks]"
CONFIRM_BOOKING_QUICK_REPLIES = "[quick_replies: Yes, confirm booking, No, change details]"  # <-- NEW


def get_last_tool_info(history: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str], Optional[Dict]]:
    last_tool_name: Optional[str] = None
    last_tool_status: Optional[str] = None
    last_tool_result: Optional[Dict] = None
    for i in range(len(history) - 1, 0, -1):
        current_item = history[i]
        prev_item = history[i - 1]
        if (current_item.get("role") == "tool" and
                prev_item.get("role") == "model" and
                prev_item.get("parts") and
                isinstance(prev_item["parts"], list) and len(prev_item["parts"]) > 0 and
                prev_item["parts"][0].get("function_call")):
            called_tool_name = prev_item["parts"][0]["function_call"].get("name")
            tool_parts = current_item.get("parts", [])
            if tool_parts:
                response_part = tool_parts[0].get("function_response", {})
                if response_part.get("name") == called_tool_name:
                    last_tool_name = called_tool_name
                    last_tool_result = response_part.get("response", {})
                    last_tool_status = last_tool_result.get("status")
            break
    return last_tool_name, last_tool_status, last_tool_result


def get_last_model_text(history: List[Dict[str, Any]]) -> Optional[str]:
    for i in range(len(history) - 1, -1, -1):
        item = history[i]
        if item.get("role") == "model":
            parts = item.get("parts", [])
            for part in parts:
                if "text" in part and part["text"]:
                    return part["text"]
    return None


def build_directive_prompt(
        session_data: SessionData,
        history: List[Dict[str, Any]],
        user_message: str
) -> str:
    current_date_str = date.today().strftime("%Y-%m-%d")
    # Use .dict() for SessionData if it's a Pydantic model, otherwise assume it's already a dict
    session_dict = session_data.dict(exclude_none=True) if hasattr(session_data, 'dict') else session_data
    session_json = json.dumps(session_dict)

    last_tool_name, last_tool_status, last_tool_result = get_last_tool_info(history)
    last_model_message = get_last_model_text(history)
    user_msg_lower = user_message.lower().strip()

    # --- INTENT DETECTION AND HIGH-PRIORITY ACTIONS ---
    if user_msg_lower == "no thanks" or \
            (user_msg_lower == "no" and "cancel this one?" in (last_model_message or "").lower()) or \
            (user_msg_lower == "no" and "would you like to register?" in (last_model_message or "").lower()) or \
            (user_msg_lower == "no" and "Is this correct?" in (
                    last_model_message or "")):  # Handles "No" to booking confirmation
        action = ""
        if session_data.current_intent == "book" and "Is this correct?" in (last_model_message or ""):
            # If they said no to booking confirmation, ask what to change
            action += "User wants to change booking details. Call `save_patient_details_in_session(preferred_date='None', selected_slot_id='None', selected_slot_text='None', visit_reason='None')`. Then ask 'Okay, what would you like to change? (e.g., date, time, or reason)'"
        else:
            if session_data.current_intent is not None or session_data.appointment_id_to_cancel is not None:
                action += "First, call `save_patient_details_in_session(current_intent='None', appointment_id_to_cancel='None')` to clear state. "
            action += "After that, your response to the user MUST be a polite goodbye (e.g., 'Okay, have a great day!'). Do NOT ask anything else."
        return (
            f"Current session data: {session_json}. Today: {current_date_str}. "
            f"User declined further action or a confirmation. {action}"
        )

    new_intent_detected = None
    # ... (keep your existing intent detection for book, check, cancel) ...
    if user_msg_lower == "book new appointment":
        new_intent_detected = "book"
    elif user_msg_lower == "check upcoming appointments":
        new_intent_detected = "check"
    elif "cancel" in user_msg_lower and (
            "appointment" in user_msg_lower or "it" in user_msg_lower or "booking" in user_msg_lower or user_msg_lower == "cancel"):
        new_intent_detected = "cancel"

    if new_intent_detected:
        if session_data.current_intent != new_intent_detected:
            # When a new intent is detected, clear previous booking/cancellation specifics
            clear_fields = {
                "current_intent": new_intent_detected,
                "appointment_id_to_cancel": "None",
                "selected_slot_id": "None",
                "selected_slot_text": "None",
                "visit_reason": "None",
            }
            # If not booking, also clear doctor/date
            if new_intent_detected != "book":
                clear_fields["doctor_id"] = "None"
                clear_fields["doctor_name_display"] = "None"
                clear_fields["preferred_date"] = "None"

            return (
                f"Current session data: {session_json}. Today: {current_date_str}. "
                f"User expressed new intent '{new_intent_detected}'. "
                f"Your first action: call `save_patient_details_in_session({json.dumps(clear_fields)})`. "
                "The next prompt will guide based on this intent (e.g., identify or start task)."
            )

    # --- BOOKING FLOW SPECIFIC LOGIC ---
    if session_data.current_intent == "book":
        # After user selects a slot from UI/text (and it's saved by LLM)
        # We expect user_message to be the reason, or a confirmation if reason was just saved.
        if session_data.doctor_id and session_data.preferred_date and \
                session_data.selected_slot_id and session_data.selected_slot_text and \
                not session_data.visit_reason and \
                last_tool_name == "save_patient_details_in_session" and \
                last_tool_result and last_tool_result.get("updated_fields", {}).get("selected_slot_id") is not None:
            return (  # Ask for reason
                f"Current session data: {session_json}. Today: {current_date_str}. Intent is 'book'. "
                f"Doctor '{session_data.doctor_name_display}', Date '{session_data.preferred_date}', Slot '{session_data.selected_slot_text}' are selected. "
                "Now, ask the user: 'Perfect. Could you please briefly describe the reason for your visit?' "
                "You can suggest `[required_input: text|Reason for visit|Reason: ]`."
            )

        # After user provides reason (and it's saved by LLM) -> Ask for confirmation
        if session_data.doctor_id and session_data.preferred_date and \
                session_data.selected_slot_id and session_data.selected_slot_text and \
                session_data.visit_reason and \
                (last_tool_name == "save_patient_details_in_session" and \
                 last_tool_result and last_tool_result.get("updated_fields", {}).get("visit_reason") is not None):
            doc_name = session_data.doctor_name_display or f"Doctor ID {session_data.doctor_id}"
            return (
                f"Current session data: {session_json}. Today: {current_date_str}. Intent is 'book'. "
                "All booking details (doctor, date, slot, reason) are gathered. "
                f"Your response to the user MUST be: 'Okay, to confirm: you'd like to book an appointment with {doc_name} on {session_data.preferred_date} at {session_data.selected_slot_text} for: \"{session_data.visit_reason}\". Is this correct?' "
                f"Use quick replies: {CONFIRM_BOOKING_QUICK_REPLIES}."
            )

        # User confirms booking (e.g., user_message is "yes, confirm booking")
        if user_msg_lower == "yes, confirm booking" and \
                session_data.doctor_id and session_data.preferred_date and \
                session_data.selected_slot_id and session_data.visit_reason and \
                last_model_message and "Is this correct?" in last_model_message:  # Check if last question was confirmation
            return (
                f"Current session data: {session_json}. Today: {current_date_str}. Intent is 'book'. "
                "User confirmed booking details. "
                f"Call `schedule_appointment(patient_id='{session_data.patient_id}', slot_id='{session_data.selected_slot_id}', reason='{session_data.visit_reason}')`."
            )

        # User wants to change details (e.g., user_message is "no, change details")
        # This is now handled by the "no thanks / no" block at the top for simplicity if last_model_message was "Is this correct?"
        # We can add a more specific one if needed:
        # elif user_msg_lower == "no, change details" and last_model_message and "Is this correct?" in last_model_message:
        #    return ( ... )

        # After user selects a date (tool `save_patient_details_in_session` for preferred_date ran), get slots
        if session_data.doctor_id and session_data.preferred_date and \
                not session_data.selected_slot_id and \
                last_tool_name == "save_patient_details_in_session" and \
                last_tool_result and last_tool_result.get("updated_fields", {}).get("preferred_date") is not None:
            return (
                f"Current session data: {session_json}. Today: {current_date_str}. Intent is 'book'. "
                f"Doctor ID {session_data.doctor_id} and date {session_data.preferred_date} are selected. "
                f"Call `get_doctor_available_slots(doctor_id='{session_data.doctor_id}', date='{session_data.preferred_date}')`."
            )

        # After listing doctors (tool `list_available_doctors` ran), user provides selection (e.g., "select_doctor_101")
        if last_tool_name == "list_available_doctors" and last_tool_status == "success" and user_msg_lower.startswith(
                "select_doctor_"):
            try:
                selected_id = user_message.split('_')[-1]
                # We need last_doctors_list from session_data now
                selected_doctor_info = next((doc for doc in session_data.last_doctors_list if doc['id'] == selected_id),
                                            None) if session_data.last_doctors_list else None
                if selected_doctor_info:
                    return (
                        f"Current session data: {session_json}. Today: {current_date_str}. Intent is 'book'. "
                        f"User selected doctor ID {selected_id} ('{selected_doctor_info['display_text']}'). "
                        f"Call `save_patient_details_in_session(doctor_id='{selected_id}', doctor_name_display='{selected_doctor_info['display_text']}')`."
                    )
            except Exception:
                pass

            # If intent is book, patient identified, but no doctor chosen yet and list_doctors hasn't just run
        if session_data.patient_id and not session_data.doctor_id and last_tool_name != "list_available_doctors":
            return (
                f"Current session data: {session_json}. Today: {current_date_str}. Intent 'book'. Patient identified. "
                "Ask for doctor preference or list available doctors by calling `list_available_doctors`."
            )

    # --- COMMON STATE HANDLING & OTHER INTENTS ---

    # After 'save_patient_details_in_session' (catch-all for other scenarios, e.g. identification details)
    if last_tool_name == "save_patient_details_in_session" and last_tool_status == "details_noted_in_session":
        # If an explicit intent is set, and identification is needed
        if not session_data.patient_id and session_data.current_intent in ["book", "check", "cancel"]:
            return (
                f"Current session data: {session_json}. Intent '{session_data.current_intent}'. Patient NOT identified. Ask for identification [required_fields:...].")

        # If intent was just set to check/cancel and patient IS identified, trigger get_appointments
        if session_data.patient_id and session_data.current_intent in ["check", "cancel"] and \
                last_tool_result and last_tool_result.get("updated_fields", {}).get("current_intent") in ["check",
                                                                                                          "cancel"]:
            return (
                f"Current session data: {session_json}. Intent '{session_data.current_intent}'. Patient identified. Call `get_patient_upcoming_appointments`.")

        # If intent was just set to book and patient IS identified, trigger doctor listing/preference
        if session_data.patient_id and session_data.current_intent == "book" and \
                last_tool_result and last_tool_result.get("updated_fields", {}).get("current_intent") == "book" and \
                not session_data.doctor_id:  # and no doctor selected yet
            return (
                f"Current session data: {session_json}. Intent 'book'. Patient identified. Ask for doctor or List doctors.")

        # If intent was just cleared
        if session_data.current_intent is None and \
                last_tool_result and last_tool_result.get("updated_fields", {}).get("current_intent") is None:
            return (
                f"Current session data: {session_json}. An intent was just cleared. Ask 'Is there anything else?' with {STANDARD_QUICK_REPLIES}.")

        # If details were saved and validation is pending
        if len({k: v for k, v in session_dict.items() if
                k in ["name", "email", "phone"] and v}) >= 2 and not session_data.patient_id:
            return (
                f"Current session data: {session_json}. Enough details for validation. Call `validate_or_identify_patient`.")

    # After identification
    if last_tool_name == "validate_or_identify_patient" and last_tool_status == "found":
        if session_data.current_intent == "book":
            return (
                f"Current session data: {session_json}. Validation successful. Intent 'book'. Ask for doctor or List doctors.")
        elif session_data.current_intent == "check" or session_data.current_intent == "cancel":
            return (
                f"Current session data: {session_json}. Validation successful. Intent '{session_data.current_intent}'. Call `get_patient_upcoming_appointments`.")
        else:
            return (
                f"Current session data: {session_json}. Validation successful. No prior intent. Ask 'What can I help with?' with {STANDARD_QUICK_REPLIES}.")
    elif last_tool_name == "validate_or_identify_patient" and last_tool_status == "not_found":
        return (
            f"Current session data: {session_json}. Validation not found. Inform user. Ask to register [quick_replies: Yes, No].")

    # After 'get_patient_upcoming_appointments'
    if last_tool_name == "get_patient_upcoming_appointments":
        # (Keep your existing logic for check/cancel including the two-step informing for no appointments)
        appointments = session_data.last_upcoming_appointments or []
        if session_data.current_intent == "cancel" and not appointments:
            return (
                f"Current session data: {session_json}. Intent 'cancel', no appointments found. Inform user: 'You have no upcoming appointments to cancel and ask user anything you need help and provide quick replies boking new appointment, thanks.' Next turn handles intent clearing.")
        elif session_data.current_intent == "check":
            msg = "You have no upcoming appointments."
            if appointments: msg = f"You have {len(appointments)} upcoming appointment(s): " + ". ".join(
                [f"ID {a.get('id')}" for a in appointments])
            return (
                f"Current session data: {session_json}. Intent 'check'. Respond: '{msg}'. Next turn handles intent clearing.")
        elif session_data.current_intent == "cancel":  # Appointments found
            if len(appointments) == 1:
                appt_id = str(appointments[0].get('id'));
                details = f"ID {appt_id}, Dr. {appointments[0].get('doctorName', 'N/A')} on {appointments[0].get('date', 'N/A')}"
                return (
                    f"Current session data: {session_json}. Intent 'cancel'. Found 1 appt. Save `appointment_id_to_cancel='{appt_id}'`. Then ask 'Cancel: {details}?' [quick_replies: Yes, cancel it, No, keep it]")
            else:
                appt_list_str = ". ".join(
                    [f"ID {a.get('id')}, Dr. {a.get('doctorName', 'N/A')} on {a.get('date', 'N/A')}" for a in
                     appointments])
                return (
                    f"Current session data: {session_json}. Intent 'cancel'. Found: {appt_list_str}. Ask 'Which ID to cancel?'")

    # After user informed (no appts for cancel / appts shown for check) -> Clear intent & ask next
    if (
            session_data.current_intent == "cancel" and last_model_message and "no upcoming appointments to cancel" in last_model_message.lower()) or \
            (
                    session_data.current_intent == "check" and last_tool_name == "get_patient_upcoming_appointments" and last_tool_status == "success"):
        intent_clear_action = "First, call `save_patient_details_in_session(current_intent='None')`. " if session_data.current_intent else ""
        qr = POST_NO_APPOINTMENTS_TO_CANCEL_QUICK_REPLIES if session_data.current_intent == "cancel" and "no upcoming" in (
                    last_model_message or "") else STANDARD_QUICK_REPLIES
        return (
            f"Current session data: {session_json}. Task for intent '{session_data.current_intent}' done or user informed. {intent_clear_action}Then, ask 'Is there anything else?' using {qr}.")

    # User confirms 'Yes, cancel it'
    if user_msg_lower == "yes, cancel it" and session_data.current_intent == "cancel" and session_data.appointment_id_to_cancel:
        return (
            f"Current session data: {session_json}. User confirmed to cancel appt ID {session_data.appointment_id_to_cancel}. Call `cancel_appointment(appointment_id='{session_data.appointment_id_to_cancel}')`. Then call `save_patient_details_in_session(appointment_id_to_cancel='None')`.")

    # User provides an ID for cancellation
    if session_data.current_intent == "cancel" and last_model_message and "Which appointment ID would you like to cancel?" in last_model_message:
        # (Keep your existing robust ID extraction here)
        match = re.search(r'\b(\d+)\b', user_message)
        if match:
            appt_id_from_user = match.group(1)
            is_valid = session_data.last_upcoming_appointments and any(
                str(a.get('id')) == appt_id_from_user for a in session_data.last_upcoming_appointments)
            if is_valid:
                return (
                    f"User provided valid ID '{appt_id_from_user}'. Call `cancel_appointment(appointment_id='{appt_id_from_user}')`.")
            else:
                return (f"User provided ID '{appt_id_from_user}', not in list. Ask again.")
        else:
            return (f"User response '{user_message}' to ID request has no clear ID. Ask again.")

    # After successful CANCELLATION (task completion & intent clearing)
    if last_tool_name == "cancel_appointment" and last_tool_status == "cancelled":
        user_facing_confirmation = "'Okay, the appointment has been cancelled.'"
        intent_clear_action = "Next, call `save_patient_details_in_session(current_intent='None', appointment_id_to_cancel='None')`. " if session_data.current_intent or session_data.appointment_id_to_cancel else ""
        return (
            f"Current session data: {session_json}. Appointment cancelled. Respond: {user_facing_confirmation}. {intent_clear_action}Then ask 'Is there anything else?' with {STANDARD_QUICK_REPLIES}.")

    # After successful BOOKING (task completion & intent clearing) - REFINED MESSAGE
    if last_tool_name == "schedule_appointment" and last_tool_status == "booked":
        appt_details = last_tool_result.get("details", {}) if last_tool_result else {}
        appt_id = appt_details.get("id", "N/A")

        # Use stored details for confirmation message for better accuracy
        doc_name = session_data.doctor_name_display or f"the doctor"
        date_val = session_data.preferred_date or "the selected date"
        time_val = session_data.selected_slot_text or "the selected time"

        user_facing_confirmation = f"'You made an appointment with {doc_name} on {date_val} at {time_val}. Your appointment ID is {appt_id}.'"

        clear_booking_fields_action = "Next, call `save_patient_details_in_session(current_intent='None', doctor_id='None', doctor_name_display='None', preferred_date='None', selected_slot_id='None', selected_slot_text='None', visit_reason='None')`. "

        return (
            f"Current session data: {session_json}. Today: {current_date_str}. "
            f"Appointment booked. Your response to the user: {user_facing_confirmation}. "
            f"{clear_booking_fields_action}"
            f"After that, your response to the user MUST be 'Is there anything else I can help with?' using {STANDARD_QUICK_REPLIES}."
        )

    # Contextual: User said 'Yes' after 'anything else?'
    if (last_model_message and "anything else" in last_model_message.lower() and user_msg_lower == "yes"):
        return (
            f"User said 'Yes' to 'anything else?'. Ask 'What else can I do for you today?' and provide {STANDARD_QUICK_REPLIES}.")

    # Generic Fallback
    action_if_intent_none = ""
    if session_data.current_intent is None and not (
            last_model_message and "anything else" in last_model_message.lower()):
        action_if_intent_none = (f"No active task. Ask 'What can I help with?' with {STANDARD_QUICK_REPLIES}.")
    elif session_data.current_intent:
        action_if_intent_none = (
            f"Intent is '{session_data.current_intent}', but no step matched. Analyze user message or clarify.")
    else:
        action_if_intent_none = f"No clear path. Ask 'How can I help?' with {STANDARD_QUICK_REPLIES}."

    return (
        f"Current session data: {session_json}. Today: {current_date_str}. "
        f"No specific directive matched. {action_if_intent_none} "
        "Analyze history and user's last message. Prioritize new explicit intents. If patient ID needed, ask."
    )