"""Punto d'ingresso di LLMWiki.exe (app desktop, senza console)."""

import sys

from llmwiki.desktop import main

if __name__ == "__main__":
    sys.exit(main())
