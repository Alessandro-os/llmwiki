# Cronologia delle versioni

## 0.5.1 · 2026-11-16

Per chi la usa:

- "Rileggi" premuto mentre il documento è ancora in lettura ora viene rispettato: prima la
  scheda usciva dal testo letto nel vecchio modo e il documento risultava già pronto.
- Un file che non si può leggere in quel momento (aperto da un altro programma, copia in
  corso) non blocca più la lettura degli altri documenti: si riprova al giro dopo.
- L'OCR acceso dall'app non viene più spento mentre legge un pezzo lungo o appena dopo
  l'accensione.
- Se il modello è spento, il testo già letto non si rilegge a ogni tentativo: resta salvato e
  cercabile, e quando il modello torna si scrive solo la scheda. Con l'OCR erano minuti di
  lavoro rifatti ogni minuto.
- In basso a sinistra si capisce chi sta facendo che cosa: "Leggo il testo" (dal file o con
  l'OCR, con la pagina) e poi "Scrivo la scheda" (con il modello). Se il modello è spento dice
  che il testo è già cercabile e che per le schede va acceso.
- La ricerca degli OCR guarda anche nelle cartelle in cima ai dischi con nomi come AI, models,
  llama, in Download e sul Desktop. Se non trova niente dice dove ha guardato.
- Dopo il caricamento l'app scrive con che cosa leggerà i PDF.
- Uno spazio nuovo parte anche con l'OCR dello spazio attuale.
- Un aggiornamento scaricato per intero ma interrotto prima del controllo non resta più bloccato.
- Il registro non si riempie più degli avvisi di pypdf.
- L'OCR riprende dalla pagina a cui era arrivato: se si spegne, o chiudi l'app, a metà di un
  documento lungo, le pagine già lette non si rifanno. Dopo la prima pagina compare il tempo
  che manca.
- Copia di sicurezza: in Impostazioni → Spazi un tasto mette documenti, indice e impostazioni
  dello spazio in un file zip; "Ripristina da una copia" lo riapre come spazio nuovo.
- Un modello generico trovato tra gli OCR è segnato "sconsigliato" e chiede conferma: può
  inventare il testo.
- Un documento tolto mentre veniva letto non ricompare più nella ricerca.

Per chi sviluppa:

- `Indexer._read_doc` confronta anche `method`, oltre all'impronta, prima di segnare "pronto".
- `Indexer._scan_fs` salta il file che dà `OSError` invece di far fallire tutta la scansione.
- `LocalOcr`: conto dei pezzi in lettura (`_reading`) sotto lo stesso lucchetto dello
  spegnimento per inattività; `ocr.log` non resta più aperto nell'app a ogni accensione.
- `state.db`: colonne `text_sha` e `text_method`; `Store.set_text` al posto di `set_lines`.
- `/api/status`: `text_waiting`, `ocr_mode`, e per ogni documento in lettura `phase`, `page`,
  `pages`. `/api/admin/ocr/detect` restituisce anche `searched`.
- `ocr_local.search_folders` è l'unico posto che dice dove si cercano gli OCR.
- `download.fetch_verified` non chiede niente al server se il file `.part` è già completo.
- `extract.PageCache` e `Ocr.identity`: pagine dell'OCR messe da parte in `.indice/pages/`.
- `backup.py` e le rotte `/api/admin/backup` e `/api/admin/restore`.
- Banco di prova: le formule in LaTeX contano come il testo (`\frac{5}{2}` = "5/2").
- I controlli su GitHub girano anche sui rami `claude/**`.
- Pubblicazione automatica: un'etichetta `v…` costruisce, collauda e pubblica la versione
  (`.github/workflows/release.yml`, `packaging/release_notes.py`).

## 0.5.0 · 2026-11-16

Per chi la usa:

- Lettura dei documenti più chiara: in basso a sinistra nome del documento, percentuale
  indicativa, tempo trascorso, modello che legge e documenti in coda; alla fine, quanto ci ha
  messo. Un tasto "Ferma la lettura" la interrompe, "Riprendi" la fa ripartire.
- Ogni documento ricorda quale modello l'ha letto, in quanto tempo e quando: lo dice la sua
  scheda in Documenti.
- Scansioni e appunti scritti a mano: si sceglie con che cosa leggere i PDF.
  - **Automatico** (predefinito): testo esatto se il PDF lo contiene, l'OCR se è una
    scansione.
  - **Testo esatto**: per i PDF fatti al computer.
  - **OCR**: per scansioni e appunti a mano.

  La scelta vale per lo spazio, e si può cambiare per ogni documento: al caricamento, o dopo
  con "Rileggi". Una leggenda ricorda chi fa meglio che cosa.
- Qualunque OCR, trovato sul computer come i modelli: "Cerca gli OCR sul computer" trova i
  modelli OCR scaricati (file GGUF, anche quelli di LM Studio), quelli accesi su un server e
  Tesseract; si sceglie con "Usa questo". L'app accende da sola l'OCR scelto quando serve,
  sulla scheda video se c'è posto (2-3 s a pagina), altrimenti sul processore, senza togliere
  memoria al modello che risponde, e lo spegne quando ha finito. Un OCR su un server può avere
  il suo comando di avvio, che l'app lancia se è spento.
- L'app non scarica nessun OCR. Se non ne trova, consiglia MiniCPM-OCR (scelto su 12 pagine
  vere di appunti, tra sei OCR: il migliore tra quelli che non inventano), con i link, una guida
  scritta (docs/12) e un tasto che copia un messaggio da mandare a Claude per farsi aiutare.
