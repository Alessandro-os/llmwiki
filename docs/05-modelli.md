# 5. Modelli

[← Indice](README.md) · codice: `llm.py`, `app.py`

## 5.1 Tre ruoli

L'app usa il modello linguistico in tre ruoli. Possono essere lo stesso modello o tre diversi.

| Ruolo | Impostazione | Che cosa fa | Quanto pesa |
|---|---|---|---|
| Risposte | `llm.agent_model` | Naviga, risponde, fa il ricontrollo delle citazioni | Poche chiamate lunghe per domanda |
| Riassunti | `llm.summary_model` | Schede, sintesi di gruppo, mappe | Il grosso del lavoro quando si aggiungono documenti |
| Giudice | `llm.judge_model` | Il sì/no sulle citazioni dubbie | Chiamate brevi |

Nell'interfaccia scegli un modello solo; gli altri due campi stanno in "Opzioni avanzate" e,
lasciati vuoti, usano lo stesso. Un modello più piccolo per i riassunti rende più veloce la
lettura dei documenti.

Il decision model della verifica non è uno di questi: è un programma a parte, sempre locale
([pagina 4](04-verifica-delle-citazioni.md)).

## 5.2 Un'interfaccia, tre implementazioni

Tutto il resto del codice parla con un'unica interfaccia, `LLM`, che offre cinque operazioni:

