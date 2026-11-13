"""Seed a session from the synthetic sample dataset."""
from __future__ import annotations

from typing import Any, Dict

from .. import store
from . import data


def create_sample_session() -> str:
    session_id = store.create_session(
        mode="sample",
        project_name=data.PROJECT_NAME,
        leaver_name=data.LEAVER_NAME,
        leaver_email=data.LEAVER_EMAIL,
        window_start=data.WINDOW_START,
        window_end=data.WINDOW_END,
        repo_full_name=data.REPO,
        summary={
            "origin": "synthetic",
            "note": data.SAMPLE_NOTE,
            "warnings": [],
            "repo": {"repo_full_name": data.REPO, "description": "Sample payments platform (fictional)"},
        },
        llm_status="pending",
    )
    store.insert_evidence(session_id, data.EVIDENCE)
    return session_id


def describe() -> Dict[str, Any]:
    return data.describe()
