"""Configuration loading and validation for AI ANPR (M1)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

VALID_SOURCES = frozenset({"rtsp", "video", "image", "webcam"})
VALID_DEVICES = frozenset({"cpu", "cuda"})
VALID_EVIDENCE_MODES = frozenset({"metadata", "upload"})

VIDEO_EXTENSIONS = (".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

FOUNDATION_DIRECTORIES = (
    "models/vehicle",
    "models/plate",
    "samples/videos",
    "samples/images",
    "runs",
    ".cache",
)


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class ValidationResult:
    """Collected validation messages for operator-facing output."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def add_error(self, message: str) -> None:
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def add_info(self, message: str) -> None:
        self.info.append(message)


def parse_str(value: str | None, default: str) -> str:
    if value is None or value.strip() == "":
        return default
    return value.strip()


def parse_optional_str(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    return value.strip()


def parse_int(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    return int(value.strip())


def parse_float(value: str | None, default: float) -> float:
    if value is None or value.strip() == "":
        return default
    return float(value.strip())


def parse_bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_path(value: str | None, default: str) -> str:
    return parse_str(value, default)


def load_env_file(path: Path | str = ".env") -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file using the standard library only."""
    env_path = Path(path)
    if not env_path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _merged_env() -> dict[str, str]:
    """Merge defaults, .env values, and operating-system environment variables."""
    merged = load_env_file(".env")
    merged.update(os.environ)
    return merged


def infer_source_from_path(source_path: str) -> tuple[str, str]:
    """Infer source type and normalized path from a generic source path."""
    lowered = source_path.strip().lower()
    if lowered.startswith("rtsp://") or lowered.startswith("rtsps://"):
        return "rtsp", source_path.strip()
    suffix = Path(source_path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image", source_path.strip()
    if suffix in VIDEO_EXTENSIONS:
        return "video", source_path.strip()
    return "video", source_path.strip()


def is_plausible_rtsp_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    return parsed.scheme in {"rtsp", "rtsps"} and bool(parsed.netloc)


@dataclass
class Config:
    """Typed ANPR configuration."""

    source: str = "video"
    rtsp_url: str = ""
    video_path: str = "samples/videos/test_vehicle.mp4"
    image_path: str = "samples/images/frame.jpg"
    camera_index: int = 0

    vehicle_model: str = "yolo11s.pt"
    plate_model: str = "models/plate/license-plate-finetune-v1s.pt"
    device: str = "cpu"

    target_fps: float = 3.0
    vehicle_conf: float = 0.35
    plate_conf: float = 0.25
    track_iou_threshold: float = 0.3
    track_expiry_seconds: float = 2.0
    early_finalize_min_votes: int = 3
    early_finalize_min_confidence: float = 0.90
    min_plate_votes: int = 2
    min_ocr_confidence: float = 0.3

    backend_enabled: bool = False
    backend_base_url: str = "http://localhost:8000/api"
    backend_email: str | None = None
    backend_password: str | None = None
    backend_camera_id: str | None = None
    backend_token_cache: str = ".cache/backend_token.json"
    backend_queue_file: str = ".cache/backend_queue.jsonl"
    backend_retry_limit: int = 3

    evidence_mode: str = "metadata"
    runs_dir: str = "runs"
    save_local_evidence: bool = True
    delete_local_after_upload: bool = False

    max_seconds: float | None = None

    @classmethod
    def from_env(cls) -> Config:
        """Load configuration from .env, environment variables, and defaults."""
        env = _merged_env()
        return cls(
            source=parse_str(env.get("ANPR_SOURCE"), "video"),
            rtsp_url=parse_str(env.get("ANPR_RTSP_URL"), ""),
            video_path=parse_path(env.get("ANPR_VIDEO_PATH"), "samples/videos/test_vehicle.mp4"),
            image_path=parse_path(env.get("ANPR_IMAGE_PATH"), "samples/images/frame.jpg"),
            camera_index=parse_int(env.get("ANPR_CAMERA_INDEX"), 0),
            vehicle_model=parse_path(env.get("ANPR_VEHICLE_MODEL"), "yolo11s.pt"),
            plate_model=parse_path(env.get("ANPR_PLATE_MODEL"), "models/plate/license-plate-finetune-v1s.pt"),
            device=parse_str(env.get("ANPR_DEVICE"), "cpu"),
            target_fps=parse_float(env.get("ANPR_TARGET_FPS"), 3.0),
            vehicle_conf=parse_float(env.get("ANPR_VEHICLE_CONF"), 0.35),
            plate_conf=parse_float(env.get("ANPR_PLATE_CONF"), 0.25),
            track_iou_threshold=parse_float(env.get("ANPR_TRACK_IOU_THRESHOLD"), 0.3),
            track_expiry_seconds=parse_float(env.get("ANPR_TRACK_EXPIRY_SECONDS"), 2.0),
            early_finalize_min_votes=parse_int(env.get("ANPR_EARLY_FINALIZE_MIN_VOTES"), 3),
            early_finalize_min_confidence=parse_float(
                env.get("ANPR_EARLY_FINALIZE_MIN_CONFIDENCE"), 0.90
            ),
            min_plate_votes=parse_int(env.get("ANPR_MIN_PLATE_VOTES"), 2),
            min_ocr_confidence=parse_float(env.get("ANPR_MIN_OCR_CONFIDENCE"), 0.3),
            backend_enabled=parse_bool(env.get("ANPR_BACKEND_ENABLED"), False),
            backend_base_url=parse_str(env.get("ANPR_BACKEND_BASE_URL"), "http://localhost:8000/api"),
            backend_email=parse_optional_str(env.get("ANPR_BACKEND_EMAIL")),
            backend_password=parse_optional_str(env.get("ANPR_BACKEND_PASSWORD")),
            backend_camera_id=parse_optional_str(env.get("ANPR_BACKEND_CAMERA_ID")),
            backend_token_cache=parse_path(env.get("ANPR_BACKEND_TOKEN_CACHE"), ".cache/backend_token.json"),
            backend_queue_file=parse_path(env.get("ANPR_BACKEND_QUEUE_FILE"), ".cache/backend_queue.jsonl"),
            backend_retry_limit=parse_int(env.get("ANPR_BACKEND_RETRY_LIMIT"), 3),
            evidence_mode=parse_str(env.get("ANPR_EVIDENCE_MODE"), "metadata"),
            runs_dir=parse_path(env.get("ANPR_RUNS_DIR"), "runs"),
            save_local_evidence=parse_bool(env.get("ANPR_SAVE_LOCAL_EVIDENCE"), True),
            delete_local_after_upload=parse_bool(env.get("ANPR_DELETE_LOCAL_AFTER_UPLOAD"), False),
        )

    def runs_dir_path(self) -> Path:
        return Path(self.runs_dir)

    def resolved_source_path(self) -> str | None:
        if self.source == "rtsp":
            return self.rtsp_url or None
        if self.source == "video":
            return self.video_path
        if self.source == "image":
            return self.image_path
        if self.source == "webcam":
            return str(self.camera_index)
        return None

    def apply_cli_overrides(self, args: Any) -> Config:
        """Apply CLI argument overrides on top of loaded configuration."""
        if getattr(args, "source", None):
            self.source = args.source
        if getattr(args, "source_path", None):
            inferred_source, inferred_path = infer_source_from_path(args.source_path)
            self.source = inferred_source
            if inferred_source == "rtsp":
                self.rtsp_url = inferred_path
            elif inferred_source == "image":
                self.image_path = inferred_path
            else:
                self.video_path = inferred_path
        if getattr(args, "video", None):
            self.source = "video"
            self.video_path = args.video
        if getattr(args, "image", None):
            self.source = "image"
            self.image_path = args.image
        if getattr(args, "camera_index", None) is not None:
            self.source = "webcam"
            self.camera_index = args.camera_index
        if getattr(args, "max_seconds", None) is not None:
            self.max_seconds = args.max_seconds
        return self


def check_foundation_config(config: Config) -> ValidationResult:
    """Ensure foundation directories exist and runs_dir is writable."""
    result = ValidationResult()

    for relative_dir in FOUNDATION_DIRECTORIES:
        directory = Path(relative_dir)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            result.add_info(f"OK: directory ready: {relative_dir}")
        except OSError as exc:
            result.add_error(f"Cannot create directory {relative_dir}: {exc}")

    runs_dir = config.runs_dir_path()
    try:
        runs_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.add_error(f"Cannot create runs directory {runs_dir}: {exc}")
        return result

    test_file = runs_dir / ".write_test"
    try:
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        result.add_info(f"OK: runs directory is writable: {runs_dir}")
    except OSError as exc:
        result.add_error(f"Runs directory is not writable ({runs_dir}): {exc}")

    return result


def _validate_source(config: Config, result: ValidationResult) -> None:
    if config.source not in VALID_SOURCES:
        result.add_error(
            f"ANPR_SOURCE must be one of {', '.join(sorted(VALID_SOURCES))}; got '{config.source}'."
        )
        return

    if config.source == "rtsp":
        if not config.rtsp_url.strip():
            result.add_error("RTSP source requires ANPR_RTSP_URL or --source-path with an RTSP URL.")
        elif not is_plausible_rtsp_url(config.rtsp_url):
            result.add_error(f"RTSP URL is not plausible: {config.rtsp_url}")
        else:
            result.add_info(f"OK: RTSP URL configured: {config.rtsp_url}")

    elif config.source == "video":
        video_path = Path(config.video_path)
        if not config.video_path.strip():
            result.add_error("Video source requires ANPR_VIDEO_PATH or --video/--source-path.")
        elif not video_path.is_file():
            result.add_error(f"Video file does not exist: {config.video_path}")
        else:
            result.add_info(f"OK: video file found: {config.video_path}")

    elif config.source == "image":
        image_path = Path(config.image_path)
        if not config.image_path.strip():
            result.add_error("Image source requires ANPR_IMAGE_PATH or --image/--source-path.")
        elif not image_path.is_file():
            result.add_error(f"Image file does not exist: {config.image_path}")
        else:
            result.add_info(f"OK: image file found: {config.image_path}")

    elif config.source == "webcam":
        if config.camera_index < 0:
            result.add_error(
                f"Webcam camera index must be >= 0; got {config.camera_index}."
            )
        else:
            result.add_info(f"OK: webcam camera index configured: {config.camera_index}")


def _validate_models(config: Config, result: ValidationResult, strict: bool) -> None:
    if not config.vehicle_model.strip():
        result.add_error("ANPR_VEHICLE_MODEL must be configured.")
    else:
        vehicle_path = Path(config.vehicle_model)
        if vehicle_path.is_file():
            result.add_info(f"OK: vehicle model found: {config.vehicle_model}")
        elif strict:
            result.add_error(f"Vehicle model file does not exist: {config.vehicle_model}")
        else:
            result.add_warning(f"Vehicle model file does not exist: {config.vehicle_model}")

    if not config.plate_model.strip():
        result.add_error("ANPR_PLATE_MODEL must be configured.")
    else:
        plate_path = Path(config.plate_model)
        if plate_path.is_file():
            result.add_info(f"OK: plate model found: {config.plate_model}")
        elif strict:
            result.add_error(f"Plate model file does not exist: {config.plate_model}")
        else:
            result.add_warning(f"Plate model file does not exist: {config.plate_model}")


def _validate_inference(config: Config, result: ValidationResult) -> None:
    if config.device not in VALID_DEVICES:
        result.add_error(
            f"ANPR_DEVICE must be one of {', '.join(sorted(VALID_DEVICES))}; got '{config.device}'."
        )
    else:
        result.add_info(f"OK: inference device configured: {config.device}")

    if config.target_fps <= 0:
        result.add_error(f"ANPR_TARGET_FPS must be > 0; got {config.target_fps}.")
    if not 0.0 <= config.vehicle_conf <= 1.0:
        result.add_error(f"ANPR_VEHICLE_CONF must be between 0 and 1; got {config.vehicle_conf}.")
    if not 0.0 <= config.plate_conf <= 1.0:
        result.add_error(f"ANPR_PLATE_CONF must be between 0 and 1; got {config.plate_conf}.")
    if not 0.0 <= config.track_iou_threshold <= 1.0:
        result.add_error(
            f"ANPR_TRACK_IOU_THRESHOLD must be between 0 and 1; got {config.track_iou_threshold}."
        )
    if config.track_expiry_seconds <= 0:
        result.add_error(
            f"ANPR_TRACK_EXPIRY_SECONDS must be > 0; got {config.track_expiry_seconds}."
        )
    if config.early_finalize_min_votes < 1:
        result.add_error(
            f"ANPR_EARLY_FINALIZE_MIN_VOTES must be >= 1; got {config.early_finalize_min_votes}."
        )
    if not 0.0 <= config.early_finalize_min_confidence <= 1.0:
        result.add_error(
            "ANPR_EARLY_FINALIZE_MIN_CONFIDENCE must be between 0 and 1; "
            f"got {config.early_finalize_min_confidence}."
        )
    if config.min_plate_votes < 1:
        result.add_error(f"ANPR_MIN_PLATE_VOTES must be >= 1; got {config.min_plate_votes}.")
    if not 0.0 <= config.min_ocr_confidence <= 1.0:
        result.add_error(
            f"ANPR_MIN_OCR_CONFIDENCE must be between 0 and 1; got {config.min_ocr_confidence}."
        )

    if config.max_seconds is not None and config.max_seconds <= 0:
        result.add_error(f"--max-seconds must be > 0; got {config.max_seconds}.")


def _validate_backend(config: Config, result: ValidationResult) -> None:
    cache_dir = Path(".cache")
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        result.add_info("OK: .cache directory ready")
    except OSError as exc:
        result.add_error(f"Cannot create .cache directory: {exc}")

    if not config.backend_enabled:
        result.add_info("OK: backend disabled; credentials not required")
        return

    required_fields = {
        "ANPR_BACKEND_BASE_URL": config.backend_base_url,
        "ANPR_BACKEND_EMAIL": config.backend_email,
        "ANPR_BACKEND_PASSWORD": config.backend_password,
        "ANPR_BACKEND_CAMERA_ID": config.backend_camera_id,
        "ANPR_BACKEND_TOKEN_CACHE": config.backend_token_cache,
        "ANPR_BACKEND_QUEUE_FILE": config.backend_queue_file,
    }
    for name, value in required_fields.items():
        if value is None or str(value).strip() == "":
            result.add_error(f"{name} is required when ANPR_BACKEND_ENABLED=true.")

    if config.backend_camera_id and not UUID_PATTERN.match(config.backend_camera_id):
        result.add_error(
            "ANPR_BACKEND_CAMERA_ID must be a UUID when backend is enabled; "
            f"got '{config.backend_camera_id}'."
        )
    elif config.backend_camera_id:
        result.add_info(f"OK: backend camera ID configured: {config.backend_camera_id}")

    if config.backend_retry_limit < 0:
        result.add_error(
            f"ANPR_BACKEND_RETRY_LIMIT must be >= 0; got {config.backend_retry_limit}."
        )


def _validate_output(config: Config, result: ValidationResult) -> None:
    if config.evidence_mode not in VALID_EVIDENCE_MODES:
        result.add_error(
            f"ANPR_EVIDENCE_MODE must be one of {', '.join(sorted(VALID_EVIDENCE_MODES))}; "
            f"got '{config.evidence_mode}'."
        )
    else:
        result.add_info(f"OK: evidence mode configured: {config.evidence_mode}")


def validate_config(config: Config, *, strict: bool = False) -> ValidationResult:
    """
    Validate full M1 configuration.

    In strict mode, missing model files are fatal errors.
    In standard mode, missing model files are warnings.
    """
    result = check_foundation_config(config)
    if not result.ok:
        return result

    _validate_source(config, result)
    _validate_models(config, result, strict=strict)
    _validate_inference(config, result)
    _validate_backend(config, result)
    _validate_output(config, result)
    return result


def format_validation_output(result: ValidationResult) -> str:
    """Format validation messages for CLI display."""
    lines: list[str] = []
    for message in result.info:
        lines.append(message)
    for message in result.warnings:
        lines.append(f"WARNING: {message}")
    for message in result.errors:
        lines.append(f"ERROR: {message}")
    return "\n".join(lines)
