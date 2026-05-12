"""
Log rotation and cleanup job.
Rotates operation logs, compresses archives, deletes old files.
"""
import logging
import gzip
import shutil
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def rotate_operation_log(
    log_path: Path,
    max_age_days: int = 30,
    rotation_size_mb: int = 10,
) -> None:
    """
    Rotate operation log and clean up old archives.
    
    Args:
        log_path: Path to data/wiki/log.md
        max_age_days: Delete archives older than this (default: 30)
        rotation_size_mb: Rotate when log exceeds this size (default: 10MB)
    """
    if not log_path.exists():
        logger.info(f"Log file does not exist: {log_path}")
        return

    log_size_mb = log_path.stat().st_size / (1024 * 1024)
    
    # Check if rotation needed
    if log_size_mb < rotation_size_mb:
        logger.debug(f"Log size {log_size_mb:.1f}MB < threshold {rotation_size_mb}MB")
        return

    # Create archive directory
    archive_dir = log_path.parent / ".archives"
    archive_dir.mkdir(exist_ok=True)

    # Rotate: rename current log to timestamped archive
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    archive_path = archive_dir / f"log_{timestamp}.md.gz"

    try:
        # Compress and archive
        with open(log_path, "rb") as f_in:
            with gzip.open(archive_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        # Clear original log (truncate to empty)
        log_path.write_text("")
        logger.info(f"Rotated log to: {archive_path}")

    except Exception as exc:
        logger.error(f"Failed to rotate log: {exc}")
        return

    # Clean up old archives
    cutoff_time = datetime.utcnow() - timedelta(days=max_age_days)
    cutoff_timestamp = cutoff_time.timestamp()

    for archive_file in archive_dir.glob("log_*.md.gz"):
        file_mtime = archive_file.stat().st_mtime
        if file_mtime < cutoff_timestamp:
            try:
                archive_file.unlink()
                logger.info(f"Deleted old archive: {archive_file.name}")
            except Exception as exc:
                logger.error(f"Failed to delete archive {archive_file.name}: {exc}")


def cleanup_stale_files(
    base_dir: Path,
    max_age_days: int = 60,
    patterns: list[str] | None = None,
) -> None:
    """
    Clean up stale files in cache/temp directories.
    
    Args:
        base_dir: Directory to scan
        max_age_days: Delete files older than this
        patterns: Glob patterns to match (e.g., ["*.tmp", "*cache*"])
    """
    if patterns is None:
        patterns = ["*.tmp", "*cache*", ".DS_Store"]

    if not base_dir.exists():
        return

    cutoff_time = datetime.utcnow() - timedelta(days=max_age_days)
    cutoff_timestamp = cutoff_time.timestamp()

    deleted_count = 0
    for pattern in patterns:
        for file_path in base_dir.rglob(pattern):
            if file_path.is_file():
                file_mtime = file_path.stat().st_mtime
                if file_mtime < cutoff_timestamp:
                    try:
                        file_path.unlink()
                        deleted_count += 1
                    except Exception as exc:
                        logger.warning(
                            f"Failed to delete {file_path.relative_to(base_dir)}: {exc}"
                        )

    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} stale files in {base_dir.name}")


async def run_cleanup_job(
    wiki_dir: Path,
    max_log_age_days: int = 30,
    max_cache_age_days: int = 60,
) -> dict[str, any]:
    """
    Run all cleanup tasks. Called by scheduler or manual trigger.
    
    Returns:
        Status report with counts of cleaned items
    """
    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "log_rotated": False,
        "stale_files_cleaned": 0,
    }

    # Rotate wiki log
    log_path = wiki_dir / "log.md"
    if log_path.exists():
        log_size_mb = log_path.stat().st_size / (1024 * 1024)
        if log_size_mb > 10:  # Rotate if >10MB
            rotate_operation_log(log_path, max_age_days=max_log_age_days)
            report["log_rotated"] = True

    # Clean temp/cache files
    data_dir = wiki_dir.parent if wiki_dir.name == "wiki" else wiki_dir
    cleanup_stale_files(
        data_dir,
        max_age_days=max_cache_age_days,
        patterns=["*.tmp", "*.log", ".DS_Store"],
    )

    logger.info(f"Cleanup job completed: {report}")
    return report
