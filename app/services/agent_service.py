import json
from sqlalchemy.orm import Session
from app.services import doc_search
TOOL_REGISTRY = {
    "search_medical_records": doc_search.generate_relevant_docs,
}

async def run_clinical_agent(query: str, user_id: int, db: Session, llm_provider) -> str:
    messages = [{"role": "user", "content": query}]
    
   
    response_message = await llm_provider.run_agent(messages)

   
    if response_message.tool_calls:

        messages.append(response_message)

        for tool_call in response_message.tool_calls:
            handler = TOOL_REGISTRY.get(tool_call.function.name)
            
            if handler:
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
                search_query = arguments.get("query", query)
                
                docs = handler(query=search_query, limit=2, user_id=user_id, db=db)
                tool_result = "\n\n".join([doc.raw_content for doc in docs]) if docs else "No relevant records found."
            else:
                tool_result = f"Error: Tool '{tool_call.function.name}' not registered."

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result
            })

        final_message = await llm_provider.run_agent(messages)
        return final_message.content or "No response generated."

    return response_message.content or "No response generated."
