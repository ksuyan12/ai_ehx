import json
from typing import Dict, Any, Protocol
from models.session_models import Session
from logger_config import get_logger

logger = get_logger(__name__)

# A simple in-memory store (NOT SUITABLE FOR PRODUCTION)
_MEMORY_SESSION_STORE: Dict[str, str] = {} # Storing as JSON strings for simplicity

class SessionStore(Protocol):
    """Defines the interface for session storage."""
    def save(self, sid: str, session_data: Session) -> None: ...
    def load(self, sid: str) -> Session: ...
    def exists(self, sid: str) -> bool: ...

class InMemorySessionStore(SessionStore):
    """In-memory implementation of the SessionStore."""

    def save(self, sid: str, session: Session) -> None:
        """Saves session data to the in-memory store."""
        try:
            # Pydantic's .json() handles serialization correctly
            _MEMORY_SESSION_STORE[sid] = session.json()
            logger.info(f"Session {sid} saved to in-memory store.")
        except Exception as e:
            logger.error(f"Failed to serialize and save session {sid}: {e}")
            raise

    def load(self, sid: str) -> Session:
        """Loads session data from the in-memory store."""
        if not self.exists(sid):
            logger.error(f"Session {sid} not found in in-memory store.")
            raise KeyError(f"Session {sid} not found.")
        try:
            session_json = _MEMORY_SESSION_STORE[sid]
            # Parse the JSON back into a Session model
            session = Session.parse_raw(session_json)
            logger.info(f"Session {sid} loaded from in-memory store.")
            return session
        except Exception as e:
            logger.error(f"Failed to load or parse session {sid}: {e}")
            raise KeyError(f"Failed to load session {sid}: {e}")


    def exists(self, sid: str) -> bool:
        """Checks if a session exists."""
        return sid in _MEMORY_SESSION_STORE

# Instance to be used by the application
session_store: SessionStore = InMemorySessionStore()