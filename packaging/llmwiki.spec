# PyInstaller: una cartella con LLMWiki.exe (app) e llmwiki-cli.exe (riga di comando).
# Si lancia con packaging/build.ps1.
from PyInstaller.utils.hooks import (collect_data_files, collect_dynamic_libs,
                                     collect_submodules, copy_metadata)

ROOT = SPECPATH + "/.."
datas = [(ROOT + "/src/llmwiki/web", "llmwiki/web")]
binaries, hiddenimports = [], []
# mcp.cli richiede typer (non serve all'app) e fa fallire l'analisi: resta fuori.
SKIP = ("mcp.cli", "onnxruntime.transformers", "onnxruntime.quantization", "onnxruntime.tools")
for package in ("mcp", "anthropic", "uvicorn", "onnxruntime", "tokenizers", "pystray", "docx", "pypdf"):
    datas += collect_data_files(package)
    binaries += collect_dynamic_libs(package)
    hiddenimports += collect_submodules(
        package, filter=lambda name: not name.startswith(SKIP), on_error="ignore")
    try:
        datas += copy_metadata(package)
    except Exception:
        pass
hiddenimports += collect_submodules("llmwiki") + ["httpx2", "multipart", "python_multipart"]

common = dict(pathex=[ROOT + "/src"], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
              excludes=["tkinter", "pytest", "torch", "transformers", "IPython", "matplotlib"],
              noarchive=False)
desktop = Analysis([SPECPATH + "/desktop_entry.py"], **common)
cli = Analysis([SPECPATH + "/cli_entry.py"], **common)

desktop_exe = EXE(PYZ(desktop.pure), desktop.scripts, [], exclude_binaries=True, name="LLMWiki",
                  console=False, icon=SPECPATH + "/llmwiki.ico")
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name="llmwiki-cli",
              console=True, icon=SPECPATH + "/llmwiki.ico")
COLLECT(desktop_exe, cli_exe, desktop.binaries, desktop.datas, cli.binaries, cli.datas, name="LLMWiki")
