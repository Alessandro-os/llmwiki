# Costruisce l'app distribuibile:
#   dist\LLMWiki\LLMWiki.exe            app desktop
#   dist\LLMWiki\llmwiki-cli.exe        riga di comando
#   dist\LLMWiki-<versione>-windows-x64.zip   da dare ad altre persone
# Uso:  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

uv sync
if ($LASTEXITCODE) { throw "uv sync non riuscito" }
uv run python -c "from llmwiki.desktop import make_icon; make_icon(256).save('packaging/llmwiki.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(256,256)])"
if ($LASTEXITCODE) { throw "icona non generata" }

uv run pyinstaller packaging\llmwiki.spec --noconfirm --clean --distpath dist --workpath build\pyinstaller
if ($LASTEXITCODE) { throw "pyinstaller non riuscito" }

Copy-Item -Force packaging\LEGGIMI.txt dist\LLMWiki\LEGGIMI.txt
Copy-Item -Force LICENSES.md dist\LLMWiki\LICENZE.md

$version = (uv run python -c "import llmwiki; print(llmwiki.__version__)").Trim()
$zip = "dist\LLMWiki-$version-windows-x64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path dist\LLMWiki -DestinationPath $zip -CompressionLevel Optimal
"Pronto: $zip ({0:n0} MB)" -f ((Get-Item $zip).Length / 1MB)
