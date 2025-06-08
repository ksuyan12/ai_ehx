import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# Import necessary components from the new structure
from config import settings
from logger_config import get_logger, setup_logging
from models.api_models import StartSessionResponse, MessageRequest, MessageResponse
from models.session_models import Session, SessionData
from sessions.store import session_store
from agent.core import process_chat_message

# Ensure logging is set up when the app starts
setup_logging()
logger = get_logger(__name__)

# Create FastAPI App
app = FastAPI(
    title="AI Appointment Agent - MedX Modular",
    version="3.0.0"
)

# Add CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Be more specific in production!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    """Health check endpoint."""
    logger.info("Health check requested.")
    return {
        "status": "ok",
        "patient_v1": settings.patient_service_v1_url,
        "appointment_v1": settings.appointment_service_v1_url,
        "debug_mode": settings.debug_mode
    }

@app.post("/session/start", response_model=StartSessionResponse)
async def start_session_endpoint():
    """Starts a new chat session and returns a session ID."""
    sid = str(uuid.uuid4())
    # Create a new session object with default data
    new_session = Session(data=SessionData(conversation_state="initial_greeting"), history=[])
    session_store.save(sid, new_session)
    logger.info(f"🚀 Session {sid} started.")
    return {"session_id": sid}

@app.post("/session/{sid}/message", response_model=MessageResponse)
async def chat_endpoint(sid: str, msg: MessageRequest):
    """Handles an incoming message within a specific session."""
    logger.info(f"← User ({sid}): {msg.message}")

    if not session_store.exists(sid):
        logger.warning(f"Session {sid} not found during message processing.")
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        # Delegate processing to the agent core
        response = process_chat_message(sid, msg.message)
        return response
    except KeyError:
        # This might catch cases where loading fails inside process_chat_message
        logger.error(f"KeyError processing session {sid}. It might have expired or an error occurred.")
        raise HTTPException(status_code=404, detail="Session not found or error during loading.")
    except Exception as e:
        logger.exception(f"💥 Unhandled exception in chat_endpoint for {sid}: {e}")
        raise HTTPException(status_code=500, detail="An internal server error occurred.")

# Main entry point for running with uvicorn (if desired)
if __name__ == "__main__":
    import uvicorn
    logger.info("AI Agent (MedX Modular v3.0.0) starting...")
    uvicorn.run(app, host="0.0.0.0", port=8083)