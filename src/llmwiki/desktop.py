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
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from . import __version__, apphome
from .app import Hub, Wiki, detect_local_servers, load_secrets, use_local_server
from .config import LOOPBACK, Config
from .server import create_app

log = logging.getLogger("llmwiki.desktop")


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


def _claim_instance():
    """Una sola copia dell'app per volta. La prima prende un lucchetto su un file e lo tiene
    finché resta aperta (lo libera Windows alla chiusura, anche se si blocca). Il controllo della
    porta da solo non basta: due avvii a pochi secondi (installatore e doppio clic) la trovano
    entrambi libera e il secondo fallisce. Restituisce il file da tenere aperto, o None."""
    handle = open(apphome.home() / "llmwiki.lock", "a+")  # noqa: SIM115 - resta aperto apposta
    handle.seek(0)
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _wait_for_other(fixed_port: int | None, no_window: bool) -> int:
    """Un'altra copia sta partendo: si aspetta che risponda e si porta in primo piano quella."""
    deadline = time.time() + 40
    while time.time() < deadline:
        # senza --port la prima copia può aver cambiato porta (se era occupata) e l'ha salvata
        port = fixed_port or int(apphome.Registry().data.get("port") or 8765)
        if _alive(port):
            if not no_window:
                open_window(f"http://127.0.0.1:{port}")
            return 0
        time.sleep(0.3)
    log.warning("un'altra copia di LLMWiki tiene il posto ma non risponde")
    return 0


def _free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return probe.getsockname()[1]
    raise RuntimeError("nessuna porta libera")


CHROMIUM = ("msedge.exe", "chrome.exe", "brave.exe", "vivaldi.exe", "chromium.exe")
WINDOW_TITLE = "LLMWiki"


def _chromium_browsers() -> list[str]:
    """Browser capaci di aprire una pagina come finestra d'app (--app=URL): per primo quello
    predefinito dell'utente, poi Edge, Chrome e Brave nei percorsi consueti."""
    found: list[str] = []
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\Shell"
                                r"\Associations\UrlAssociations\http\UserChoice") as key:
                prog_id = winreg.QueryValueEx(key, "ProgId")[0]
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id + r"\shell\open\command") as key:
                command = winreg.QueryValueEx(key, "")[0]
            exe = command.split('"')[1] if command.startswith('"') else command.split(" ")[0]
            if Path(exe).name.lower() in CHROMIUM:
                found.append(exe)
        except (OSError, IndexError):
            pass
    bases = [os.environ.get(name) for name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
    for relative in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe",
                     r"BraveSoftware\Brave-Browser\Application\brave.exe"):
        found += [str(Path(base) / relative) for base in bases if base]
    unique = dict.fromkeys(os.path.normcase(path) for path in found if Path(path).is_file())
    return list(unique)


def _find_window() -> int:
    """Handle della finestra dell'app (una finestra Chromium il cui titolo contiene LLMWiki), o 0."""
    if sys.platform != "win32":
        return 0
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(256)
            kind = ctypes.create_unicode_buffer(64)
            user32.GetWindowTextW(hwnd, title, 256)
            user32.GetClassNameW(hwnd, kind, 64)
            if WINDOW_TITLE.lower() in title.value.lower() and kind.value.startswith("Chrome_WidgetWin"):
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else 0


def open_window(url: str) -> None:
    """Apre l'interfaccia in una finestra propria, senza barra degli indirizzi. Non si fida
    del fatto che il browser sia partito: controlla che la finestra esista davvero, e se
    nessun browser ci riesce apre una scheda normale nel browser predefinito."""
    hwnd = _find_window()
    if hwnd:  # già aperta: la si riporta davanti invece di aprirne un'altra
        import ctypes

        ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        return
    for browser in _chromium_browsers():
        try:
            subprocess.Popen([browser, f"--app={url}", "--window-size=1320,880"])
        except OSError:
            continue
        deadline = time.time() + 8
        while time.time() < deadline:
            if _find_window():
                return
            time.sleep(0.4)
        log.warning("%s non ha aperto la finestra: provo altro", Path(browser).name)
    log.info("apro l'interfaccia nel browser predefinito")
    webbrowser.open(url)


