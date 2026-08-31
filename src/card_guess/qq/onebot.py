import json
from pathlib import Path


def extract_mentioned_text(event: dict) -> str | None:
    if event.get("post_type") != "message":
        return None

    if event.get("message_type") != "group":
        return None

    self_id = str(event.get("self_id"))
    message = event.get("message", [])

    mentioned = False
    text_parts = []

    for segment in message:
        if segment.get("type") == "at":
            qq = segment.get("data", {}).get("qq")
            if qq == self_id:
                mentioned = True

        if segment.get("type") == "text":
            text_parts.append(segment.get("data", {}).get("text", ""))

    if not mentioned:
        return None

    return "".join(text_parts).strip()


def build_message_segments(text: str, image_path=None):
    segments = [{"type": "text", "data": {"text": text}}]

    if image_path is not None:
        file_value = Path(image_path).as_posix()
        segments.append({
            "type": "image",
            "data": {"file": file_value},
        })

    return segments


def build_friend_add_request_action(flag: str, approve: bool = True):
    return {
        "action": "set_friend_add_request",
        "params": {
            "flag": flag,
            "approve": approve,
        },
    }


def build_group_add_request_action(flag: str, approve: bool = True):
    return {
        "action": "set_group_add_request",
        "params": {
            "flag": flag,
            "approve": approve,
        },
    }


async def send_action(websocket, action: dict):
    await websocket.send(json.dumps(action))