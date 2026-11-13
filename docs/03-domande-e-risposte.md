# 3. Domande e risposte

[← Indice](README.md) · codice: `agent.py`, `tools.py`, `prompts.py`

## 3.1 Chi risponde

Risponde un **agente**: il modello linguistico (`llm.agent_model`) messo in un ciclo in cui, a
ogni passo, decide quali strumenti chiamare, riceve i risultati e decide il passo successivo.
Non riceve i documenti in anticipo: all'inizio ha solo la domanda e le regole. Tutto ciò che
sa dei tuoi documenti lo ottiene chiedendolo con gli strumenti.

Questo sostituisce il grafo precompilato. Se un contratto rimanda a un allegato, nessuno ha
scritto in anticipo "contratto → allegato": l'agente legge il rimando nella scheda o nel testo
e va a cercare l'allegato in quel momento.

## 3.2 Gli strumenti

Sono gli stessi per l'agente interno, per l'interfaccia e per i modelli collegati via MCP.

| Strumento | Che cosa restituisce |
|---|---|
| `list_folder(path)` | La mappa della cartella, le sottocartelle, gli identificativi delle sintesi di gruppo, i documenti pronti con titolo e numero di righe (al massimo 60: per gli altri rimanda a sintesi e ricerca). Dice anche quanti documenti non hanno ancora la scheda. |
| `read_node(node_id)` | Il testo di una sintesi di gruppo e l'elenco degli elementi che riassume. |
| `read_summary(doc)` | La scheda di un documento. |
| `read_document(doc, start_line, end_line)` | Le righe originali numerate, al massimo 400 per chiamata. È la fonte da cui citare. |
| `search(query, folder, limit)` | Ricerca per parole nel testo e nelle schede: documento, righe, estratto. Funziona anche sui documenti senza scheda. |
| `find_documents(name)` | Documenti il cui nome o titolo contiene, o somiglia a, quello cercato. Serve a seguire un rimando ("Allegato B", "NDA Acme"). |
| `delegate(tasks)` | Lancia esploratori in parallelo (vedi 3.5). |
| `answer(answer, citations)` | Consegna la risposta. È l'unico modo di concludere. |

Gli strumenti perdonano gli errori del modello: un percorso scritto con maiuscole diverse o
senza la cartella viene ricondotto al documento giusto se il candidato è uno solo; altrimenti
l'errore torna al modello con i nomi più simili ("Forse: …"), e il modello si corregge al
passo dopo. Un risultato più lungo di 60.000 caratteri viene troncato con l'invito a
restringere la richiesta.

## 3.3 Le regole che l'agente riceve

Stanno nel prompt di sistema (`prompts.AGENT`). In sintesi:

1. Parti dalla mappa della radice e scendi: mappa, sintesi, scheda, testo originale. Usa la
   ricerca per i termini precisi.
2. Mappe, sintesi e schede servono a orientarsi. **I fatti vanno letti nel testo originale**
   prima di citarli.
3. Quando un documento rimanda ad altro (allegati, contratti quadro, persone, codici, link
   `[[nota]]`), segui il rimando.
4. Rispondi con ciò che è scritto nei documenti, non con conoscenze generali. Se serve
   qualcosa che nei documenti non c'è, dillo e tienilo separato.
5. Chiama più strumenti nello stesso passo quando le letture sono indipendenti.
6. Concludi con `answer`. Ogni affermazione di fatto porta un marcatore `[n]`; per ogni `n`
   c'è una citazione con documento, **intervallo di righe stretto** e l'affermazione riscritta
   in modo che si capisca da sola.
7. Un confronto tra due documenti si cita con due citazioni, una per documento.
8. Se i documenti non contengono la risposta, dillo. Se affermi che un documento *non*
   contiene qualcosa, cita l'intero documento o l'intera sezione letta.

L'agente sa che ogni citazione sarà verificata confrontando l'affermazione con quelle righe, e
che un intervallo sbagliato o troppo largo la fa fallire.

## 3.4 Il ciclo, passo per passo

1. L'app apre una conversazione con il modello: regole, descrizione degli strumenti, domanda.
   Se hai scelto una cartella di partenza, viene aggiunta alla domanda.
2. Il modello risponde con una o più chiamate a strumenti. L'app le esegue **tutte insieme**
   e gli restituisce i risultati. Questo è un passo.
3. Si ripete finché il modello chiama `answer`.

Tre casi particolari:

- **Il modello scrive testo senza chiamare strumenti.** L'app gli ricorda di consegnare con
  `answer`. Se nemmeno allora lo fa, si passa al ripiego (3.7).
- **Limite di passi.** Dopo 24 passi (`agent.max_steps`) l'app chiede di consegnare subito con
  ciò che è stato letto. Se il modello non consegna, ripiego.
- **Errore di uno strumento.** Non interrompe nulla: il messaggio d'errore è il risultato di
  quella chiamata.

Consegnata la risposta, parte la verifica delle citazioni ([pagina 4](04-verifica-delle-citazioni.md)).

## 3.5 Esploratori

Per le domande ampie l'agente ha `delegate`: indica fino a 8 sotto-domande, ciascuna con una
cartella di partenza. Per ognuna l'app avvia un esploratore, cioè un altro agente con gli
stessi strumenti di lettura, che:

- risponde solo alla sua sotto-domanda;
- ha al massimo 12 passi (`agent.explorer_steps`);
- non può lanciare altri esploratori;
- non fa verificare le sue citazioni: le restituisce all'agente principale, che le riusa nella
  risposta finale, dove vengono verificate.

