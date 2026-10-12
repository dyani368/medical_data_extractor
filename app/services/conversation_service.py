import json
from datetime import datetime, UTC
from sqlalchemy.orm import Session
from app.models.conversation_model import Conversation, Message
from app.schemas.document_schema import SearchRequest
from fastapi import HTTPException

def get_or_create_conversation(db: Session, user_id: int, conversation_id: int = None) -> Conversation:
    if conversation_id is not None:
        conv = db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.user_id == user_id).first()
        if conv:
            return conv
        raise HTTPException(status_code=404, detail="Conversation not found")
    new_conv = Conversation(user_id=user_id)
    db.add(new_conv)
    db.commit()
    db.refresh(new_conv)
    return new_conv

def save_message(db: Session, conversation_id: int, role: str, content: str, tool_calls: list = None, tool_call_id: str = None) -> Message:
    tool_calls_data = None
    if tool_calls:
        tool_calls_data = []
        for tc in tool_calls:
            tool_calls_data.append({
                "id": tc.id,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments
                },
                "type": "function"
            })
            
    new_msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        tool_calls=tool_calls_data,
        tool_call_id=tool_call_id
    )
    db.add(new_msg)
    db.query(Conversation).filter(Conversation.id == conversation_id).update(
        {Conversation.updated_at: datetime.now(UTC)}, synchronize_session=False
    )
    db.commit()
    db.refresh(new_msg)
    return new_msg

def get_conversation_history(db: Session, conversation_id: int, limit: int = 10) -> list:
    # A single agent turn can contain several tool-call/result pairs. Fetch
    # enough rows to select complete turns, then trim by whole user turns.
    messages_db = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(
        Message.created_at.desc(), Message.id.desc()
    ).limit(max(40, limit * 4)).all()
    messages_db.reverse()
    while messages_db and messages_db[0].role != "user":
        messages_db.pop(0)

    turns = []
    for message in messages_db:
        if message.role == "user":
            turns.append([message])
        elif turns:
            turns[-1].append(message)
    selected_turns = []
    selected_count = 0
    for turn in reversed(turns):
        selected_turns.append(turn)
        selected_count += len(turn)
        if selected_count >= limit:
            break
    messages_db = [message for turn in reversed(selected_turns) for message in turn]

    available_tool_results = {message.tool_call_id for message in messages_db
                              if message.role == "tool" and message.tool_call_id}
    incomplete_tool_call_ids = set()
    for message in messages_db:
        if message.role == "assistant" and message.tool_calls:
            call_ids = {call.get("id") for call in message.tool_calls if call.get("id")}
            if not call_ids.issubset(available_tool_results):
                incomplete_tool_call_ids.update(call_ids)
    
    formatted_messages = []
    for msg in messages_db:
        if msg.role == "assistant" and msg.tool_calls:
            call_ids = {call.get("id") for call in msg.tool_calls if call.get("id")}
            if call_ids & incomplete_tool_call_ids:
                continue
        if msg.role == "tool" and msg.tool_call_id in incomplete_tool_call_ids:
            continue
        fmt_msg = {"role": msg.role}
        if msg.content:
            fmt_msg["content"] = msg.content
        if msg.tool_call_id:
            fmt_msg["tool_call_id"] = msg.tool_call_id
        if msg.tool_calls:
            # Reconstruct tool_calls for OpenAI compatibility
            # This is a bit tricky, usually we can just pass the dict or object back
            # Wait, openai expects specific objects, but dicts often work. We'll pass the raw dict.
            fmt_msg["tool_calls"] = msg.tool_calls
        formatted_messages.append(fmt_msg)
    return formatted_messages
