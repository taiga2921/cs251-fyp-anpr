"""ANPR runtime with M9 evidence delivery architecture."""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from config import Config, ValidationResult
from backend import BackendClient, FlushQueueResult

ASSUMED_VIDEO_FPS = 30.0
VEHICLE_CLASS_NAMES = frozenset({"car", "motorcycle", "bus", "truck"})
MALAYSIAN_PLATE_PATTERN = re.compile(r"^[A-Z]{1,4}[0-9]{1,4}[A-Z]?$")


class SourceRuntimeError(Exception):
    """Raised when a source cannot be opened or read."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ModelLoadError(SourceRuntimeError):
    """Raised when configured models cannot be loaded."""


class OCRLoadError(SourceRuntimeError):
    """Raised when the OCR engine cannot be initialized."""


@dataclass
class FramePacket:
    """Unified frame contract for all source types."""

    frame_index: int
    timestamp: float
    image: np.ndarray
    source_type: str
    source_path: str | None
    is_last: bool = False


@dataclass
class Detection:
    """Normalized detection result in full-frame coordinates."""

    bbox: tuple[int, int, int, int]
    confidence: float
    class_id: int | None = None
    class_name: str | None = None


@dataclass
class OCRReading:
    """Raw OCR output for a plate crop."""

    raw_text: str
    confidence: float


@dataclass
class PlateCandidate:
    """Normalized and validated plate candidate (not persisted as events in M5)."""

    raw_text: str
    normalized_text: str
    confidence: float
    plate_bbox: tuple[int, int, int, int]
    vehicle_bbox: tuple[int, int, int, int] | None = None


@dataclass
class PlateVote:
    """Single OCR vote attached to a vehicle track."""

    plate_text: str
    raw_text: str
    confidence: float
    timestamp: float
    frame_index: int
    plate_bbox: tuple[int, int, int, int]
    vehicle_bbox: tuple[int, int, int, int] | None = None


@dataclass
class TrackState:
    """In-memory vehicle track with vote buffer and best evidence state."""

    track_id: int
    bbox: tuple[int, int, int, int]
    first_seen_at: float
    last_seen_at: float
    first_frame_index: int
    last_frame_index: int
    plate_votes: list[PlateVote] = field(default_factory=list)
    best_plate_crop: np.ndarray | None = None
    best_full_frame: np.ndarray | None = None
    best_annotated_frame: np.ndarray | None = None
    best_confidence: float = 0.0
    decision_finalized: bool = False
    finalized: bool = False
    finalization_reason: str | None = None


@dataclass
class FinalizedTrackCandidate:
    """Track-level plate decision finalized in memory."""

    track_id: int
    plate_number: str
    confidence: float
    votes: int
    first_seen_at: float
    last_seen_at: float
    finalization_reason: str


@dataclass
class FinalizedEvent:
    """Persisted local ANPR event record (M6)."""

    event_id: str
    run_id: str
    track_id: int
    plate_number: str
    confidence: float
    votes: int
    first_seen_at: float
    last_seen_at: float
    first_frame_index: int | None
    last_frame_index: int | None
    finalization_reason: str
    source_type: str
    source_path: str | None
    vehicle_bbox: tuple[int, int, int, int] | None
    plate_bbox: tuple[int, int, int, int] | None
    evidence: dict[str, str | None]
    backend: dict[str, object]
    dry_run: bool
    created_at: str


@dataclass
class RuntimeMetrics:
    """Collected metrics during a dry-run execution."""

    frames_read: int = 0
    frames_processed: int = 0
    source_opened: bool = False
    source_completed: bool = False
    source_fps: float | None = None
    assumed_source_fps: float | None = None
    frame_skip_interval: int | None = None
    stop_reason: str = "unknown"
    duration_seconds: float = 0.0
    runtime_error: str | None = None
    runtime_warnings: list[str] = field(default_factory=list)
    log_lines: list[str] = field(default_factory=list)
    models_loaded: bool = False
    vehicle_model: str = ""
    plate_model: str = ""
    device: str = "cpu"
    vehicle_detection_calls: int = 0
    plate_detection_calls: int = 0
    vehicle_detections: int = 0
    plate_detections: int = 0
    vehicle_detect_ms_total: float = 0.0
    plate_detect_ms_total: float = 0.0
    plate_crops_extracted: int = 0
    plate_crops_rejected: int = 0
    ocr_engine_loaded: bool = False
    ocr_calls: int = 0
    ocr_readings: int = 0
    plate_candidates: int = 0
    plate_candidates_rejected: int = 0
    ocr_ms_total: float = 0.0
    tracks_created: int = 0
    tracks_updated: int = 0
    active_tracks: int = 0
    tracks_finalized: int = 0
    tracks_finalized_early: int = 0
    tracks_finalized_expired: int = 0
    tracks_finalized_source_end: int = 0
    track_finalizations_rejected: int = 0
    plate_votes_added: int = 0
    decision_finalized_tracks_skipped: int = 0
    events_finalized: int = 0
    events_written: int = 0
    evidence_files_saved: int = 0
    evidence_save_failures: int = 0
    duplicate_events_suppressed: int = 0
    backend_jobs_queued: int = 0
    backend_jobs_succeeded: int = 0
    backend_jobs_failed: int = 0
    backend_jobs_exhausted: int = 0
    backend_logs_sent: int = 0
    backend_camera_verified: bool = False
    backend_images_sent: int = 0
    local_evidence_deleted: int = 0


@dataclass
class DryRunResult:
    """Summary returned after a dry-run execution."""

    run_dir: Path
    worker_log: Path
    worker_summary: Path
    events_file: Path
    summary: dict


def _fps_is_valid(raw_fps: float) -> bool:
    return raw_fps > 0 and math.isfinite(raw_fps) and not math.isnan(raw_fps)


def _clip_bbox(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    ix1 = max(0, int(round(x1)))
    iy1 = max(0, int(round(y1)))
    ix2 = min(width, int(round(x2)))
    iy2 = min(height, int(round(y2)))
    if ix2 <= ix1 or iy2 <= iy1:
        return None
    return ix1, iy1, ix2, iy2


def extract_plate_crop(frame: np.ndarray, plate_detection: Detection) -> np.ndarray | None:
    """Extract a plate crop from a full frame using a plate detection bbox."""
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = plate_detection.bbox
    bbox = _clip_bbox(x1, y1, x2, y2, width, height)
    if bbox is None:
        return None
    cx1, cy1, cx2, cy2 = bbox
    crop = frame[cy1:cy2, cx1:cx2]
    if crop.size == 0:
        return None
    return crop


def preprocess_plate(crop: np.ndarray, scale: float = 2.0) -> np.ndarray:
    """Apply simple deterministic preprocessing for OCR."""
    if len(crop.shape) == 3:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    else:
        gray = crop.copy()

    if scale > 0 and scale != 1.0:
        gray = cv2.resize(
            gray,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )

    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
    sharpened = cv2.filter2D(gray, -1, kernel)
    return sharpened


def normalize_plate_text(raw_text: str) -> str:
    """Normalize plate text to uppercase alphanumeric characters only."""
    upper = raw_text.upper()
    return re.sub(r"[^A-Z0-9]", "", upper)


def validate_plate_text(normalized_text: str) -> tuple[bool, str | None]:
    """Validate a normalized plate string against conservative Malaysian rules."""
    if not normalized_text:
        return False, "empty plate text"
    if len(normalized_text) < 4:
        return False, "plate text too short"
    if len(normalized_text) > 10:
        return False, "plate text too long"
    if not re.search(r"[A-Z]", normalized_text):
        return False, "plate text has no letters"
    if not re.search(r"[0-9]", normalized_text):
        return False, "plate text has no digits"
    if not MALAYSIAN_PLATE_PATTERN.match(normalized_text):
        return False, "plate text does not match Malaysian private-vehicle pattern"
    return True, None


def calculate_iou(
    bbox_a: tuple[int, int, int, int],
    bbox_b: tuple[int, int, int, int],
) -> float:
    """Compute intersection-over-union for two axis-aligned bounding boxes."""
    ax1, ay1, ax2, ay2 = bbox_a
    bx1, by1, bx2, by2 = bbox_b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0
    inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    union = area_a + area_b - inter_area
    if union <= 0:
        return 0.0
    return inter_area / union


def match_detection_to_track(
    detection: Detection,
    tracks: dict[int, TrackState],
    iou_threshold: float,
    exclude_track_ids: set[int] | None = None,
) -> TrackState | None:
    """Return the best matchable track for a detection by IoU (one-to-one per frame)."""
    exclude_track_ids = exclude_track_ids or set()
    best_track: TrackState | None = None
    best_iou = 0.0
    for track in tracks.values():
        if track.track_id in exclude_track_ids:
            continue
        if track.finalized:
            continue
        iou = calculate_iou(track.bbox, detection.bbox)
        if iou > best_iou:
            best_iou = iou
            best_track = track
    if best_track is not None and best_iou >= iou_threshold:
        return best_track
    return None


def create_track(
    detection: Detection,
    packet: FramePacket,
    track_id: int,
) -> TrackState:
    """Create a new in-memory vehicle track."""
    return TrackState(
        track_id=track_id,
        bbox=detection.bbox,
        first_seen_at=packet.timestamp,
        last_seen_at=packet.timestamp,
        first_frame_index=packet.frame_index,
        last_frame_index=packet.frame_index,
    )


def select_best_plate_for_track(track: TrackState) -> tuple[str, float, int] | None:
    """
    Select the winning plate text for a track using deterministic majority voting.

    Tie-break order: vote count, average confidence, best confidence,
    most recent vote, lexicographic plate text.
    """
    if not track.plate_votes:
        return None

    groups: dict[str, list[PlateVote]] = {}
    for vote in track.plate_votes:
        groups.setdefault(vote.plate_text, []).append(vote)

    def sort_key(item: tuple[str, list[PlateVote]]) -> tuple:
        plate_text, votes = item
        vote_count = len(votes)
        avg_confidence = sum(v.confidence for v in votes) / vote_count
        best_confidence = max(v.confidence for v in votes)
        most_recent = max(v.timestamp for v in votes)
        return (
            vote_count,
            avg_confidence,
            best_confidence,
            most_recent,
            plate_text,
        )

    best_plate, best_votes = max(groups.items(), key=sort_key)
    avg_confidence = sum(v.confidence for v in best_votes) / len(best_votes)
    return best_plate, avg_confidence, len(best_votes)


def _annotate_evidence_frame(
    frame: np.ndarray,
    track_id: int,
    plate_text: str,
    plate_bbox: tuple[int, int, int, int],
    vehicle_bbox: tuple[int, int, int, int] | None,
    confidence: float | None = None,
) -> np.ndarray:
    """Draw vehicle/plate boxes, track id, plate text, and confidence on a frame copy."""
    annotated = frame.copy()
    if vehicle_bbox is not None:
        vx1, vy1, vx2, vy2 = vehicle_bbox
        cv2.rectangle(annotated, (vx1, vy1), (vx2, vy2), (0, 255, 0), 2)
        cv2.putText(
            annotated,
            f"track {track_id}",
            (vx1, max(vy1 - 8, 0)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
        )
    px1, py1, px2, py2 = plate_bbox
    cv2.rectangle(annotated, (px1, py1), (px2, py2), (0, 0, 255), 2)
    label = plate_text
    if confidence is not None:
        label = f"{plate_text} {confidence:.2f}"
    cv2.putText(
        annotated,
        label,
        (px1, min(py2 + 20, annotated.shape[0] - 1)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 0, 255),
        2,
    )
    return annotated


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_backend_state() -> dict[str, object]:
    return {
        "queued": False,
        "posted": False,
        "event_id": None,
        "images_sent": 0,
        "error": None,
    }


def _backend_state_queued() -> dict[str, object]:
    return {
        "queued": True,
        "posted": False,
        "event_id": None,
        "images_sent": 0,
        "error": None,
    }


def _backend_state_enqueue_failed(error: str) -> dict[str, object]:
    return {
        "queued": False,
        "posted": False,
        "event_id": None,
        "images_sent": 0,
        "error": error,
    }


def finalized_event_to_dict(event: FinalizedEvent) -> dict[str, object]:
    """Convert a FinalizedEvent to a JSON-serializable dict."""
    payload: dict[str, object] = {}
    for item in fields(event):
        value = getattr(event, item.name)
        if isinstance(value, tuple):
            payload[item.name] = list(value)
        elif isinstance(value, Path):
            payload[item.name] = str(value).replace("\\", "/")
        else:
            payload[item.name] = value
    return payload


class ANPRProcessor:
    """ANPR processor with source reading, scheduling, and YOLO detection."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._capture: cv2.VideoCapture | None = None
        self._source_fps: float | None = None
        self._assumed_source_fps: float | None = None
        self._frame_skip_interval: int | None = None
        self._use_wall_clock: bool = False
        self._last_processed_time: float | None = None
        self._stop_reason: str = "unknown"
        self._vehicle_model: Any = None
        self._plate_model: Any = None
        self._models_loaded: bool = False
        self._ocr_engine: Any = None
        self._run_candidates: list[PlateCandidate] = []
        self._tracks: dict[int, TrackState] = {}
        self._next_track_id: int = 1
        self._finalized_track_candidates: list[FinalizedTrackCandidate] = []
        self._finalized_events: list[FinalizedEvent] = []
        self._run_dir: Path | None = None
        self._run_id: str = ""
        self._events_file: Path | None = None
        self._evidence_dirs: dict[str, Path] = {}
        self._plate_last_event_at: dict[str, float] = {}
        self._dry_run: bool = True
        self._backend_client: BackendClient | None = None

    def _make_run_dir(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = self.config.runs_dir_path() / f"run_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _source_label(self) -> str:
        if self.config.source == "webcam":
            return f"webcam index {self.config.camera_index}"
        if self.config.source == "rtsp":
            return "RTSP stream (ANPR_RTSP_URL)"
        source_path = self._safe_source_path()
        return source_path or self.config.source

    def _safe_source_path(self) -> str | None:
        if self.config.source == "rtsp":
            return "ANPR_RTSP_URL"
        if self.config.source == "video":
            return self.config.video_path
        if self.config.source == "image":
            return self.config.image_path
        if self.config.source == "webcam":
            return str(self.config.camera_index)
        return None

    def _ensure_device_available(self) -> None:
        if self.config.device != "cuda":
            return
        try:
            import torch
        except ImportError as exc:
            raise ModelLoadError(
                "ANPR_DEVICE=cuda but PyTorch is not available."
            ) from exc
        if not torch.cuda.is_available():
            raise ModelLoadError(
                "ANPR_DEVICE=cuda but CUDA is not available on this system. "
                "Use ANPR_DEVICE=cpu."
            )

    def load_models(self, metrics: RuntimeMetrics) -> None:
        """Load vehicle and plate YOLO models once per runtime."""
        vehicle_path = Path(self.config.vehicle_model)
        plate_path = Path(self.config.plate_model)

        if not vehicle_path.is_file():
            raise ModelLoadError(
                f"Vehicle model file not found: {self.config.vehicle_model}"
            )
        if not plate_path.is_file():
            raise ModelLoadError(
                f"Plate model file not found: {self.config.plate_model}"
            )

        self._ensure_device_available()
        metrics.log_lines.append("Model loading started.")

        try:
            from ultralytics import YOLO

            self._vehicle_model = YOLO(str(vehicle_path))
            metrics.log_lines.append(f"Vehicle model loaded: {self.config.vehicle_model}")
            self._plate_model = YOLO(str(plate_path))
            metrics.log_lines.append(f"Plate model loaded: {self.config.plate_model}")
        except Exception as exc:
            raise ModelLoadError(f"Failed to load YOLO models: {exc}") from exc

        self._models_loaded = True
        metrics.models_loaded = True
        metrics.vehicle_model = self.config.vehicle_model
        metrics.plate_model = self.config.plate_model
        metrics.device = self.config.device
        metrics.log_lines.append(f"Device: {self.config.device}")

    def load_ocr_engine(self, metrics: RuntimeMetrics) -> None:
        """Initialize the OCR engine once per runtime.

        M4 uses PaddleOCR 2.x legacy API for stable local crop OCR:
        PaddleOCR(...).ocr(image, cls=False)
        """
        if self.config.ocr_engine != "paddleocr":
            raise OCRLoadError(f"Unsupported OCR engine: {self.config.ocr_engine}")

        metrics.log_lines.append("OCR engine loading started.")
        try:
            from paddleocr import PaddleOCR

            self._ocr_engine = PaddleOCR(
                use_angle_cls=False,
                lang=self.config.ocr_lang,
                show_log=False,
            )
        except ImportError as exc:
            raise OCRLoadError(
                "PaddleOCR is not installed. Install with: pip install -r requirements.txt"
            ) from exc
        except Exception as exc:
            raise OCRLoadError(f"Failed to initialize PaddleOCR: {exc}") from exc

        metrics.ocr_engine_loaded = True
        metrics.log_lines.append(
            f"OCR engine loaded: {self.config.ocr_engine} (PaddleOCR 2.x legacy API)"
        )

    def read_plate_text(
        self,
        plate_crop: np.ndarray,
        metrics: RuntimeMetrics,
    ) -> OCRReading | None:
        """Run OCR on a plate crop and return the best reading."""
        if self._ocr_engine is None:
            raise OCRLoadError("OCR engine is not loaded.")

        metrics.ocr_calls += 1
        start = time.perf_counter()

        image = plate_crop
        if len(plate_crop.shape) == 2:
            image = cv2.cvtColor(plate_crop, cv2.COLOR_GRAY2BGR)

        try:
            result = self._ocr_engine.ocr(image, cls=False)
        except Exception as exc:
            raise SourceRuntimeError(f"OCR failed: {exc}") from exc
        finally:
            metrics.ocr_ms_total += (time.perf_counter() - start) * 1000.0

        if not result or result[0] is None:
            return None

        fragments: list[tuple[str, float]] = []
        for line in result[0]:
            if not line or len(line) < 2:
                continue
            text_info = line[1]
            if not text_info or len(text_info) < 2:
                continue
            text = str(text_info[0]).strip()
            confidence = float(text_info[1])
            if text:
                fragments.append((text, confidence))

        if not fragments:
            return None

        if len(fragments) == 1:
            metrics.ocr_readings += 1
            return OCRReading(raw_text=fragments[0][0], confidence=fragments[0][1])

        fragments.sort(key=lambda item: item[1], reverse=True)
        combined_text = "".join(text for text, _ in fragments)
        avg_confidence = sum(conf for _, conf in fragments) / len(fragments)
        metrics.ocr_readings += 1
        return OCRReading(raw_text=combined_text, confidence=avg_confidence)

    def _process_plate_detection(
        self,
        frame: np.ndarray,
        plate_detection: Detection,
        vehicle_detection: Detection | None,
        metrics: RuntimeMetrics,
    ) -> PlateCandidate | None:
        """Extract, preprocess, OCR, normalize, and validate a plate detection."""
        crop = extract_plate_crop(frame, plate_detection)
        if crop is None:
            metrics.plate_crops_rejected += 1
            return None

        metrics.plate_crops_extracted += 1
        ocr_input = (
            preprocess_plate(crop, self.config.ocr_scale)
            if self.config.ocr_preprocess
            else crop
        )
        reading = self.read_plate_text(ocr_input, metrics)
        if reading is None or reading.confidence < self.config.min_ocr_confidence:
            metrics.plate_candidates_rejected += 1
            return None

        normalized = normalize_plate_text(reading.raw_text)
        valid, _reason = validate_plate_text(normalized)
        if not valid:
            metrics.plate_candidates_rejected += 1
            return None

        metrics.plate_candidates += 1
        return PlateCandidate(
            raw_text=reading.raw_text,
            normalized_text=normalized,
            confidence=reading.confidence,
            plate_bbox=plate_detection.bbox,
            vehicle_bbox=vehicle_detection.bbox if vehicle_detection else None,
        )

    def update_tracks(
        self,
        vehicle_detections: list[Detection],
        packet: FramePacket,
        metrics: RuntimeMetrics,
    ) -> list[tuple[TrackState, Detection]]:
        """Match vehicle detections to tracks via IoU (one track per detection per frame)."""
        matched: list[tuple[TrackState, Detection]] = []
        assigned_track_ids: set[int] = set()
        sorted_detections = sorted(
            vehicle_detections,
            key=lambda detection: detection.confidence,
            reverse=True,
        )
        for detection in sorted_detections:
            track = match_detection_to_track(
                detection,
                self._tracks,
                self.config.track_iou_threshold,
                exclude_track_ids=assigned_track_ids,
            )
            if track is not None:
                track.bbox = detection.bbox
                track.last_seen_at = packet.timestamp
                track.last_frame_index = packet.frame_index
                metrics.tracks_updated += 1
                assigned_track_ids.add(track.track_id)
            else:
                track = create_track(detection, packet, self._next_track_id)
                self._tracks[track.track_id] = track
                self._next_track_id += 1
                metrics.tracks_created += 1
                assigned_track_ids.add(track.track_id)
            matched.append((track, detection))
        metrics.active_tracks = sum(
            1 for track in self._tracks.values() if not track.finalized
        )
        return matched

    def add_plate_candidate_to_track(
        self,
        track: TrackState,
        candidate: PlateCandidate,
        frame: np.ndarray,
        packet: FramePacket,
        metrics: RuntimeMetrics,
    ) -> None:
        """Append a validated plate candidate to a track vote buffer and evidence state."""
        if track.decision_finalized:
            return
        vote = PlateVote(
            plate_text=candidate.normalized_text,
            raw_text=candidate.raw_text,
            confidence=candidate.confidence,
            timestamp=packet.timestamp,
            frame_index=packet.frame_index,
            plate_bbox=candidate.plate_bbox,
            vehicle_bbox=candidate.vehicle_bbox,
        )
        track.plate_votes.append(vote)
        metrics.plate_votes_added += 1

        if candidate.confidence > track.best_confidence:
            track.best_confidence = candidate.confidence
            track.best_full_frame = frame.copy()
            crop = extract_plate_crop(frame, Detection(bbox=candidate.plate_bbox, confidence=1.0))
            track.best_plate_crop = crop.copy() if crop is not None else None
            track.best_annotated_frame = _annotate_evidence_frame(
                frame,
                track.track_id,
                candidate.normalized_text,
                candidate.plate_bbox,
                candidate.vehicle_bbox,
                candidate.confidence,
            )

    def should_finalize_track(
        self,
        track: TrackState,
        packet: FramePacket,
    ) -> tuple[bool, str | None]:
        """Return True when early high-confidence voting criteria are met."""
        if track.decision_finalized or track.finalized or not track.plate_votes:
            return False, None

        groups: dict[str, list[PlateVote]] = {}
        for vote in track.plate_votes:
            groups.setdefault(vote.plate_text, []).append(vote)

        for plate_text, votes in groups.items():
            if len(votes) < self.config.early_finalize_min_votes:
                continue
            avg_confidence = sum(v.confidence for v in votes) / len(votes)
            if avg_confidence >= self.config.early_finalize_min_confidence:
                return True, "early_high_confidence"
        return False, None

    def _min_votes_for_finalize(self, reason: str) -> int:
        if reason == "early_high_confidence":
            return self.config.early_finalize_min_votes
        if reason == "source_end" and self.config.source == "image":
            return 1
        return self.config.min_plate_votes

    def finalize_track(
        self,
        track: TrackState,
        reason: str,
        metrics: RuntimeMetrics,
    ) -> FinalizedTrackCandidate | None:
        """Finalize a track once using vote-buffer majority selection."""
        if track.decision_finalized or track.finalized:
            return None

        selection = select_best_plate_for_track(track)
        if selection is None:
            if reason in {"track_expired", "source_end"}:
                track.finalized = True
                track.finalization_reason = reason
                metrics.track_finalizations_rejected += 1
            return None

        plate_number, confidence, vote_count = selection
        min_votes = self._min_votes_for_finalize(reason)
        if vote_count < min_votes:
            if reason in {"track_expired", "source_end"}:
                track.finalized = True
                track.finalization_reason = reason
                metrics.track_finalizations_rejected += 1
            return None

        track.decision_finalized = True
        track.finalization_reason = reason
        if reason in {"track_expired", "source_end"}:
            track.finalized = True

        metrics.tracks_finalized += 1
        if reason == "early_high_confidence":
            metrics.tracks_finalized_early += 1
        elif reason == "track_expired":
            metrics.tracks_finalized_expired += 1
        elif reason == "source_end":
            metrics.tracks_finalized_source_end += 1

        finalized = FinalizedTrackCandidate(
            track_id=track.track_id,
            plate_number=plate_number,
            confidence=round(confidence, 4),
            votes=vote_count,
            first_seen_at=track.first_seen_at,
            last_seen_at=track.last_seen_at,
            finalization_reason=reason,
        )
        self._finalized_track_candidates.append(finalized)
        self._persist_finalized_event(track, finalized, metrics)
        return finalized

    def _event_bboxes(
        self,
        track: TrackState,
        plate_number: str,
    ) -> tuple[tuple[int, int, int, int] | None, tuple[int, int, int, int] | None]:
        """Resolve vehicle and plate bboxes for an event from track votes."""
        matching = [vote for vote in track.plate_votes if vote.plate_text == plate_number]
        if matching:
            best_vote = max(matching, key=lambda vote: vote.confidence)
            vehicle_bbox = best_vote.vehicle_bbox or track.bbox
            return vehicle_bbox, best_vote.plate_bbox
        return track.bbox, None

    def _ensure_evidence_dirs(self, run_dir: Path) -> None:
        """Create evidence subdirectories under a run folder."""
        evidence_root = run_dir / "evidence"
        self._evidence_dirs = {
            "full": evidence_root / "full",
            "plate": evidence_root / "plate",
            "annotated": evidence_root / "annotated",
        }
        for directory in self._evidence_dirs.values():
            directory.mkdir(parents=True, exist_ok=True)

    def _relative_run_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.config.project_root_path()).as_posix()
        except ValueError:
            return path.resolve().as_posix()

    def _cleanup_expired_evidence(self, current_run_dir: Path, metrics: RuntimeMetrics) -> None:
        """Delete evidence files in old runs past retention; never touch the current run."""
        retention_days = self.config.evidence_retention_days
        if retention_days <= 0:
            return

        runs_root = self.config.runs_dir_path().resolve()
        current_resolved = current_run_dir.resolve()
        cutoff = time.time() - (retention_days * 86400)

        for run_dir in runs_root.glob("run_*"):
            if not run_dir.is_dir():
                continue
            try:
                if run_dir.resolve() == current_resolved:
                    continue
            except OSError:
                continue

            evidence_dir = run_dir / "evidence"
            if not evidence_dir.is_dir():
                continue

            try:
                if evidence_dir.stat().st_mtime > cutoff:
                    continue
            except OSError:
                continue

            for file_path in evidence_dir.rglob("*"):
                if not file_path.is_file():
                    continue
                try:
                    file_path.resolve().relative_to(runs_root)
                except ValueError:
                    continue
                try:
                    file_path.unlink()
                    metrics.local_evidence_deleted += 1
                except OSError:
                    metrics.log_lines.append(
                        f"Warning: failed to delete expired evidence file {file_path}"
                    )

    def _save_evidence_images(
        self,
        track: TrackState,
        event_id: str,
        candidate: FinalizedTrackCandidate,
        metrics: RuntimeMetrics,
    ) -> dict[str, str | None]:
        """Save best evidence images for a finalized event."""
        evidence: dict[str, str | None] = {
            "full": None,
            "plate": None,
            "annotated": None,
        }
        if not self.config.save_local_evidence:
            return evidence
        if not self._evidence_dirs:
            return evidence

        vehicle_bbox, plate_bbox = self._event_bboxes(track, candidate.plate_number)
        annotated_image = track.best_annotated_frame
        if track.best_full_frame is not None and plate_bbox is not None:
            annotated_image = _annotate_evidence_frame(
                track.best_full_frame,
                track.track_id,
                candidate.plate_number,
                plate_bbox,
                vehicle_bbox,
                candidate.confidence,
            )

        image_sets = {
            "full": (track.best_full_frame, self._evidence_dirs["full"] / f"{event_id}_full.jpg"),
            "plate": (
                track.best_plate_crop,
                self._evidence_dirs["plate"] / f"{event_id}_plate.jpg",
            ),
            "annotated": (
                annotated_image,
                self._evidence_dirs["annotated"] / f"{event_id}_annotated.jpg",
            ),
        }
        for key, (image, path) in image_sets.items():
            if image is None or image.size == 0:
                metrics.evidence_save_failures += 1
                warning = f"Evidence {key} image missing for {event_id}"
                if warning not in metrics.runtime_warnings:
                    metrics.runtime_warnings.append(warning)
                metrics.log_lines.append(f"Warning: {warning}")
                continue
            if cv2.imwrite(str(path), image):
                evidence[key] = self._relative_run_path(path)
                metrics.evidence_files_saved += 1
            else:
                metrics.evidence_save_failures += 1
                warning = f"Failed to write evidence {key} image for {event_id}"
                if warning not in metrics.runtime_warnings:
                    metrics.runtime_warnings.append(warning)
                metrics.log_lines.append(f"Warning: {warning}")
        return evidence

    def write_event_record(self, events_file: Path, event: FinalizedEvent) -> None:
        """Append one JSON object as a single UTF-8 line to events.jsonl."""
        line = json.dumps(finalized_event_to_dict(event), separators=(",", ":"))
        with events_file.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _write_backend_results(self, run_dir: Path, flush_result: FlushQueueResult) -> None:
        """Write post-flush backend job status for events finalized in this run."""
        if self._backend_client is None:
            return

        local_event_ids = {event.event_id for event in self._finalized_events}
        results = self._backend_client.job_results_for_local_events(local_event_ids)
        if not results:
            return

        payload = {
            "flush": {
                "processed": flush_result.processed,
                "succeeded": flush_result.succeeded,
                "failed": flush_result.failed,
                "exhausted": flush_result.exhausted,
                "pending": flush_result.pending,
                "malformed": flush_result.malformed,
                "camera_verified": flush_result.camera_verified,
                "logs_sent": flush_result.logs_sent,
                "images_sent": flush_result.images_sent,
            },
            "events": results,
        }
        output_path = run_dir / "backend_results.json"
        output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _persist_finalized_event(
        self,
        track: TrackState,
        candidate: FinalizedTrackCandidate,
        metrics: RuntimeMetrics,
    ) -> None:
        """Convert a finalized track candidate into a persisted event and evidence."""
        if self._run_dir is None or self._events_file is None:
            return

        plate_number = candidate.plate_number
        cooldown = self.config.duplicate_cooldown_seconds
        if cooldown > 0 and plate_number in self._plate_last_event_at:
            elapsed = candidate.last_seen_at - self._plate_last_event_at[plate_number]
            if elapsed < cooldown:
                metrics.duplicate_events_suppressed += 1
                metrics.log_lines.append(
                    f"Duplicate event suppressed for plate {plate_number} "
                    f"(cooldown {cooldown}s, elapsed {elapsed:.3f}s)"
                )
                return

        event_id = f"local-{self._run_id}-track_{candidate.track_id}"
        vehicle_bbox, plate_bbox = self._event_bboxes(track, plate_number)
        evidence = self._save_evidence_images(track, event_id, candidate, metrics)

        backend_state = _default_backend_state()
        if (
            not self._dry_run
            and self.config.backend_enabled
            and self._backend_client is not None
        ):
            event_dict_preview = {
                "event_id": event_id,
                "plate_number": plate_number,
                "confidence": candidate.confidence,
                "last_seen_at": candidate.last_seen_at,
                "created_at": _utc_now_iso(),
                "source_type": self.config.source,
                "evidence": evidence,
            }
            enqueue_result = self._backend_client.enqueue_event(event_dict_preview)
            if enqueue_result.success:
                backend_state = _backend_state_queued()
                metrics.backend_jobs_queued += 1
                metrics.log_lines.append(
                    f"Backend job queued: {event_id} job_id={enqueue_result.job_id}"
                )
            else:
                backend_state = _backend_state_enqueue_failed(enqueue_result.message)
                metrics.log_lines.append(
                    f"Backend enqueue failed for {event_id}: {enqueue_result.message}"
                )

        event = FinalizedEvent(
            event_id=event_id,
            run_id=self._run_id,
            track_id=candidate.track_id,
            plate_number=plate_number,
            confidence=candidate.confidence,
            votes=candidate.votes,
            first_seen_at=candidate.first_seen_at,
            last_seen_at=candidate.last_seen_at,
            first_frame_index=track.first_frame_index,
            last_frame_index=track.last_frame_index,
            finalization_reason=candidate.finalization_reason,
            source_type=self.config.source,
            source_path=self._safe_source_path(),
            vehicle_bbox=vehicle_bbox,
            plate_bbox=plate_bbox,
            evidence=evidence,
            backend=backend_state,
            dry_run=self._dry_run,
            created_at=_utc_now_iso(),
        )
        self.write_event_record(self._events_file, event)
        self._finalized_events.append(event)
        metrics.events_finalized += 1
        metrics.events_written += 1
        self._plate_last_event_at[plate_number] = candidate.last_seen_at
        metrics.log_lines.append(
            f"Event persisted: {event_id} plate={plate_number} "
            f"reason={candidate.finalization_reason}"
        )

    def _retire_track(self, track: TrackState, reason: str) -> None:
        """Retire a track from matching without creating a duplicate candidate."""
        if track.finalized:
            return
        track.finalized = True
        if track.finalization_reason is None:
            track.finalization_reason = reason

    def finalize_expired_tracks(
        self,
        packet: FramePacket,
        metrics: RuntimeMetrics,
    ) -> None:
        """Finalize tracks that have not been seen within the expiry window."""
        for track in list(self._tracks.values()):
            if track.finalized:
                continue
            elapsed = packet.timestamp - track.last_seen_at
            if elapsed < self.config.track_expiry_seconds:
                continue
            if track.decision_finalized:
                self._retire_track(track, "track_expired")
                continue
            self.finalize_track(track, "track_expired", metrics)

    def finalize_active_tracks_at_source_end(
        self,
        packet: FramePacket,
        metrics: RuntimeMetrics,
    ) -> None:
        """Flush remaining active tracks when the source ends."""
        for track in list(self._tracks.values()):
            if track.finalized:
                continue
            if track.decision_finalized:
                self._retire_track(track, "source_end")
                continue
            self.finalize_track(track, "source_end", metrics)

    def _check_early_finalization(
        self,
        packet: FramePacket,
        metrics: RuntimeMetrics,
    ) -> None:
        for track in self._tracks.values():
            if track.finalized or track.decision_finalized:
                continue
            should_finalize, reason = self.should_finalize_track(track, packet)
            if should_finalize and reason:
                self.finalize_track(track, reason, metrics)

    def _parse_yolo_results(
        self,
        results: Any,
        frame_width: int,
        frame_height: int,
        *,
        filter_vehicles: bool = False,
        offset_x: int = 0,
        offset_y: int = 0,
    ) -> list[Detection]:
        detections: list[Detection] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            names: dict[int, str] = result.names or {}
            for box in boxes:
                confidence = float(box.conf[0].item())
                class_id = int(box.cls[0].item()) if box.cls is not None else None
                class_name = names.get(class_id) if class_id is not None else None
                if filter_vehicles and class_name is not None:
                    if class_name.lower() not in VEHICLE_CLASS_NAMES:
                        continue

                xyxy = box.xyxy[0].tolist()
                bbox = _clip_bbox(
                    xyxy[0] + offset_x,
                    xyxy[1] + offset_y,
                    xyxy[2] + offset_x,
                    xyxy[3] + offset_y,
                    frame_width,
                    frame_height,
                )
                if bbox is None:
                    continue
                detections.append(
                    Detection(
                        bbox=bbox,
                        confidence=confidence,
                        class_id=class_id,
                        class_name=class_name,
                    )
                )
        return detections

    def detect_vehicles(
        self,
        frame: np.ndarray,
        metrics: RuntimeMetrics,
    ) -> list[Detection]:
        """Run vehicle detection on a full frame."""
        if not self._models_loaded or self._vehicle_model is None:
            raise ModelLoadError("Vehicle model is not loaded.")

        height, width = frame.shape[:2]
        start = time.perf_counter()
        metrics.vehicle_detection_calls += 1

        try:
            results = self._vehicle_model.predict(
                frame,
                conf=self.config.vehicle_conf,
                device=self.config.device,
                verbose=False,
            )
        except Exception as exc:
            raise SourceRuntimeError(f"Vehicle detection failed: {exc}") from exc
        detections = self._parse_yolo_results(
            results,
            width,
            height,
            filter_vehicles=True,
        )

        metrics.vehicle_detections += len(detections)
        metrics.vehicle_detect_ms_total += (time.perf_counter() - start) * 1000.0
        return detections

    def detect_plates(
        self,
        frame: np.ndarray,
        vehicle_detection: Detection | None,
        metrics: RuntimeMetrics,
    ) -> list[Detection]:
        """Run plate detection on a vehicle crop or the full frame."""
        if not self._models_loaded or self._plate_model is None:
            raise ModelLoadError("Plate model is not loaded.")

        height, width = frame.shape[:2]
        offset_x = 0
        offset_y = 0
        inference_image = frame

        if vehicle_detection is not None:
            x1, y1, x2, y2 = vehicle_detection.bbox
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                return []
            inference_image = crop
            offset_x = x1
            offset_y = y1

        start = time.perf_counter()
        metrics.plate_detection_calls += 1

        try:
            results = self._plate_model.predict(
                inference_image,
                conf=self.config.plate_conf,
                device=self.config.device,
                verbose=False,
            )
        except Exception as exc:
            raise SourceRuntimeError(f"Plate detection failed: {exc}") from exc
        detections = self._parse_yolo_results(
            results,
            width,
            height,
            offset_x=offset_x,
            offset_y=offset_y,
        )

        metrics.plate_detections += len(detections)
        metrics.plate_detect_ms_total += (time.perf_counter() - start) * 1000.0
        return detections

    def open_source(self) -> None:
        """Open the configured source and initialize scheduler state."""
        self._capture = None
        self._source_fps = None
        self._assumed_source_fps = None
        self._frame_skip_interval = None
        self._use_wall_clock = False
        self._last_processed_time = None
        self._stop_reason = "unknown"

        if self.config.source == "image":
            return

        if self.config.source == "webcam":
            capture = cv2.VideoCapture(self.config.camera_index)
            label = f"webcam source: index {self.config.camera_index}"
        elif self.config.source == "rtsp":
            capture = cv2.VideoCapture(self.config.rtsp_url)
            label = "RTSP source (ANPR_RTSP_URL)"
        elif self.config.source == "video":
            capture = cv2.VideoCapture(self.config.video_path)
            label = f"video source: {self.config.video_path}"
        else:
            raise SourceRuntimeError(f"Unsupported source type: {self.config.source}")

        if not capture.isOpened():
            capture.release()
            raise SourceRuntimeError(f"Failed to open {label}")

        raw_fps = float(capture.get(cv2.CAP_PROP_FPS))
        if self.config.source == "video":
            if _fps_is_valid(raw_fps):
                self._source_fps = raw_fps
                self._frame_skip_interval = max(
                    1, round(self._source_fps / self.config.target_fps)
                )
            else:
                self._assumed_source_fps = ASSUMED_VIDEO_FPS
                self._frame_skip_interval = max(
                    1, round(ASSUMED_VIDEO_FPS / self.config.target_fps)
                )
        elif _fps_is_valid(raw_fps):
            self._source_fps = raw_fps
            self._frame_skip_interval = max(
                1, round(self._source_fps / self.config.target_fps)
            )
        else:
            self._use_wall_clock = True

        self._capture = capture

    def close_source(self) -> None:
        """Release capture resources."""
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def should_process_frame(self, packet: FramePacket) -> bool:
        """Return True when the scheduler accepts a frame for processing."""
        if self.config.source == "image":
            return True

        if self._frame_skip_interval is not None:
            return packet.frame_index % self._frame_skip_interval == 0

        if self._use_wall_clock:
            if self._last_processed_time is None:
                return True
            min_interval = 1.0 / self.config.target_fps
            return (packet.timestamp - self._last_processed_time) >= min_interval

        return True

    def _packet_timestamp(self, frame_index: int) -> float:
        """Return frame timestamp for tracking; video uses source timeline."""
        if self.config.source == "video":
            fps = self._source_fps or self._assumed_source_fps or ASSUMED_VIDEO_FPS
            return frame_index / fps
        return time.time()

    def _iter_image_frames(self) -> Iterator[FramePacket]:
        path = self.config.image_path
        image = cv2.imread(path)
        if image is None:
            raise SourceRuntimeError(f"Failed to read image source: {path}")

        self._stop_reason = "image_complete"
        yield FramePacket(
            frame_index=0,
            timestamp=time.time(),
            image=image,
            source_type="image",
            source_path=path,
            is_last=True,
        )

    def _iter_capture_frames(self) -> Iterator[FramePacket]:
        if self._capture is None:
            raise SourceRuntimeError("Video capture is not open.")

        source_type = self.config.source
        source_path = self._safe_source_path()
        start_time = time.time()
        frame_index = 0
        pending: FramePacket | None = None

        while True:
            if (
                self.config.max_seconds is not None
                and (time.time() - start_time) >= self.config.max_seconds
            ):
                self._stop_reason = "max_seconds_reached"
                if pending is not None:
                    pending.is_last = True
                    yield pending
                break

            ok, frame = self._capture.read()
            if not ok:
                if pending is not None:
                    pending.is_last = True
                    yield pending
                if frame_index == 0:
                    self._stop_reason = "zero_frames"
                elif source_type == "video":
                    self._stop_reason = "video_end"
                else:
                    self._stop_reason = "stream_read_failed"
                break

            packet = FramePacket(
                frame_index=frame_index,
                timestamp=self._packet_timestamp(frame_index),
                image=frame,
                source_type=source_type,
                source_path=source_path,
                is_last=False,
            )
            if pending is not None:
                yield pending
            pending = packet
            frame_index += 1

    def iter_frames(self) -> Iterator[FramePacket]:
        """Yield frames from the configured source."""
        if self.config.source == "image":
            yield from self._iter_image_frames()
            return

        if self._capture is None:
            raise SourceRuntimeError("Source is not open.")
        yield from self._iter_capture_frames()

    def _average_ms(self, total_ms: float, calls: int) -> float:
        if calls <= 0:
            return 0.0
        return round(total_ms / calls, 3)

    def _build_summary(
        self,
        run_dir: Path,
        validation_result: ValidationResult,
        metrics: RuntimeMetrics,
        *,
        strict: bool,
        status: str,
    ) -> dict:
        warnings = list(validation_result.warnings) + list(metrics.runtime_warnings)
        finalized_summary = [
            {
                "track_id": item.track_id,
                "plate_number": item.plate_number,
                "confidence": item.confidence,
                "votes": item.votes,
                "finalization_reason": item.finalization_reason,
            }
            for item in self._finalized_track_candidates
        ]
        events_summary = [
            {
                "event_id": item.event_id,
                "track_id": item.track_id,
                "plate_number": item.plate_number,
                "confidence": item.confidence,
                "votes": item.votes,
                "finalization_reason": item.finalization_reason,
            }
            for item in self._finalized_events
        ]
        summary: dict = {
            "status": status,
            "milestone": "M9",
            "source_type": self.config.source,
            "source_path": self._safe_source_path(),
            "evidence_mode": self.config.evidence_mode,
            "evidence_retention_days": self.config.evidence_retention_days,
            "frames_read": metrics.frames_read,
            "frames_processed": metrics.frames_processed,
            "events_finalized": metrics.events_finalized,
            "events_written": metrics.events_written,
            "evidence_files_saved": metrics.evidence_files_saved,
            "evidence_save_failures": metrics.evidence_save_failures,
            "duplicate_events_suppressed": metrics.duplicate_events_suppressed,
            "finalized_events": events_summary,
            "backend_enabled": self.config.backend_enabled,
            "backend_jobs_queued": metrics.backend_jobs_queued,
            "backend_jobs_succeeded": metrics.backend_jobs_succeeded,
            "backend_jobs_failed": metrics.backend_jobs_failed,
            "backend_jobs_exhausted": metrics.backend_jobs_exhausted,
            "backend_logs_sent": metrics.backend_logs_sent,
            "backend_images_sent": metrics.backend_images_sent,
            "backend_camera_verified": metrics.backend_camera_verified,
            "local_evidence_deleted": metrics.local_evidence_deleted,
            "backend_queue_file": self.config.backend_queue_file,
            "validation_mode": "strict" if strict else "standard",
            "warnings": warnings,
            "errors": [metrics.runtime_error] if metrics.runtime_error else [],
            "run_dir": str(run_dir).replace("\\", "/"),
            "target_fps": self.config.target_fps,
            "source_fps": metrics.source_fps,
            "frame_skip_interval": metrics.frame_skip_interval,
            "source_opened": metrics.source_opened,
            "source_completed": metrics.source_completed,
            "stop_reason": metrics.stop_reason,
            "max_seconds": self.config.max_seconds,
            "duration_seconds": round(metrics.duration_seconds, 3),
            "models_loaded": metrics.models_loaded,
            "vehicle_model": metrics.vehicle_model or self.config.vehicle_model,
            "plate_model": metrics.plate_model or self.config.plate_model,
            "device": metrics.device or self.config.device,
            "vehicle_detection_calls": metrics.vehicle_detection_calls,
            "plate_detection_calls": metrics.plate_detection_calls,
            "vehicle_detections": metrics.vehicle_detections,
            "plate_detections": metrics.plate_detections,
            "average_vehicle_detect_ms": self._average_ms(
                metrics.vehicle_detect_ms_total,
                metrics.vehicle_detection_calls,
            ),
            "average_plate_detect_ms": self._average_ms(
                metrics.plate_detect_ms_total,
                metrics.plate_detection_calls,
            ),
            "ocr_engine": self.config.ocr_engine,
            "ocr_engine_loaded": metrics.ocr_engine_loaded,
            "plate_crops_extracted": metrics.plate_crops_extracted,
            "plate_crops_rejected": metrics.plate_crops_rejected,
            "ocr_calls": metrics.ocr_calls,
            "ocr_readings": metrics.ocr_readings,
            "plate_candidates": metrics.plate_candidates,
            "plate_candidates_rejected": metrics.plate_candidates_rejected,
            "average_ocr_ms": self._average_ms(metrics.ocr_ms_total, metrics.ocr_calls),
            "tracks_created": metrics.tracks_created,
            "tracks_updated": metrics.tracks_updated,
            "active_tracks": metrics.active_tracks,
            "tracks_finalized": metrics.tracks_finalized,
            "tracks_finalized_early": metrics.tracks_finalized_early,
            "tracks_finalized_expired": metrics.tracks_finalized_expired,
            "tracks_finalized_source_end": metrics.tracks_finalized_source_end,
            "track_finalizations_rejected": metrics.track_finalizations_rejected,
            "plate_votes_added": metrics.plate_votes_added,
            "decision_finalized_tracks_skipped": metrics.decision_finalized_tracks_skipped,
            "finalized_track_candidates": finalized_summary,
        }
        if metrics.assumed_source_fps is not None:
            summary["assumed_source_fps"] = metrics.assumed_source_fps
        return summary

    def _write_run_outputs(
        self,
        run_dir: Path,
        validation_result: ValidationResult,
        metrics: RuntimeMetrics,
        *,
        strict: bool,
        status: str,
    ) -> DryRunResult:
        worker_log = run_dir / "worker.log"
        worker_summary = run_dir / "worker_summary.json"
        events_file = run_dir / "events.jsonl"

        worker_log.write_text("\n".join(metrics.log_lines) + "\n", encoding="utf-8")

        summary = self._build_summary(
            run_dir, validation_result, metrics, strict=strict, status=status
        )
        worker_summary.write_text(
            json.dumps(summary, indent=2) + "\n",
            encoding="utf-8",
        )
        if not events_file.exists():
            events_file.write_text("", encoding="utf-8")

        return DryRunResult(
            run_dir=run_dir,
            worker_log=worker_log,
            worker_summary=worker_summary,
            events_file=events_file,
            summary=summary,
        )

    def _finalize_stop_reason(self, metrics: RuntimeMetrics) -> None:
        if metrics.frames_read == 0 and metrics.source_opened:
            metrics.stop_reason = "zero_frames"
            warning = "Source opened but returned zero frames"
            if warning not in metrics.runtime_warnings:
                metrics.runtime_warnings.append(warning)
        elif self.config.source == "image" and metrics.frames_read > 0:
            metrics.stop_reason = "image_complete"
        elif self._stop_reason != "unknown":
            metrics.stop_reason = self._stop_reason

    def run_dry_run(
        self,
        validation_result: ValidationResult,
        *,
        strict: bool = False,
    ) -> DryRunResult:
        """Run the pipeline in dry-run mode without backend side effects."""
        return self._execute_run(validation_result, strict=strict, dry_run=True)

    def run(
        self,
        validation_result: ValidationResult,
        *,
        strict: bool = False,
    ) -> DryRunResult:
        """Run the pipeline with local events and optional backend queue enqueue."""
        return self._execute_run(validation_result, strict=strict, dry_run=False)

    def _execute_run(
        self,
        validation_result: ValidationResult,
        *,
        strict: bool = False,
        dry_run: bool = True,
    ) -> DryRunResult:
        """
        Open source, load models, read frames, run detection/OCR/tracking, and write outputs.

        Dry-run persists local events only. Non-dry-run may enqueue backend jobs.
        """
        self._dry_run = dry_run
        self._backend_client = (
            BackendClient(self.config) if self.config.backend_enabled and not dry_run else None
        )
        run_dir = self._make_run_dir()
        self._run_dir = run_dir
        self._run_id = run_dir.name
        self._events_file = run_dir / "events.jsonl"
        self._events_file.write_text("", encoding="utf-8")
        self._ensure_evidence_dirs(run_dir)
        validation_mode = "strict" if strict else "standard"
        metrics = RuntimeMetrics()
        status = "completed"
        self._run_candidates = []
        self._tracks = {}
        self._next_track_id = 1
        self._finalized_track_candidates = []
        self._finalized_events = []
        self._plate_last_event_at = {}

        metrics.log_lines.extend(
            [
                f"{'M6 dry-run' if dry_run else 'M9 run'} started.",
                f"Source type: {self.config.source}",
                f"Source: {self._source_label()}",
                f"Validation mode: {validation_mode}",
                f"Backend enabled: {self.config.backend_enabled}",
                f"Dry run: {dry_run}",
                f"Backend queue file: {self.config.backend_queue_file}",
                f"Target FPS: {self.config.target_fps}",
                f"Max seconds: {self.config.max_seconds}",
                f"Track IoU threshold: {self.config.track_iou_threshold}",
                f"Track expiry seconds: {self.config.track_expiry_seconds}",
                f"Early finalize min votes: {self.config.early_finalize_min_votes}",
                f"Early finalize min confidence: {self.config.early_finalize_min_confidence}",
                f"Min plate votes: {self.config.min_plate_votes}",
                f"Duplicate cooldown seconds: {self.config.duplicate_cooldown_seconds}",
                f"Evidence mode: {self.config.evidence_mode}",
                f"Evidence retention days: {self.config.evidence_retention_days}",
                f"Save local evidence: {self.config.save_local_evidence}",
            ]
        )
        if validation_result.warnings:
            metrics.log_lines.append(f"Config warnings: {len(validation_result.warnings)}")

        start_time = time.time()
        try:
            self.open_source()
            if self.config.source != "image":
                metrics.source_opened = self._capture is not None
                metrics.source_fps = self._source_fps
                metrics.assumed_source_fps = self._assumed_source_fps
                metrics.frame_skip_interval = self._frame_skip_interval
                if metrics.source_fps is not None:
                    metrics.log_lines.append(f"Source FPS: {metrics.source_fps}")
                elif metrics.assumed_source_fps is not None:
                    metrics.log_lines.append(
                        f"Assumed source FPS: {metrics.assumed_source_fps}"
                    )
                if metrics.frame_skip_interval is not None:
                    metrics.log_lines.append(
                        f"Frame skip interval: {metrics.frame_skip_interval}"
                    )
                elif self._use_wall_clock:
                    metrics.log_lines.append(
                        "Frame skip interval: wall-clock fallback (source FPS unavailable)"
                    )

            self.load_models(metrics)
            self.load_ocr_engine(metrics)

            last_packet: FramePacket | None = None
            for packet in self.iter_frames():
                last_packet = packet
                metrics.source_opened = True
                metrics.frames_read += 1
                if self.should_process_frame(packet):
                    metrics.frames_processed += 1
                    self._last_processed_time = packet.timestamp
                    vehicles = self.detect_vehicles(packet.image, metrics)
                    matched_tracks = self.update_tracks(vehicles, packet, metrics)
                    frame_candidates: list[PlateCandidate] = []
                    for track, vehicle in matched_tracks:
                        if track.decision_finalized:
                            metrics.decision_finalized_tracks_skipped += 1
                            continue
                        plates = self.detect_plates(packet.image, vehicle, metrics)
                        for plate in plates:
                            candidate = self._process_plate_detection(
                                packet.image,
                                plate,
                                vehicle,
                                metrics,
                            )
                            if candidate is not None:
                                frame_candidates.append(candidate)
                                self.add_plate_candidate_to_track(
                                    track,
                                    candidate,
                                    packet.image,
                                    packet,
                                    metrics,
                                )
                    self._run_candidates.extend(frame_candidates)
                    self._check_early_finalization(packet, metrics)
                    self.finalize_expired_tracks(packet, metrics)

                if packet.is_last:
                    self.finalize_active_tracks_at_source_end(packet, metrics)

            if last_packet is not None:
                self.finalize_active_tracks_at_source_end(last_packet, metrics)

            metrics.active_tracks = sum(
                1 for track in self._tracks.values() if not track.finalized
            )

            metrics.source_completed = True
            self._finalize_stop_reason(metrics)

            if (
                not dry_run
                and self.config.backend_enabled
                and self._backend_client is not None
                and self.config.source in {"image", "video"}
            ):
                flush_result = self._backend_client.flush_queue()
                metrics.backend_jobs_succeeded += flush_result.succeeded
                metrics.backend_jobs_failed += flush_result.failed
                metrics.backend_jobs_exhausted += flush_result.exhausted
                metrics.backend_logs_sent += flush_result.logs_sent
                metrics.backend_images_sent += flush_result.images_sent
                metrics.backend_camera_verified = flush_result.camera_verified
                metrics.log_lines.append(
                    "Backend queue flush: "
                    f"processed={flush_result.processed} "
                    f"succeeded={flush_result.succeeded} "
                    f"failed={flush_result.failed} "
                    f"exhausted={flush_result.exhausted} "
                    f"pending={flush_result.pending} "
                    f"malformed={flush_result.malformed} "
                    f"images_sent={flush_result.images_sent} "
                    f"logs_sent={flush_result.logs_sent} "
                    f"camera_verified={flush_result.camera_verified}"
                )
                self._write_backend_results(run_dir, flush_result)
                metrics.log_lines.append(f"Backend results written: {run_dir / 'backend_results.json'}")

            if not dry_run:
                self._cleanup_expired_evidence(run_dir, metrics)
        except SourceRuntimeError as exc:
            metrics.runtime_error = exc.message
            metrics.stop_reason = "runtime_error"
            metrics.source_completed = False
            status = "failed"
            metrics.log_lines.append(f"Runtime error: {exc.message}")
        finally:
            self.close_source()
            metrics.duration_seconds = time.time() - start_time

        metrics.log_lines.extend(
            [
                f"Frames read: {metrics.frames_read}",
                f"Frames processed: {metrics.frames_processed}",
                f"Vehicle detection calls: {metrics.vehicle_detection_calls}",
                f"Plate detection calls: {metrics.plate_detection_calls}",
                f"Vehicle detections: {metrics.vehicle_detections}",
                f"Plate detections: {metrics.plate_detections}",
                f"Average vehicle detect ms: {self._average_ms(metrics.vehicle_detect_ms_total, metrics.vehicle_detection_calls)}",
                f"Average plate detect ms: {self._average_ms(metrics.plate_detect_ms_total, metrics.plate_detection_calls)}",
                f"Plate crops extracted: {metrics.plate_crops_extracted}",
                f"Plate crops rejected: {metrics.plate_crops_rejected}",
                f"OCR calls: {metrics.ocr_calls}",
                f"OCR readings: {metrics.ocr_readings}",
                f"Plate candidates: {metrics.plate_candidates}",
                f"Plate candidates rejected: {metrics.plate_candidates_rejected}",
                f"Average OCR ms: {self._average_ms(metrics.ocr_ms_total, metrics.ocr_calls)}",
                f"Tracks created: {metrics.tracks_created}",
                f"Tracks updated: {metrics.tracks_updated}",
                f"Active tracks: {metrics.active_tracks}",
                f"Plate votes added: {metrics.plate_votes_added}",
                f"Decision-finalized tracks skipped: {metrics.decision_finalized_tracks_skipped}",
                f"Tracks finalized: {metrics.tracks_finalized}",
                f"Tracks finalized early: {metrics.tracks_finalized_early}",
                f"Tracks finalized expired: {metrics.tracks_finalized_expired}",
                f"Tracks finalized source end: {metrics.tracks_finalized_source_end}",
                f"Track finalizations rejected: {metrics.track_finalizations_rejected}",
                f"Finalized track candidates: {len(self._finalized_track_candidates)}",
                f"Events finalized: {metrics.events_finalized}",
                f"Events written: {metrics.events_written}",
                f"Evidence files saved: {metrics.evidence_files_saved}",
                f"Evidence save failures: {metrics.evidence_save_failures}",
                f"Duplicate events suppressed: {metrics.duplicate_events_suppressed}",
                f"Backend jobs queued: {metrics.backend_jobs_queued}",
                f"Backend jobs succeeded: {metrics.backend_jobs_succeeded}",
                f"Backend jobs failed: {metrics.backend_jobs_failed}",
                f"Backend jobs exhausted: {metrics.backend_jobs_exhausted}",
                f"Backend images sent: {metrics.backend_images_sent}",
                f"Backend logs sent: {metrics.backend_logs_sent}",
                f"Local evidence deleted: {metrics.local_evidence_deleted}",
                f"Backend camera verified: {metrics.backend_camera_verified}",
                f"Source completed: {metrics.source_completed}",
                f"Stop reason: {metrics.stop_reason}",
            ]
        )
        for warning in metrics.runtime_warnings:
            metrics.log_lines.append(f"Warning: {warning}")
        metrics.log_lines.extend(
            [
                f"Duration seconds: {metrics.duration_seconds:.3f}",
                f"{'M6 dry-run' if dry_run else 'M9 run'} {status}.",
            ]
        )

        return self._write_run_outputs(
            run_dir,
            validation_result,
            metrics,
            strict=strict,
            status=status,
        )
