from unittest.mock import AsyncMock, MagicMock

import pytest

from app import main


@pytest.mark.asyncio
async def test_process_redacts_before_persistence_and_llm(monkeypatch):
    monkeypatch.setattr(main, "sanitize", lambda text: text.replace("Jane Doe", "<PERSON>"))
    monkeypatch.setattr(main, "embed_text", lambda text: [0.0] * 384)
    provider = MagicMock()
    provider.generate = AsyncMock(
        return_value='{"summary":"Example","category":"General","key_entities":{},"confidence":0.8}'
    )
    monkeypatch.setattr(main, "llm_provider", provider)
    db = MagicMock()

    await main.run_extraction_pipeline("Jane Doe took aspirin", "note.txt", db, 42)

    document = db.add.call_args_list[0].args[0]
    assert document.raw_content == "<PERSON> took aspirin"
    provider.generate.assert_awaited_once_with("<PERSON> took aspirin")
