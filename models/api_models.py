from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional

class StartSessionResponse(BaseModel):
    session_id: str

class MessageRequest(BaseModel):
    message: str

class MessageResponse(BaseModel):
    reply: str
    quick_replies: Optional[List[str]] = None
    required_fields: Optional[List[Dict[str, str]]] = None
    appointment_slots: Optional[List[Dict[str, str]]] = None
    available_doctors: Optional[List[Dict[str, str]]] = None
    required_input: Optional[Dict[str, str]] = None
    session_data_debug: Optional[Dict] = None