"""Unit tests for M15 OCR throttle and performance summary helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from anpr import (
    ANPRProcessor,
    Detection,
    FramePacket,
    PlateVote,
    RuntimeMetrics,
    TrackState,
)
from config import Config, ValidationResult


def _packet(timestamp: float = 1.0) -> FramePacket:
    return FramePacket(
        frame_index=0,
        timestamp=timestamp,
        image=np.zeros((80, 80, 3), dtype=np.uint8),
        source_type="video",
        source_path="samples/videos/test.mp4",
    )


def _track_with_votes(votes: list[tuple[str, float, float]] | None = None) -> TrackState:
    track = TrackState(
        track_id=1,
        bbox=(10, 10, 50, 50),
        first_seen_at=0.0,
        last_seen_at=0.0,
        first_frame_index=0,
        last_frame_index=0,
    )
    for index, (plate, confidence, ts) in enumerate(votes or []):
        track.plate_votes.append(
            PlateVote(
                plate_text=plate,
                raw_text=plate,
                confidence=confidence,
                timestamp=ts,
                frame_index=index,
                plate_bbox=(20, 20, 40, 40),
                vehicle_bbox=(10, 10, 50, 50),
            )
        )
    return track


class TestOcrThrottle:
    def test_should_not_throttle_without_existing_votes(self):
        processor = ANPRProcessor(Config(ocr_min_interval_seconds=0.35))
        track = _track_with_votes()
        assert processor.should_throttle_ocr_for_track(track, timestamp=1.0) is False

    def test_should_throttle_when_interval_not_elapsed(self):
        processor = ANPRProcessor(Config(ocr_min_interval_seconds=0.35))
        track = _track_with_votes([("ABC1234", 0.9, 0.5)])
        track.last_ocr_at = 1.0
        assert processor.should_throttle_ocr_for_track(track, timestamp=1.2) is True

    def test_should_not_throttle_after_interval_elapsed(self):
        processor = ANPRProcessor(Config(ocr_min_interval_seconds=0.35))
        track = _track_with_votes([("ABC1234", 0.9, 0.5)])
        track.last_ocr_at = 1.0
        assert processor.should_throttle_ocr_for_track(track, timestamp=1.4) is False

    def test_throttle_disabled_when_interval_zero(self):
        processor = ANPRProcessor(Config(ocr_min_interval_seconds=0.0))
        track = _track_with_votes([("ABC1234", 0.9, 0.5)])
        track.last_ocr_at = 1.0
        assert processor.should_throttle_ocr_for_track(track, timestamp=1.1) is False


class TestPerformanceSummary:
    def _processor(self) -> ANPRProcessor:
        config = Config(source="video", runs_dir="runs")
        processor = ANPRProcessor(config)
        processor._run_dir = Path("runs/test_run")
        return processor

    def test_build_summary_includes_m15_metrics(self):
        processor = self._processor()
        metrics = RuntimeMetrics(
            frames_read=30,
            frames_processed=15,
            duration_seconds=5.0,
            ocr_calls=10,
            plate_candidates=8,
            events_finalized=2,
            ocr_calls_skipped_by_throttle=4,
            models_loaded=True,
            event_latencies_seconds=[2.5, 3.1],
        )
        summary = processor._build_summary(
            Path("runs/test_run"),
            ValidationResult(),
            metrics,
            strict=False,
            status="completed",
        )
        assert summary["milestone"] == "M15"
        assert summary["processed_fps"] == 3.0
        assert summary["effective_read_fps"] == 6.0
        assert summary["average_event_latency_seconds"] == 2.8
        assert summary["max_event_latency_seconds"] == 3.1
        assert summary["ocr_calls_skipped_by_throttle"] == 4
        assert summary["tuning_profile"]["ocr_min_interval_seconds"] == 0.35
        assert summary["performance_targets"]["processed_fps"] == "3-5"
        assert summary["performance_target_results"]["backend_posting_non_blocking"] is True

    def test_event_latency_recorded_on_track_expiry(self):
        processor = self._processor()
        metrics = RuntimeMetrics()
        track = _track_with_votes(
            [("ABC1234", 0.9, 0.0), ("ABC1234", 0.9, 0.5)]
        )
        track.last_seen_at = 1.0
        processor._tracks[track.track_id] = track
        processor.finalize_expired_tracks(_packet(timestamp=3.5), metrics)
        assert metrics.event_latencies_seconds == [pytest.approx(2.5)]
