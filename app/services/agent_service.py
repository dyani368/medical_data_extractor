import json
import time
from sqlalchemy.orm import Session
from app.services import doc_search
from app.services.conversation_service import get_or_create_conversation, get_conversation_history, save_message
from app.models.audit_model import AgentAuditLog


def redact_text(text: str) -> str:
    from app.core.sanitize import sanitize

    return sanitize(text)

TOOL_REGISTRY = {
    "search_medical_records": doc_search.generate_relevant_docs,
}

NO_EVIDENCE = "I do not have sufficient information in the available records to answer this query."


def format_search_results(docs) -> tuple[str, list[dict]]:
    sources = []
    passages = []
    for doc in docs:
        source = {"document_id": doc.id, "filename": redact_text(doc.filename)}
        sources.append(source)
        passages.append(f"[doc:{doc.id}] {redact_text(doc.raw_content)}")
    return "\n\n".join(passages) if passages else "No relevant records found.", sources


def search_tool_arguments(raw_arguments: str, query: str, user_id: int, db: Session) -> dict:
    """Only the search text is accepted from the model; scope is server owned."""
    try:
        arguments = json.loads(raw_arguments)
    except (json.JSONDecodeError, TypeError):
        arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    search_query = arguments.get("query")
    if not isinstance(search_query, str) or not search_query.strip():
        search_query = query
    return {"query": search_query, "limit": 2, "user_id": user_id, "db": db}

async def run_clinical_agent(query: str, user_id: int, db: Session, llm_provider, conversation_id: int = None) -> dict:
    query = redact_text(query)
    conv = get_or_create_conversation(db, user_id, conversation_id)

    # Save user message
    save_message(db, conv.id, "user", query)

    # Get history with sliding window (e.g., last 10 messages) to prevent context bloat
    messages = get_conversation_history(db, conv.id, limit=10)

    # Retrieval is required for the first model turn. Otherwise a model may answer
    # directly, which this evidence-gated endpoint must refuse even when records exist.
    response_message = await llm_provider.run_agent(messages, require_tool=True)

    if response_message.tool_calls:
        sources = []
        # Save assistant message with tool calls
        save_message(db, conv.id, "assistant", response_message.content, tool_calls=response_message.tool_calls)

        messages.append({
            "role": "assistant",
            "content": response_message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                } for tc in response_message.tool_calls
            ]
        })

        for tool_call in response_message.tool_calls:
            handler = TOOL_REGISTRY.get(tool_call.function.name)

            if handler:
                kwargs = search_tool_arguments(tool_call.function.arguments, query, user_id, db)
                arguments = {"query": kwargs["query"]}

                start_time = time.time()
                audit_log = AgentAuditLog(
                    user_id=user_id,
                    conversation_id=conv.id,
                    action="tool_execution",
                    tool_name=tool_call.function.name,
                    inputs=arguments
                )
                db.add(audit_log)

                try:
                    docs = handler(**kwargs)
                    tool_result, found_sources = format_search_results(docs)
                    sources.extend(found_sources)
                    audit_log.outputs = {"status": "success", "length": len(tool_result)}
                except Exception as e:
                    tool_result = "Search failed. Please retry."
                    audit_log.outputs = {"status": "error"}
                    audit_log.error = type(e).__name__
                finally:
                    audit_log.latency_ms = (time.time() - start_time) * 1000
                    db.commit()
            else:
                tool_result = f"Error: Tool '{tool_call.function.name}' not registered."

            # Save tool response
            save_message(db, conv.id, "tool", tool_result, tool_call_id=tool_call.id)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result
            })

        if not sources:
            save_message(db, conv.id, "assistant", NO_EVIDENCE)
            return {"response": NO_EVIDENCE, "conversation_id": conv.id, "sources": []}

        final_message = await llm_provider.run_agent(messages, require_tool=False)

        # Save final assistant response
        save_message(db, conv.id, "assistant", final_message.content)

        return {"response": final_message.content or "No response generated.", "conversation_id": conv.id, "sources": sources}

    # Clinical answers require retrieved evidence even if the model skips tools.
    save_message(db, conv.id, "assistant", NO_EVIDENCE)

    return {"response": NO_EVIDENCE, "conversation_id": conv.id, "sources": []}

async def run_clinical_agent_stream(query: str, user_id: int, db: Session, llm_provider, conversation_id: int = None):
    query = redact_text(query)
    conv = get_or_create_conversation(db, user_id, conversation_id)
    save_message(db, conv.id, "user", query)
    messages = get_conversation_history(db, conv.id, limit=10)

    response_message = await llm_provider.run_agent(messages, require_tool=True)

    if response_message.tool_calls:
        sources = []
        save_message(db, conv.id, "assistant", response_message.content, tool_calls=response_message.tool_calls)
        messages.append({
            "role": "assistant",
            "content": response_message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                } for tc in response_message.tool_calls
            ]
        })

        for tool_call in response_message.tool_calls:
            handler = TOOL_REGISTRY.get(tool_call.function.name)
            if handler:
                kwargs = search_tool_arguments(tool_call.function.arguments, query, user_id, db)
                arguments = {"query": kwargs["query"]}

                start_time = time.time()
                audit_log = AgentAuditLog(
                    user_id=user_id,
                    conversation_id=conv.id,
                    action="tool_execution",
                    tool_name=tool_call.function.name,
                    inputs=arguments
                )
                db.add(audit_log)

                try:
                    docs = handler(**kwargs)
                    tool_result, found_sources = format_search_results(docs)
                    sources.extend(found_sources)
                    audit_log.outputs = {"status": "success", "length": len(tool_result)}
                except Exception as e:
                    tool_result = "Search failed. Please retry."
                    audit_log.outputs = {"status": "error"}
                    audit_log.error = type(e).__name__
                finally:
                    audit_log.latency_ms = (time.time() - start_time) * 1000
                    db.commit()
            else:
                tool_result = f"Error: Tool '{tool_call.function.name}' not registered."

            save_message(db, conv.id, "tool", tool_result, tool_call_id=tool_call.id)
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": tool_result})

        if not sources:
            yield f"data: {NO_EVIDENCE}\n\n"
            save_message(db, conv.id, "assistant", NO_EVIDENCE)
            return

        yield f"event: sources\ndata: {json.dumps(sources)}\n\n"
        final_content = ""
        async for chunk in llm_provider.run_agent_stream(messages):
            yield chunk
            # parse the data: string
            if chunk.startswith("data: "):
                content_chunk = chunk[6:].strip()
                if content_chunk:
                    final_content += content_chunk + " "

        save_message(db, conv.id, "assistant", final_content.strip())
        return

    yield f"data: {NO_EVIDENCE}\n\n"
    save_message(db, conv.id, "assistant", NO_EVIDENCE)
