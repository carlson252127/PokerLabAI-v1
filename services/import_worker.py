from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot
from services.analytical_store import AnalyticalStore
from services.parser_service import ParserService


class ImportWorker(QObject):
    progress = Signal(int, int, str)
    performance = Signal(object)
    finished = Signal(int, int, int)
    failed = Signal(str)

    def __init__(
        self,
        files: list[str],
        database_path: str,
        batch_size_hands: int = 25_000,
    ) -> None:
        super().__init__()
        self.files = files
        self.database_path = database_path
        # Small batches multiply DuckDB transaction and index-maintenance
        # overhead as the database grows. 25k is still memory-friendly for
        # normal hand-history files while being large enough for bulk writes.
        self.batch_size_hands = max(10_000, int(batch_size_hands))
        self._cancelled = False

    @Slot()
    def run(self) -> None:
        parser = ParserService()
        store = AnalyticalStore(self.database_path)
        inserted_total = 0
        skipped_total = 0
        unsupported_total = 0
        parsed_total = 0
        started = time.perf_counter()
        write_batch_size = self.batch_size_hands
        last_write_seconds = 0.0
        last_write_hands_per_second = 0.0

        try:
            pending_files, cached_files = store.pending_files(self.files)
            total_files = len(pending_files)
            self.performance.emit({
                "phase": "scan",
                "cached_files": cached_files,
                "pending_files": total_files,
                "hands_per_second": 0.0,
                "eta_seconds": 0.0,
                "parsed_hands": 0,
            })

            if not pending_files:
                self.finished.emit(0, 0, 0)
                return

            parsed_buffer: list[dict] = []
            file_records: list[tuple[str, int]] = []
            write_jobs: queue.Queue[object] = queue.Queue(maxsize=1)
            write_results: queue.Queue[dict] = queue.Queue()
            writer_failed = threading.Event()
            writer_sentinel = object()
            writer_sentinel_sent = False
            pending_write_hands = 0
            pending_write_batches = 0

            def writer_loop() -> None:
                try:
                    with store.connect() as con:
                        while True:
                            job = write_jobs.get()
                            if job is writer_sentinel:
                                write_jobs.task_done()
                                return

                            batch, records, file_index, current_file = job
                            batch_hands = len(batch)
                            write_started = time.perf_counter()
                            try:
                                con.execute("BEGIN TRANSACTION")
                                inserted, skipped = store.insert_parsed_batch(
                                    batch,
                                    con=con,
                                )
                                store.mark_files_imported(records, con)
                                con.execute("COMMIT")
                            except Exception:
                                try:
                                    con.execute("ROLLBACK")
                                except Exception:
                                    pass
                                raise

                            write_seconds = max(
                                0.001,
                                time.perf_counter() - write_started,
                            )
                            write_results.put({
                                "kind": "commit",
                                "inserted": inserted,
                                "skipped": skipped,
                                "batch_hands": batch_hands,
                                "write_seconds": write_seconds,
                                "file_index": file_index,
                                "current_file": current_file,
                            })
                            write_jobs.task_done()
                except Exception as exc:
                    writer_failed.set()
                    write_results.put({
                        "kind": "error",
                        "message": f"{type(exc).__name__}: {exc}",
                    })

            writer_thread = threading.Thread(
                target=writer_loop,
                name="PokerLabDuckDBWriter",
                daemon=True,
            )
            writer_thread.start()

            def collect_write_results() -> None:
                nonlocal inserted_total
                nonlocal skipped_total
                nonlocal last_write_seconds
                nonlocal last_write_hands_per_second
                nonlocal pending_write_hands
                nonlocal pending_write_batches

                while True:
                    try:
                        result = write_results.get_nowait()
                    except queue.Empty:
                        break

                    if result["kind"] == "error":
                        raise RuntimeError(result["message"])

                    inserted_total += int(result["inserted"])
                    skipped_total += int(result["skipped"])
                    batch_hands = int(result["batch_hands"])
                    last_write_seconds = float(result["write_seconds"])
                    last_write_hands_per_second = (
                        batch_hands / last_write_seconds
                    )
                    pending_write_hands = max(
                        0,
                        pending_write_hands - batch_hands,
                    )
                    pending_write_batches = max(
                        0,
                        pending_write_batches - 1,
                    )

                    elapsed = max(0.001, time.perf_counter() - started)
                    completed_hands = inserted_total + skipped_total
                    rate = completed_hands / elapsed
                    remaining_files = max(
                        0,
                        total_files - int(result["file_index"]),
                    )
                    avg_file_seconds = elapsed / max(
                        1,
                        int(result["file_index"]),
                    )
                    self.performance.emit({
                        "phase": "commit",
                        "cached_files": cached_files,
                        "pending_files": total_files,
                        "hands_per_second": rate,
                        "eta_seconds": remaining_files * avg_file_seconds,
                        "parsed_hands": parsed_total,
                        "inserted_hands": inserted_total,
                        "skipped_hands": skipped_total,
                        "written_hands": batch_hands,
                        "pending_write_hands": pending_write_hands,
                        "pending_write_batches": pending_write_batches,
                        "batch_target": write_batch_size,
                        "last_write_seconds": last_write_seconds,
                        "last_write_hands_per_second": last_write_hands_per_second,
                        "current_file": Path(result["current_file"]).name,
                    })

            def ensure_writer_ok() -> None:
                collect_write_results()
                if writer_failed.is_set():
                    try:
                        result = write_results.get_nowait()
                    except queue.Empty:
                        raise RuntimeError("DuckDB writer beklenmedik şekilde durdu.")
                    raise RuntimeError(result.get("message", "DuckDB writer durdu."))

            def enqueue_write(
                batch: list[dict],
                records: list[tuple[str, int]],
                file_index: int,
                current_file: str,
            ) -> None:
                nonlocal pending_write_hands
                nonlocal pending_write_batches

                job = (batch, records, file_index, current_file)
                while True:
                    ensure_writer_ok()
                    try:
                        write_jobs.put(job, timeout=0.10)
                        pending_write_hands += len(batch)
                        pending_write_batches += 1
                        return
                    except queue.Full:
                        continue

            try:
                last_file_index = 0
                last_file_path = pending_files[0]
                for index, file_path in enumerate(pending_files, start=1):
                    if self._cancelled:
                        break

                    ensure_writer_ok()
                    parsed_count = 0
                    for parsed_hand in parser.iter_file(file_path):
                        if self._cancelled:
                            break
                        parsed_buffer.append(parsed_hand)
                        parsed_count += 1
                        parsed_total += 1

                        if len(parsed_buffer) >= write_batch_size:
                            enqueue_write(
                                parsed_buffer,
                                [],
                                index,
                                file_path,
                            )
                            parsed_buffer = []

                    if self._cancelled:
                        # Partial chunks may already be queued, but the source
                        # file must remain pending so a later run completes it.
                        pass
                    elif parsed_count == 0:
                        unsupported_total += 1
                        # Unsupported files are not cached, so parser fixes can retry.
                    else:
                        # Only the final chunk owns the file-cache marker. If an
                        # import stops earlier, the file is retried and hand PKs
                        # safely discard already committed chunks.
                        file_records.append((file_path, parsed_count))

                    last_file_index = index
                    last_file_path = file_path
                    elapsed = max(0.001, time.perf_counter() - started)
                    completed_hands = inserted_total + skipped_total
                    rate = (
                        completed_hands / elapsed
                        if completed_hands
                        else parsed_total / elapsed
                    )
                    remaining_files = total_files - index
                    avg_file_seconds = elapsed / max(1, index)
                    eta = remaining_files * avg_file_seconds
                    self.progress.emit(index, total_files, file_path)
                    self.performance.emit({
                        "phase": "parse",
                        "cached_files": cached_files,
                        "pending_files": total_files,
                        "hands_per_second": rate,
                        "eta_seconds": eta,
                        "parsed_hands": parsed_total,
                        "inserted_hands": inserted_total,
                        "skipped_hands": skipped_total,
                        "buffered_hands": len(parsed_buffer),
                        "pending_write_hands": pending_write_hands,
                        "pending_write_batches": pending_write_batches,
                        "batch_target": write_batch_size,
                        "last_write_seconds": last_write_seconds,
                        "last_write_hands_per_second": last_write_hands_per_second,
                        "current_file": Path(file_path).name,
                    })

                    if self._cancelled:
                        break

                    if len(parsed_buffer) >= write_batch_size or (
                        file_records and not parsed_buffer
                    ):
                        enqueue_write(
                            parsed_buffer,
                            file_records,
                            index,
                            file_path,
                        )
                        # The writer owns the queued list objects. Never clear
                        # or mutate them after enqueueing.
                        parsed_buffer = []
                        file_records = []

                if parsed_buffer:
                    enqueue_write(
                        parsed_buffer,
                        file_records,
                        last_file_index,
                        last_file_path,
                    )
                    parsed_buffer = []
                    file_records = []

                ensure_writer_ok()
                self.performance.emit({
                    "phase": "write",
                    "cached_files": cached_files,
                    "pending_files": total_files,
                    "hands_per_second": (
                        (inserted_total + skipped_total)
                        / max(0.001, time.perf_counter() - started)
                    ),
                    "eta_seconds": 0.0,
                    "parsed_hands": parsed_total,
                    "inserted_hands": inserted_total,
                    "skipped_hands": skipped_total,
                    "pending_write_hands": pending_write_hands,
                    "pending_write_batches": pending_write_batches,
                    "batch_target": write_batch_size,
                    "current_file": Path(last_file_path).name,
                })

                while not writer_sentinel_sent:
                    ensure_writer_ok()
                    try:
                        write_jobs.put(writer_sentinel, timeout=0.10)
                        writer_sentinel_sent = True
                    except queue.Full:
                        continue
                while writer_thread.is_alive():
                    writer_thread.join(timeout=0.10)
                    collect_write_results()
                collect_write_results()
                ensure_writer_ok()
            finally:
                if writer_thread.is_alive() and not writer_sentinel_sent:
                    while writer_thread.is_alive():
                        try:
                            write_jobs.put(writer_sentinel, timeout=0.10)
                            writer_sentinel_sent = True
                            break
                        except queue.Full:
                            continue
                    writer_thread.join()

            self.performance.emit({
                "phase": "finished",
                "cached_files": cached_files,
                "pending_files": total_files,
                "hands_per_second": parsed_total / max(0.001, time.perf_counter() - started),
                "eta_seconds": 0.0,
                "parsed_hands": parsed_total,
                "inserted_hands": inserted_total,
                "skipped_hands": skipped_total,
                "cancelled": self._cancelled,
            })
            self.finished.emit(inserted_total, skipped_total, unsupported_total)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    @Slot()
    def cancel(self) -> None:
        self._cancelled = True
