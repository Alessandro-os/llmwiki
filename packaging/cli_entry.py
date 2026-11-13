"""Punto d'ingresso di llmwiki-cli.exe (riga di comando: server, indicizzazione, MCP su stdio)."""

import sys

from llmwiki.cli import main

if __name__ == "__main__":
    sys.exit(main())
