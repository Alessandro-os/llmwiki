# 2. Lettura dei documenti

[← Indice](README.md) · codice: `indexer.py`, `extract.py`, `store.py`

Nell'app si chiama "lettura dei documenti"; nel codice "indicizzazione". Sono due lavori
separati che girano insieme: le **schede** (un lavoro per documento) e l'**albero** (riassunti
sopra le schede).

## 2.1 Come l'app si accorge dei documenti

Mentre l'app è accesa, ogni 20 secondi (`index.watch_seconds`) guarda la cartella `documenti`
dello spazio, sottocartelle comprese. Guarda subito, senza aspettare, quando carichi un file
dall'interfaccia o premi "Riprova a leggerli".

Per ogni file:

1. Lo considera solo se ha un'estensione leggibile (elenco in 2.2) e se né il file né una
   cartella sopra di lui ha un nome che comincia con `.` o `~$` (i file temporanei di Word).
2. Se dimensione e data di modifica sono uguali all'ultima volta, non fa nulla.
3. Altrimenti calcola l'impronta SHA-256 del contenuto. Se è uguale a quella registrata (il
   file è stato solo "toccato") aggiorna la data e basta.
4. Se il contenuto è nuovo o diverso, il documento va **in coda**.

Poi confronta ciò che ha trovato con ciò che conosceva:

- **File sparito e un file nuovo con lo stesso contenuto**: è uno spostamento o un cambio di
  nome. Testo e scheda seguono il file al nuovo percorso; il modello non viene chiamato.
- **File sparito e basta**: il documento, il suo testo, la sua scheda e le sue voci nella
  ricerca vengono cancellati; l'albero viene segnato da aggiornare.

Ogni documento ha uno stato:

| Stato | Nell'app | Significato |
|---|---|---|
| `pending` | in coda | aspetta il suo turno |
| `indexing` | in lettura | il modello lo sta leggendo |
| `ready` | pronto | ha la scheda |
| `error` | non letto | qualcosa è andato storto; il motivo è in Impostazioni → Lettura dei documenti |

## 2.2 Dal file alle righe numerate

| Formato | Come viene letto |
|---|---|
| `.txt .md .markdown .rst .csv .tsv .json .xml .yaml .yml .log .ini .toml .tex` | Testo così com'è. Codifica: UTF-16 solo se il file lo dichiara (BOM), poi UTF-8, poi Windows-1252. |
| `.html .htm` | Solo il testo visibile; script e stili sono scartati. |
| `.pdf` | Il testo di ogni pagina, preceduto da una riga `=== Pagina N ===`. Se nessuna pagina ha testo (una scansione) il documento va in errore e il messaggio dice di scegliere l'OCR. Con l'OCR (2.2.1) ogni pagina è letta come immagine. |
| `.docx` | I paragrafi, poi le righe delle tabelle con le celle separate da una barra verticale. |

### 2.2.1 PDF con l'OCR

Tre modi di leggere i PDF (Impostazioni → Lettura dei documenti, `[ocr] mode` in `wiki.toml`):

| Modo | Che cosa fa | Per |
|---|---|---|
| **Automatico** (predefinito) | Testo esatto se il PDF lo contiene; se non ne contiene (una scansione, appunti a mano), MiniCPM-OCR | quasi tutto |
| **Testo esatto** | Solo il testo che il PDF contiene: perfetto e istantaneo. Un PDF senza testo va in errore, e il messaggio dice di scegliere l'OCR | PDF nati al computer (Word, slide, LaTeX) |
| **MiniCPM-OCR** | Ogni pagina letta come immagine, anche se il PDF contiene testo | scansioni con un testo nascosto sbagliato, pagine miste |

Il modo dello spazio vale per i documenti nuovi. Ogni documento può averne uno suo:
- al caricamento, con "Come leggere i PDF";
- dopo, con "Rileggi" nella sua scheda (colonna `method` di `state.db`; vuota = quello dello spazio).

La pagina ha una leggenda su chi fa meglio che cosa, che riassume le misure del README.

**MiniCPM-OCR gestito dall'app** (`minicpm.py`).

Scelto il 16/11/2026 tra sei OCR, su 12 pagine vere di appunti. È il migliore tra quelli che non inventano:
- sullo stampato è alla pari con Unlimited OCR 2, ma 30 volte più veloce;
- a mano legge circa la metà delle parole.

I modelli generici che vedono le immagini, come Strata, leggevano di più a mano, ma inventano frasi e numeri. Per questo non sono proposti.

