@AGENTS.md

## Solo per Claude Code (app desktop)

- I comandi lanciati dall'app Claude girano dentro il suo pacchetto: una cartella **nuova** creata
  in `%LOCALAPPDATA%` o `%APPDATA%` finisce in `%LOCALAPPDATA%\Packages\Claude_*\LocalCache` e la
  vede solo la sessione, non l'utente. Ciò che deve vedere anche l'utente va fuori da AppData; per
  creare qualcosa nella AppData vera si lancia uno script con `explorer.exe "file.cmd"` e se ne
  legge il log. Prima di cancellare un "doppione" in LocalCache, controlla che esista anche fuori.