| Operazione | A che cosa serve |
|---|---|
| `complete` | Testo in, testo fuori (schede, sintesi, mappe) |
| `complete_json` | Testo in, oggetto con una struttura data fuori (ricontrollo, ricerca diretta) |
| `judge` | Probabilità che un passaggio sostenga un'affermazione |
| `conversation` | Dialogo a più passi con strumenti (l'agente) |
| `list_models`, `probe` | Elenco dei modelli del fornitore; prova di che cosa sa fare un modello |

Le implementazioni sono tre:

- **`AnthropicLLM`**: Claude, con la libreria ufficiale di Anthropic.
- **`OpenAICompatLLM`**: qualunque server che parli il protocollo `/chat/completions` di
  OpenAI. Sono quasi tutti: OpenAI, Gemini, OpenRouter, Mistral, Groq, e in locale Strata,
  llama.cpp, Ollama, LM Studio, vLLM.
- **`MockLLM`**: nessun modello. Le "schede" sono le prime righe del documento e il giudizio è
  una sovrapposizione di parole. Serve alla prova dimostrativa e ai test.

Cambiare modello significa cambiare impostazioni: indice, agente e verifica non lo sanno.

## 5.3 I fornitori nell'interfaccia

Il menu "Quale modello usare" propone:

| Voce | Indirizzo | Chiave salvata come |
|---|---|---|
| Un modello sul mio computer | lo scrivi tu, o lo trova l'app | nessuna |
| Claude (Anthropic) | gestito dalla libreria | `ANTHROPIC_API_KEY` |
| OpenAI | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | `GEMINI_API_KEY` |
| OpenRouter | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |
| Mistral | `https://api.mistral.ai/v1` | `MISTRAL_API_KEY` |
| Groq | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` |
| Un altro servizio compatibile OpenAI | lo scrivi tu | `LLM_API_KEY` |
| Nessuno: prova dimostrativa | | |

Aggiungere un fornitore compatibile è una riga nella tabella `PROVIDERS` di `app.py`.

**Chiavi.** La chiave incollata nell'interfaccia viene salvata in
`%LOCALAPPDATA%\LLMWiki\secrets.json`, fuori dagli spazi (che possono finire in cartelle
condivise), e non torna mai all'interfaccia: questa sa solo se una chiave c'è. Una variabile
d'ambiente con lo stesso nome, se già impostata, ha la precedenza.

**Modelli locali trovati da soli.** L'app prova quattro porte sul computer: 8080 (Strata,
llama.cpp), 11434 (Ollama), 1234 (LM Studio), 8000 (vLLM). Se una risponde con un elenco di
modelli, propone il primo. Lo fa al primo avvio e con "Cerca i modelli accesi su questo
computer".

**"Mostra i modelli disponibili"** chiede l'elenco al fornitore. Se scegli il modello da
questo elenco e il server ne dichiara la finestra di contesto, l'app la registra in
`llm.context_tokens` e la usa per non mandare più testo di quanto il modello ne legga. Se la
finestra non è nota il valore resta 0 e nessun limite viene applicato in anticipo: resta il
dimezzamento automatico quando il modello rifiuta una richiesta troppo lunga.

## 5.4 Che cosa succede quando a un modello manca qualcosa

Ogni capacità che non tutti i modelli hanno ha un ripiego, scelto dall'app.

### Strumenti

Impostazione `llm.tool_mode`: `auto` (predefinito), `native`, `text`.

1. **Native.** Gli strumenti sono dichiarati al server nel formato del fornitore e il modello
   risponde con chiamate strutturate.
2. **Testuale.** Gli strumenti sono descritti nel prompt, con nome, descrizione e argomenti, e
   al modello si chiede di rispondere solo con un oggetto di questa forma:

   ```
   {"calls": [{"tool": "search", "args": {"query": "penali ritardo"}}]}
   ```

   L'app legge l'oggetto anche se attorno c'è altro testo o un blocco di ragionamento, esegue
   le chiamate e riporta i risultati come testo nel turno successivo. Se il modello risponde
   con testo libero, al turno dopo gli viene ricordato il formato.
3. **Ricerca diretta.** Se nemmeno così il modello consegna una risposta, l'app cerca al posto
   suo ([pagina 3](03-domande-e-risposte.md), 3.7).

In `auto` l'app parte dalle chiamate native. Se al primo turno il server le rifiuta, oppure il
modello non ne fa nessuna, ricomincia la conversazione in modalità testuale. Se è stato il
server a rifiutarle, l'app se lo ricorda e per le domande successive parte direttamente dal
testo.

### Uscita strutturata

Prima prova lo schema imposto dal server (`response_format` per i compatibili OpenAI,
`output_config.format` per Claude). Se il server lo rifiuta o il modello non lo rispetta, lo
schema viene scritto nel prompt e la risposta è letta con tolleranza: si toglie il
ragionamento, si prende il primo oggetto JSON nel testo, e in caso di fallimento si riprova
una volta.

### Probabilità per il giudice

Logprob se il server li espone, altrimenti punteggio dichiarato dal modello
([pagina 4](04-verifica-delle-citazioni.md), passo 2).

### Parametri facoltativi di Claude

Con Claude l'app manda tre parametri in più: il livello di impegno (`effort`), la cache del
prefisso della conversazione, e il rilancio lato server dei rifiuti dei classificatori (solo
su alcuni modelli, disattivabile con `llm.refusal_fallbacks`). Se un modello ne rifiuta uno,
l'app lo toglie, riprova la stessa richiesta e per quel modello non lo manda più.

### Finestra di contesto piccola

Quando `llm.context_tokens` è noto:

- i documenti vengono letti a pezzi più corti ([pagina 2](02-lettura-dei-documenti.md), 2.5);
- un singolo risultato di strumento viene troncato prima;
- se la conversazione dell'agente cresce oltre circa 3 caratteri per token di finestra, i
  risultati più vecchi vengono sostituiti con "[risultato già letto, omesso per fare spazio]",
  dal più vecchio, lasciando intatti gli ultimi. Vale per i compatibili OpenAI e per la
  modalità testuale; con Claude la conversazione non viene accorciata.

## 5.5 Errori: rifiutato o non disponibile

L'app distingue due tipi di errore, perché richiedono reazioni opposte.

| Tipo | Quando | Reazione |
|---|---|---|
| **Rifiutato** | Il server ha risposto con un errore 4xx (tranne 408, 409, 429): parametro non supportato, chiave errata, testo troppo lungo | Non serve riprovare uguale. Si prova il ripiego (senza quel parametro, in modalità testuale, a pezzi più corti) oppure si segnala. |
| **Non disponibile** | Nessuna risposta, errori 5xx, 408, 409, 429: server spento, sovraccarico, limite di richieste | Riprovare ha senso. Subito, fino a 4 tentativi con attese crescenti; poi i documenti restano in coda e l'app riprova ogni minuto. |

Ogni richiesta ha un tempo massimo di 600 secondi (`llm.timeout`).

## 5.6 Quanto ragiona il modello

I tre ruoli hanno un livello di impegno: `agent_effort` (high), `summary_effort` (medium),
`judge_effort` (low).

- Con **Claude** il livello viene sempre mandato.
- Con i **compatibili OpenAI** viene mandato come `reasoning_effort` solo se
  `llm.send_reasoning_effort` è attivo, perché non tutti i server lo accettano.

Nell'interfaccia è l'opzione "Quanto ragiona prima di rispondere". Scegliendo "Poco" si
attiva l'invio e si mettono a `low` risposte e riassunti. Con Qwen su Strata, sulle 9 domande
di prova: sempre 9 risposte corrette, tempo medio da 111 a 68 secondi, citazioni da 41 a 18
(risposte più asciutte).

## 5.7 "Salva e prova"

Dopo aver salvato, l'app fa tre prove vere sul modello scelto e ne riferisce l'esito:

1. Gli chiede di scrivere una parola. → "Il modello risponde", oppure l'errore.
2. Gli dà uno strumento che somma due numeri e gli chiede quanto fa 2 più 3, prima con le
   chiamate native e poi in modalità testuale. → "Sa cercare da solo nei documenti", "…in
   modalità compatibile", oppure "l'app cercherà al posto suo".
3. Gli fa giudicare una citazione ovvia e guarda se arrivano i logprob. → "Può anche
   controllare le citazioni in modo rapido", oppure il consiglio di usare il verificatore.

## 5.8 Che cosa è stato provato

| Che cosa | Come |
|---|---|
| Qwen 3.8 Flash Next su Strata, chiamate native | Dal vivo: 9 su 9 sulla raccolta di esempio, 23 su 24 su quella difficile |
| Lo stesso modello costretto alla modalità testuale | Dal vivo: 9 su 9, 17 citazioni tutte confermate, 150 secondi di media |
| Server che rifiuta gli strumenti, modello che li ignora, JSON non rispettato, contesto piccolo, server che si spegne a metà | Con server finti, in `tests/test_independence.py` |
| Claude, OpenAI, Gemini, OpenRouter, Mistral, Groq | **Non provati dal vivo**: servono le rispettive chiavi |
