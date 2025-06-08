from typing import Dict, Any, List
from logger_config import get_logger


from typing import Dict, Any, List
from logger_config import get_logger
import google.generativeai as genai

logger = get_logger(__name__)

def content_to_dict(content_obj: Any) -> Dict[str, Any]:
    """
    Converts a Google Generative AI Content object into a serializable
    dictionary. If the input is already a dictionary, it returns it
    as is to prevent recursion. It's made more robust to avoid empty parts.
    """
    if isinstance(content_obj, dict):
        # Perform a basic check. If it looks like our format, return it.
        if "role" in content_obj and "parts" in content_obj:
            # Ensure no part within an existing dict is empty
            checked_parts = []
            for part in content_obj.get("parts", []):
                if isinstance(part, dict) and any(key in part for key in ["text", "function_call", "function_response"]):
                     checked_parts.append(part)
                else:
                    logger.warning(f"Skipping potentially empty/malformed part in existing dict: {part}")
            content_obj["parts"] = checked_parts
            return content_obj
        else:
            logger.warning(f"Passing through potentially malformed dict: {content_obj}")
            return content_obj # Pass through but log

    # Process Content objects or similar
    role = getattr(content_obj, 'role', "model")
    parts_list = []
    if hasattr(content_obj, 'parts'):
        for part_content in content_obj.parts:
            part_dict = {}
            try:
                fc = getattr(part_content, 'function_call', None)
                fr = getattr(part_content, 'function_response', None)
                txt = getattr(part_content, 'text', None)

                if fc and fc.name and fc.args is not None:
                    part_dict["function_call"] = {"name": fc.name, "args": dict(fc.args)}
                elif fr and fr.name and fr.response is not None:
                    resp = fr.response
                    part_dict["function_response"] = {
                        "name": fr.name,
                        "response": dict(resp) if hasattr(resp, 'items') else resp
                    }
                elif txt is not None: # Only add if text is not None
                    part_dict["text"] = txt

                # Only add the part_dict if it actually contains data
                if part_dict:
                    parts_list.append(part_dict)
                else:
                    logger.debug(f"Part had no extractable & valid content: {type(part_content)}")

            except Exception as e:
                 logger.error(f"Error processing part {part_content}: {e}")

    return {"role": role, "parts": parts_list}


def sanitize_history(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ensures all items in the history are serializable dicts."""
    return [content_to_dict(item) for item in history]


# addding this funciton
def dict_to_content(history_dicts: List[Dict[str, Any]]) -> List[genai.types.ContentDict]:
    """
    Converts a list of history dictionaries back into a list of
    Google Generative AI Content objects (or ContentDicts).
    Performs basic validation to avoid sending empty parts.
    """
    content_list = []
    for item in history_dicts:
        role = item.get("role")
        parts = item.get("parts", [])

        valid_parts = []
        for part in parts:
            # Ensure the part is a dict and has *some* key we expect
            if isinstance(part, dict) and any(key in part for key in ["text", "function_call", "function_response"]):
                # If it's a function_response, ensure its 'response' isn't None
                if "function_response" in part and part["function_response"].get("response") is None:
                    logger.warning(f"Skipping function_response with None response: {part}")
                    continue
                # If it's text, ensure it isn't None
                if "text" in part and part["text"] is None:
                    logger.warning(f"Skipping part with None text: {part}")
                    continue
                valid_parts.append(part)
            else:
                logger.warning(f"Skipping unknown or empty part during dict_to_content: {part}")


        if role and valid_parts:
            content_list.append({'role': role, 'parts': valid_parts})
        elif role and not parts:  # Allow user turns with empty parts (though unlikely here)
            content_list.append({'role': role, 'parts': []})
        else:
            logger.error(f"Could not convert item to ContentDict due to missing role or parts: {item}")

    return content_list