- **Scaricamento.** "Scarica (1,7 GB)" scarica il modello GGUF ufficiale (Q8_0) e la sua parte visiva da `openbmb/MiniCPM-OCR-1.0-gguf`, a revisione fissa. Scarica anche llama.cpp b12364 in versione Vulkan (36 MB), che usa la scheda video di qualunque marca. Ogni file è controllato con la sua impronta SHA-256, e lo scaricamento riprende se si interrompe. Tutto va in `%LOCALAPPDATA%\LLMWiki\ocr\minicpm-ocr`. In "Opzioni avanzate" si può indicare un `llama-server.exe` già installato.
- **Accensione.** Alla prima pagina da leggere l'app avvia `llama-server`:
  - sulla scheda video, se ha almeno 3 GB liberi: 2-3 s a pagina;
  - altrimenti sul processore: 30-50 s a pagina, senza togliere memoria al modello che risponde;
  - se sulla scheda video non parte, riprova sul processore.

  Dopo 3 minuti senza pagine da leggere si spegne. La scheda del documento dice dove ha girato: «MiniCPM-OCR (processore)».
- **Lettura a strisce.** Ogni pagina è tagliata in 4 strisce orizzontali, dove c'è meno inchiostro (`ocr.strips`), e le strisce sono lette una dopo l'altra. Su sei pagine di appunti a mano le parole giuste passano dal 37% al 45%. L'istruzione è quella ufficiale, `Text Recognition:`.
- **Se manca.** Un PDF da leggere con l'OCR aspetta, e in basso a sinistra c'è scritto di scaricare MiniCPM-OCR. Appena è scaricato, la lettura riparte da sola.

**Un altro OCR** (Opzioni avanzate). L'app non dipende da MiniCPM: si può collegare qualunque OCR (`ocr.py`).

| Tipo | Che cos'è | Esempi |
|---|---|---|
| server | Un modello che legge immagini, con l'API compatibile OpenAI | Unlimited OCR, PaddleOCR-VL, DeepSeek-OCR con SGLang, vLLM o llama.cpp |
| tesseract | Il programma Tesseract installato | Tesseract 5 |

"Cerca altri OCR sul computer":
- interroga i server noti (8080, 8090, 11434, 1234, 8000, 30000, 10000);
- prova ogni modello, fino a 6 per server, con un'immagine che contiene la scritta `CARNOT 1824`;
- propone solo chi la legge davvero.

**Per tutti gli OCR:**
- le pagine diventano immagini a 200 dpi (pypdfium2), una alla volta;
- ogni pagina, e per MiniCPM ogni striscia, fa avanzare la percentuale (2.9);
- il testo letto diventa righe numerate e citabili, come quello estratto;
- ogni documento ricorda l'OCR che l'ha letto (colonna `ocr`);
- il testo arriva a pezzi, e se un tratto di 80 caratteri si ripete 4 volte la lettura si ferma (`ocr.loop_start`): alcuni OCR, davanti a pagine di soli disegni, ripetono la stessa riga all'infinito;
- coordinate e segnali di impaginazione (Unlimited OCR, DeepSeek-OCR) vengono tolti (`ocr.clean_text`);
- se l'OCR è spento o occupato, il documento aspetta e l'app riprova ogni minuto.
Il testo viene poi normalizzato: le righe più lunghe di 240 caratteri sono spezzate tra una
parola e l'altra, le righe vuote consecutive diventano una sola, le vuote in fondo spariscono.
Righe corte servono a citare intervalli stretti.

Il risultato è salvato in `.indice/text/<percorso>.txt`, una riga per riga. **Tutto il resto
del sistema ragiona su questo file**: l'agente lo legge nel formato `N| testo`, le citazioni
indicano i suoi numeri di riga, la verifica rilegge quelle righe.

Esempio reale (`contratti/contratto_fornitura_acme.md`, righe 18-21 come le vede il modello):

```
18| ## Art. 9 · Penali
19| In caso di ritardo nella consegna è prevista una penale del 2% del valore
20| dell'ordine per ogni settimana completa di ritardo, fino a un massimo del 10%.
21| Oltre le cinque settimane di ritardo il Cliente può risolvere il contratto.
```

## 2.3 Indice di ricerca

Appena estratto, e prima che il modello lo legga, il testo entra nell'indice di ricerca
(SQLite FTS5, dentro `.indice/state.db`). Da questo momento il documento si può già cercare e
leggere, anche se la scheda non c'è ancora.

- Il testo è indicizzato a blocchi di 30 righe che si sovrappongono di 5, così ogni risultato
  porta con sé le righe in cui si trova.
- Anche la scheda, quando arriva, viene indicizzata (come un blocco unico).
- Gli accenti non contano (`perche` trova `perché`).