Ne lavorano insieme al massimo 4 (`agent.explorers`). Un esploratore che fallisce restituisce
il suo errore e non fa cadere gli altri.

## 3.6 Domande di approfondimento

Con "spiegami meglio il secondo punto" l'interfaccia manda anche gli ultimi scambi. L'agente
riceve gli ultimi 3 (domanda fino a 600 caratteri, risposta fino a 1.800) con un'avvertenza:
servono solo a capire a che cosa si riferisce la nuova domanda; i fatti vanno comunque riletti
e citati dai documenti.

## 3.7 Se il modello non sa usare gli strumenti

Ci sono tre livelli, scelti da soli ([pagina 5](05-modelli.md) spiega i primi due):

1. chiamate a strumenti native del modello;
2. strumenti descritti a parole, con le chiamate lette da un oggetto JSON nel testo;
3. **ricerca diretta**: l'app cerca la domanda, prende i 5 passaggi di testo più pertinenti, li
   dà al modello e chiede una risposta fondata solo su quelli, con le citazioni.

Il terzo livello non naviga e non segue rimandi, quindi è meno completo; ma funziona con
qualunque modello che sappia leggere e scrivere, e le citazioni vengono verificate allo stesso
modo. La risposta porta il campo `mode` = "ricerca diretta" invece di "agente".

## 3.8 Che cosa vedi mentre lavora

L'interfaccia usa `/api/ask/stream`: una riga per evento.

| Evento | Che cosa mostra l'interfaccia |
|---|---|
| `step` | "apro la cartella contratti", "leggo la scheda di …", "leggo …, righe 18–21", "cerco «penali ritardo»", "mi faccio aiutare da 3 aiutanti in parallelo" |
| `verifying` | il controllo delle citazioni è iniziato |
| `answer` | la risposta completa |
| `error` | il motivo per cui la domanda non è riuscita |
| `ping` | nulla: tiene viva la connessione ogni 15 secondi di silenzio |

**Ferma** chiude la connessione, e chiudere la connessione annulla il lavoro: il modello
smette di essere interrogato.

## 3.9 Che cosa contiene una risposta

| Campo | Contenuto |
|---|---|
| `answer` | Il testo con i marcatori `[1]`, `[2]`… |
| `citations` | Per ogni marcatore: documento, righe, affermazione, esito, confidenza, metodo, nota, righe citate |
| `warnings` | Quante citazioni non sono confermate |
| `steps`, `trace` | Quanti passi e quali strumenti sono stati chiamati |
| `complete` | Falso se l'agente non ha consegnato con `answer` e nemmeno il ripiego ha prodotto una risposta |
| `verified` | Vero se le citazioni sono passate dalla verifica |
| `mode` | "agente" oppure "ricerca diretta" |
| `markdown` | La risposta pronta da leggere, con ✓ e ⚠ accanto ai marcatori e l'elenco delle fonti |

Un marcatore `[n]` nel testo a cui non corrisponde nessuna citazione viene mostrato come
`[n ⚠]`.

Ogni scambio fatto dall'interfaccia viene salvato nella cronologia dello spazio, separata per
persona; "Nuova conversazione" svuota la propria. Le domande arrivate via MCP o dalla riga di
comando non vengono salvate.

## 3.10 Un esempio dall'inizio alla fine

Domanda sui documenti di esempio: *"Ci sono penali per ritardo nel contratto di fornitura con
Acme? Quanto valgono?"*

Il percorso tipico dell'agente (l'ordine esatto cambia da una volta all'altra, perché lo
decide il modello):

| Passo | Chiamata | Che cosa ne ricava |
|---|---|---|
| 1 | `list_folder("")` | La mappa della radice: esiste una cartella `contratti` che parla di forniture e penali. |
| 2 | `list_folder("contratti")` | La mappa della cartella. Una voce dice: "`contratti/contratto_fornitura_acme.md`: … penali fino al 10%, recesso oltre cinque settimane…". |
| 3 | `read_summary("contratti/contratto_fornitura_acme.md")` | La scheda: "Penale per ritardo nella consegna: 2% … `(righe 19-20)`". |
| 4 | `read_document("contratti/contratto_fornitura_acme.md", 18, 21)` | Le righe originali dell'Art. 9. |
| 5 | `answer(...)` | La risposta con due citazioni. |

Le due citazioni consegnate hanno questa forma:

```
[1] contratti/contratto_fornitura_acme.md, righe 19-20
    affermazione: "Il contratto di fornitura con Acme prevede una penale del 2% del valore
                   dell'ordine per ogni settimana completa di ritardo, fino a un massimo del 10%."
[2] contratti/contratto_fornitura_acme.md, riga 21
    affermazione: "Oltre le cinque settimane di ritardo il Cliente può risolvere il contratto."
```

Poi la verifica: per ciascuna, il decision model confronta l'affermazione con le righe citate.
Nell'ultima prova registrata (Qwen su Strata, costretto alla modalità testuale) questa domanda
ha avuto risposta corretta, 2 citazioni, entrambe confermate dal decision model al primo
controllo, in 145 secondi.

Un secondo esempio mostra i rimandi. Alla domanda *"Il contratto con Acme richiama un accordo
di riservatezza: quando è stato firmato e quanto durano i suoi obblighi?"* l'agente legge
nella riga 25 del contratto *vedi documento "NDA Acme" nella cartella legale*, chiama
`find_documents("NDA Acme")`, apre `legale/nda_acme.md` e cita da lì. Nella stessa prova: 3
citazioni confermate (alcune dal decision model, altre dal sì/no del modello), 204 secondi.