def _first_run(registry: apphome.Registry) -> None:
    """Primo avvio: uno spazio pronto all'uso, collegato al modello locale se ce n'è uno
    acceso; altrimenti in modalità demo, finché non si sceglie un modello dalle Impostazioni."""
    template = Config.from_dict({"llm": {"provider": "mock"}}, apphome.home())
    servers = asyncio.run(detect_local_servers())
    if servers:
        use_local_server(template, servers[0])
        log.info("primo avvio: collegato a %s (%s)", servers[0]["name"], template.llm.agent_model)
    registry.add("Personale", template=template)


def _open_hub(registry: apphome.Registry) -> tuple[Hub, dict]:
    """Apre lo spazio attivo. Se la sua cartella è stata spostata o cancellata ripiega sul
    primo spazio che si apre, invece di lasciare l'utente senza applicazione."""
    active = registry.active()
    problems = []
    for space in [active, *(s for s in registry.spaces if s is not active)]:
        config_file = Path(space["path"]) / "wiki.toml"
        try:
            if not config_file.is_file():
                raise FileNotFoundError(f"manca {config_file}")
            hub = Hub(Wiki(Config.load(config_file)), registry)
        except Exception as exc:
            log.warning("spazio %s non apribile: %s", space["path"], exc)
            problems.append(f"«{space['name']}» ({space['path']}): {exc}")
            continue
        if space is not active:
            registry.set_active(space["id"])
        return hub, space
    raise RuntimeError("nessuno spazio si apre:\n" + "\n".join(problems))


def _run_tray(url: str, hub: Hub, quit_app, stop: threading.Event) -> bool:
    """Icona nell'area di notifica; resta qui finché l'app non viene chiusa.
    Ritorna False se l'icona non si può creare (in quel caso l'app resta comunque accesa)."""
    try:
        import pystray

        icon = pystray.Icon("LLMWiki", make_icon(64), "LLMWiki", pystray.Menu(
            pystray.MenuItem("Apri LLMWiki", lambda *_: open_window(url), default=True),
            pystray.MenuItem("Apri la cartella dei documenti",
                             lambda *_: os.startfile(hub.wiki.cfg.docs_dir)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Esci", lambda *_: quit_app()),
        ))
    except Exception:
        log.exception("icona nell'area di notifica non disponibile")
        return False
    threading.Thread(target=lambda: (stop.wait(), icon.stop()), daemon=True).start()
    icon.run()
    return True


def main(argv: list[str] | None = None) -> int:
    """Un'app senza console non può fallire in silenzio: l'errore va mostrato."""
    try:
        return _main(argv)
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
    instance = _claim_instance()
    if instance is None:
        return _wait_for_other(args.port, args.no_window)

    if not registry.spaces:
        _first_run(registry)
    hub, space = _open_hub(registry)
    cfg = hub.wiki.cfg
    port = _free_port(port)
    if not args.port and registry.data.get("port") != port:
        registry.data["port"] = port
        registry.save()
    # In rete solo se esiste almeno un utente: altrimenti chiunque potrebbe leggere i documenti.
    host = cfg.server.host if (cfg.server.host in LOOPBACK or cfg.server.users) else "127.0.0.1"
    cfg.server.host, cfg.server.port = host, port

    server = uvicorn.Server(uvicorn.Config(create_app(hub), host=host, port=port,
                                           log_config=None, access_log=False))
    stop = threading.Event()

    def quit_app() -> None:
        server.should_exit = True
        stop.set()

    hub.quit = quit_app
    thread = threading.Thread(target=server.run, name="llmwiki-server", daemon=True)
    thread.start()
    deadline = time.time() + 40
    while time.time() < deadline and thread.is_alive() and not _alive(port):
        time.sleep(0.2)
    if not thread.is_alive():
        raise RuntimeError("il server interno non è partito")
    url = f"http://127.0.0.1:{port}"
    log.info("LLMWiki %s su %s (spazio: %s)", __version__, url, space["name"])
    if not args.no_window:  # in un thread: l'attesa della finestra non ritarda l'icona
        threading.Thread(target=open_window, args=(url,), daemon=True).start()

    if args.no_tray or not _run_tray(url, hub, quit_app, stop):
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
