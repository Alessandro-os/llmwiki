# Come si lavora su LLMWiki

Istruzioni per chiunque sviluppi questo progetto: Claude Code, opencode, pi o una persona.
Sono il metodo con cui LLMWiki è stata costruita dalla 0.1 alla 0.4 (con Claude Fable 5.2),
ricavato dal lavoro fatto e dalle correzioni dell'utente. Valgono con qualunque modello.

Come è fatto il codice, i comandi e i test: [docs/09-sviluppo.md](docs/09-sviluppo.md).
Come funziona l'app: [docs/README.md](docs/README.md). Cose in sospeso: [DA_FARE.md](DA_FARE.md).

## Per chi è

- L'utente parla italiano, spesso detta a voce: rispondi e scrivi in italiano semplice.
  Codice, commenti, commit, interfaccia e documentazione sono in italiano.
- Non è uno sviluppatore. Vuole un **software vero**, da installare e dare ad altri: niente
  script sparsi, niente passaggi a mano. Serve sia a un'azienda (contratti, documenti) sia a chi
  studia sui propri appunti in markdown.
- Delega le scelte tecniche **dentro il compito chiesto**. Non aggiungere compiti, prove,
  sezioni o pagine che non ha chiesto: proponili con una domanda. Vale soprattutto per ciò che
  occupa le sue risorse (Strata, scheda video, opencode e pi fermi).

## Le cose che non si rompono mai

1. **Una citazione confermata deve essere vera.** È il cuore del prodotto. Una risposta può
   essere incompleta; non può essere falsa e mostrata come verificata. Ogni modifica a
   estrazione, agente o verifica si giudica prima di tutto su questo.
2. **Funziona con qualunque modello.** Ogni capacità che non tutti i modelli hanno ha un
   ripiego automatico (strumenti a parole, risposta di riserva, parametri rifiutati tolti,
   pezzi più corti). Mai codice che funziona solo con Claude o solo con Strata.
3. **Funziona sempre.** Modello spento o sovraccarico = documenti in attesa, non in errore.
   Spazio cancellato = si apre un altro spazio. Un errore dice all'utente che cosa fare.
4. **In locale per prima cosa.** I documenti non escono dal PC se l'utente non sceglie un
   servizio online. L'app scrive solo in `%LOCALAPPDATA%\LLMWiki` e `Documenti\LLMWiki`.
5. **Usabile da chiunque.** Niente termini tecnici in primo piano; le opzioni per esperti
   stanno sotto "Opzioni avanzate".

## Il ciclo di lavoro

1. **Capisci prima di toccare.** Leggi per intero i moduli che cambierai. Le API delle
   librerie (anthropic, mcp, onnxruntime…) si verificano sul pacchetto installato, non a
   memoria: ispeziona firme e classi con Python prima di scrivere.
2. **Piano corto, poi lavora da solo.** Pochi passi chiari; poi avanti fino alla fine senza
   chiedere conferme su dettagli tecnici. Fermati solo per decisioni che sono sue.
3. **Test insieme al codice.** Ogni comportamento nuovo o difetto corretto ha il suo test in
   `tests/`, che gira senza modelli né chiavi (fornitore `mock`, server HTTP finti). Scrivi
   test sui casi veri e scomodi: file Windows-1252, BOM, nomi accentati, PDF senza testo,
   file spostati o modificati durante la lettura, server che si spegne a metà.
4. **Dopo ogni modifica:** `uv run ruff check` e `uv run pytest`. Verdi tutti e due, poi commit.
5. **Misura ciò che tocca la qualità.** Prompt, verifica, ricerca, scelta di un modello: si
   misurano con `evals/run.py` **prima e dopo**. Senza numeri non si dice "migliorato". I
   risultati vanno nella tabella "Misure" del `README.md`.
6. **Prova dal vivo, non solo i test.**
   - L'app dal sorgente, con `LLMWIKI_HOME` puntato a una cartella di prova, mai sugli spazi veri.
   - L'interfaccia guardata a schermo nel browser, in tema scuro **e** chiaro.
   - MCP con un vero client MCP; una domanda vera al modello vero quando la modifica lo riguarda.
   - Prima di una versione: `packaging\build.ps1` (collaudo automatico dell'eseguibile), poi
     installer installato in una cartella temporanea, provato e disinstallato.
7. **Pulisci.** Chiudi i processi e le porte che hai aperto, cancella i file di prova, togli i
   pacchetti delle versioni vecchie da `dist`. Non chiudere mai processi dell'utente (Brave,
   Strata, opencode, pi).

