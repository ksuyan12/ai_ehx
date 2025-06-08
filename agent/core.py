import json
from typing import Dict, Any, List, Tuple
from models.session_models import Session, SessionData
from models.api_models import MessageResponse
from sessions.store import session_store
from tools.implementations import AVAILABLE_PYTHON_TOOLS
from agent import llm_handler, prompt_builder, ui_parser
from utils.helpers import content_to_dict, sanitize_history
from logger_config import get_logger
from config import settings
import json

logger = get_logger(__name__)
MAX_TURNS = 8

def handle_initial_greeting(sid: str, session: Session, user_message: str) -> MessageResponse:
    """Handles the very first message in a session."""
    final_reply_to_user = "Hi, I am MedX AI assistant. How can I help you today?"
    initial_quick_replies = ["Book new appointment", "Check upcoming appointments", "Cancel appointment"]
    logger.info(f"Saluto Bot ({sid}): {final_reply_to_user} with QRs: {initial_quick_replies}")

    session.history.append({"role": "user", "parts": [{"text": user_message}]})
    session.history.append({"role": "model", "parts": [{"text": final_reply_to_user}]})
    session.data.conversation_state = "active_conversation"
    session_store.save(sid, session)

    return MessageResponse(
        reply=final_reply_to_user,
        quick_replies=initial_quick_replies
    )

def process_chat_message(sid: str, user_message: str) -> MessageResponse:
    """Processes an incoming chat message using the agent and LLM."""
    session = session_store.load(sid)

    if session.data.conversation_state == "initial_greeting":
        return handle_initial_greeting(sid, session, user_message)

    session.history.append({"role": "user", "parts": [{"text": user_message}]})

    turn_count = 0
    final_reply = "" # Initialize final_reply here

    while turn_count < MAX_TURNS:
        turn_count += 1
        logger.info(f"🔄 Turn {turn_count} for {sid}. History: {len(session.history)}. Data: {session.data.dict()}")

        # 1. Build Directive and Prepare History
        directive = prompt_builder.build_directive_prompt(session.data, session.history, user_message)
        current_turn_history = sanitize_history(session.history)
        current_turn_history.append({"role": "user", "parts": [{"text": directive}]})

        # --- START DIAGNOSTIC LOGGING ---
        try:
            logger.debug(f"History being sent to Gemini (Turn {turn_count}):")
            logger.debug(json.dumps(current_turn_history, indent=2))
        except Exception as log_e:
            logger.error(f"Error logging history: {log_e}")
        # --- END DIAGNOSTIC LOGGING ---
        # 2. Call LLM
        llm_response = llm_handler.call_gemini(current_turn_history)

        if not llm_response or not llm_response.candidates:
            logger.error(f"🚨 Gemini returned no candidates for {sid}.")
            final_reply = "I'm having trouble processing. Could you try again?"
            # Ensure model response is added before breaking
            if not session.history or session.history[-1]['role'] != 'model':
                session.history.append({"role": "model", "parts": [{"text": final_reply}]})
            break

        candidate = llm_response.candidates[0]
        gemini_response_dict = content_to_dict(candidate.content)
        session.history.append(gemini_response_dict) # Add LLM response to history

        logger.debug(f"Gemini candidate ({sid}): Finish: {candidate.finish_reason.name}, Content: {gemini_response_dict}")

        # 3. Process Tool Calls (if any) - MODIFIED TO HANDLE MULTIPLE
        function_calls = [
            p["function_call"]
            for p in gemini_response_dict.get("parts", [])
            if "function_call" in p
        ]

        if function_calls:
            tool_results_for_history = []
            tool_call_executed = False

            for fc_dict in function_calls:
                func_name, args = fc_dict["name"], fc_dict["args"]
                logger.info(f"🤖 Gemini wants to call: {func_name}({args})")

                # Execute the tool
                result = _execute_tool(func_name, args, session.data)

                # Update session based on tool result
                _update_session_from_tool(func_name, result, session.data)

                # Prepare the response part for history
                tool_results_for_history.append(
                    {"function_response": {"name": func_name, "response": result}}
                )
                tool_call_executed = True

            # If any tool was called, add ALL results and continue the loop
            if tool_call_executed:
                session.history.append({"role": "tool", "parts": tool_results_for_history})
                continue # Go to the next turn for LLM to process the tool result

        # 4. Process Text Response (if no tool call, or after tool call in next turn)
        text_part = next((p for p in gemini_response_dict.get("parts", []) if "text" in p), None)

        if candidate.finish_reason.name in ["STOP", "MAX_TOKENS"] and text_part:
            final_reply = text_part["text"].strip()
            logger.info(f"🤖 Gemini final text reply for {sid}: {final_reply}")
            break # Exit the loop, we have a reply for the user
        elif candidate.finish_reason.name == "TOOL_CALLS" and not function_calls:
             logger.warning(f"Gemini indicated TOOL_CALLS but no function_call processed for {sid}.")
             final_reply = "I tried to perform an action but hit a snag. Please try again."
             break
        else: # Unhandled finish or no text
            logger.error(f"🚨 Unhandled state: Finish={candidate.finish_reason.name}, Text={text_part is not None}")
            final_reply = "I'm not sure how to proceed. Can you rephrase?"
            # Ensure a model response is added even in error cases before breaking
            if not session.history or session.history[-1]['role'] != 'model':
                 session.history.append({"role": "model", "parts": [{"text": final_reply}]})
            break

    # 5. Handle Loop Exit (Max turns or error)
    if not final_reply: # Check if a final reply was set
        if turn_count >= MAX_TURNS:
            logger.warning(f"Max turns reached for session {sid}.")
            final_reply = "We seem to be going in circles. Could you restate your request?"
        else:
            logger.warning(f"Loop ended unexpectedly for {sid}. Using fallback.")
            final_reply = "Is there anything else I can help with?" # Fallback

        # Ensure a model response is added if we fell through without one
        if not session.history or session.history[-1]['role'] != 'model':
             session.history.append({"role": "model", "parts": [{"text": final_reply}]})


    # 6. Parse UI Tags and Format Response
    qr, rf, dd, ds, ri, clean_reply = ui_parser.parse_ui_tags(final_reply)

    response_payload = MessageResponse(reply=clean_reply)
    if qr: response_payload.quick_replies = qr
    if rf: response_payload.required_fields = rf
    if ri: response_payload.required_input = ri
    if dd and session.data.last_doctors_list: response_payload.available_doctors = session.data.last_doctors_list
    if ds and session.data.last_slots_list: response_payload.appointment_slots = session.data.last_slots_list
    if settings.debug_mode: response_payload.session_data_debug = session.data.dict()

    # 7. Save Session and Return
    session_store.save(sid, session)
    logger.info(f"→ Bot ({sid}): {response_payload.reply}")
    return response_payload


