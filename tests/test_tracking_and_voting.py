"""Unit tests for tracking, voting, finalization, and duplicate cooldown."""

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
    calculate_iou,
    create_track,
    match_detection_to_track,
    select_best_plate_for_track,
)
from config import Config


def _packet(timestamp: float = 1.0, frame_index: int = 0, is_last: bool = False) -> FramePacket:
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    return FramePacket(
        frame_index=frame_index,
        timestamp=timestamp,
        image=image,
        source_type="video",
        source_path="samples/videos/test.mp4",
        is_last=is_last,
    )


def _track_with_votes(
    track_id: int = 1,
    votes: list[tuple[str, float, float]] | None = None,
) -> TrackState:
    track = TrackState(
        track_id=track_id,
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


class TestIoUAndTracking:
    def test_calculate_iou_identical_boxes(self):
        box = (0, 0, 100, 100)
        assert calculate_iou(box, box) == pytest.approx(1.0)

    def test_calculate_iou_disjoint_boxes(self):
        assert calculate_iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0

    def test_match_detection_to_track_prefers_highest_iou(self):
        detection = Detection(bbox=(12, 12, 48, 48), confidence=0.9)
        tracks = {
            1: TrackState(
                track_id=1,
                bbox=(10, 10, 50, 50),
                first_seen_at=0.0,
                last_seen_at=0.0,
                first_frame_index=0,
                last_frame_index=0,
            ),
            2: TrackState(
                track_id=2,
                bbox=(80, 80, 95, 95),
                first_seen_at=0.0,
                last_seen_at=0.0,
                first_frame_index=0,
                last_frame_index=0,
            ),
        }
        matched = match_detection_to_track(detection, tracks, iou_threshold=0.3)
        assert matched is not None
        assert matched.track_id == 1

    def test_create_track_uses_packet_timestamps(self):
        packet = _packet(timestamp=3.5, frame_index=7)
        detection = Detection(bbox=(1, 2, 3, 4), confidence=0.8)
        track = create_track(detection, packet, track_id=9)
        assert track.track_id == 9
        assert track.first_seen_at == 3.5
        assert track.last_frame_index == 7


class TestVoteSelection:
    def test_select_best_plate_for_track_majority_wins(self):
        track = _track_with_votes(
            votes=[
                ("ABC1234", 0.95, 1.0),
                ("ABC1234", 0.93, 1.1),
                ("XYZ9999", 0.99, 1.2),
            ]
        )
        result = select_best_plate_for_track(track)
        assert result == ("ABC1234", pytest.approx(0.94), 2)

    def test_select_best_plate_for_track_empty_returns_none(self):
        track = _track_with_votes(votes=[])
        assert select_best_plate_for_track(track) is None


class TestFinalizationBehavior:
    def _processor(self, **overrides) -> ANPRProcessor:
        config = Config(
            min_plate_votes=2,
            early_finalize_min_votes=3,
            early_finalize_min_confidence=0.90,
            track_expiry_seconds=2.0,
            duplicate_cooldown_seconds=10.0,
            source="video",
            runs_dir="runs",
        )
        for key, value in overrides.items():
            setattr(config, key, value)
        processor = ANPRProcessor(config)
        processor._run_dir = Path("runs/test_run")
        processor._events_file = processor._run_dir / "events.jsonl"
        processor._events_file.parent.mkdir(parents=True, exist_ok=True)
        processor._events_file.write_text("", encoding="utf-8")
        processor._run_id = "test_run"
        processor._dry_run = True
        processor._ensure_evidence_dirs(processor._run_dir)
        return processor

    def test_should_finalize_track_early_high_confidence(self):
        processor = self._processor()
        track = _track_with_votes(
            votes=[
                ("PMK8811", 0.95, 1.0),
                ("PMK8811", 0.94, 1.1),
                ("PMK8811", 0.93, 1.2),
            ]
        )
        should, reason = processor.should_finalize_track(track, _packet())
        assert should is True
        assert reason == "early_high_confidence"

    def test_finalize_track_source_end_requires_min_votes(self):
        processor = self._processor(min_plate_votes=2)
        metrics = RuntimeMetrics()
        track = _track_with_votes(votes=[("JKE9900", 0.9, 1.0)])
        result = processor.finalize_track(track, "source_end", metrics)
        assert result is None
        assert track.finalized is True
        assert metrics.track_finalizations_rejected == 1

    def test_finalize_track_source_end_image_allows_single_vote(self):
        processor = self._processor(source="image", min_plate_votes=2)
        metrics = RuntimeMetrics()
        track = _track_with_votes(votes=[("JKE9900", 0.9, 1.0)])
        result = processor.finalize_track(track, "source_end", metrics)
        assert result is not None
        assert result.plate_number == "JKE9900"
        assert metrics.tracks_finalized_source_end == 1

    def test_finalize_expired_tracks(self):
        processor = self._processor(track_expiry_seconds=2.0, min_plate_votes=1)
        metrics = RuntimeMetrics()
        track = _track_with_votes(
            votes=[("WXY1234", 0.9, 0.0), ("WXY1234", 0.9, 0.5)]
        )
        track.last_seen_at = 0.0
        processor._tracks[track.track_id] = track
        processor.finalize_expired_tracks(_packet(timestamp=3.0), metrics)
        assert metrics.tracks_finalized_expired == 1

    def test_finalize_active_tracks_at_source_end(self):
        processor = self._processor(min_plate_votes=1)
        metrics = RuntimeMetrics()
        track = _track_with_votes(votes=[("ABC1001", 0.92, 1.0), ("ABC1001", 0.91, 1.1)])
        processor._tracks[track.track_id] = track
        processor.finalize_active_tracks_at_source_end(_packet(is_last=True), metrics)
        assert metrics.tracks_finalized_source_end == 1

    def test_duplicate_cooldown_suppresses_second_event(self):
        processor = self._processor(duplicate_cooldown_seconds=10.0, min_plate_votes=1)
        metrics = RuntimeMetrics()
        track = _track_with_votes(votes=[("ABC1001", 0.95, 1.0), ("ABC1001", 0.94, 1.1)])
        processor._tracks[track.track_id] = track
        processor.finalize_track(track, "source_end", metrics)
        assert metrics.events_written == 1

        track2 = _track_with_votes(track_id=2, votes=[("ABC1001", 0.96, 5.0), ("ABC1001", 0.95, 5.1)])
        processor._tracks[track2.track_id] = track2
        processor.finalize_track(track2, "source_end", metrics)
        assert metrics.duplicate_events_suppressed == 1
        assert metrics.events_written == 1
