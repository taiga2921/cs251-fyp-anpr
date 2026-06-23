"""Unit tests for backend queue, token cache, and retry eligibility."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend import (
    BackendApiError,
    BackendClient,
    BackendQueueJob,
    BackendToken,
    FlushQueueResult,
    _is_retryable_job,
)
from config import Config


def _sample_job(**overrides) -> BackendQueueJob:
    payload = {
        "job_id": "job-1",
        "local_event_id": "local-evt-1",
        "status": "pending",
        "attempts": 0,
        "retry_limit": 2,
        "max_attempts": 3,
        "backend_event_id": None,
        "images_sent": 0,
        "logs_sent": 0,
        "last_error": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "event": {
            "camera_id": "11111111-1111-1111-1111-111111111111",
            "plate_number": "ABC1234",
            "confidence": 0.9,
            "detection_time": "2026-01-01T00:00:00Z",
            "is_valid": True,
            "is_flagged": False,
        },
        "evidence": {"full": None, "plate": None, "annotated": None},
        "evidence_mode": "metadata",
    }
    payload.update(overrides)
    return BackendQueueJob.from_dict(payload)


class TestRetryEligibility:
    @pytest.mark.parametrize("status", ["pending", "failed"])
    def test_is_retryable_job_for_pending_and_failed(self, status):
        job = _sample_job(status=status)
        assert _is_retryable_job(job) is True

    def test_is_retryable_job_for_posting_with_backend_event_id(self):
        job = _sample_job(status="posting", backend_event_id="evt-backend-1")
        assert _is_retryable_job(job) is True

    def test_is_retryable_job_false_for_succeeded(self):
        job = _sample_job(status="succeeded")
        assert _is_retryable_job(job) is False


class TestBackendToken:
    def test_token_is_valid_within_buffer(self, backend_enabled_config, project_root):
        client = BackendClient(backend_enabled_config)
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        token = BackendToken(access_token="abc", token_type="bearer", expires_at=expires)
        assert client._token_is_valid(token) is True

    def test_token_is_invalid_when_expired(self, backend_enabled_config):
        client = BackendClient(backend_enabled_config)
        expires = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        token = BackendToken(access_token="abc", token_type="bearer", expires_at=expires)
        assert client._token_is_valid(token) is False

    def test_save_and_load_token_roundtrip(self, backend_enabled_config):
        client = BackendClient(backend_enabled_config)
        token = BackendToken(
            access_token="token-value",
            token_type="bearer",
            expires_at="2099-01-01T00:00:00Z",
        )
        client.save_token(token)
        loaded = client.load_token()
        assert loaded is not None
        assert loaded.access_token == "token-value"


class TestBackendQueue:
    def test_flush_queue_when_backend_disabled(self, minimal_config):
        client = BackendClient(minimal_config)
        result = client.flush_queue()
        assert result.success is True
        assert result.processed == 0
        assert "disabled" in result.message.lower()

    def test_enqueue_and_read_queue_roundtrip(self, backend_enabled_config):
        client = BackendClient(backend_enabled_config)
        finalized_event = {
            "event_id": "local-run-track_1",
            "plate_number": "ABC1234",
            "confidence": 0.91,
            "last_seen_at": 1_700_000_000.0,
            "created_at": "2026-01-01T00:00:00Z",
            "source_type": "image",
            "evidence": {},
        }
        enqueue = client.enqueue_event(finalized_event)
        assert enqueue.success is True
        jobs, malformed = client.read_queue()
        assert malformed == 0
        assert len(jobs) == 1
        assert jobs[0].local_event_id == "local-run-track_1"

    def test_flush_queue_processes_successful_job(self, backend_enabled_config, monkeypatch):
        client = BackendClient(backend_enabled_config)
        enqueue = client.enqueue_event(
            {
                "event_id": "local-run-track_2",
                "plate_number": "PMK8811",
                "confidence": 0.88,
                "last_seen_at": 1_700_000_000.0,
                "created_at": "2026-01-01T00:00:00Z",
                "source_type": "video",
                "evidence": {},
            }
        )
        assert enqueue.success is True

        monkeypatch.setattr(client, "verify_camera_mapping", lambda: None)
        monkeypatch.setattr(
            client,
            "_process_job",
            lambda job, all_jobs=None, job_index=None: _sample_job(
                job_id=job.job_id,
                local_event_id=job.local_event_id,
                status="succeeded",
                backend_event_id="backend-evt-1",
            ),
        )

        result = client.flush_queue()
        assert isinstance(result, FlushQueueResult)
        assert result.success is True
        assert result.succeeded == 1

    def test_flush_queue_marks_exhausted_jobs(self, backend_enabled_config, monkeypatch):
        client = BackendClient(backend_enabled_config)
        exhausted_job = _sample_job(status="failed", attempts=3, max_attempts=3)
        client.write_queue([exhausted_job])
        monkeypatch.setattr(client, "verify_camera_mapping", lambda: None)

        result = client.flush_queue()
        assert result.exhausted == 1
        jobs, _ = client.read_queue()
        assert jobs[0].status == "exhausted"

    def test_flush_queue_skips_validation_failed_jobs(self, backend_enabled_config, monkeypatch):
        client = BackendClient(backend_enabled_config)
        client.write_queue([_sample_job(status="validation_failed")])
        monkeypatch.setattr(client, "verify_camera_mapping", lambda: None)

        result = client.flush_queue()
        assert result.skipped == 1
        assert result.processed == 0

    def test_malformed_queue_line_is_quarantined(self, backend_enabled_config):
        client = BackendClient(backend_enabled_config)
        queue_path = Path(backend_enabled_config.backend_queue_file)
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.write_text("{not-json}\n", encoding="utf-8")

        jobs, malformed = client.read_queue()
        assert jobs == []
        assert malformed == 1
        assert client.bad_queue_path.is_file()

    def test_build_event_payload_does_not_include_vehicle_id(self, backend_enabled_config):
        client = BackendClient(backend_enabled_config)
        payload = client.build_event_payload(
            {
                "plate_number": "abc-1234",
                "confidence": 1.5,
                "created_at": "2026-01-01T00:00:00Z",
                "source_type": "image",
            }
        )
        assert "vehicle_id" not in payload
        assert payload["plate_number"] == "ABC-1234"
        assert payload["confidence"] == 1.0
