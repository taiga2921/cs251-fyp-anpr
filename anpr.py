"""ANPR runtime with M2 source reader and frame scheduler."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from config import Config, ValidationResult


class SourceRuntimeError(Exception):
    """Raised when a source cannot be opened or read."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


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
class RuntimeMetrics:
    """Collected metrics during a dry-run execution."""

    frames_read: int = 0
    frames_processed: int = 0
    source_opened: bool = False
    source_completed: bool = False
    source_fps: float | None = None
    frame_skip_interval: int | None = None
    duration_seconds: float = 0.0
    runtime_error: str | None = None
    log_lines: list[str] = field(default_factory=list)


@dataclass
class DryRunResult:
    """Summary returned after a dry-run execution."""

    run_dir: Path
    worker_log: Path
    worker_summary: Path
    events_file: Path
    summary: dict


class ANPRProcessor:
    """ANPR processor with M2 source reading and frame scheduling."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._capture: cv2.VideoCapture | None = None
        self._source_fps: float | None = None
        self._frame_skip_interval: int | None = None
        self._last_processed_time: float | None = None

    def _make_run_dir(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = self.config.runs_dir_path() / f"run_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _source_label(self) -> str:
        source_path = self.config.resolved_source_path()
        if self.config.source == "webcam":
            return f"webcam index {self.config.camera_index}"
        return source_path or self.config.source

    def open_source(self) -> None:
        """Open the configured source and initialize scheduler state."""
        self._capture = None
        self._source_fps = None
        self._frame_skip_interval = None
        self._last_processed_time = None

        if self.config.source == "image":
            return

        if self.config.source == "webcam":
            capture = cv2.VideoCapture(self.config.camera_index)
            label = f"webcam source: index {self.config.camera_index}"
        elif self.config.source == "rtsp":
            capture = cv2.VideoCapture(self.config.rtsp_url)
            label = f"RTSP source: {self.config.rtsp_url}"
        elif self.config.source == "video":
            capture = cv2.VideoCapture(self.config.video_path)
            label = f"video source: {self.config.video_path}"
        else:
            raise SourceRuntimeError(f"Unsupported source type: {self.config.source}")

        if not capture.isOpened():
            capture.release()
            raise SourceRuntimeError(f"Failed to open {label}")

        raw_fps = capture.get(cv2.CAP_PROP_FPS)
        if raw_fps and raw_fps > 0 and not math.isnan(raw_fps):
            self._source_fps = float(raw_fps)
            self._frame_skip_interval = max(
                1, round(self._source_fps / self.config.target_fps)
            )

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

        if self._last_processed_time is None:
            return True

        min_interval = 1.0 / self.config.target_fps
        return (packet.timestamp - self._last_processed_time) >= min_interval

    def _iter_image_frames(self) -> Iterator[FramePacket]:
        path = self.config.image_path
        image = cv2.imread(path)
        if image is None:
            raise SourceRuntimeError(f"Failed to read image source: {path}")

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
        source_path = self.config.resolved_source_path()
        start_time = time.time()
        frame_index = 0
        pending: FramePacket | None = None

        while True:
            if (
                self.config.max_seconds is not None
                and (time.time() - start_time) >= self.config.max_seconds
            ):
                if pending is not None:
                    pending.is_last = True
                    yield pending
                break

            ok, frame = self._capture.read()
            if not ok:
                if pending is not None:
                    pending.is_last = True
                    yield pending
                break

            packet = FramePacket(
                frame_index=frame_index,
                timestamp=time.time(),
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

    def _build_summary(
        self,
        run_dir: Path,
        validation_result: ValidationResult,
        metrics: RuntimeMetrics,
        *,
        strict: bool,
        status: str,
    ) -> dict:
        source_path = self.config.resolved_source_path()
        summary: dict = {
            "status": status,
            "milestone": "M2",
            "source_type": self.config.source,
            "source_path": source_path,
            "frames_read": metrics.frames_read,
            "frames_processed": metrics.frames_processed,
            "events_finalized": 0,
            "backend_enabled": self.config.backend_enabled,
            "validation_mode": "strict" if strict else "standard",
            "warnings": list(validation_result.warnings),
            "errors": [metrics.runtime_error] if metrics.runtime_error else [],
            "run_dir": str(run_dir).replace("\\", "/"),
            "target_fps": self.config.target_fps,
            "source_fps": metrics.source_fps,
            "frame_skip_interval": metrics.frame_skip_interval,
            "source_opened": metrics.source_opened,
            "source_completed": metrics.source_completed,
            "duration_seconds": round(metrics.duration_seconds, 3),
        }
        if self.config.max_seconds is not None:
            summary["max_seconds"] = self.config.max_seconds
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
        events_file.write_text("", encoding="utf-8")

        return DryRunResult(
            run_dir=run_dir,
            worker_log=worker_log,
            worker_summary=worker_summary,
            events_file=events_file,
            summary=summary,
        )

    def run_dry_run(
        self,
        validation_result: ValidationResult,
        *,
        strict: bool = False,
    ) -> DryRunResult:
        """
        Open the configured source, read frames, apply scheduling, and write outputs.

        No models, detection, OCR, tracking, evidence, or backend calls are performed.
        """
        run_dir = self._make_run_dir()
        validation_mode = "strict" if strict else "standard"
        source_path = self.config.resolved_source_path()
        metrics = RuntimeMetrics()
        status = "completed"

        metrics.log_lines.extend(
            [
                "M2 dry-run started.",
                f"Source type: {self.config.source}",
                f"Source: {self._source_label()}",
                f"Validation mode: {validation_mode}",
                f"Target FPS: {self.config.target_fps}",
            ]
        )
        if self.config.max_seconds is not None:
            metrics.log_lines.append(f"Max seconds: {self.config.max_seconds}")
        if validation_result.warnings:
            metrics.log_lines.append(f"Config warnings: {len(validation_result.warnings)}")

        start_time = time.time()
        try:
            self.open_source()
            if self.config.source != "image":
                metrics.source_opened = self._capture is not None
                metrics.source_fps = self._source_fps
                metrics.frame_skip_interval = self._frame_skip_interval
                if metrics.source_fps is not None:
                    metrics.log_lines.append(f"Source FPS: {metrics.source_fps}")
                if metrics.frame_skip_interval is not None:
                    metrics.log_lines.append(
                        f"Frame skip interval: {metrics.frame_skip_interval}"
                    )
                else:
                    metrics.log_lines.append(
                        "Frame skip interval: wall-clock fallback (source FPS unavailable)"
                    )

            for packet in self.iter_frames():
                metrics.source_opened = True
                metrics.frames_read += 1
                if self.should_process_frame(packet):
                    metrics.frames_processed += 1
                    self._last_processed_time = packet.timestamp

            metrics.source_completed = True
        except SourceRuntimeError as exc:
            metrics.runtime_error = exc.message
            status = "failed"
            metrics.log_lines.append(f"Runtime error: {exc.message}")
        finally:
            self.close_source()
            metrics.duration_seconds = time.time() - start_time

        metrics.log_lines.extend(
            [
                f"Frames read: {metrics.frames_read}",
                f"Frames processed: {metrics.frames_processed}",
                f"Source completed: {metrics.source_completed}",
                f"Duration seconds: {metrics.duration_seconds:.3f}",
                f"M2 dry-run {status}.",
            ]
        )

        return self._write_run_outputs(
            run_dir,
            validation_result,
            metrics,
            strict=strict,
            status=status,
        )
