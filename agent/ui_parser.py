import re
from typing import Optional, List, Dict, Tuple
from logger_config import get_logger

logger = get_logger(__name__)

def parse_ui_tags(text: str) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]], bool, bool, Optional[Dict[str, str]], str]:
    """Parses all UI tags from text and returns them + cleaned text."""
    cleaned_text = text
    quick_reply_list = None
    required_fields_list = None
    required_input_dict = None
    display_doctors_flag = False
    display_slots_flag = False

    # Quick Replies: [quick_replies: Option1, Option2]
    qr_match = re.search(r"\[quick_replies:\s*(.+?)\s*\]", cleaned_text)
    if qr_match:
        suggestions_str = qr_match.group(1)
        quick_reply_list = [s.strip() for s in suggestions_str.split(',')]
        cleaned_text = re.sub(r"\[quick_replies:\s*(.+?)\s*\]", "", cleaned_text).strip()

    # Required Fields: [required_fields: name|Label|type|placeholder, ...]
    rf_match = re.search(r"\[required_fields:\s*(.+?)\s*\]", cleaned_text)
    if rf_match:
        fields_str = rf_match.group(1)
        required_fields_list = []
        field_definitions = [f.strip() for f in fields_str.split(',')]
        for fd_str in field_definitions:
            parts = [p.strip() for p in fd_str.split('|')]
            if len(parts) == 4:
                required_fields_list.append({"name": parts[0], "label": parts[1], "type": parts[2], "placeholder": parts[3]})
            else:
                logger.warning(f"Malformed required_field definition: {fd_str}")
        cleaned_text = re.sub(r"\[required_fields:\s*(.+?)\s*\]", "", cleaned_text).strip()

    # Required Input: [required_input: type|Label Text|submit_message_prefix]
    ri_match = re.search(r"\[required_input:\s*(.+?)\s*\]", cleaned_text)
    if ri_match:
        input_str = ri_match.group(1)
        parts = [p.strip() for p in input_str.split('|')]
        if len(parts) == 3:
            required_input_dict = {"type": parts[0], "label": parts[1], "submit_message_prefix": parts[2]}
        else:
            logger.warning(f"Malformed required_input definition: {input_str}")
        cleaned_text = re.sub(r"\[required_input:\s*(.+?)\s*\]", "", cleaned_text).strip()

    # Display Doctors: [display_doctors]
    if "[display_doctors]" in cleaned_text:
        display_doctors_flag = True
        cleaned_text = cleaned_text.replace("[display_doctors]", "").strip()

    # Display Slots: [display_slots]
    if "[display_slots]" in cleaned_text:
        display_slots_flag = True
        cleaned_text = cleaned_text.replace("[display_slots]", "").strip()

    return quick_reply_list, required_fields_list, display_doctors_flag, display_slots_flag, required_input_dict, cleaned_text.strip()