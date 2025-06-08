from google.generativeai.types import Tool, FunctionDeclaration

TOOLS_CONFIG_LIST = Tool(
    function_declarations=[
        FunctionDeclaration(
            name="save_patient_details_in_session",
            description="Saves or updates patient details (name, email, phone, etc.) or conversational state (like current_intent, selected doctor/slot/reason, appointment_id_to_cancel) to session memory. Use this when the user provides personal info or when an intent needs to be stored or cleared, or when booking details are gathered.",
            parameters={"type": "OBJECT", "properties": {
                "name": {"type": "STRING", "description": "Patient's full name"},
                "email": {"type": "STRING", "description": "Patient's email address"},
                "phone": {"type": "STRING", "description": "Patient's phone number"},
                "gender": {"type": "STRING", "description": "Patient's gender"},
                "birthDate": {"type": "STRING", "description": "Patient's birth date (YYYY-MM-DD)"},
                "address_line": {"type": "STRING", "description": "Patient's address line"},
                "address_city": {"type": "STRING", "description": "Patient's city"},
                "address_country": {"type": "STRING", "description": "Patient's country"},
                "doctor_id": {"type": "STRING", "description": "ID of the selected doctor"},
                "doctor_name_display": {"type": "STRING", "description": "Display name of the selected doctor, e.g., Dr. John Doe (Cardiologist)"}, # <-- NEW
                "preferred_date": {"type": "STRING", "description": "Preferred date for appointment (YYYY-MM-DD)"},
                "selected_slot_id": {"type": "STRING", "description": "The ID of the chosen appointment slot."},         # <-- NEW
                "selected_slot_text": {"type": "STRING", "description": "The display text of the chosen slot, e.g., '10:00 AM - 10:30 AM'."}, # <-- NEW
                "visit_reason": {"type": "STRING", "description": "The reason for the patient's visit."},               # <-- NEW
                "current_intent": {"type": "STRING", "description": "The user's current primary goal, e.g., 'book', 'cancel', 'check', or 'None' to clear."},
                "appointment_id_to_cancel": {"type": "STRING", "description": "The ID of the appointment confirmed for cancellation, or 'None' to clear."}
            }}
        ),
        FunctionDeclaration(
            name="validate_or_identify_patient",
            description="Validates if a patient exists using at least two identifiers (name, email, phone). Returns patientId if found.",
            parameters={"type": "OBJECT", "properties": {
                "name": {"type": "STRING"},
                "email": {"type": "STRING"},
                "phone": {"type": "STRING"},
            }}
        ),
        FunctionDeclaration(
            name="register_new_patient",
            description="Registers a new patient. Requires name, email, phone. Optional: gender, birthDate, address.",
            parameters={"type": "OBJECT", "properties": {
                "name": {"type": "STRING"},
                "email": {"type": "STRING"},
                "phone": {"type": "STRING"},
                "gender": {"type": "STRING"},
                "birthDate": {"type": "STRING"},
                "address_line": {"type": "STRING"},
                "address_city": {"type": "STRING"},
                "address_country": {"type": "STRING"},
            }, "required": ["name", "email", "phone"]}
        ),
        FunctionDeclaration(
            name="list_available_doctors",
            description="Lists available doctors. Use if the user asks for options or hasn't specified one.",
            parameters={"type": "OBJECT", "properties": {}}
        ),
        FunctionDeclaration(
            name="get_doctor_available_slots",
            description="Gets available time slots for a specific doctor_id and date (YYYY-MM-DD).",
            parameters={"type": "OBJECT", "properties": {
                "doctor_id": {"type": "STRING"},
                "date": {"type": "STRING", "description": "Date in YYYY-MM-DD format."},
            }, "required": ["doctor_id", "date"]}
        ),
        FunctionDeclaration(
            name="schedule_appointment",
            description="Schedules an appointment. Requires patient_id, selected_slot_id, and visit_reason.", # Updated description
            parameters={"type": "OBJECT", "properties": {
                "patient_id": {"type": "STRING"},
                "slot_id": {"type": "STRING", "description": "This should be the selected_slot_id from the session"}, # Renamed for clarity internally
                "reason": {"type": "STRING", "description": "This should be the visit_reason from the session."}, # Renamed for clarity internally
            }, "required": ["patient_id", "slot_id", "reason"]}
        ),
        FunctionDeclaration(
            name="get_patient_upcoming_appointments",
            description="Gets upcoming appointments for a specific patient_id.",
            parameters={"type": "OBJECT", "properties": {
                "patient_id": {"type": "STRING"},
            }, "required": ["patient_id"]}
        ),
        FunctionDeclaration(
            name="cancel_appointment",
            description="Cancels an existing appointment using its appointment_id.",
            parameters={"type": "OBJECT", "properties": {
                "appointment_id": {"type": "STRING"},
            }, "required": ["appointment_id"]}
        ),
    ]
)