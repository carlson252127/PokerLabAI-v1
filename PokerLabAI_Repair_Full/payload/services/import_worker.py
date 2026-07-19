from __future__ import annotations

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
        self.batch_size_hands = max(2_000, int(batch_size_hands))
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

            with store.connect() as con:
                for index, file_path in enumerate(pending_files, start=1):
                    if self._cancelled:
                        break

                    parsed = parser.parse_file(file_path)
                    parsed_count = len(parsed) if parsed else 0
                    if not parsed:
                        unsupported_total += 1
                        # Unsupported files are not cached, so parser fixes can retry.
                    else:
                        parsed_buffer.extend(parsed)
                        file_records.append((file_path, parsed_count))
                        parsed_total += parsed_count

                    should_flush = (
                        len(parsed_buffer) >= self.batch_size_hands
                        or index == total_files
                    )
                    if should_flush and parsed_buffer:
                        con.execute("BEGIN TRANSACTION")
                        try:
                            inserted, skipped = store.insert_parsed_batch(
                                parsed_buffer,
                                con=con,
                            )
                            store.mark_files_imported(file_records, con)
                            con.execute("COMMIT")
                        except Exception:
                            con.execute("ROLLBACK")
                            raise

                        inserted_total += inserted
                        skipped_total += skipped
                        parsed_buffer.clear()
                        file_records.clear()

                    elapsed = max(0.001, time.perf_counter() - started)
                    rate = parsed_total / elapsed
                    remaining_files = total_files - index
                    avg_file_seconds = elapsed / max(1, index)
                    eta = remaining_files * avg_file_seconds

                    self.progress.emit(index, total_files, file_path)
                    self.performance.emit({
                        "phase": "import",
                        "cached_files": cached_files,
                        "pending_files": total_files,
                        "hands_per_second": rate,
                        "eta_seconds": eta,
                        "parsed_hands": parsed_total,
                        "inserted_hands": inserted_total,
                        "skipped_hands": skipped_total,
                        "current_file": Path(file_path).name,
                    })

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
