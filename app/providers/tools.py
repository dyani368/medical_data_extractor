tools = [
    {
        "type": "function",
        "function": {
            "name": "search_medical_records",
            "description": "Search clinical trial documents and patient records for symptoms, medications, or diagnoses.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The clinical query or keywords to search for."
                    }
                },
                "required": ["query"]
            }
        }
    }
]