def _execute_tool(func_name: str, args: Dict, session_data: SessionData) -> Dict:
    """Executes the requested tool function with safety checks."""
    if func_name not in AVAILABLE_PYTHON_TOOLS:
        logger.error(f"Tool {func_name} not found.")
        return {"status": "error", "message": "Tool not found."}

    python_func = AVAILABLE_PYTHON_TOOLS[func_name]

    # Inject patient_id if needed and available
    if "patient_id" in python_func.__code__.co_varnames and \
       "patient_id" not in args and session_data.patient_id:
        args["patient_id"] = session_data.patient_id

    # Sanitize appointment_id for cancel_appointment
    if func_name == "cancel_appointment" and "appointment_id" in args:
        try: args["appointment_id"] = str(int(float(str(args["appointment_id"]))))
        except ValueError: return {"status": "error", "message": "Invalid appointment ID format."}

    try:
        result = python_func(**args)
        logger.info(f"🛠️ Tool {func_name} result: {result}")
        return result
    except Exception as e:
        logger.exception(f"Exception during tool execution {func_name}: {e}")
        return {"status": "error", "message": f"Tool execution failed: {e}"}

def _update_session_from_tool(func_name: str, result: Dict, session_data: SessionData) -> None:
    """Updates the session data based on the result of a tool call."""
    status = result.get("status")

    if func_name == "save_patient_details_in_session" and status == "details_noted_in_session":
        for k, v in result.get("updated_fields", {}).items():
            if hasattr(session_data, k): # Check if attribute exists before setting
                setattr(session_data, k, v)
        logger.info(f"Session updated with: {result.get('updated_fields', {})}")

    elif func_name == "validate_or_identify_patient":
        session_data.last_validation_status = status
        if status == "found" and result.get("patient_id"):
            session_data.patient_id = result.get("patient_id")
            logger.info(f"Patient ID {session_data.patient_id} stored in session.")

    elif func_name == "register_new_patient" and status == "registered":
        session_data.patient_id = result.get("patient_id")
        logger.info(f"Patient ID {session_data.patient_id} stored from registration.")

    elif func_name == "list_available_doctors" and status == "success":
        session_data.last_doctors_list = result.get("doctors")

    elif func_name == "get_doctor_available_slots" and status == "success":
        session_data.last_slots_list = result.get("slots")

    # --- NEW/CRITICAL FIX HERE ---
    elif func_name == "get_patient_upcoming_appointments" and status == "success":
        session_data.last_upcoming_appointments = result.get("appointments", [])
        logger.info(f"Session updated with upcoming appointments: {len(session_data.last_upcoming_appointments)} found.")
    elif func_name == "get_patient_upcoming_appointments" and status == "no_appointments_found":
        session_data.last_upcoming_appointments = [] # Explicitly set to empty list
        logger.info(f"Session updated: no upcoming appointments found.")
    # --- END NEW/CRITICAL FIX ---

    # Update session_data for appointment_id_to_cancel if it was part of save_patient_details
    if func_name == "save_patient_details_in_session":
        if "appointment_id_to_cancel" in result.get("updated_fields", {}):
            session_data.appointment_id_to_cancel = result["updated_fields"]["appointment_id_to_cancel"]
        if "doctor_name_display" in result.get("updated_fields", {}): # Ensure new fields from previous change are handled
            session_data.doctor_name_display = result["updated_fields"]["doctor_name_display"]
        if "selected_slot_id" in result.get("updated_fields", {}):
            session_data.selected_slot_id = result["updated_fields"]["selected_slot_id"]
        if "selected_slot_text" in result.get("updated_fields", {}):
            session_data.selected_slot_text = result["updated_fields"]["selected_slot_text"]
        if "visit_reason" in result.get("updated_fields", {}):
            session_data.visit_reason = result["updated_fields"]["visit_reason"]
