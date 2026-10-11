tools = [
    {
        "type": "function",
        "function": {
            "name": "search_medical_records",
            "description": "Find passages in the authenticated user's uploaded records for a factual question.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "description": "A standalone question or search phrase."}
            }, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_extraction_result",
            "description": "Get the stored summary, category, and extracted entities for a document already found in this user's records. Use when the user asks about the document's extracted summary or structured fields.",
            "parameters": {"type": "object", "properties": {
                "document_id": {"type": "integer", "description": "A document ID from this user's search results."}
            }, "required": ["document_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_related_document_chunks",
            "description": "Fetch nearby passages from the same uploaded document when a relevant result seems split across chunks. Use its document ID from search results.",
            "parameters": {"type": "object", "properties": {
                "document_id": {"type": "integer", "description": "A document ID from this user's search results."}
            }, "required": ["document_id"]},
        },
    },
]