- Ogni documento ricorda quale OCR l'ha letto e dove ha girato. Se l'OCR non c'è o è spento, i
  PDF aspettano invece di finire in errore.
- Tasto Aggiorna: a ogni avvio l'app controlla su GitHub se c'è una versione nuova e, se c'è,
  lo mostra in basso a destra nella pagina principale. Premendolo scarica la versione nuova,
  ne controlla l'impronta, si chiude e si riapre aggiornata, senza lasciare file della
  versione vecchia. Documenti, spazi e impostazioni restano.
- La finestra di LLMWiki ha la sua icona, anche nella barra delle applicazioni: prima
  mostrava quella del browser.
- Due avvii a pochi secondi di distanza (l'installatore e un doppio clic) non danno più
  l'errore "il server interno non è partito": la seconda copia aspetta la prima e la porta in
  primo piano.
- Salvare le impostazioni due volte di seguito poteva lasciare l'app appesa, senza risposta:
  ora lo spazio si chiude e si riapre sempre.

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
- `ocr_local.py` (`find_models`: coppie modello + `mmproj` nelle cartelle note, file di bozza
  esclusi; `find_llama_servers`; `LocalOcr`: llama-server acceso sulla scheda video o sul
  processore, spento dopo 3 minuti) e `ocr_catalog.json` (OCR conosciuti: istruzione, strisce,
  per che cosa vanno bene, dove si scaricano). `app.find_local_ocr`, `detect_ocr(folders)`.
  `Ocr.read` taglia a strisce e chiama `read_piece` delle sottoclassi; `ServerOcr` ha `prompt`,
  `parts` e `start_command`. `ocr.loop_start` (freno alle ripetizioni, testo in stream),
  `ocr.clean_text` (coordinate e segnali di Unlimited OCR e DeepSeek-OCR, `[Non-Text]` di MiniCPM-OCR);
  `ocr.strips` non taglia strisce più basse di 200 pixel (`MIN_STRIP`). `[ocr] mode` =
  `auto | text | ocr`, `kind` = `local | server | tesseract`, più `name`, `prompt`, `strips`,
  `folders`, `model_path`, `mmproj_path`, `llama_server`, `start_command`. `/api/admin/settings`
  aggiunge `ocr_catalog` e `ocr_folder`. Colonna `method` in `docs` e rotta
  `/api/admin/doc-method`; `/api/upload` accetta `method`.
- `update.py` (`Updater`: controllo su GitHub, scaricamento, installazione silenziosa) e
  `download.py` (`fetch_verified`, ora usato anche da `nli.Download`). Rotta
  `/api/admin/update`; `/api/status` aggiunge `update` nell'app desktop. Installatore:
  `[InstallDelete]` di `{app}\_internal` e riavvio dopo l'installazione silenziosa. Test in
  `tests/test_update.py`.
- `icon.py`: unica fonte dell'icona (prima in `desktop.py`); il server la serve come
  `/favicon.ico` e `/icon.png`, pubbliche.
- `desktop._claim_instance()`: lucchetto su `llmwiki.lock` per una sola copia. Test:
  `test_second_launch_while_the_first_is_starting_does_not_fail`.
- `asyncio.timeout` al posto di `asyncio.wait_for` (sorveglianza della cartella, flusso delle
  risposte): in Python 3.11 `wait_for` perde l'annullamento se arriva nello stesso istante in
  cui l'attesa finisce, e `Indexer.stop()` restava appeso. Test:
  `test_closing_right_after_a_rescan_request_does_not_hang`.

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
