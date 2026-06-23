"""CLI entry point for AI ANPR (M15)."""

from __future__ import annotations

import argparse
import sys

from anpr import ANPRProcessor
from backend import BackendClient
from config import Config, RTSP_URL_CLI_ERROR, format_validation_output, is_rtsp_source_path, validate_backend_config, validate_config


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-anpr",
        description="AI ANPR CLI — M15 performance and accuracy tuning architecture",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser(
        "check-config",
        help="Validate configuration, sources, models, and backend settings",
    )
    check_parser.add_argument(
        "--strict",
        action="store_true",
        help="Require configured model files to exist",
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Run ANPR processing with M15 performance tuning runtime",
    )
    run_parser.add_argument(
        "--source",
        choices=["rtsp", "video", "image", "webcam"],
        help="Input source type",
    )
    run_parser.add_argument(
        "--source-path",
        help="Local video or image file path (not for RTSP URLs; use ANPR_RTSP_URL in .env)",
    )
    run_parser.add_argument(
        "--video",
        help="Path to a video file",
    )
    run_parser.add_argument(
        "--image",
        help="Path to an image file",
    )
    run_parser.add_argument(
        "--camera-index",
        type=int,
        help="Webcam camera index",
    )
    run_parser.add_argument(
        "--max-seconds",
        type=float,
        help="Maximum processing duration in seconds",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Local events/evidence only; no backend enqueue or posting",
    )
    run_parser.add_argument(
        "--strict",
        action="store_true",
        help="Require configured model files to exist",
    )

    subparsers.add_parser(
        "flush-backend-queue",
        help="Flush pending backend queue jobs to the Laravel API",
    )

    return parser


def _print_validation_result(title: str, result) -> None:
    print(title)
    print("-" * 40)
    print(format_validation_output(result))
    print("-" * 40)
    if result.warnings:
        print(f"Warnings: {len(result.warnings)}")
    if result.errors:
        print(f"Errors: {len(result.errors)}")
        print("FAILURE: configuration validation failed.")
    elif result.warnings:
        print("SUCCESS: configuration is valid with warnings.")
    else:
        print("SUCCESS: configuration is valid.")


def cmd_check_config(config: Config, args: argparse.Namespace) -> int:
    result = validate_config(config, strict=args.strict)
    _print_validation_result("Configuration check", result)
    return 0 if result.ok else 1


def _print_run_summary(dry_run) -> None:
    print(f"Run directory: {dry_run.run_dir}")
    print(f"Frames read: {dry_run.summary.get('frames_read', 0)}")
    print(f"Frames processed: {dry_run.summary.get('frames_processed', 0)}")
    print(f"Vehicle detections: {dry_run.summary.get('vehicle_detections', 0)}")
    print(f"Plate detections: {dry_run.summary.get('plate_detections', 0)}")
    print(f"OCR calls: {dry_run.summary.get('ocr_calls', 0)}")
    print(f"OCR readings: {dry_run.summary.get('ocr_readings', 0)}")
    print(f"Plate candidates: {dry_run.summary.get('plate_candidates', 0)}")
    print(f"Tracks created: {dry_run.summary.get('tracks_created', 0)}")
    print(f"Plate votes added: {dry_run.summary.get('plate_votes_added', 0)}")
    print(f"Tracks finalized: {dry_run.summary.get('tracks_finalized', 0)}")
    finalized = dry_run.summary.get("finalized_track_candidates", [])
    print(f"Finalized track candidates: {len(finalized)}")
    print(f"Events finalized: {dry_run.summary.get('events_finalized', 0)}")
    print(f"Events written: {dry_run.summary.get('events_written', 0)}")
    print(f"Evidence files saved: {dry_run.summary.get('evidence_files_saved', 0)}")
    print(f"Duplicate events suppressed: {dry_run.summary.get('duplicate_events_suppressed', 0)}")
    print(f"Processed FPS: {dry_run.summary.get('processed_fps', 0)}")
    avg_latency = dry_run.summary.get("average_event_latency_seconds")
    print(
        f"Average event latency (s): "
        f"{avg_latency if avg_latency is not None else 'n/a'}"
    )
    print(f"OCR calls skipped by throttle: {dry_run.summary.get('ocr_calls_skipped_by_throttle', 0)}")
    print(f"Backend jobs queued: {dry_run.summary.get('backend_jobs_queued', 0)}")
    print(f"Backend jobs succeeded: {dry_run.summary.get('backend_jobs_succeeded', 0)}")
    print(f"Backend jobs failed: {dry_run.summary.get('backend_jobs_failed', 0)}")
    print(f"Backend jobs exhausted: {dry_run.summary.get('backend_jobs_exhausted', 0)}")
    print(f"Worker log: {dry_run.worker_log}")
    print(f"Worker summary: {dry_run.worker_summary}")
    print(f"Events file: {dry_run.events_file}")


def cmd_run(config: Config, args: argparse.Namespace) -> int:
    if getattr(args, "source_path", None) and is_rtsp_source_path(args.source_path):
        print(f"ERROR: {RTSP_URL_CLI_ERROR}")
        return 1

    config.apply_cli_overrides(args)

    if not args.dry_run and not config.backend_enabled:
        print(
            "ERROR: Non-dry-run execution requires ANPR_BACKEND_ENABLED=true.\n"
            "Use --dry-run for local-only validation."
        )
        return 1

    result = validate_config(config, strict=args.strict)
    if not result.ok:
        print("Configuration validation failed before run:")
        print(format_validation_output(result))
        return 1

    processor = ANPRProcessor(config)
    run_result = (
        processor.run_dry_run(result, strict=args.strict)
        if args.dry_run
        else processor.run(result, strict=args.strict)
    )

    if run_result.summary.get("status") == "failed":
        error = run_result.summary.get("errors", ["Unknown runtime error"])
        print(f"ERROR: {error[0] if error else 'Run failed.'}")
        _print_run_summary(run_result)
        return 1

    label = "Dry-run completed successfully." if args.dry_run else "Run completed successfully."
    print(label)
    _print_run_summary(run_result)
    if result.warnings:
        print(f"Warnings ({len(result.warnings)}):")
        for warning in result.warnings:
            print(f"  - {warning}")
    return 0


def cmd_flush_backend_queue(config: Config) -> int:
    if not config.backend_enabled:
        print("Backend disabled (ANPR_BACKEND_ENABLED=false). No jobs to flush.")
        return 0

    result = validate_backend_config(config)
    if not result.ok:
        print("Backend configuration validation failed before queue flush:")
        print(format_validation_output(result))
        return 1

    client = BackendClient(config)
    flush_result = client.flush_queue()
    print(flush_result.message)
    print(f"Processed: {flush_result.processed}")
    print(f"Succeeded: {flush_result.succeeded}")
    print(f"Failed: {flush_result.failed}")
    print(f"Exhausted: {flush_result.exhausted}")
    print(f"Skipped: {flush_result.skipped}")
    print(f"Pending: {flush_result.pending}")
    print(f"Malformed: {flush_result.malformed}")
    return 0 if flush_result.success else 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    config = Config.from_env()

    if args.command == "check-config":
        return cmd_check_config(config, args)
    if args.command == "run":
        return cmd_run(config, args)
    if args.command == "flush-backend-queue":
        return cmd_flush_backend_queue(config)

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
