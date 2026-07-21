from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time
from typing import Any, Iterator, Mapping
from uuid import uuid4

from .source_state import EFFECTIVE_OK_CACHED, SourceState


STANDARD_CARDS_SOURCE_ID = "hsreplay_cards_legend_1d"
_RECORD_SCHEMA_VERSION = 1
_MANIFEST_SCHEMA_VERSION = 2
_DEFAULT_MAX_STALE_HOURS = 36.0
_DEFAULT_QUARANTINE_LIMIT = 20
_DEFAULT_PUBLICATION_RETENTION = 5
_MIN_PUBLICATION_RETENTION = 2
_MAX_PUBLICATION_RETENTION = 20
_MAX_FUTURE_CLOCK_SKEW_SECONDS = 300.0
_MAX_DIAGNOSTICS_BYTES = 32_768
PUBLIC_STANDARD_CARDS_REPRESENTATION_SCHEMA_VERSION = "1"
_UNSET = object()
_write_lock = threading.RLock()
_transaction_thread_lock = threading.RLock()
_transaction_lock_pid = os.getpid()
_transaction_local = threading.local()


class PublicationUnavailable(RuntimeError):
    def __init__(self, reason: str, detail: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or reason


@dataclass(frozen=True)
class PublishedDataset:
    dataset: dict[str, Any]
    dataset_version: str
    published_at: str
    stale: bool
    fallback_reason: str | None
    age_hours: float
    representation_revision: str


@dataclass(frozen=True)
class PublicationDecision:
    accepted: bool
    dataset_version: str
    reason: str
    diagnostics: dict[str, Any]
    rejection_kind: str | None = None


@dataclass(frozen=True)
class PublicationReconciliation:
    dataset: dict[str, Any]
    dataset_version: str
    candidate_dataset_version: str | None
    status: dict[str, Any]
    cache_synced: bool
    status_synced: bool
    superseded: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class PublicationAttempt:
    generation: int
    attempt_id: str
    started_at: str


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def dataset_version(dataset: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(dataset)).hexdigest()


def _bounded_diagnostics(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized = json.loads(
        json.dumps(dict(payload or {}), ensure_ascii=False, default=str)
    )
    encoded = _canonical_json(normalized)
    if len(encoded) <= _MAX_DIAGNOSTICS_BYTES:
        return normalized
    return {
        "truncated": True,
        "original_bytes": len(encoded),
        "preview": encoded[: _MAX_DIAGNOSTICS_BYTES - 256].decode(
            "utf-8", errors="replace"
        ),
    }


def _finite_bounded_float(
    value: Any,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(parsed):
        return default
    return min(max(parsed, minimum), maximum)


def _configured_max_stale_hours() -> float:
    return _finite_bounded_float(
        os.environ.get(
            "HS_STANDARD_CARDS_MAX_STALE_HOURS",
            str(_DEFAULT_MAX_STALE_HOURS),
        ),
        default=_DEFAULT_MAX_STALE_HOURS,
        minimum=0.25,
        maximum=168.0,
    )


def _configured_quarantine_limit() -> int:
    raw = os.environ.get(
        "HS_STANDARD_CARDS_QUARANTINE_LIMIT", str(_DEFAULT_QUARANTINE_LIMIT)
    )
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_QUARANTINE_LIMIT
    return min(max(value, 1), 100)


def _configured_publication_retention() -> int:
    raw = os.environ.get(
        "HS_STANDARD_CARDS_PUBLICATION_RETENTION",
        str(_DEFAULT_PUBLICATION_RETENTION),
    )
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_PUBLICATION_RETENTION
    return min(
        max(value, _MIN_PUBLICATION_RETENTION),
        _MAX_PUBLICATION_RETENTION,
    )


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _effective_now(now: datetime | None) -> datetime:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _dataset_age_hours(
    dataset: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_stale_hours: float | None = None,
    reason_prefix: str,
) -> float:
    try:
        fetched_at = _parse_utc(dataset.get("fetched_at"))
    except (TypeError, ValueError) as exc:
        raise PublicationUnavailable(
            f"{reason_prefix}_corrupt", "Dataset timestamp is invalid"
        ) from exc
    effective_now = _effective_now(now)
    delta_seconds = (effective_now - fetched_at).total_seconds()
    if delta_seconds < -_MAX_FUTURE_CLOCK_SKEW_SECONDS:
        raise PublicationUnavailable(
            f"{reason_prefix}_from_future",
            (
                "Dataset timestamp is more than "
                f"{int(_MAX_FUTURE_CLOCK_SKEW_SECONDS)} seconds in the future"
            ),
        )
    age_hours = max(0.0, delta_seconds / 3600.0)
    allowed_age = (
        _configured_max_stale_hours()
        if max_stale_hours is None
        else _finite_bounded_float(
            max_stale_hours,
            default=_DEFAULT_MAX_STALE_HOURS,
            minimum=0.25,
            maximum=168.0,
        )
    )
    if age_hours > allowed_age:
        raise PublicationUnavailable(
            f"{reason_prefix}_too_old",
            f"Dataset is {age_hours:.2f}h old (limit {allowed_age:.2f}h)",
        )
    return age_hours


def _durable_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    with _write_lock:
        try:
            with temporary.open("wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o644)
            os.replace(temporary, path)
            try:
                directory_fd = os.open(path.parent, os.O_RDONLY)
            except OSError:
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)


def _process_thread_lock() -> threading.RLock:
    global _transaction_thread_lock, _transaction_lock_pid
    process_id = os.getpid()
    if _transaction_lock_pid != process_id:
        _transaction_thread_lock = threading.RLock()
        _transaction_lock_pid = process_id
    return _transaction_thread_lock


class DatasetPublicationStore:
    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            from .storage import root_dir

            root = root_dir()
        self.root = Path(root)

    def _source_root(self, source_id: str) -> Path:
        if source_id != STANDARD_CARDS_SOURCE_ID:
            raise ValueError(f"Publication channel is not enabled for {source_id}")
        path = self.root / "publications" / source_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def candidate_path(self, source_id: str) -> Path:
        return self._source_root(source_id) / "candidate.json"

    def published_path(self, source_id: str) -> Path:
        # Schema 2 reuses the legacy path as an atomic migration-safe manifest.
        return self._source_root(source_id) / "published.json"

    def versions_dir(self, source_id: str) -> Path:
        path = self._source_root(source_id) / "versions"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def version_path(self, source_id: str, version: str) -> Path:
        if (
            len(version) != 64
            or any(character not in "0123456789abcdef" for character in version)
        ):
            raise ValueError("Invalid publication dataset version")
        return self.versions_dir(source_id) / f"{version}.json"

    def quarantine_dir(self, source_id: str) -> Path:
        path = self._source_root(source_id) / "quarantine"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def attempt_state_path(self, source_id: str) -> Path:
        return self._source_root(source_id) / "attempt-state.json"

    def _compatibility_status_path(self, source_id: str) -> Path:
        """Return the mutable status beside this store, including test stores."""

        return self.root / "statuses" / f"{source_id}.json"

    def _read_compatibility_status(self, source_id: str) -> dict[str, Any] | None:
        path = self._compatibility_status_path(source_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Mutable status is not an object")
        return payload

    def _read_attempt_state(self, source_id: str) -> dict[str, Any] | None:
        path = self.attempt_state_path(source_id)
        if not path.exists():
            return None
        record = self._read_record(path, reason="attempt_state_corrupt")
        if (
            record.get("schema_version") != 1
            or record.get("source_id") != source_id
            or not isinstance(record.get("last_generation"), int)
            or isinstance(record.get("last_generation"), bool)
            or int(record["last_generation"]) < 1
        ):
            raise PublicationUnavailable(
                "attempt_state_corrupt", "Invalid publication attempt state"
            )
        return record

    def begin_publication_attempt(self, source_id: str) -> PublicationAttempt:
        """Durably allocate a source-local monotonic refresh generation."""

        with self.publication_transaction(source_id):
            recovered = False
            try:
                state = self._read_attempt_state(source_id)
            except PublicationUnavailable:
                state = None
                recovered = True
            last_generation = (
                int(state["last_generation"]) if state is not None else 0
            )
            try:
                status = self._read_compatibility_status(source_id) or {}
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                status = {}
            status_generation = status.get("publication_attempt_generation")
            if isinstance(status_generation, int) and not isinstance(
                status_generation, bool
            ):
                last_generation = max(last_generation, status_generation)
            if state is None and (
                recovered
                or last_generation
                or self.published_path(source_id).exists()
            ):
                # Losing/corrupting the control file must never move the clock
                # behind an in-flight attempt from before recovery.
                last_generation = max(last_generation, time.time_ns())
            attempt = PublicationAttempt(
                generation=last_generation + 1,
                attempt_id=uuid4().hex,
                started_at=_now_iso(),
            )
            _durable_write_json(
                self.attempt_state_path(source_id),
                {
                    "schema_version": 1,
                    "source_id": source_id,
                    "last_generation": attempt.generation,
                    "last_attempt_id": attempt.attempt_id,
                    "last_started_at": attempt.started_at,
                },
            )
            return attempt

    @contextmanager
    def publication_transaction(self, source_id: str) -> Iterator[None]:
        lock_path = self._source_root(source_id) / ".publication.lock"
        key = str(lock_path.resolve())
        process_id = os.getpid()
        lock = _process_thread_lock()
        with lock:
            local_pid = getattr(_transaction_local, "pid", None)
            if local_pid != process_id:
                _transaction_local.pid = process_id
                _transaction_local.held = set()
            held: set[str] = _transaction_local.held
            if key in held:
                yield
                return
            with lock_path.open("a+b") as stream:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                held.add(key)
                try:
                    yield
                finally:
                    held.remove(key)
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def stage_candidate(
        self,
        source_id: str,
        dataset: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self.publication_transaction(source_id):
            snapshot = json.loads(
                json.dumps(dict(dataset), ensure_ascii=False, default=str)
            )
            version = dataset_version(snapshot)
            record = {
                "schema_version": _RECORD_SCHEMA_VERSION,
                "source_id": source_id,
                "dataset_version": version,
                "staged_at": _now_iso(),
                "fetched_at": snapshot.get("fetched_at"),
                "backend": snapshot.get("backend"),
                "dataset": snapshot,
            }
            _durable_write_json(self.candidate_path(source_id), record)
            return record

    def _read_record(self, path: Path, *, reason: str) -> dict[str, Any]:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise PublicationUnavailable(
                reason, f"Missing publication file: {path.name}"
            ) from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PublicationUnavailable(
                reason, f"Unreadable publication file: {path.name}"
            ) from exc
        if not isinstance(record, dict):
            raise PublicationUnavailable(
                reason, f"Invalid publication record: {path.name}"
            )
        return record

    @staticmethod
    def _verified_dataset(record: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
        dataset = record.get("dataset")
        version = record.get("dataset_version")
        if not isinstance(dataset, dict) or not isinstance(version, str):
            raise PublicationUnavailable(
                reason, "Publication record has no dataset/version"
            )
        if dataset_version(dataset) != version:
            raise PublicationUnavailable(reason, "Publication dataset hash mismatch")
        return dataset

    def _verified_version_record(
        self,
        source_id: str,
        version: str,
        *,
        reason: str = "published_corrupt",
    ) -> dict[str, Any]:
        record = self._read_record(self.version_path(source_id, version), reason=reason)
        if record.get("schema_version") != _RECORD_SCHEMA_VERSION:
            raise PublicationUnavailable(reason, "Unsupported version-record schema")
        if record.get("source_id") != source_id:
            raise PublicationUnavailable(reason, "Version-record source mismatch")
        if record.get("dataset_version") != version:
            raise PublicationUnavailable(reason, "Version-record identity mismatch")
        self._verified_dataset(record, reason=reason)
        return record

    def _read_publication_pointer(
        self,
        source_id: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Read and validate the pointer without dereferencing its current version.

        Callers must hold ``publication_transaction`` for as long as they use the
        returned pointer. Keeping pointer validation separate is intentional: an
        administrator must be able to roll back from a checksum-valid manifest
        whose current immutable file was damaged.
        """

        publication = self._read_record(
            self.published_path(source_id), reason="published_corrupt"
        )
        # Backward-compatible schema-1 publication record.
        if "dataset" in publication:
            if publication.get("schema_version") != _RECORD_SCHEMA_VERSION:
                raise PublicationUnavailable(
                    "published_corrupt", "Unsupported legacy publication schema"
                )
            if publication.get("source_id") != source_id:
                raise PublicationUnavailable("published_corrupt", "Source id mismatch")
            self._verified_dataset(publication, reason="published_corrupt")
            return None, publication

        if publication.get("schema_version") != _MANIFEST_SCHEMA_VERSION:
            raise PublicationUnavailable(
                "published_corrupt", "Unsupported manifest schema"
            )
        if publication.get("source_id") != source_id:
            raise PublicationUnavailable("published_corrupt", "Source id mismatch")
        current = publication.get("current_version")
        versions = publication.get("versions")
        checksum = publication.get("manifest_checksum")
        if (
            not isinstance(current, str)
            or not isinstance(versions, list)
            or not versions
            or versions[0] != current
            or any(not isinstance(item, str) for item in versions)
            or len(set(versions)) != len(versions)
            or len(versions) > _MAX_PUBLICATION_RETENTION
            or any(
                len(item) != 64
                or any(character not in "0123456789abcdef" for character in item)
                for item in versions
            )
            or not isinstance(checksum, str)
        ):
            raise PublicationUnavailable(
                "published_corrupt", "Invalid publication manifest"
            )
        checksum_payload = {
            key: publication.get(key)
            for key in (
                "schema_version",
                "source_id",
                "current_version",
                "versions",
                "updated_at",
            )
        }
        expected_checksum = hashlib.sha256(
            _canonical_json(checksum_payload)
        ).hexdigest()
        if checksum != expected_checksum:
            raise PublicationUnavailable(
                "published_corrupt", "Publication manifest checksum mismatch"
            )
        return publication, publication

    def _manifest_and_current_record(
        self,
        source_id: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        with self.publication_transaction(source_id):
            manifest, pointer = self._read_publication_pointer(source_id)
            if manifest is None:
                return None, pointer
            current = str(manifest["current_version"])
            return manifest, self._verified_version_record(source_id, current)

    def _history_versions(self, source_id: str) -> tuple[list[str], dict[str, Any] | None]:
        manifest, current_record = self._manifest_and_current_record(source_id)
        if manifest is None:
            return [str(current_record["dataset_version"])], current_record
        return list(manifest["versions"]), None

    def quarantine_candidate(
        self,
        source_id: str,
        candidate_version: str,
        *,
        reason: str,
        diagnostics: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.publication_transaction(source_id):
            candidate = self._read_record(
                self.candidate_path(source_id), reason="candidate_corrupt"
            )
            dataset = self._verified_dataset(candidate, reason="candidate_corrupt")
            if candidate.get("dataset_version") != candidate_version:
                raise PublicationUnavailable(
                    "candidate_changed", "Candidate changed before quarantine"
                )
            created_at = _now_iso()
            record = {
                "schema_version": _RECORD_SCHEMA_VERSION,
                "source_id": source_id,
                "dataset_version": candidate_version,
                "created_at": created_at,
                "fetched_at": dataset.get("fetched_at"),
                "backend": dataset.get("backend"),
                "reason": str(reason or "candidate rejected")[:2000],
                "diagnostics": _bounded_diagnostics(diagnostics),
                "dataset": dataset,
            }
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            path = (
                self.quarantine_dir(source_id)
                / f"{stamp}.{candidate_version[:16]}.json"
            )
            _durable_write_json(path, record)
            self._prune_quarantine(source_id)
            return self._quarantine_summary(record)

    def _prune_quarantine(self, source_id: str) -> None:
        paths = sorted(
            self.quarantine_dir(source_id).glob("*.json"),
            key=lambda path: path.name,
            reverse=True,
        )
        for stale in paths[_configured_quarantine_limit() :]:
            try:
                stale.unlink(missing_ok=True)
            except OSError as exc:
                self._log_quarantine_prune_failure(source_id, stale, exc)

    @staticmethod
    def _log_quarantine_prune_failure(
        source_id: str, path: Path, exc: OSError
    ) -> None:
        try:
            from .refresh_log import log_action

            log_action(
                "dataset.quarantine.prune.fail",
                source_id=source_id,
                level="warn",
                detail=f"Failed to remove quarantined candidate {path.name}: {exc}"[
                    :1000
                ],
            )
        except Exception:
            pass

    @staticmethod
    def _quarantine_summary(record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: record.get(key)
            for key in (
                "source_id",
                "dataset_version",
                "created_at",
                "fetched_at",
                "backend",
                "reason",
                "diagnostics",
            )
        }

    def list_quarantine(
        self, source_id: str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        safe_limit = min(max(int(limit), 1), 100)
        paths = sorted(
            self.quarantine_dir(source_id).glob("*.json"),
            key=lambda path: path.name,
            reverse=True,
        )
        for path in paths[:safe_limit]:
            try:
                record = self._read_record(path, reason="quarantine_corrupt")
            except PublicationUnavailable:
                rows.append(
                    {
                        "source_id": source_id,
                        "reason": "quarantine_corrupt",
                        "file": path.name,
                    }
                )
                continue
            rows.append(self._quarantine_summary(record))
        return rows

    @staticmethod
    def _version_summary(
        record: Mapping[str, Any], *, current: bool
    ) -> dict[str, Any]:
        dataset = record.get("dataset") if isinstance(record.get("dataset"), dict) else {}
        return {
            "source_id": record.get("source_id"),
            "dataset_version": record.get("dataset_version"),
            "published_at": record.get("published_at"),
            "fetched_at": dataset.get("fetched_at"),
            "backend": dataset.get("backend"),
            "current": current,
        }

    def list_published_versions(self, source_id: str) -> list[dict[str, Any]]:
        with self.publication_transaction(source_id):
            if not self.published_path(source_id).exists():
                return []
            manifest, current_record = self._manifest_and_current_record(source_id)
            if manifest is None:
                return [self._version_summary(current_record, current=True)]
            rows: list[dict[str, Any]] = []
            for index, version in enumerate(manifest["versions"]):
                record = self._verified_version_record(source_id, version)
                rows.append(self._version_summary(record, current=index == 0))
            return rows

    def read_version_dataset(self, source_id: str, version: str) -> dict[str, Any]:
        with self.publication_transaction(source_id):
            manifest, pointer = self._read_publication_pointer(source_id)
            if manifest is None:
                if pointer.get("dataset_version") != version:
                    raise PublicationUnavailable(
                        "rollback_version_not_retained",
                        "Requested version is not retained",
                    )
                return self._verified_dataset(pointer, reason="published_corrupt")
            if version not in manifest["versions"]:
                raise PublicationUnavailable(
                    "rollback_version_not_retained", "Requested version is not retained"
                )
            record = self._verified_version_record(source_id, version)
            return self._verified_dataset(record, reason="published_corrupt")

    def rollback_target_version(
        self, source_id: str, requested_version: str | None = None
    ) -> str:
        with self.publication_transaction(source_id):
            manifest, pointer = self._read_publication_pointer(source_id)
            if manifest is None:
                raise PublicationUnavailable(
                    "rollback_previous_missing", "No previous publication is retained"
                )
            current = str(manifest["current_version"])
            history = list(manifest["versions"])
            if requested_version:
                if requested_version not in history:
                    raise PublicationUnavailable(
                        "rollback_version_not_retained",
                        "Requested version is not retained",
                    )
                if requested_version == current:
                    raise PublicationUnavailable(
                        "rollback_already_current",
                        "Requested version is already current",
                    )
                self._verified_version_record(source_id, requested_version)
                return requested_version
            for version in history:
                if version == current:
                    continue
                try:
                    self._verified_version_record(source_id, version)
                except PublicationUnavailable:
                    continue
                return str(version)
            raise PublicationUnavailable(
                "rollback_previous_missing", "No valid previous publication is retained"
            )

    def pointer_dataset_version(self, source_id: str) -> str | None:
        """Return the manifest pointer without requiring its immutable file to open."""

        with self.publication_transaction(source_id):
            if not self.published_path(source_id).exists():
                return None
            manifest, pointer = self._read_publication_pointer(source_id)
            if manifest is None:
                return str(pointer["dataset_version"])
            return str(manifest["current_version"])

    def _persist_legacy_version(
        self, source_id: str, record: Mapping[str, Any]
    ) -> str:
        version = str(record["dataset_version"])
        path = self.version_path(source_id, version)
        if path.exists():
            self._verified_version_record(source_id, version)
        else:
            _durable_write_json(path, dict(record))
        return version

    def _discover_valid_versions(self, source_id: str) -> list[str]:
        records: list[tuple[datetime, datetime, str]] = []
        latest_allowed = datetime.now(UTC).timestamp() + _MAX_FUTURE_CLOCK_SKEW_SECONDS
        for path in self.versions_dir(source_id).glob("*.json"):
            try:
                record = self._verified_version_record(source_id, path.stem)
                dataset = self._verified_dataset(record, reason="published_corrupt")
                fetched_at = _parse_utc(dataset.get("fetched_at"))
                published_at = _parse_utc(record.get("published_at"))
            except (PublicationUnavailable, ValueError):
                continue
            if fetched_at.timestamp() > latest_allowed:
                continue
            records.append((fetched_at, published_at, path.stem))
        records.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return [version for _fetched_at, _published_at, version in records]

    def freshest_valid_immutable_dataset(
        self, source_id: str
    ) -> tuple[str, dict[str, Any]] | None:
        """Recover the freshest checksum-valid immutable snapshot for gate baselines."""

        with self.publication_transaction(source_id):
            versions = self._discover_valid_versions(source_id)
            if not versions:
                return None
            version = versions[0]
            record = self._verified_version_record(source_id, version)
            return version, self._verified_dataset(record, reason="published_corrupt")

    def immutable_recovery_candidates(
        self, source_id: str
    ) -> list[tuple[str, dict[str, Any]]]:
        """Return checksum-valid immutable snapshots, freshest timestamp first."""

        with self.publication_transaction(source_id):
            candidates: list[tuple[str, dict[str, Any]]] = []
            for version in self._discover_valid_versions(source_id):
                try:
                    record = self._verified_version_record(source_id, version)
                    dataset = self._verified_dataset(
                        record, reason="published_corrupt"
                    )
                except PublicationUnavailable:
                    continue
                candidates.append((version, dataset))
            return candidates

    @staticmethod
    def _log_prune_failure(source_id: str, path: Path, exc: OSError) -> None:
        try:
            from .refresh_log import log_action

            log_action(
                "dataset.publication.prune.fail",
                source_id=source_id,
                level="warn",
                detail=f"Failed to remove retained publication {path.name}: {exc}"[:1000],
            )
        except Exception:
            pass

    def _write_manifest(self, source_id: str, versions: list[str]) -> dict[str, Any]:
        retained = versions[: _configured_publication_retention()]
        manifest = {
            "schema_version": _MANIFEST_SCHEMA_VERSION,
            "source_id": source_id,
            "current_version": retained[0],
            "versions": retained,
            "updated_at": _now_iso(),
        }
        manifest["manifest_checksum"] = hashlib.sha256(
            _canonical_json(manifest)
        ).hexdigest()
        _durable_write_json(self.published_path(source_id), manifest)
        keep = set(retained)
        for path in self.versions_dir(source_id).glob("*.json"):
            if path.stem not in keep:
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    # Manifest commit is the transaction boundary. Retention
                    # cleanup is maintenance and must never invert that result.
                    self._log_prune_failure(source_id, path, exc)
        return manifest

    def promote_candidate(
        self,
        source_id: str,
        candidate_version: str,
        *,
        validation: Mapping[str, Any],
        attempt_generation: int | None = None,
    ) -> dict[str, Any]:
        if validation.get("ok") is not True:
            raise ValueError("Cannot promote a candidate that did not pass validation")
        with self.publication_transaction(source_id):
            if attempt_generation is None:
                attempt_generation = self.begin_publication_attempt(
                    source_id
                ).generation
            try:
                attempt_state = self._read_attempt_state(source_id)
            except PublicationUnavailable as exc:
                raise PublicationUnavailable(
                    "publication_attempt_state_corrupt",
                    "Cannot prove that this publication attempt is current",
                ) from exc
            latest_generation = (
                attempt_state.get("last_generation")
                if isinstance(attempt_state, dict)
                else None
            )
            if (
                not isinstance(attempt_generation, int)
                or isinstance(attempt_generation, bool)
                or not isinstance(latest_generation, int)
                or attempt_generation != latest_generation
            ):
                raise PublicationUnavailable(
                    "publication_attempt_superseded",
                    "Publication attempt was superseded by a newer refresh or control action",
                )
            candidate = self._read_record(
                self.candidate_path(source_id), reason="candidate_corrupt"
            )
            dataset = self._verified_dataset(candidate, reason="candidate_corrupt")
            if candidate.get("dataset_version") != candidate_version:
                raise PublicationUnavailable(
                    "candidate_changed", "Candidate changed before publication"
                )
            published = {
                "schema_version": _RECORD_SCHEMA_VERSION,
                "source_id": source_id,
                "dataset_version": candidate_version,
                "published_at": _now_iso(),
                "validation": {
                    "ok": True,
                    "reason": str(validation.get("reason") or "ok")[:2000],
                    "diagnostics": _bounded_diagnostics(
                        validation.get("diagnostics")
                        if isinstance(validation.get("diagnostics"), Mapping)
                        else None
                    ),
                },
                "dataset": dataset,
            }
            version_path = self.version_path(source_id, candidate_version)
            if version_path.exists():
                existing = self._verified_version_record(source_id, candidate_version)
                if existing.get("dataset") != dataset:
                    raise PublicationUnavailable(
                        "published_corrupt", "Immutable version record changed"
                    )
                published = existing
            else:
                _durable_write_json(version_path, published)

            existing_versions: list[str] = []
            if self.published_path(source_id).exists():
                try:
                    manifest, current_record = self._manifest_and_current_record(source_id)
                    if manifest is None:
                        existing_versions = [
                            self._persist_legacy_version(source_id, current_record)
                        ]
                    else:
                        existing_versions = list(manifest["versions"])
                except PublicationUnavailable:
                    # A newly validated candidate repairs an unreadable manifest
                    # while preserving every checksum-valid immutable version.
                    existing_versions = self._discover_valid_versions(source_id)
            else:
                # The manifest may have been lost after immutable records were
                # durably committed. Preserve those records during repair.
                existing_versions = self._discover_valid_versions(source_id)
            sanitized_versions: list[str] = []
            for version in existing_versions:
                try:
                    self._verified_version_record(source_id, version)
                except PublicationUnavailable:
                    continue
                sanitized_versions.append(version)
            history = [candidate_version] + [
                version for version in sanitized_versions if version != candidate_version
            ]
            self._write_manifest(source_id, history)
            return published

    def rollback_to_version(
        self,
        source_id: str,
        target_version: str,
        *,
        validation: Mapping[str, Any],
    ) -> dict[str, Any]:
        if validation.get("ok") is not True:
            raise ValueError("Cannot roll back to a version that failed validation")
        with self.publication_transaction(source_id):
            manifest, _pointer = self._read_publication_pointer(source_id)
            if manifest is None:
                raise PublicationUnavailable(
                    "rollback_previous_missing", "No previous publication is retained"
                )
            history = list(manifest["versions"])
            if target_version not in history:
                raise PublicationUnavailable(
                    "rollback_version_not_retained", "Requested version is not retained"
                )
            if history[0] == target_version:
                raise PublicationUnavailable(
                    "rollback_already_current", "Requested version is already current"
                )
            target = self._verified_version_record(source_id, target_version)
            valid_history: list[str] = []
            for version in history:
                if version == target_version:
                    continue
                try:
                    self._verified_version_record(source_id, version)
                except PublicationUnavailable:
                    continue
                valid_history.append(version)
            self._write_manifest(
                source_id,
                [target_version] + valid_history,
            )
            return target

    def reconcile_current_publication(
        self,
        source_id: str,
        *,
        candidate_dataset_version: str | None,
        expected_dataset_version: str | None,
        status: Mapping[str, Any],
        attempt_generation: int | None = None,
        attempt_id: str | None = None,
        attempt_started_at: str | None = None,
    ) -> PublicationReconciliation:
        """Synchronize mutable compatibility files to the authoritative LKG.

        Manifest selection, mutable-cache write and status write share the same
        publication transaction. If a caller was superseded before acquiring the
        lock, the actual current immutable snapshot wins and all version fields
        describe that snapshot.
        """

        with self.publication_transaction(source_id):
            if attempt_generation is None:
                attempt = self.begin_publication_attempt(source_id)
                attempt_generation = attempt.generation
                attempt_id = attempt.attempt_id
                attempt_started_at = attempt.started_at
            if (
                not isinstance(attempt_generation, int)
                or isinstance(attempt_generation, bool)
                or attempt_generation < 1
            ):
                raise ValueError("attempt_generation must be a positive integer")
            attempt_id = str(attempt_id or candidate_dataset_version or uuid4().hex)
            attempt_started_at = str(
                attempt_started_at or status.get("fetched_at") or _now_iso()
            )

            _manifest, record = self._manifest_and_current_record(source_id)
            dataset = self._verified_dataset(record, reason="published_corrupt")
            current_version = str(record["dataset_version"])
            warnings: list[str] = []

            from . import storage

            try:
                existing_status = storage.load_status(source_id)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                existing_status = None
            existing_generation = (
                existing_status.get("publication_attempt_generation")
                if isinstance(existing_status, dict)
                else None
            )
            if not isinstance(existing_generation, int) or isinstance(
                existing_generation, bool
            ):
                existing_generation = 0
            try:
                attempt_state = self._read_attempt_state(source_id) or {}
            except PublicationUnavailable:
                attempt_state = {}
            latest_generation = attempt_state.get("last_generation")
            if not isinstance(latest_generation, int) or isinstance(
                latest_generation, bool
            ):
                latest_generation = attempt_generation

            manifest_superseded = bool(
                expected_dataset_version
                and expected_dataset_version != current_version
            )
            generation_superseded = attempt_generation < max(
                existing_generation, latest_generation
            )
            superseded = manifest_superseded or generation_superseded
            existing_matches_current = isinstance(existing_status, dict) and (
                current_version
                in {
                    existing_status.get("dataset_version"),
                    existing_status.get("published_dataset_version"),
                }
            )
            preserved_winner_status = superseded and existing_matches_current

            cache_synced = True
            try:
                storage.save_dataset(source_id, dataset)
                # A compliant writer cannot change this while we hold the lock;
                # the explicit check also catches manual/non-compliant mutation.
                after_version = self.pointer_dataset_version(source_id)
                if after_version != current_version:
                    raise PublicationUnavailable(
                        "publication_changed_during_sync",
                        "Publication pointer changed during cache reconciliation",
                    )
            except Exception as exc:
                cache_synced = False
                warnings.append(f"{type(exc).__name__}: {exc}"[:1000])

            status_source: Mapping[str, Any] = (
                existing_status
                if preserved_winner_status and isinstance(existing_status, dict)
                else status
            )
            payload = json.loads(
                json.dumps(dict(status_source), ensure_ascii=False, default=str)
            )
            attempted_state = payload.get("state")
            refresh_failed = attempted_state not in (None, SourceState.OK)
            failed_at = payload.get("fetched_at")
            failed_error = payload.get("detail") or payload.get("error")

            if not preserved_winner_status:
                payload["state"] = SourceState.OK
                payload["fetched_at"] = dataset.get("fetched_at")
                if dataset.get("backend") is not None:
                    payload["backend"] = dataset.get("backend")
                if dataset.get("content_length") is not None:
                    payload["content_length"] = dataset.get("content_length")
            winning_candidate_version = (
                payload.get("candidate_dataset_version")
                if preserved_winner_status
                else current_version
                if superseded
                else candidate_dataset_version
            )
            if not isinstance(winning_candidate_version, str):
                winning_candidate_version = current_version
            payload["candidate_dataset_version"] = winning_candidate_version
            payload["published_dataset_version"] = current_version
            payload["dataset_version"] = current_version

            if preserved_winner_status:
                applied_generation = existing_generation
                applied_attempt_id = payload.get("publication_attempt_id")
                applied_started_at = payload.get("publication_attempt_started_at")
            elif superseded:
                applied_generation = max(
                    attempt_generation, existing_generation, latest_generation
                )
                applied_attempt_id = attempt_state.get("last_attempt_id") or attempt_id
                applied_started_at = (
                    attempt_state.get("last_started_at") or attempt_started_at
                )
                refresh_failed = False
            else:
                applied_generation = attempt_generation
                applied_attempt_id = attempt_id
                applied_started_at = attempt_started_at
            payload["publication_attempt_generation"] = applied_generation
            payload["publication_attempt_id"] = applied_attempt_id
            payload["publication_attempt_started_at"] = applied_started_at

            if superseded:
                payload["publication_superseded"] = True
                payload["superseded_expected_dataset_version"] = (
                    expected_dataset_version
                )
                payload["superseded_candidate_dataset_version"] = (
                    candidate_dataset_version
                )
                payload["superseded_attempt_generation"] = attempt_generation
            else:
                for key in (
                    "publication_superseded",
                    "superseded_expected_dataset_version",
                    "superseded_candidate_dataset_version",
                    "superseded_attempt_generation",
                ):
                    payload.pop(key, None)

            if not preserved_winner_status and refresh_failed:
                payload.update(
                    {
                        "serving_cached_dataset": True,
                        "effective_state": EFFECTIVE_OK_CACHED,
                        "last_refresh_state": attempted_state,
                        "last_refresh_at": failed_at,
                        "last_refresh_error": failed_error or "live refresh failed",
                        "detail": "Serving published LKG; latest refresh failed.",
                    }
                )
            elif not preserved_winner_status and cache_synced:
                for key in (
                    "serving_cached_dataset",
                    "effective_state",
                    "last_refresh_state",
                    "last_refresh_at",
                    "last_refresh_error",
                    "cached_dataset_age_hours",
                    "publication_cache_sync_error",
                ):
                    payload.pop(key, None)

            if not cache_synced:
                cache_error = warnings[-1]
                payload["serving_cached_dataset"] = True
                payload["effective_state"] = EFFECTIVE_OK_CACHED
                payload["publication_cache_sync_error"] = cache_error
                if not refresh_failed and not preserved_winner_status:
                    payload["last_refresh_state"] = "cache_sync_error"
                    payload["last_refresh_at"] = _now_iso()
                    payload["last_refresh_error"] = cache_error

            status_synced = True
            try:
                storage.save_status(source_id, payload)
            except Exception as exc:
                status_synced = False
                warnings.append(f"{type(exc).__name__}: {exc}"[:1000])

            return PublicationReconciliation(
                dataset=dataset,
                dataset_version=current_version,
                candidate_dataset_version=winning_candidate_version,
                status=payload,
                cache_synced=cache_synced,
                status_synced=status_synced,
                superseded=superseded,
                warnings=tuple(warnings),
            )

    def record_status_without_publication(
        self,
        source_id: str,
        *,
        status: Mapping[str, Any],
        attempt_generation: int | None = None,
        attempt_id: str | None = None,
        attempt_started_at: str | None = None,
    ) -> dict[str, Any]:
        """Record a cold failure without allowing an older attempt to win.

        The publication lock covers both the manifest recheck and status CAS.
        If an LKG appeared after a caller's failed reconciliation, the normal
        reconciliation path wins instead of writing a cold status beside it.
        """

        with self.publication_transaction(source_id):
            if attempt_generation is None:
                attempt = self.begin_publication_attempt(source_id)
                attempt_generation = attempt.generation
                attempt_id = attempt.attempt_id
                attempt_started_at = attempt.started_at
            if (
                not isinstance(attempt_generation, int)
                or isinstance(attempt_generation, bool)
                or attempt_generation < 1
            ):
                raise ValueError("attempt_generation must be a positive integer")

            if self.published_path(source_id).exists():
                try:
                    return self.reconcile_current_publication(
                        source_id,
                        candidate_dataset_version=(
                            str(status.get("candidate_dataset_version"))
                            if status.get("candidate_dataset_version")
                            else None
                        ),
                        expected_dataset_version=None,
                        status=status,
                        attempt_generation=attempt_generation,
                        attempt_id=attempt_id,
                        attempt_started_at=attempt_started_at,
                    ).status
                except PublicationUnavailable:
                    # A corrupt pointer has no usable LKG, but the same locked
                    # generation CAS below still protects failure provenance.
                    pass

            try:
                attempt_state = self._read_attempt_state(source_id) or {}
            except PublicationUnavailable:
                attempt_state = {}
            latest_generation = attempt_state.get("last_generation")
            if not isinstance(latest_generation, int) or isinstance(
                latest_generation, bool
            ):
                latest_generation = attempt_generation

            from . import storage

            try:
                existing_status = storage.load_status(source_id)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                existing_status = None
            existing_generation = (
                existing_status.get("publication_attempt_generation")
                if isinstance(existing_status, dict)
                else None
            )
            if not isinstance(existing_generation, int) or isinstance(
                existing_generation, bool
            ):
                existing_generation = 0
            if attempt_generation < max(latest_generation, existing_generation):
                if isinstance(existing_status, dict):
                    return existing_status
                superseded = json.loads(
                    json.dumps(dict(status), ensure_ascii=False, default=str)
                )
                superseded["publication_superseded"] = True
                superseded["superseded_attempt_generation"] = attempt_generation
                return superseded

            payload = json.loads(
                json.dumps(dict(status), ensure_ascii=False, default=str)
            )
            payload["publication_attempt_generation"] = attempt_generation
            payload["publication_attempt_id"] = str(
                attempt_id or attempt_state.get("last_attempt_id") or uuid4().hex
            )
            payload["publication_attempt_started_at"] = str(
                attempt_started_at
                or attempt_state.get("last_started_at")
                or payload.get("fetched_at")
                or _now_iso()
            )
            payload.pop("published_dataset_version", None)
            payload.pop("dataset_version", None)
            storage.save_status(source_id, payload)
            return payload

    def read_published_unbounded(self, source_id: str) -> dict[str, Any] | None:
        with self.publication_transaction(source_id):
            if not self.published_path(source_id).exists():
                return None
            _manifest, record = self._manifest_and_current_record(source_id)
            return self._verified_dataset(record, reason="published_corrupt")

    def current_dataset_version(self, source_id: str) -> str | None:
        with self.publication_transaction(source_id):
            if not self.published_path(source_id).exists():
                return None
            _manifest, record = self._manifest_and_current_record(source_id)
            return str(record["dataset_version"])

    def read_published(
        self,
        source_id: str,
        *,
        max_stale_hours: float | None = None,
        now: datetime | None = None,
        current_dataset: dict[str, Any] | None | object = _UNSET,
        current_error: Exception | None = None,
        status: dict[str, Any] | None | object = _UNSET,
    ) -> PublishedDataset:
        with self.publication_transaction(source_id):
            _manifest, record = self._manifest_and_current_record(source_id)
            dataset = self._verified_dataset(record, reason="published_corrupt")
            try:
                age_hours = _dataset_age_hours(
                    dataset,
                    now=now,
                    max_stale_hours=max_stale_hours,
                    reason_prefix="published",
                )
            except PublicationUnavailable as exc:
                if exc.reason == "published_corrupt":
                    raise PublicationUnavailable(
                        "published_corrupt", "Published dataset timestamp is invalid"
                    ) from exc
                raise

        if current_dataset is _UNSET and current_error is None:
            try:
                from .storage import load_dataset

                current_dataset = load_dataset(source_id)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                current_error = exc
                current_dataset = None
        if status is _UNSET:
            try:
                from .storage import load_status

                status = load_status(source_id)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                status = None

        published_version = str(record["dataset_version"])
        fallback_reason: str | None = None
        if current_error is not None:
            fallback_reason = "current_dataset_corrupt"
        elif current_dataset is None:
            fallback_reason = "current_dataset_missing"
        elif not isinstance(current_dataset, dict):
            fallback_reason = "current_dataset_corrupt"
        elif dataset_version(current_dataset) != record.get("dataset_version"):
            fallback_reason = "current_dataset_not_published"

        if fallback_reason is None and isinstance(status, dict):
            status_versions = [
                value
                for value in (
                    status.get("dataset_version"),
                    status.get("published_dataset_version"),
                )
                if isinstance(value, str) and value
            ]
            last_state = status.get("last_refresh_state")
            state = status.get("state")
            if any(value != published_version for value in status_versions):
                fallback_reason = "status_not_published"
            elif status.get("serving_cached_dataset") and last_state:
                fallback_reason = f"latest_refresh_failed:{last_state}"
            elif state not in (None, "ok"):
                fallback_reason = f"latest_refresh_failed:{state}"

        published_at = str(record.get("published_at") or "")
        version = published_version
        representation_revision = hashlib.sha256(
            _canonical_json(
                {
                    "representation_schema_version": (
                        PUBLIC_STANDARD_CARDS_REPRESENTATION_SCHEMA_VERSION
                    ),
                    "dataset_version": version,
                    "published_at": published_at,
                    "stale": fallback_reason is not None,
                    "fallback_reason": fallback_reason,
                }
            )
        ).hexdigest()
        return PublishedDataset(
            dataset=dataset,
            dataset_version=version,
            published_at=published_at,
            stale=fallback_reason is not None,
            fallback_reason=fallback_reason,
            age_hours=round(age_hours, 3),
            representation_revision=representation_revision,
        )


def _validation_report_payload(report: Any) -> dict[str, Any]:
    return {
        "ok": bool(report.ok),
        "score": report.score,
        "metrics": dict(report.metrics),
        "issues": [
            {
                "code": issue.code,
                "message": issue.message,
                "field": issue.field,
                "severity": issue.severity,
            }
            for issue in report.issues
        ],
    }


def validate_standard_cards_snapshot(
    source: Any,
    dataset: Mapping[str, Any],
) -> PublicationDecision:
    """Revalidate an in-memory Standard snapshot without mutating publication state."""

    if source.id != STANDARD_CARDS_SOURCE_ID:
        raise ValueError(f"Publication channel is not enabled for {source.id}")
    data = dataset.get("data") if isinstance(dataset, Mapping) else None
    parsed = dict(data) if isinstance(data, Mapping) else {}
    backend = str(dataset.get("backend") or "unknown")

    from .publish_gate import validate_candidate_for_publish
    from .source_validators import (
        validate_standard_card_aliases,
        validate_structured,
    )

    gate = validate_candidate_for_publish(source, parsed, backend=backend)
    structured = parsed.get("structured") or {}
    semantic = validate_structured(
        source.id, structured if isinstance(structured, dict) else {}
    )
    aliases = validate_standard_card_aliases(parsed)
    temporal_error: PublicationUnavailable | None = None
    try:
        _dataset_age_hours(dataset, reason_prefix="candidate")
    except PublicationUnavailable as exc:
        temporal_error = exc

    diagnostics: dict[str, Any] = {
        "backend": backend,
        "publish_gate": {
            "ok": gate.ok,
            "reason": gate.reason,
            "extra": gate.extra,
        },
        "semantic": _validation_report_payload(semantic),
        "aliases": _validation_report_payload(aliases),
        "temporal": {
            "ok": temporal_error is None,
            "reason": temporal_error.detail if temporal_error else "ok",
            "code": temporal_error.reason if temporal_error else None,
        },
    }
    accepted = gate.ok and semantic.ok and aliases.ok and temporal_error is None
    reason = (
        temporal_error.detail
        if temporal_error is not None
        else aliases.reason
        if not aliases.ok
        else gate.reason
        if not gate.ok
        else semantic.reason
    )
    version = dataset_version(dict(dataset))
    return PublicationDecision(
        accepted=accepted,
        dataset_version=version,
        reason=reason,
        diagnostics=diagnostics,
        rejection_kind=None if accepted else "validation",
    )


def validate_and_publish_standard_cards_candidate(
    source: Any,
    dataset: Mapping[str, Any],
    *,
    store: DatasetPublicationStore | None = None,
    publication_attempt: PublicationAttempt | None = None,
    validated_previous: Mapping[str, Any] | None | object = _UNSET,
) -> PublicationDecision:
    """Durably stage, fully validate and atomically publish Standard cards."""

    if source.id != STANDARD_CARDS_SOURCE_ID:
        raise ValueError(f"Publication channel is not enabled for {source.id}")
    publication_store = store or DatasetPublicationStore()
    attempt = publication_attempt or publication_store.begin_publication_attempt(
        source.id
    )
    with publication_store.publication_transaction(source.id):
        # Staging is deliberately the first side effect inside the transaction.
        candidate = publication_store.stage_candidate(source.id, dataset)
        candidate_version = str(candidate["dataset_version"])
        snapshot_validation = validate_standard_cards_snapshot(source, dataset)
        diagnostics = dict(snapshot_validation.diagnostics)

        previous: dict[str, Any] | None = None
        recovered_version: str | None = None
        manifest_repair_allowed = False
        try:
            published_previous = publication_store.read_published_unbounded(source.id)
        except PublicationUnavailable as exc:
            diagnostics["previous_publication"] = {
                "ok": False,
                "reason": exc.reason,
            }
            try:
                manifest_repair_allowed = (
                    publication_store.pointer_dataset_version(source.id) is None
                )
            except PublicationUnavailable:
                manifest_repair_allowed = True
        else:
            if published_previous is None:
                manifest_repair_allowed = True
            elif validated_previous is _UNSET:
                previous = published_previous

        if validated_previous is not _UNSET:
            previous = (
                dict(validated_previous)
                if isinstance(validated_previous, Mapping)
                else None
            )
            diagnostics["previous_publication_recovery"] = {
                "ok": previous is not None,
                "source": "fully_validated_recovery_candidate",
            }
        elif previous is None:
            recovered = publication_store.freshest_valid_immutable_dataset(source.id)
            if recovered is not None:
                recovered_version, previous = recovered
                diagnostics["previous_publication_recovery"] = {
                    "ok": True,
                    "dataset_version": recovered_version,
                    "source": "immutable_version",
                }

        obsolete = False
        obsolete_reason: str | None = None
        exact_immutable_repair = bool(
            manifest_repair_allowed
            and recovered_version
            and recovered_version == candidate_version
        )
        if previous is not None:
            try:
                candidate_time = _parse_utc(dataset.get("fetched_at"))
                previous_time = _parse_utc(previous.get("fetched_at"))
                if candidate_time <= previous_time and not exact_immutable_repair:
                    obsolete = True
                    obsolete_reason = (
                        "candidate fetched_at is not newer than the current publication"
                    )
            except (TypeError, ValueError):
                # Temporal validation handles a malformed candidate. A malformed
                # previous timestamp must not prevent a valid repair publication.
                pass
        diagnostics["ordering"] = {
            "ok": not obsolete,
            "reason": (
                "exact immutable snapshot is repairing a missing/corrupt manifest"
                if exact_immutable_repair
                else obsolete_reason or "ok"
            ),
        }

        from .dataset_regression import check_dataset_regression

        parsed = dataset.get("data") if isinstance(dataset.get("data"), Mapping) else {}
        regression = False
        regression_reason: str | None = None
        regression_extra: dict[str, Any] = {}
        if previous is not None:
            regression, regression_reason, regression_extra = check_dataset_regression(
                source,
                previous_data=(
                    previous.get("data") if isinstance(previous, dict) else None
                ),
                new_data=dict(parsed),
            )
        diagnostics["regression"] = {
            "detected": regression,
            "reason": regression_reason,
            **regression_extra,
        }

        if not snapshot_validation.accepted or obsolete or regression:
            reason = (
                obsolete_reason
                or regression_reason
                or snapshot_validation.reason
                or "candidate rejected"
            )
            rejection_kind = (
                "obsolete"
                if obsolete
                else "regression"
                if regression
                else "validation"
            )
            publication_store.quarantine_candidate(
                source.id,
                candidate_version,
                reason=reason,
                diagnostics=diagnostics,
            )
            return PublicationDecision(
                accepted=False,
                dataset_version=candidate_version,
                reason=reason,
                diagnostics=diagnostics,
                rejection_kind=rejection_kind,
            )

        try:
            publication_store.promote_candidate(
                source.id,
                candidate_version,
                validation={"ok": True, "reason": "ok", "diagnostics": diagnostics},
                attempt_generation=attempt.generation,
            )
        except PublicationUnavailable as exc:
            if exc.reason != "publication_attempt_superseded":
                raise
            diagnostics["publication_attempt"] = {
                "ok": False,
                "reason": exc.reason,
                "generation": attempt.generation,
            }
            publication_store.quarantine_candidate(
                source.id,
                candidate_version,
                reason=exc.detail,
                diagnostics=diagnostics,
            )
            return PublicationDecision(
                accepted=False,
                dataset_version=candidate_version,
                reason=exc.detail,
                diagnostics=diagnostics,
                rejection_kind="superseded",
            )
        return PublicationDecision(
            accepted=True,
            dataset_version=candidate_version,
            reason="ok",
            diagnostics=diagnostics,
        )
