from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from eneo.analysis.analysis_repo import AnalysisRepository


@pytest.mark.asyncio
async def test_hydrates_all_info_blobs_before_file_projection(monkeypatch):
    blobs = [MagicMock(), MagicMock()]
    hydrate = AsyncMock()
    attach_files = AsyncMock()
    monkeypatch.setattr(
        "eneo.analysis.analysis_repo.InfoBlobRepository.hydrate_original_availability",
        hydrate,
    )
    monkeypatch.setattr(
        "eneo.analysis.analysis_repo.attach_question_files", attach_files
    )
    repo = AnalysisRepository(AsyncMock(), MagicMock())
    questions = [SimpleNamespace(info_blobs=blobs, questions_files=[])]

    await repo._hydrate_sessions([SimpleNamespace(questions=questions)])

    hydrate.assert_awaited_once_with(blobs)
    attach_files.assert_awaited_once_with(questions, loader=repo.file_content_loader)
