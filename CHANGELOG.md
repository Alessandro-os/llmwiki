# Cronologia delle versioni

## 0.3.0 · 2026-11-14

Per chi la usa:

- Mentre risponde l'app mostra cosa sta facendo (quale cartella apre, cosa cerca, quali righe
  legge) e la domanda si può fermare.
- Domande di approfondimento: "spiegami meglio il secondo punto" tiene conto degli scambi
  precedenti, ma i fatti vengono comunque riletti e citati dai documenti.
- La conversazione resta salvata per spazio e per persona; "Nuova conversazione" la svuota.
- Dalla citazione si apre il testo originale con le righe citate evidenziate.
- La finestra si apre con il browser predefinito in modalità app (Brave, Chrome, Edge) e l'app
  controlla che sia comparsa davvero; altrimenti apre una scheda normale.
- Impostazione per far ragionare meno i modelli locali (più veloce, schede meno dettagliate).
- Corretti: i file di testo in codifica Windows-1252 venivano letti male; un PDF scansionato
  senza testo risultava indicizzato a vuoto invece che segnalato.

Per chi sviluppa:

- `evals/run.py`: banco di prova per il giudice delle citazioni, per le risposte end-to-end e
  per la tenuta con migliaia di documenti.
- `packaging/smoke_test.py`: collaudo dell'eseguibile, eseguito a ogni build.
- `packaging/installer.iss`: installer Inno Setup, generato dalla build se Inno Setup c'è.
- Lint con ruff, test su PDF, Word, HTML e nomi di file accentati.
- L'albero dei riassunti si aggiorna a coda vuota, non a ogni scheda.

## 0.2.0 · 2026-11-13

- App desktop: `LLMWiki.exe`, icona nell'area di notifica, primo avvio che collega da solo il
  modello locale.
- Spazi separati (Studio, Lavoro, Azienda) e impostazioni dall'interfaccia.
- Decision model dedicato (mDeBERTa-v3 NLI multilingue) e verifica a cascata.
- Accessi: dal computer dell'app senza token, dalla rete con token personale;
  amministrazione solo locale.

## 0.1.0 · 2026-11-13

- Indicizzazione parallela ad albero di riassunti, agente con navigazione in tempo reale,
  citazioni verificate, server condiviso e MCP.
