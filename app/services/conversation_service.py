import json
from sqlalchemy.orm import Session
from app.models.conversation_model import Conversation, Message
from app.schemas.document_schema import SearchRequest

def get_or_create_conversation(db: Session, user_id: int, conversation_id: int = None) -> Conversation:
    if conversation_id:
        conv = db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.user_id == user_id).first()
        if conv:
            return conv
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
    db.commit()
    db.refresh(new_msg)
    return new_msg

def get_conversation_history(db: Session, conversation_id: int, limit: int = 10) -> list:
    messages_db = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.created_at.desc()).limit(limit).all()
    messages_db.reverse()
    
    formatted_messages = []
    for msg in messages_db:
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
