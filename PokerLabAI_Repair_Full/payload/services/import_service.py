from __future__ import annotations

import os
from pathlib import Path


class ImportService:
    SUPPORTED_EXTENSIONS = (".txt", ".xml")

    def scan_folder(self, folder: str) -> list[str]:
        files_found: list[str] = []

        for root, _, files in os.walk(folder):
            for file_name in files:
                if file_name.lower().endswith(self.SUPPORTED_EXTENSIONS):
                    files_found.append(str(Path(root) / file_name))

        files_found.sort()
        return files_found
