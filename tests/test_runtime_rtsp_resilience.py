"""Unit tests for RTSP reconnect and shutdown behavior without a real camera."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from anpr import ANPRProcessor, RuntimeMetrics
from config import Config, mask_rtsp_url


class TestRtspResilience:
    def _rtsp_processor(self) -> ANPRProcessor:
        config = Config(
            source="rtsp",
            rtsp_url="rtsp://user:secret@192.168.1.50:554/stream1",
            rtsp_reconnect_enabled=True,
            rtsp_reconnect_max_attempts=2,
            rtsp_reconnect_initial_delay_seconds=0.01,
            rtsp_reconnect_max_delay_seconds=0.05,
            runs_dir="runs",
        )
        return ANPRProcessor(config)

    def test_attempt_rtsp_reconnect_succeeds_on_second_try(self, monkeypatch):
        processor = self._rtsp_processor()
        metrics = RuntimeMetrics()
        attempts = {"count": 0}

        class FakeCapture:
            def __init__(self, url):
                attempts["count"] += 1
                self.url = url

            def isOpened(self):
                return attempts["count"] >= 2

        monkeypatch.setattr("anpr.cv2.VideoCapture", FakeCapture)
        monkeypatch.setattr(processor, "close_source", lambda: None)
        monkeypatch.setattr("anpr.time.sleep", lambda _seconds: None)

        assert processor._attempt_rtsp_reconnect(metrics) is True
        assert metrics.rtsp_reconnect_attempts == 2
        assert metrics.rtsp_reconnect_successes == 1

    def test_attempt_rtsp_reconnect_exhausted_stops_runtime(self, monkeypatch):
        processor = self._rtsp_processor()
        metrics = RuntimeMetrics()

        class FailingCapture:
            def __init__(self, url):
                self.url = url

            def isOpened(self):
                return False

        monkeypatch.setattr("anpr.cv2.VideoCapture", FailingCapture)
        monkeypatch.setattr(processor, "close_source", lambda: None)
        monkeypatch.setattr("anpr.time.sleep", lambda _seconds: None)

        assert processor._attempt_rtsp_reconnect(metrics) is False
        assert processor._stop_reason == "rtsp_reconnect_exhausted"
        assert metrics.rtsp_reconnect_attempts == 3

    def test_request_stop_sets_shutdown_reason(self):
        processor = self._rtsp_processor()
        processor.request_stop("manual_shutdown")
        assert processor._stop_requested is True
        assert processor._stop_reason == "manual_shutdown"

    def test_source_label_masks_rtsp_credentials(self):
        processor = self._rtsp_processor()
        label = processor._source_label()
        assert "secret" not in label
        assert mask_rtsp_url(processor.config.rtsp_url) in label

    def test_finalize_active_tracks_on_shutdown_runs_once(self):
        processor = self._rtsp_processor()
        metrics = RuntimeMetrics()
        from anpr import FramePacket
        import numpy as np

        packet = FramePacket(
            frame_index=0,
            timestamp=1.0,
            image=np.zeros((10, 10, 3), dtype=np.uint8),
            source_type="rtsp",
            source_path="ANPR_RTSP_URL",
            is_last=True,
        )
        processor.request_stop("manual_shutdown")
        processor.finalize_active_tracks_on_shutdown(packet, metrics)
        processor.finalize_active_tracks_on_shutdown(packet, metrics)
        assert processor._shutdown_tracks_finalized is True
