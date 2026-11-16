# Cronologia delle versioni

## 0.5.0 · 2026-11-16

Per chi la usa:

- Lettura dei documenti più chiara: in basso a sinistra nome del documento, percentuale
  indicativa, tempo trascorso, modello che legge e documenti in coda; alla fine, quanto ci ha
  messo. Un tasto "Ferma la lettura" la interrompe, "Riprendi" la fa ripartire.
- Ogni documento ricorda quale modello l'ha letto, in quanto tempo e quando: lo dice la sua
  scheda in Documenti.
- Scansioni e appunti scritti a mano: si sceglie con che cosa leggere i PDF.
  - **Automatico** (predefinito): testo esatto se il PDF lo contiene, MiniCPM-OCR se è una
    scansione.
  - **Testo esatto**: per i PDF fatti al computer.
  - **MiniCPM-OCR**: per scansioni e appunti a mano.

  La scelta vale per lo spazio, e si può cambiare per ogni documento: al caricamento, o dopo
  con "Rileggi". Una leggenda ricorda chi fa meglio che cosa.
- MiniCPM-OCR si scarica con un clic (1,7 GB, impronte controllate). L'app lo accende da sola
  sulla scheda video se c'è posto (2-3 s a pagina), altrimenti sul processore, senza togliere
  memoria al modello che risponde, e lo spegne quando ha finito. È stato scelto su 12 pagine
  vere di appunti, tra sei OCR: è il migliore tra quelli che non inventano.
- In "Opzioni avanzate" si può collegare un altro OCR qualunque: "Cerca altri OCR sul
  computer" propone solo quelli che leggono davvero un'immagine di prova. Ogni documento
  ricorda quale OCR l'ha letto e dove ha girato. Se l'OCR non c'è o è spento, i PDF aspettano
  invece di finire in errore.
- Tasto Aggiorna: a ogni avvio l'app controlla su GitHub se c'è una versione nuova e, se c'è,
  lo mostra in basso a destra nella pagina principale. Premendolo scarica la versione nuova,
  ne controlla l'impronta, si chiude e si riapre aggiornata, senza lasciare file della
  versione vecchia. Documenti, spazi e impostazioni restano.
- La finestra di LLMWiki ha la sua icona, anche nella barra delle applicazioni: prima
  mostrava quella del browser.
