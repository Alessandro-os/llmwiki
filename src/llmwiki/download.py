"""Scaricamento di un file grande: riprende da dove si era interrotto e lo usa solo se la sua
impronta SHA-256 è quella attesa. Lo usano il decision model (`nli.py`) e gli aggiornamenti
dell'app (`update.py`)."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path


def fetch_verified(http, url: str, target: Path, size: int, sha256: str,
                   progress: Callable[[int], None] = lambda done: None) -> None:
    """Scarica `url` in `target` passando da `target.part`. `progress` riceve i byte scaricati.
    Un file con impronta diversa viene cancellato: meglio riscaricare che usare un file rotto."""
    part = target.with_name(target.name + ".part")
    offset = part.stat().st_size if part.exists() else 0
    if offset > size:
        part.unlink()
        offset = 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with http.stream("GET", url, headers=headers) as response:
        if offset and response.status_code != 206:
            offset = 0  # il server non riprende: si ricomincia
        response.raise_for_status()
        with part.open("ab" if offset else "wb") as handle:
            done = offset
            for block in response.iter_bytes(1 << 20):
                handle.write(block)
                done += len(block)
                progress(done)
    digest = hashlib.sha256()
    with part.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    if digest.hexdigest() != sha256.lower():
        part.unlink()
        raise RuntimeError(f"{target.name}: file scaricato corrotto (impronta diversa)")
    os.replace(part, target)
