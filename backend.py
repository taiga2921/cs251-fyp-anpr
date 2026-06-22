"""Backend client, token cache, and queue for M7."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

from config import Config, UPLOAD_MODE_ERROR

TOKEN_EXPIRY_BUFFER_SECONDS = 60
QUEUE_STATUSES_RETRYABLE = frozenset({"pending", "failed"})
QUEUE_STATUSES_SKIP = frozenset({"succeeded", "exhausted", "validation_failed"})
EVIDENCE_IMAGE_TYPES = ("full", "plate", "annotated")
IMAGE_STATUSES_FINAL = frozenset({"succeeded", "skipped", "validation_failed"})
IMAGE_STATUSES_RETRYABLE = frozenset({"pending", "failed"})


@dataclass
class BackendToken:
    access_token: str
    token_type: str
    expires_at: str


@dataclass
class BackendQueueJob:
    job_id: str
    local_event_id: str
    status: str
    attempts: int
    retry_limit: int
    max_attempts: int
    backend_event_id: str | None
    images_sent: int
    last_error: str | None
    created_at: str
    updated_at: str
    event: dict[str, Any]
    evidence: dict[str, str | None]
    image_statuses: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "local_event_id": self.local_event_id,
            "status": self.status,
            "attempts": self.attempts,
            "retry_limit": self.retry_limit,
            "max_attempts": self.max_attempts,
            "backend_event_id": self.backend_event_id,
            "images_sent": self.images_sent,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "event": self.event,
            "evidence": self.evidence,
            "image_statuses": self.image_statuses,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BackendQueueJob:
        evidence = dict(payload.get("evidence", {}))
        retry_limit = payload.get("retry_limit")
        max_attempts = payload.get("max_attempts")
        if retry_limit is not None:
            retry_limit = int(retry_limit)
            max_attempts = (
                int(max_attempts) if max_attempts is not None else retry_limit + 1
            )
        elif max_attempts is not None:
            max_attempts = int(max_attempts)
            retry_limit = max(0, max_attempts - 1)
        else:
            retry_limit = 3
            max_attempts = 4

        image_statuses = dict(payload.get("image_statuses", {}))

        job = cls(
            job_id=str(payload["job_id"]),
            local_event_id=str(payload["local_event_id"]),
            status=str(payload.get("status", "pending")),
            attempts=int(payload.get("attempts", 0)),
            retry_limit=retry_limit,
            max_attempts=max_attempts,
            backend_event_id=payload.get("backend_event_id"),
            images_sent=int(payload.get("images_sent", 0)),
            last_error=payload.get("last_error"),
            created_at=str(payload.get("created_at", _utc_now_iso())),
            updated_at=str(payload.get("updated_at", _utc_now_iso())),
            event=dict(payload.get("event", {})),
            evidence=evidence,
            image_statuses=image_statuses,
        )
        return _normalize_job_image_statuses(job)


@dataclass
class BackendQueueResult:
    success: bool
    message: str
    job_id: str | None = None


@dataclass
class FlushQueueResult:
    success: bool
    message: str
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    exhausted: int = 0
    skipped: int = 0
    pending: int = 0
    malformed: int = 0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _detection_time_from_event(event: dict[str, Any]) -> str:
    created_at = str(event.get("created_at", _utc_now_iso()))
    last_seen_at = event.get("last_seen_at")
    source_type = str(event.get("source_type", ""))
    if source_type in {"rtsp", "webcam", "image"} and isinstance(last_seen_at, (int, float)):
        if last_seen_at > 1_000_000_000:
            return datetime.fromtimestamp(last_seen_at, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
    return created_at


def _normalize_job_image_statuses(job: BackendQueueJob) -> BackendQueueJob:
    if not job.image_statuses:
        for key in EVIDENCE_IMAGE_TYPES:
            if job.evidence.get(key):
                job.image_statuses[key] = "pending"
    return job


def _count_succeeded_images(job: BackendQueueJob) -> int:
    return sum(1 for status in job.image_statuses.values() if status == "succeeded")


class BackendClient:
    """Laravel API client with token cache and JSONL queue."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.token_cache_path = Path(config.backend_token_cache)
        self.queue_file_path = Path(config.backend_queue_file)
        self.bad_queue_path = self.queue_file_path.parent / "backend_queue.bad.jsonl"
        self.base_url = config.backend_base_url.rstrip("/")

    def _ensure_parent_dirs(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

    def _read_json_file(self, path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_json_file(self, path: Path, payload: dict[str, Any]) -> None:
        self._ensure_parent_dirs(path)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def load_token(self) -> BackendToken | None:
        payload = self._read_json_file(self.token_cache_path)
        if not payload or not payload.get("access_token"):
            return None
        return BackendToken(
            access_token=str(payload["access_token"]),
            token_type=str(payload.get("token_type", "bearer")),
            expires_at=str(payload.get("expires_at", "")),
        )

    def save_token(self, token: BackendToken) -> None:
        self._write_json_file(
            self.token_cache_path,
            {
                "access_token": token.access_token,
                "token_type": token.token_type,
                "expires_at": token.expires_at,
            },
        )

    def _token_is_valid(self, token: BackendToken) -> bool:
        if not token.expires_at:
            return False
        try:
            expires_at = _parse_iso_datetime(token.expires_at)
        except ValueError:
            return False
        now = datetime.now(timezone.utc)
        return expires_at > now + timedelta(seconds=TOKEN_EXPIRY_BUFFER_SECONDS)

    def login(self) -> BackendToken:
        if not self.config.backend_email or not self.config.backend_password:
            raise RuntimeError("Backend email and password are required for login.")

        response = self._request(
            "POST",
            "/auth/login",
            {
                "email": self.config.backend_email,
                "password": self.config.backend_password,
            },
            headers={},
            authorized=False,
            retry_on_401=False,
        )
        data = response.get("data")
        if not isinstance(data, dict) or not data.get("access_token"):
            raise RuntimeError("Login response did not include access_token.")

        expires_in = int(data.get("expires_in", 3600))
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        token = BackendToken(
            access_token=str(data["access_token"]),
            token_type=str(data.get("token_type", "bearer")),
            expires_at=expires_at,
        )
        self.save_token(token)
        return token

    def get_valid_token(self, *, force_refresh: bool = False) -> BackendToken:
        if not force_refresh:
            cached = self.load_token()
            if cached is not None and self._token_is_valid(cached):
                return cached
        return self.login()

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        *,
        headers: dict[str, str],
        authorized: bool = True,
        retry_on_401: bool = True,
        token: BackendToken | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        payload = None
        req_headers = {"Accept": "application/json"}
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            req_headers["Content-Type"] = "application/json"

        if authorized:
            token = token or self.get_valid_token()
            req_headers["Authorization"] = f"{token.token_type} {token.access_token}"

        req_headers.update(headers)
        http_request = request.Request(url, data=payload, headers=req_headers, method=method)

        try:
            with request.urlopen(http_request, timeout=self.config.backend_timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
                if not raw.strip():
                    return {}
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise RuntimeError(f"Unexpected non-object response from {path}.")
                return parsed
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            parsed: dict[str, Any] = {}
            if raw.strip():
                try:
                    loaded = json.loads(raw)
                    if isinstance(loaded, dict):
                        parsed = loaded
                except json.JSONDecodeError:
                    parsed = {"message": raw}

            if exc.code == 401 and authorized and retry_on_401:
                refreshed = self.get_valid_token(force_refresh=True)
                return self._request(
                    method,
                    path,
                    body,
                    headers=headers,
                    authorized=True,
                    retry_on_401=False,
                    token=refreshed,
                )

            message = str(parsed.get("message") or exc.reason or "HTTP error")
            raise RuntimeError(f"HTTP {exc.code} for {path}: {message}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Network error for {path}: {exc.reason}") from exc

    def build_event_payload(self, finalized_event: dict[str, Any]) -> dict[str, Any]:
        if not self.config.backend_camera_id:
            raise RuntimeError("ANPR_BACKEND_CAMERA_ID is required for backend posting.")

        confidence = float(finalized_event.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))

        return {
            "camera_id": self.config.backend_camera_id,
            "plate_number": str(finalized_event.get("plate_number", "")),
            "confidence": round(confidence, 4),
            "detection_time": _detection_time_from_event(finalized_event),
            "is_valid": True,
            "is_flagged": False,
            "latitude": None,
            "longitude": None,
        }

    def read_queue(self) -> tuple[list[BackendQueueJob], int]:
        if not self.queue_file_path.is_file():
            return [], 0
        jobs: list[BackendQueueJob] = []
        malformed = 0
        for line_number, line in enumerate(
            self.queue_file_path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                malformed += 1
                self._quarantine_bad_line(line_number, line, str(exc))
                continue
            if not isinstance(payload, dict):
                malformed += 1
                self._quarantine_bad_line(line_number, line, "Queue line is not a JSON object.")
                continue
            try:
                jobs.append(BackendQueueJob.from_dict(payload))
            except (KeyError, TypeError, ValueError) as exc:
                malformed += 1
                self._quarantine_bad_line(line_number, line, str(exc))
        return jobs, malformed

    def _quarantine_bad_line(self, line_number: int, raw: str, error: str) -> None:
        record = {"line_number": line_number, "raw": raw, "error": error}
        self._ensure_parent_dirs(self.bad_queue_path)
        with self.bad_queue_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

    def write_queue(self, jobs: list[BackendQueueJob]) -> None:
        self._ensure_parent_dirs(self.queue_file_path)
        lines = [json.dumps(job.to_dict(), separators=(",", ":")) for job in jobs]
        content = "\n".join(lines)
        if content:
            content += "\n"

        directory = self.queue_file_path.parent
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=directory,
            delete=False,
        ) as handle:
            handle.write(content)
            temp_name = handle.name
        os.replace(temp_name, self.queue_file_path)

    def _checkpoint_queue(self, jobs: list[BackendQueueJob]) -> None:
        """Atomically persist the full queue (e.g. after backend_event_id is assigned)."""
        self.write_queue(jobs)

    def enqueue_event(self, finalized_event: dict[str, Any]) -> BackendQueueResult:
        try:
            event_payload = self.build_event_payload(finalized_event)
        except RuntimeError as exc:
            return BackendQueueResult(success=False, message=str(exc))

        now = _utc_now_iso()
        retry_limit = self.config.backend_retry_limit
        job = BackendQueueJob(
            job_id=str(uuid.uuid4()),
            local_event_id=str(finalized_event.get("event_id", "")),
            status="pending",
            attempts=0,
            retry_limit=retry_limit,
            max_attempts=retry_limit + 1,
            backend_event_id=None,
            images_sent=0,
            last_error=None,
            created_at=now,
            updated_at=now,
            event=event_payload,
            evidence={
                key: finalized_event.get("evidence", {}).get(key)
                for key in EVIDENCE_IMAGE_TYPES
            },
        )
        _normalize_job_image_statuses(job)
        jobs, _ = self.read_queue()
        jobs.append(job)
        self.write_queue(jobs)
        return BackendQueueResult(
            success=True,
            message=f"Queued backend job for {job.local_event_id}",
            job_id=job.job_id,
        )

    def _extract_backend_event_id(self, response: dict[str, Any]) -> str:
        data = response.get("data")
        if isinstance(data, dict) and data.get("id"):
            return str(data["id"])
        raise RuntimeError("Event creation response did not include data.id.")

    def _image_resolution(self, path: str | None) -> str | None:
        if not path:
            return None
        try:
            import cv2

            image = cv2.imread(path)
            if image is None:
                return None
            height, width = image.shape[:2]
            return f"{width}x{height}"
        except Exception:
            return None

    def _image_file_size(self, path: str | None) -> int | None:
        if not path:
            return None
        file_path = Path(path)
        if not file_path.is_file():
            return None
        return file_path.stat().st_size

    def _post_image_metadata(
        self,
        job: BackendQueueJob,
        backend_event_id: str,
        image_type: str,
        file_path: str,
    ) -> None:
        payload = {
            "anpr_event_id": backend_event_id,
            "image_type": image_type,
            "file_path": file_path,
            "file_size": self._image_file_size(file_path),
            "resolution": self._image_resolution(file_path),
            "expires_at": None,
        }
        self._request("POST", "/anpr-images", payload, headers={})

    def _ensure_upload_mode_supported(self) -> None:
        if self.config.backend_enabled and self.config.evidence_mode == "upload":
            raise RuntimeError(UPLOAD_MODE_ERROR)

    def _send_pending_image_metadata(self, job: BackendQueueJob, backend_event_id: str) -> None:
        for image_type in EVIDENCE_IMAGE_TYPES:
            status = job.image_statuses.get(image_type)
            if status in IMAGE_STATUSES_FINAL:
                continue

            file_path = job.evidence.get(image_type)
            if not file_path:
                job.image_statuses[image_type] = "skipped"
                continue

            try:
                self._post_image_metadata(job, backend_event_id, image_type, file_path)
            except RuntimeError as exc:
                message = str(exc)
                if "HTTP 422" in message or "Validation failed" in message:
                    job.image_statuses[image_type] = "validation_failed"
                    raise RuntimeError(message) from exc
                job.image_statuses[image_type] = "failed"
                raise

            job.image_statuses[image_type] = "succeeded"

    def _pending_image_types(self, job: BackendQueueJob) -> list[str]:
        pending: list[str] = []
        for image_type in EVIDENCE_IMAGE_TYPES:
            status = job.image_statuses.get(image_type)
            if status in IMAGE_STATUSES_RETRYABLE or status is None:
                if job.evidence.get(image_type):
                    pending.append(image_type)
        return pending

    def _process_job(
        self,
        job: BackendQueueJob,
        all_jobs: list[BackendQueueJob] | None = None,
        job_index: int | None = None,
    ) -> BackendQueueJob:
        job = _normalize_job_image_statuses(job)
        now = _utc_now_iso()
        job.status = "posting"
        job.updated_at = now

        try:
            self._ensure_upload_mode_supported()

            backend_event_id = job.backend_event_id
            event_created = False
            if not backend_event_id:
                response = self._request("POST", "/anpr-events", job.event, headers={})
                backend_event_id = self._extract_backend_event_id(response)
                job.backend_event_id = backend_event_id
                job.updated_at = _utc_now_iso()
                event_created = True

            if event_created and all_jobs is not None and job_index is not None:
                all_jobs[job_index] = job
                self._checkpoint_queue(all_jobs)

            if self.config.evidence_mode == "metadata":
                self._send_pending_image_metadata(job, backend_event_id)
                pending_images = self._pending_image_types(job)
                if pending_images:
                    raise RuntimeError(
                        "Image metadata incomplete for: " + ", ".join(pending_images)
                    )

            job.images_sent = _count_succeeded_images(job)
            job.status = "succeeded"
            job.last_error = None
            job.updated_at = _utc_now_iso()
            return job
        except RuntimeError as exc:
            message = str(exc)
            job.last_error = message
            job.updated_at = _utc_now_iso()
            job.images_sent = _count_succeeded_images(job)

            if message == UPLOAD_MODE_ERROR:
                job.status = "validation_failed"
                return job

            if "HTTP 422" in message or "Validation failed" in message:
                job.status = "validation_failed"
                return job

            job.attempts += 1
            if job.attempts >= job.max_attempts:
                job.status = "exhausted"
            else:
                job.status = "failed"
            return job

    def flush_queue(self) -> FlushQueueResult:
        if not self.config.backend_enabled:
            return FlushQueueResult(
                success=True,
                message="Backend is disabled; no queue items processed.",
                processed=0,
            )

        try:
            self._ensure_upload_mode_supported()
        except RuntimeError as exc:
            return FlushQueueResult(success=False, message=str(exc))

        jobs, malformed = self.read_queue()
        if malformed:
            print(
                f"WARNING: Skipped {malformed} malformed queue line(s); "
                f"quarantined to {self.bad_queue_path}"
            )

        if not jobs:
            if malformed:
                self._checkpoint_queue([])
            message = "Backend queue is empty."
            if malformed:
                message += f" Skipped {malformed} malformed line(s)."
            return FlushQueueResult(
                success=True,
                message=message,
                processed=0,
                pending=0,
                malformed=malformed,
            )

        processed = 0
        succeeded = 0
        failed = 0
        exhausted = 0
        skipped = 0

        for index, job in enumerate(jobs):
            if job.status in QUEUE_STATUSES_SKIP:
                skipped += 1
                continue

            if job.status not in QUEUE_STATUSES_RETRYABLE:
                skipped += 1
                continue

            if job.attempts >= job.max_attempts:
                job.status = "exhausted"
                exhausted += 1
                skipped += 1
                jobs[index] = job
                continue

            processed += 1
            jobs[index] = self._process_job(jobs[index], jobs, index)
            job = jobs[index]

            if job.status == "succeeded":
                succeeded += 1
            elif job.status == "exhausted":
                exhausted += 1
            elif job.status == "validation_failed":
                failed += 1
            elif job.status == "failed":
                failed += 1

        self._checkpoint_queue(jobs)
        pending = sum(1 for job in jobs if job.status in QUEUE_STATUSES_RETRYABLE)

        return FlushQueueResult(
            success=True,
            message="Backend queue flush completed.",
            processed=processed,
            succeeded=succeeded,
            failed=failed,
            exhausted=exhausted,
            skipped=skipped,
            pending=pending,
            malformed=malformed,
        )

    def job_results_for_local_events(
        self, local_event_ids: set[str]
    ) -> dict[str, dict[str, Any]]:
        if not local_event_ids:
            return {}
        jobs, _ = self.read_queue()
        results: dict[str, dict[str, Any]] = {}
        for job in jobs:
            if job.local_event_id not in local_event_ids:
                continue
            results[job.local_event_id] = {
                "job_id": job.job_id,
                "status": job.status,
                "backend_event_id": job.backend_event_id,
                "images_sent": job.images_sent,
                "last_error": job.last_error,
            }
        return results