Come viene trasformata una ricerca: si tolgono le parole vuote (articoli, preposizioni, "cosa",
"quale"…) e quelle sotto le tre lettere che non sono numeri; alle parole di almeno cinque
lettere si toglie l'ultima e si cerca per prefisso, così `penale` trova anche `penali`; i
termini sono in alternativa (basta uno), e l'ordine dei risultati premia i blocchi che ne
contengono di più e di più rari (BM25). Al massimo 50 risultati.

È una ricerca per parole, non per significato: "recesso" non trova "disdetta". A questo
rimedia l'agente, che prova sinonimi e scende dalle mappe.

## 2.4 La scheda

Il modello dei riassunti (`llm.summary_model`) riceve il documento con le righe numerate e
scrive la scheda, nella lingua del documento, con questa struttura fissa:

- titolo descrittivo, tipo, data o periodo;
- **Sintesi**: da 3 a 6 frasi;
- **Punti chiave**: i contenuti specifici, ciascuno con le sue righe;
- **Entità e riferimenti**: persone, aziende, codici, concetti e altri documenti citati, con il
  nome esatto usato nel testo (compresi i link `[[nota]]`): servono a saltare ai documenti
  collegati;
- **Domande a cui risponde**: da 3 a 6.

La scheda deve permettere all'agente di capire, senza aprire il documento, se è rilevante e a
quali righe guardare. Un pezzo della scheda reale del contratto di sopra, scritta da Qwen:

```
- Penale per ritardo nella consegna: 2% del valore dell'ordine per ogni settimana completa
  di ritardo, fino al massimo del 10% `(righe 19-20)`.
- Documento di riferimento per la riservatezza: "NDA Acme" nella cartella legale `(riga 25)`.
```

La scheda è salvata in `.indice/summaries/<percorso>.md`. Il titolo del documento mostrato
nell'app è la prima intestazione della scheda.

**Controllo prima di salvare.** Quando il modello ha finito, l'app ricontrolla l'impronta del
file. Se nel frattempo è stato modificato o cancellato, la scheda descrive un testo che non
esiste più: viene scartata e il documento riparte.

## 2.5 Documenti lunghi

Un documento sta in una sola richiesta se il suo testo non supera il limite
`index.chunk_chars` (24.000 caratteri). Se la finestra del modello è nota
(`llm.context_tokens`), il limite si abbassa a due caratteri per token di finestra, e non
scende mai sotto 2.000.

Oltre il limite:

1. il documento è diviso in parti consecutive, a righe intere;
2. il modello prende **appunti** su ogni parte, tutte insieme in parallelo; ogni parte arriva
   con i numeri di riga originali, quindi gli appunti citano le righe giuste;
3. se gli appunti messi insieme superano ancora il limite, vengono condensati a gruppi di 4,
   finché ci stanno;
4. dagli appunti il modello scrive la scheda.

Se il modello rifiuta comunque la richiesta perché troppo lunga, il limite si dimezza e si
riprova, fino a 2.000 caratteri. Così un modello con poco contesto legge a pezzi più piccoli
senza che tu debba impostare nulla.

## 2.6 L'albero dei riassunti

L'albero si costruisce cartella per cartella, partendo dalle più interne.

**Dentro una cartella.** Ogni documento ha un numero d'ordine: l'ordine di arrivo in quella
cartella (0, 1, 2…). I documenti pronti si raggruppano per posizione: numero d'ordine diviso
`index.fanout` (8).

- Se gli elementi sono 8 o meno: nessuna sintesi di gruppo, si passa direttamente alla mappa.
- Se sono di più: i documenti 0-7 formano il gruppo `L1-0000`, gli 8-15 il gruppo `L1-0001`, e
  così via. Per ogni gruppo il modello scrive una sintesi (circa 350 parole al massimo: un
  paragrafo sul gruppo, una voce per elemento con il suo identificativo esatto, i temi che li
  attraversano).
- Se le sintesi di livello 1 sono a loro volta più di 8, si raggruppano allo stesso modo in
  sintesi di livello 2 (`L2-0000`…), e così via finché restano al massimo 8 elementi.
- Un gruppo con un solo elemento non riceve una sintesi: l'elemento sale così com'è.

**La mappa.** Gli elementi rimasti in cima, più le mappe delle sottocartelle, vengono
riassunti nella mappa della cartella: che cosa contiene, una voce per elemento con "quando
conviene aprirlo", entità e periodi ricorrenti.

Quanti livelli servono:

| Documenti in una cartella | Sintesi | Che cosa riassume la mappa |
|---|---|---|
| fino a 8 | nessuna | le schede |
| da 9 a 64 | fino a 8 di livello 1 | le sintesi di livello 1 |
| da 65 a 512 | livello 1 e livello 2 | le sintesi di livello 2 |
| da 513 a 4096 | tre livelli | le sintesi di livello 3 |

