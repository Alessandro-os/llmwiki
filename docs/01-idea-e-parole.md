# 1. L'idea e le parole

[← Indice](README.md)

## Da dove parte

Una "LLM wiki" classica funziona così: un agente legge i documenti uno alla volta e scrive
pagine di wiki collegate tra loro in un grafo; poi si interroga la wiki. Ha quattro problemi,
e LLMWiki è costruita attorno alle quattro risposte.

| Problema | Risposta di LLMWiki | Dove è spiegata |
|---|---|---|
| **Lentezza.** Un agente indicizza un documento alla volta. | Ogni documento riceve la sua scheda in modo indipendente dagli altri, quindi molti documenti avanzano insieme e se ne possono aggiungere a lavoro in corso. | [Pagina 2](02-lettura-dei-documenti.md) |
| **Fonti non verificate.** La risposta cita un documento, ma nessuno controlla che il documento dica davvero quella cosa. | Ogni citazione è una terna (affermazione, documento, righe). Un modello piccolo e veloce decide se le righe sostengono l'affermazione; se non ne è sicuro si riprova in altro modo; se fallisce ancora compare ⚠. | [Pagina 4](04-verifica-delle-citazioni.md) |
| **Un utente alla volta.** Ognuno deve compilarsi la propria wiki. | Un solo computer compila la wiki. Gli altri si collegano dal browser o da un modello loro (MCP), ognuno con un token personale. | [Pagina 6](06-server-accessi-mcp.md) |
| **Il grafo esplode.** Oltre qualche centinaio di documenti tenere coerente il grafo diventa impossibile. | Niente grafo precompilato. Sopra i documenti c'è un albero di riassunti (riassunti di riassunti); i collegamenti si seguono al momento della domanda. | [Pagine 2](02-lettura-dei-documenti.md) e [3](03-domande-e-risposte.md) |

## I due usi

La stessa app serve a due cose, e non c'è una modalità da scegliere: cambia solo che cosa metti
nello spazio.

- **Studio personale.** Una cartella di appunti in markdown. Le risposte usano solo ciò che è
  scritto negli appunti: se una spiegazione richiede qualcosa che lì non c'è, l'agente deve
  dirlo e tenerlo separato dalle affermazioni citate. I link tra note `[[nome nota]]` vengono
  seguiti come rimandi.
- **Azienda.** Contratti, policy, verbali in uno spazio condiviso. I colleghi si collegano al
  computer che tiene la wiki; l'amministrazione resta su quel computer.

## Vocabolario

Le parole sono usate sempre con questo significato, qui e nell'app.

| Parola | Significato |
|---|---|
| **Spazio** | Una raccolta separata: una cartella con i suoi documenti, il suo indice e le sue impostazioni. Esempi: Personale, Studio, Azienda. |
| **Documento** | Un file dentro `documenti/` di uno spazio. È identificato dal percorso relativo, per esempio `contratti/contratto_fornitura_acme.md`. |
| **Riga** | L'unità con cui si cita. Il testo di ogni documento viene diviso in righe numerate da 1, lunghe al massimo 240 caratteri. |
| **Scheda** | Il riassunto di un documento scritto dal modello: sintesi, punti chiave con le righe, entità e rimandi, domande a cui risponde. |
| **Sintesi di gruppo** | Il riassunto di un gruppo di schede della stessa cartella (o di un gruppo di sintesi). Compare solo quando una cartella ha più di 8 elementi. |
| **Mappa** | Il riassunto di tutto ciò che una cartella contiene. È il primo testo che l'agente legge entrando in una cartella. |
| **Albero** | L'insieme di schede, sintesi e mappe: dalla mappa della radice si scende fino alle righe di un documento. |
| **Agente** | Il modello linguistico mentre risponde a una domanda: decide da solo che cosa aprire e che cosa cercare, un passo dopo l'altro. |
| **Strumento** | Un'azione che l'agente può chiedere all'app: aprire una cartella, leggere righe, cercare. |
| **Esploratore** | Un secondo agente lanciato dal primo su una sotto-domanda, in parallelo ad altri. |
| **Citazione** | Marcatore `[n]` nella risposta più: documento, riga iniziale, riga finale, affermazione. |
| **Affermazione** (`claim`) | La frase che la citazione sostiene, riscritta dall'agente in modo che si capisca da sola. È ciò che viene verificato. |
| **Decision model** (nell'app: *verificatore*) | Un piccolo modello che non scrive testo: riceve le righe citate e l'affermazione e restituisce la probabilità che le prime implichino la seconda. |
| **Soglia** | La probabilità minima per confermare una citazione. Predefinita: 0,6. |
| **Modello** | Il modello linguistico collegato all'app: locale (Strata, Ollama, LM Studio…) o un servizio online (Claude, OpenAI, Gemini…). |
| **Token** | Qui ha due sensi. *Token personale*: il codice che una persona usa per collegarsi dalla rete. *Token del modello*: l'unità in cui un modello misura il testo (3-4 caratteri). |
| **MCP** | Il protocollo con cui un modello esterno usa gli strumenti di LLMWiki. |
