"""Integration tests for CLI command behavior with mocked ANPR runtime."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from anpr import DryRunResult, RuntimeMetrics
from config import ValidationResult
import main


def _fake_dry_run_result(run_dir: Path) -> DryRunResult:
    events_file = run_dir / "events.jsonl"
    events_file.write_text(
        json.dumps({"event_id": "local-test-track_1", "plate_number": "ABC1234"}) + "\n",
        encoding="utf-8",
    )
    summary = {
        "status": "completed",
        "frames_read": 1,
        "frames_processed": 1,
        "events_finalized": 1,
        "events_written": 1,
        "evidence_files_saved": 3,
        "tracks_finalized": 1,
    }
    worker_log = run_dir / "worker.log"
    worker_log.write_text("ok\n", encoding="utf-8")
    worker_summary = run_dir / "worker_summary.json"
    worker_summary.write_text(json.dumps(summary), encoding="utf-8")
    return DryRunResult(
        run_dir=run_dir,
        worker_log=worker_log,
        worker_summary=worker_summary,
        events_file=events_file,
        summary=summary,
    )


class TestCliIntegration:
    def test_check_config_command(self, minimal_config, sample_image, monkeypatch):
        minimal_config.image_path = str(sample_image)
        monkeypatch.setattr(main, "Config", type("C", (), {"from_env": staticmethod(lambda: minimal_config)}))
        code = main.main(["check-config"])
        assert code == 0

    def test_run_image_dry_run_strict_with_mocked_processor(
        self, minimal_config, sample_image, fake_model_files, monkeypatch, project_root
    ):
        minimal_config.image_path = str(sample_image)
        run_dir = project_root / "runs/run_test"
        run_dir.mkdir(parents=True)

        class FakeProcessor:
            def __init__(self, config):
                self.config = config

            def run_dry_run(self, validation_result, *, strict=False):
                return _fake_dry_run_result(run_dir)

        monkeypatch.setattr(main, "Config", type("C", (), {"from_env": staticmethod(lambda: minimal_config)}))
        monkeypatch.setattr(main, "ANPRProcessor", FakeProcessor)

        code = main.main(
            [
                "run",
                "--source",
                "image",
                "--image",
                str(sample_image),
                "--dry-run",
                "--strict",
            ]
        )
        assert code == 0
        assert (run_dir / "events.jsonl").is_file()
        assert (run_dir / "worker_summary.json").is_file()

    def test_run_video_dry_run_strict_with_mocked_processor(
        self, minimal_config, sample_video, fake_model_files, monkeypatch, project_root
    ):
        minimal_config.video_path = str(sample_video)
        minimal_config.source = "video"
        run_dir = project_root / "runs/run_video"
        run_dir.mkdir(parents=True)

        class FakeProcessor:
            def __init__(self, config):
                self.config = config

            def run_dry_run(self, validation_result, *, strict=False):
                result = _fake_dry_run_result(run_dir)
                result.summary["tracks_finalized_source_end"] = 1
                return result

        monkeypatch.setattr(main, "Config", type("C", (), {"from_env": staticmethod(lambda: minimal_config)}))
        monkeypatch.setattr(main, "ANPRProcessor", FakeProcessor)

        code = main.main(
            [
                "run",
                "--source",
                "video",
                "--video",
                str(sample_video),
                "--dry-run",
                "--strict",
            ]
        )
        assert code == 0

    def test_flush_backend_queue_disabled(self, minimal_config, monkeypatch):
        monkeypatch.setattr(main, "Config", type("C", (), {"from_env": staticmethod(lambda: minimal_config)}))
        code = main.main(["flush-backend-queue"])
        assert code == 0

    def test_flush_backend_queue_with_fake_client(self, backend_enabled_config, monkeypatch):
        class FakeClient:
            def __init__(self, config):
                self.config = config

            def flush_queue(self):
                from backend import FlushQueueResult

                return FlushQueueResult(
                    success=True,
                    message="Backend queue flush completed.",
                    processed=1,
                    succeeded=1,
                )

        monkeypatch.setattr(main, "Config", type("C", (), {"from_env": staticmethod(lambda: backend_enabled_config)}))
        monkeypatch.setattr(main, "BackendClient", FakeClient)
        code = main.main(["flush-backend-queue"])
        assert code == 0

    def test_dry_run_does_not_enqueue_backend_jobs(self, minimal_config, sample_image, monkeypatch, project_root):
        minimal_config.image_path = str(sample_image)
        minimal_config.backend_enabled = False
        run_dir = project_root / "runs/run_no_backend"
        run_dir.mkdir(parents=True)
        enqueue_called = {"value": False}

        class FakeProcessor:
            def __init__(self, config):
                self.config = config
                self._backend_client = None

            def run_dry_run(self, validation_result, *, strict=False):
                assert self._backend_client is None
                return _fake_dry_run_result(run_dir)

        class SpyBackendClient:
            def __init__(self, config):
                enqueue_called["value"] = True

        monkeypatch.setattr(main, "Config", type("C", (), {"from_env": staticmethod(lambda: minimal_config)}))
        monkeypatch.setattr(main, "ANPRProcessor", FakeProcessor)
        monkeypatch.setattr(main, "BackendClient", SpyBackendClient)

        code = main.main(
            [
                "run",
                "--source",
                "image",
                "--image",
                str(sample_image),
                "--dry-run",
            ]
        )
        assert code == 0
        assert enqueue_called["value"] is False
