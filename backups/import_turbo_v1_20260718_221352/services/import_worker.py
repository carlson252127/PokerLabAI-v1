from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot
from services.analytical_store import AnalyticalStore
from services.parser_service import ParserService


class ImportWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(int, int, int)
    failed = Signal(str)

    def __init__(self, files: list[str], database_path: str) -> None:
        super().__init__()
        self.files = files
        self.database_path = database_path
        self._cancelled = False

    @Slot()
    def run(self) -> None:
        parser = ParserService()
        store = AnalyticalStore(self.database_path)
        store.create_tables()
        inserted_total = skipped_total = unsupported_total = 0
        try:
            total_files = len(self.files)
            for index, file_path in enumerate(self.files, start=1):
                if self._cancelled:
                    break
                parsed = parser.parse_file(file_path)
                if not parsed:
                    unsupported_total += 1
                else:
                    inserted, skipped = store.insert_parsed_batch(parsed)
                    inserted_total += inserted
                    skipped_total += skipped
                self.progress.emit(index, total_files, file_path)
            self.finished.emit(inserted_total, skipped_total, unsupported_total)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    @Slot()
    def cancel(self) -> None:
        self._cancelled = True
