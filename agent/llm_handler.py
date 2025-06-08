import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from typing import List, Dict, Any
from config import settings
from tools.definitions import TOOLS_CONFIG_LIST
from logger_config import get_logger
from utils.helpers import dict_to_content



logger = get_logger(__name__)

# Configure GenAI
genai.configure(api_key=settings.gemini_api_key)

SYSTEM_PROMPT = """You are MedX Hospital's friendly and efficient AI appointment assistant.
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

# def call_gemini(history: List[Dict[str, Any]]) -> Any:
#     """
#     Starts a chat session with Gemini, sends the history, and returns the response.
#     """
#     logger.debug(f"Calling Gemini with history length: {len(history)}")
#     try:
#         chat_session = gemini_model.start_chat(history=history)
#         # We send an empty message (" ") because the 'directive' prompt is
#         # added as the last user message, giving Gemini context to act upon.
#         response = chat_session.send_message(" ")
#         return response
#     except Exception as e:
#         logger.exception(f"Exception during Gemini API call: {e}")
#         return Non
#
#         MODIFED VERSION

def call_gemini(history: List[Dict[str, Any]]) -> Any:
    """
    Starts a chat session with Gemini, sends the history (converted to
    Content objects), and returns the response.
    """
    logger.debug(f"Calling Gemini with history length: {len(history)}")
    try:
        # --- FIX: Convert history dicts to Content objects ---
        gemini_history = dict_to_content(history)
        logger.debug(f"Converted history for Gemini: {gemini_history}")
        # --- END FIX ---

        chat_session = gemini_model.start_chat(history=gemini_history) # <-- Use converted history
        response = chat_session.send_message(" ")
        return response
    except Exception as e:
        logger.exception(f"Exception during Gemini API call: {e}")
        # Log the history that caused the error for easier debugging
        try:
            import json
            logger.error(f"History causing error: {json.dumps(history, indent=2)}")
        except:
             logger.error(f"History causing error (raw): {history}")
        return None