- Due avvii a pochi secondi di distanza (l'installatore e un doppio clic) non danno più
  l'errore "il server interno non è partito": la seconda copia aspetta la prima e la porta in
  primo piano.

Per chi sviluppa:

- `indexer.Progress` (avanzamento per documento), `Indexer.pause()` / `resume()`, rotte
  `/api/admin/index/pause` e `/resume`; `status()` aggiunge `reading`, `last_done`, `paused`,
  `reader`. Colonne `model`, `seconds`, `read_at` in `docs`, aggiunte anche ai database
  esistenti (`Store._add_columns`, primo aggiornamento dello schema).
- `ocr.py` (`Ocr`, `ServerOcr`, `TesseractOcr`, `make_ocr`, `probe`, `find_tesseract`),
  `app.detect_ocr`, sezione `[ocr]` in `wiki.toml`, rotte `/api/admin/ocr/detect` e
  `/ocr/test`, colonna `ocr` in `docs`. Dipendenza nuova: pypdfium2 (pagine PDF come
  immagini). `LOCAL_SERVERS` aggiunge llama.cpp 8090 e SGLang 30000 e 10000. Test in
  `tests/test_ocr.py`.
- `minicpm.py` (`Install`, `ManagedOcr`: scaricamento verificato, llama-server acceso sulla
  scheda video o sul processore, spento dopo 3 minuti di inattività), `ocr.strips` (pagina a
  strisce), `ocr.loop_start` (freno alle ripetizioni, testo in stream), `ocr.clean_text`
  (coordinate e segnali di Unlimited OCR e DeepSeek-OCR). `[ocr] mode` = `auto | text | ocr`,
  `kind` = `minicpm | server | tesseract`, `llama_server`. Colonna `method` in `docs` e rotta
  `/api/admin/doc-method`; `/api/upload` accetta `method`; rotta `/api/admin/ocr/install`.
- `update.py` (`Updater`: controllo su GitHub, scaricamento, installazione silenziosa) e
  `download.py` (`fetch_verified`, ora usato anche da `nli.Download`). Rotta
  `/api/admin/update`; `/api/status` aggiunge `update` nell'app desktop. Installatore:
  `[InstallDelete]` di `{app}\_internal` e riavvio dopo l'installazione silenziosa. Test in
  `tests/test_update.py`.
- `icon.py`: unica fonte dell'icona (prima in `desktop.py`); il server la serve come
  `/favicon.ico` e `/icon.png`, pubbliche.
- `desktop._claim_instance()`: lucchetto su `llmwiki.lock` per una sola copia. Test:
  `test_second_launch_while_the_first_is_starting_does_not_fail`.

## 0.4.1 · 2026-11-15

Per chi la usa:

- Se il verificatore delle citazioni c'è ma non si può leggere, l'app si apre lo stesso e
  verifica con il modello. Prima non partiva affatto ("nessuno spazio si apre", errore 448).

Per chi sviluppa:

- `nli.installed()` tratta un `OSError` come modello assente e lo scrive nel log. Test:
  `test_unreadable_decision_model_does_not_block_the_app`.

## 0.4.0 · 2026-11-14

Per chi la usa:

- Interfaccia ridisegnata: tre sezioni (Chiedi, Documenti, Impostazioni), tre passi guidati al
  primo avvio, linguaggio senza termini tecnici, tema chiaro o scuro secondo il sistema.
- Il modello acceso sul computer viene trovato da solo e si collega con un clic.
- Qualunque fornitore dalle Impostazioni: Claude, OpenAI, Gemini, OpenRouter, Mistral, Groq o
  un altro servizio compatibile; la chiave si incolla una volta e i modelli si scelgono da un
  elenco. "Salva e prova" dice in chiaro che cosa sa fare il modello scelto.
- L'app funziona anche con modelli che non sanno usare gli strumenti di ricerca: passa da sola
  a una modalità compatibile e, se nemmeno quella riesce, cerca al posto del modello.
- Se il modello si spegne mentre l'app legge i documenti, la lettura aspetta e riprende da
  sola; i documenti non finiscono più in errore.
- Con modelli dal contesto piccolo i documenti lunghi vengono letti a pezzi più corti.

Per chi sviluppa:

- `llm.py`: protocollo testuale per gli strumenti (`TextToolConversation`), scelta automatica
  tra chiamate native e testo, parametri facoltativi di Claude tolti se rifiutati, elenco dei
  modelli e diagnosi (`probe`).
- `tests/test_independence.py`: server finti che rifiutano gli strumenti, li ignorano, non
  rispettano il JSON, hanno poco contesto o si spengono a metà.
- Nuove impostazioni: `llm.tool_mode`, `llm.context_tokens`.

## 0.3.1 · 2026-11-14

Per chi la usa:

- Spostare o rinominare un file non costa più una nuova lettura da parte del modello: testo e
  scheda lo seguono.
- Un documento modificato mentre il modello lo stava leggendo viene riletto, invece di restare
  con la scheda della versione vecchia.
- Le affermazioni di assenza ("l'allegato non prevede penali") vengono confermate quando le
  righe citate coprono tutto il documento, invece di finire con ⚠.
- Se la cartella dello spazio attivo è stata spostata o cancellata, l'app apre un altro spazio.
- Avviso in alto quando alcuni documenti non sono stati indicizzati.
- Installer `LLMWiki-<versione>-setup.exe`.

Per chi sviluppa:

- Revisione del codice: server, app desktop e verifica divisi in funzioni piccole; una sola
  fonte per la configurazione (`Config.save()`), creazione utenti e rilevamento dei modelli
  locali condivisi tra app e riga di comando.
- Un server di modelli spento non viene più scambiato per un server senza logprob.
- `evals/run.py answers --suite difficile`: 64 documenti molto simili tra loro e 24 domande
  con risposta nota.
- Controlli automatici pronti per GitHub (`.github/workflows/ci.yml`), fine riga uniformi.

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
