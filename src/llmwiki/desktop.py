"""App desktop: doppio clic, si apre una finestra, resta un'icona nell'area di notifica.

Dietro c'è lo stesso server della riga di comando, avviato sullo spazio attivo. Al primo avvio
crea uno spazio "Personale" e, se trova un modello acceso sul computer, lo collega da solo.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from . import __version__, apphome
from .app import Hub, Wiki, load_secrets
from .config import Config

log = logging.getLogger("llmwiki.desktop")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def make_icon(size: int = 64):
    """Icona disegnata al volo: un quadrato scuro con tre righe e un segno di spunta verde."""
    from PIL import Image, ImageDraw

    scale = size / 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2 * scale, 2 * scale, 62 * scale, 62 * scale), radius=14 * scale,
                           fill=(24, 24, 22, 255), outline=(95, 191, 127, 255), width=max(1, round(2 * scale)))
    for y, width in ((20, 30), (30, 22), (40, 26)):
        draw.rounded_rectangle((14 * scale, y * scale, (14 + width) * scale, (y + 4) * scale),
                               radius=2 * scale, fill=(236, 235, 230, 255))
    draw.line([(38 * scale, 42 * scale), (44 * scale, 49 * scale), (54 * scale, 33 * scale)],
              fill=(95, 191, 127, 255), width=max(2, round(5 * scale)), joint="curve")
    return image


def _setup_logging() -> None:
    for name in ("stdout", "stderr"):  # un eseguibile senza console non ha né l'uno né l'altro
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115
    handler = logging.handlers.RotatingFileHandler(
        apphome.logs_dir() / "llmwiki.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def _alive(port: int) -> bool:
    import httpx

    try:
        data = httpx.get(f"http://127.0.0.1:{port}/api/status", timeout=1.5).json()
    except Exception:
        return False
    return isinstance(data, dict) and "version" in data


def _free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return probe.getsockname()[1]
    raise RuntimeError("nessuna porta libera")


def open_window(url: str) -> None:
    """Finestra senza barra degli indirizzi (Edge in modalità app, presente su Windows 10/11);
    altrimenti il browser predefinito."""
    candidates = [shutil.which("msedge")]
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.environ.get("LOCALAPPDATA")):
        if base:
            candidates.append(str(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"))
    for edge in candidates:
        if edge and Path(edge).is_file():
            try:
                process = subprocess.Popen([edge, f"--app={url}", "--window-size=1320,880"])  # noqa: S603
            except OSError:
                continue
            try:  # se Edge è già aperto il processo passa la mano ed esce con 0: va bene così
                if process.wait(timeout=2) == 0:
                    return
            except subprocess.TimeoutExpired:
                return  # è rimasto aperto: la finestra è sua
            log.warning("Edge non ha aperto la finestra (codice %s): uso il browser predefinito",
                        process.returncode)
            break
    webbrowser.open(url)


def _first_run(registry: apphome.Registry) -> None:
    """Primo avvio: uno spazio pronto all'uso, collegato al modello locale se ce n'è uno."""
    from .server import detect_local_servers

    template = Config.from_dict({"llm": {"provider": "mock"}}, apphome.home())
    try:
        found = asyncio.run(detect_local_servers())
    except Exception:
        found = []
    if found:
        server = found[0]
        template.llm.provider = "openai"
        template.llm.base_url = server["base_url"]
        template.llm.agent_model = template.llm.summary_model = template.llm.judge_model = server["models"][0]
        template.index.concurrency = 2
        log.info("primo avvio: collegato a %s (%s)", server["name"], server["models"][0])
    registry.add("Personale", template=template)


def main(argv: list[str] | None = None) -> int:
    """Un'app senza console non può fallire in silenzio: l'errore va mostrato."""
    try:
        return _main(argv)
    except SystemExit:
        raise
    except Exception as exc:
        log.exception("avvio non riuscito")
        message = (f"LLMWiki non è riuscito ad avviarsi:\n\n{exc}\n\n"
                   f"Dettagli in {apphome.logs_dir() / 'llmwiki.log'}")
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "LLMWiki", 0x10)
        else:
            print(message, file=sys.stderr)
        return 1


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="LLMWiki")
    parser.add_argument("--port", type=int, help="porta locale (default: quella salvata, 8765)")
    parser.add_argument("--no-window", action="store_true", help="non aprire la finestra")
    parser.add_argument("--no-tray", action="store_true", help="senza icona nell'area di notifica")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    _setup_logging()
    load_secrets()
    registry = apphome.Registry()
    port = args.port or int(registry.data.get("port") or 8765)
    if _alive(port):  # già aperta: si riporta in primo piano quella
        if not args.no_window:
            open_window(f"http://127.0.0.1:{port}")
        return 0

    if not registry.spaces:
        _first_run(registry)
    space = registry.active()
    try:
        hub = Hub(Wiki(Config.load(Path(space["path"]) / "wiki.toml")), registry)
    except Exception as exc:
        raise RuntimeError(f"lo spazio «{space['name']}» ({space['path']}) non si apre: {exc}") from exc
    cfg = hub.wiki.cfg
    port = _free_port(port)
    if not args.port and registry.data.get("port") != port:
        registry.data["port"] = port
        registry.save()
    host = cfg.server.host if (cfg.server.host in LOOPBACK or cfg.server.users) else "127.0.0.1"
    cfg.server.host, cfg.server.port = host, port

    import uvicorn

    from .server import create_app

    app = create_app(hub)
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_config=None,
                                           access_log=False))  # niente riga di log a ogni richiesta
    stop = threading.Event()

    def quit_app() -> None:
        server.should_exit = True
        stop.set()

    hub.quit = quit_app
    thread = threading.Thread(target=server.run, name="llmwiki-server", daemon=True)
    thread.start()
    deadline = time.time() + 40
    while time.time() < deadline and not _alive(port) and thread.is_alive():
        time.sleep(0.2)
    if not thread.is_alive():
        log.error("il server non è partito")
        return 1
    url = f"http://127.0.0.1:{port}"
    log.info("LLMWiki %s su %s (spazio: %s)", __version__, url, space["name"])
    if not args.no_window:
        open_window(url)

    tray = None
    if not args.no_tray:
        try:
            import pystray

            def on_quit(icon, _item):
                quit_app()
                icon.stop()

            tray = pystray.Icon("LLMWiki", make_icon(64), "LLMWiki", pystray.Menu(
                pystray.MenuItem("Apri LLMWiki", lambda *_: open_window(url), default=True),
                pystray.MenuItem("Apri la cartella dei documenti",
                                 lambda *_: os.startfile(hub.wiki.cfg.docs_dir)),  # noqa: S606
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Esci", on_quit),
            ))
        except Exception:
            log.exception("icona nell'area di notifica non disponibile")
    if tray is not None:
        threading.Thread(target=lambda: (stop.wait(), tray.stop()), daemon=True).start()
        tray.run()  # resta qui finché non si sceglie Esci
        quit_app()
    else:
        try:
            while thread.is_alive() and not stop.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        quit_app()
    thread.join(timeout=15)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