Con Strata acceso, test e build rallentano il modello: durante una misura con il modello vero
non lanciare lavori pesanti.

## Il codice

- **Funzioni piccole**, che fanno una cosa. Una funzione che cresce oltre qualche decina di
  istruzioni si divide (il server aveva una funzione da 200: ora sono rotte separate).
- **Una sola fonte per ogni cosa.** Un formato, un elenco, una regola stanno in un posto solo
  (il file di configurazione lo scrive solo `Config.save()`). Prima di aggiungere, cerca se
  esiste già.
- **Niente codice morto, niente superfluo.** Niente astrazioni "per il futuro", niente opzioni
  che nessuno ha chiesto. Ogni tanto cerca codice mai usato (ruff, vulture) anche nella pagina web.
- **Le dipendenze vanno guadagnate con una misura.** Esempi: LettuceDetect scartato perché
  richiede PyTorch e misurava peggio; ricerca per significato non aggiunta perché la ricerca per
  parole trovava il documento giusto 24 volte su 24.
- **I moduli dipendono verso il basso**, secondo la mappa in `docs/09-sviluppo.md`.
- **I commenti spiegano il perché**, non il cosa. Le scelte importanti scrivono nel docstring
  che cosa è stato confrontato e perché il resto è stato scartato (vedi `nli.py`).
- **Testi per l'utente:** frasi brevi, italiano semplice, e negli errori il passo da fare.

## Decidere con i fatti

- Confronta i candidati su dati veri e tieni la tabella del confronto (vedi la scelta del
  decision model: AUC, tempi, dimensioni, licenza).
- Misura sul PC vero, non fidarti delle stime. Se una misura smentisce la documentazione,
  **correggi la documentazione subito** e dillo.
- Distingui sempre ciò che hai misurato da ciò che hai dedotto: "non misurato", "provato solo
  contro un server finto", "non visto a schermo".
- Scarichi un file? Controlla dimensione e SHA-256 con quelli della fonte prima di usarlo.

## Documentazione e versioni

- Cambia il comportamento → aggiorna la pagina giusta di `docs/` nello stesso commit, con i
  numeri ricontrollati sul codice e i link verificati.
- `CHANGELOG.md` diviso tra "per chi la usa" e "per chi sviluppa". Versione uguale in
  `pyproject.toml` e `src/llmwiki/__init__.py`.
- `DA_FARE.md` è l'elenco unico delle cose in sospeso: tienilo aggiornato, non creare altri elenchi.
- **Commit** piccoli e frequenti, in italiano: titolo che dice l'effetto, corpo che spiega il
  perché, in fondo la riga `Co-Authored-By:` del modello che ha fatto il lavoro. Mai push.

## Come si riferisce all'utente

L'utente segue il lavoro anche dal telefono e legge solo il messaggio finale. Il resoconto:

1. **Prima riga: l'esito**, cioè che cosa ora funziona e dove si trova.
2. **Che cosa è verificato e come** (test, misura, prova dal vivo), con i numeri in una tabella.
3. **Che cosa non è verificato o non è fatto**, detto chiaramente, mai nascosto.
4. **Difetti trovati e corretti**, e i propri errori ammessi apertamente.
5. **Una domanda chiusa alla fine** se serve una sua decisione ("sì" / "non ora"), con il
   comando pronto se deve fare qualcosa lui.

Spiega i termini tecnici la prima volta che li usi. Niente elenchi di opzioni senza una
raccomandazione.

## Confini

- Mai push su GitHub, mai credenziali o chiavi inserite da te, mai l'indirizzo email
  dell'utente fuori dal git locale.
- Non toccare `file personale per i comandi da terminale.txt`.
- Mai riavviare, scaricare o cambiare il modello di Strata senza il suo sì: ferma opencode e pi.
- Installare programmi (winget e simili): lo chiedi all'utente e gli dai il comando.
- Un blocco di sicurezza (per esempio la cancellazione nella radice di `C:`) non si aggira:
  si spiega e si lascia fare all'utente.
- I modelli stanno in `C:\AI-Workspace\modelli` (vedi il suo `LEGGIMI.txt`): niente file di
  modelli sparsi altrove.
