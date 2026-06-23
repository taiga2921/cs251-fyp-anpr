"""Shared pytest fixtures for AI ANPR tests."""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from config import Config


@pytest.fixture
def project_root(tmp_path, monkeypatch):
    """Isolated project root with foundation directories."""
    for name in ("models/vehicle", "models/plate", "samples/videos", "samples/images", "runs", ".cache"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)

    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def minimal_config(project_root) -> Config:
    """Config with backend disabled and no real model files."""
    return Config(
        source="image",
        image_path="samples/images/test.jpg",
        video_path="samples/videos/test.mp4",
        vehicle_model="models/vehicle/yolo11s.pt",
        plate_model="models/plate/license-plate-finetune-v1s.pt",
        backend_enabled=False,
        runs_dir="runs",
        backend_token_cache=".cache/backend_token.json",
        backend_queue_file=".cache/backend_queue.jsonl",
    )


@pytest.fixture
def sample_image(project_root) -> Path:
    """Create a small synthetic JPEG for source validation."""
    path = project_root / "samples/images/test.jpg"
    image = np.zeros((120, 200, 3), dtype=np.uint8)
    cv2.rectangle(image, (20, 40), (180, 90), (255, 255, 255), -1)
    cv2.imwrite(str(path), image)
    return path


@pytest.fixture
def sample_video(project_root) -> Path:
    """Create a short synthetic MP4 for source validation."""
    path = project_root / "samples/videos/test.mp4"
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        10.0,
        (160, 120),
    )
    for _ in range(5):
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return path


@pytest.fixture
def fake_model_files(project_root) -> tuple[Path, Path]:
    """Touch placeholder model files for strict validation."""
    vehicle = project_root / "models/vehicle/yolo11s.pt"
    plate = project_root / "models/plate/license-plate-finetune-v1s.pt"
    vehicle.write_bytes(b"fake-model")
    plate.write_bytes(b"fake-model")
    return vehicle, plate


@pytest.fixture
def backend_enabled_config(minimal_config) -> Config:
    """Backend-enabled config with deterministic credentials."""
    minimal_config.backend_enabled = True
    minimal_config.backend_base_url = "http://127.0.0.1:8000/api"
    minimal_config.backend_email = "ai@example.com"
    minimal_config.backend_password = "secret"
    minimal_config.backend_camera_id = "11111111-1111-1111-1111-111111111111"
    return minimal_config


@pytest.fixture(autouse=True)
def _clear_env_overrides(monkeypatch):
    """Prevent host environment from leaking into unit tests."""
    for key in list(os.environ):
        if key.startswith("ANPR_"):
            monkeypatch.delenv(key, raising=False)