Gli identificativi hanno la forma `cartella::L1-0002` e `cartella::map` (per la radice:
`::map`). I file stanno in `.indice/tree/<cartella>/L1-0002.md` e `_map.md`.

## 2.7 Perché un documento nuovo costa poco

Ogni nodo (sintesi o mappa) ricorda un'impronta dei figli da cui è stato scritto: per ciascuno
tipo, identificativo e impronta del contenuto. Quando l'albero viene aggiornato, un nodo si
riscrive solo se quell'impronta è cambiata.

Poiché i gruppi sono per posizione, un documento nuovo prende l'ultimo numero d'ordine e cade
nell'ultimo gruppo. Si riscrivono quindi: un nodo per livello nella sua cartella, la mappa
della cartella, e le mappe delle cartelle sopra fino alla radice. Tutti gli altri nodi restano
com'erano. Un documento cancellato lascia un buco nella numerazione, e gli altri non si
spostano.

Provato con 5.000 documenti (modello finto): una seconda passata senza novità dura 1,4
secondi e non fa nessuna chiamata al modello.

**Quando si aggiorna.** L'albero aspetta che la coda delle schede sia vuota: con un modello
lento le schede arrivano una alla volta, e rifare le mappe a ogni scheda raddoppierebbe il
lavoro. Durante un caricamento molto grande si aggiorna comunque ogni 10 minuti.

## 2.8 Che cosa gira in parallelo

`index.concurrency` (8; 2 quando l'app collega da sola un modello locale) limita due cose:
quanti documenti sono in lettura insieme e quante richieste al modello sono aperte insieme.
Dentro questo limite partono in parallelo le schede di documenti diversi, gli appunti sulle
parti di un documento lungo, le sottocartelle e i nodi dello stesso livello dell'albero.

Un server locale che elabora una richiesta alla volta (come Strata) mette comunque in fila le
richieste: il parallelismo rende soprattutto con i servizi online.

## 2.9 Avanzamento, tempo e modello

In basso a sinistra, per ogni documento in lettura: nome, percentuale e tempo trascorso,
poi il modello che legge (`llm.summary_model`) e quanti documenti aspettano in coda. Finito un
documento resta scritto quanto ci ha messo.

La percentuale è **indicativa**: passi fatti su passi previsti. I passi sono l'estrazione del
testo più le chiamate al modello. Per un documento lungo si conoscono solo dopo averlo diviso
in parti, e le condensazioni si aggiungono quando servono: la percentuale può fermarsi o
tornare un po' indietro, e non arriva a 100 prima della fine.

Ogni documento letto ricorda **modello, durata e data** (colonne `model`, `seconds`,
`read_at` di `state.db`). La scheda in Documenti li mostra: "Scheda scritta da … in …". I
documenti letti prima della 0.5 dicono "modello non registrato".

**Ferma la lettura** (solo dal computer dell'app) interrompe le schede in corso e
l'aggiornamento dell'albero. I documenti tornano in coda, senza perdere niente: si riparte da
capo quando si preme Riprendi. La pausa dura finché l'app resta aperta, e al riavvio la
lettura riprende da sola.

Gli spazi creati da versioni precedenti si aprono normalmente: le colonne nuove si
aggiungono all'apertura.

## 2.10 Quante chiamate al modello

- Documento che sta in una richiesta: **1** chiamata.
- Documento lungo in *n* parti: *n* per gli appunti, eventuali chiamate per condensarli, **1**
  per la scheda.
- Albero: **1** per ogni sintesi o mappa da riscrivere.

Esempio: i 10 documenti di `examples/docs` stanno in 6 cartelle più la radice, nessuna con più
di 8 documenti. Prima lettura: 10 schede + 7 mappe = 17 chiamate. Con Qwen su Strata una
scheda richiede circa 45 secondi.

## 2.11 Quando qualcosa va storto

| Caso | Che cosa fa l'app |
|---|---|
| Il modello è spento, sovraccarico o limita le richieste | Il documento torna in coda, non in errore. L'app aspetta 60 secondi e riprova da sola; in basso a sinistra spiega perché è ferma. Lo stesso vale per l'albero. |
| Il documento non si può leggere (PDF scansionato, file corrotto) o il modello rifiuta la richiesta | Stato "non letto" con il motivo. |
| L'app viene chiusa a metà | Al riavvio ciò che era in lettura torna in coda. |
| Un documento è in errore | Al riavvio viene ritentato, fino a 3 tentativi. "Riprova a leggerli" azzera il conto. Modificare il file lo rimette in coda. |
| La sorveglianza incontra un file illeggibile | L'errore viene annotato e la sorveglianza continua. |

I file dell'indice sono scritti in modo atomico (prima un file temporaneo, poi la
sostituzione): uno spegnimento improvviso non lascia una scheda scritta a metà.
