# Come funziona LLMWiki

Questa cartella spiega il funzionamento di LLMWiki passaggio per passaggio: che cosa succede a
un documento da quando lo aggiungi a quando è pronto, che cosa succede a una domanda da quando
la scrivi a quando la risposta compare con le citazioni controllate, e che cosa c'è attorno
(modelli, accessi, app, file su disco).

Ogni numero e ogni nome citato qui viene dal codice della versione 0.4.1. Dove una cosa non è
stata provata, c'è scritto.

Sono appunti in markdown: puoi anche copiare questa cartella dentro uno spazio di LLMWiki e
farle domande.

## Il giro completo in una pagina

**Un documento** entra nella cartella `documenti` dello spazio e percorre questa strada:

```
 documenti/contratto.pdf
        │  1. estrazione: il testo diventa righe numerate
        ▼
 .indice/text/contratto.pdf.txt ──► 2. indice di ricerca per parole (da qui è già cercabile)
        │  3. il modello legge il testo e scrive la scheda
        ▼
 .indice/summaries/contratto.pdf.md          (scheda: sintesi, punti chiave con le righe, rimandi)
        │  4. le schede di una cartella si riassumono a gruppi di 8
        ▼
 .indice/tree/<cartella>/L1-0000.md          (sintesi di gruppo, solo se i documenti sono più di 8)
        │  5. tutto ciò che sta in una cartella si riassume nella sua mappa
        ▼
 .indice/tree/<cartella>/_map.md ──► mappa della cartella madre ──► ... ──► mappa della radice
```

I passaggi 1-3 riguardano un documento solo, quindi più documenti avanzano insieme e se ne
possono aggiungere altri a lavoro in corso. I passaggi 4-5 rifanno soltanto i nodi che hanno
un figlio cambiato.

**Una domanda** percorre quest'altra:

```
 domanda
    │
    ▼
 agente ◄──► strumenti: apri cartella · leggi sintesi · leggi scheda · leggi righe · cerca · trova documento
    │        (scende dalla mappa al testo originale; segue i rimandi tra documenti; può lanciare
    │         esploratori in parallelo)
    ▼
 risposta con marcatori [1] [2] + per ognuno: documento, righe, affermazione
    │
    ▼  per ogni citazione, in parallelo
 decision model ──sotto soglia──► sì/no del modello ──sotto soglia──► ricontrollo con contesto
    │ sopra soglia                    │ sopra soglia                      │ confermata    │ no
    ▼                                 ▼                                   ▼               ▼
    ✓                                 ✓                                   ✓               ⚠
```

Non esiste un grafo dei collegamenti scritto in anticipo: i collegamenti li percorre l'agente
mentre risponde. Per questo aggiungere documenti non costringe a ricalcolare nulla oltre al
ramo in cui cadono.

## Le pagine

| Pagina | Che cosa spiega |
|---|---|
| [1. L'idea e le parole](01-idea-e-parole.md) | I quattro problemi di partenza, le quattro risposte, il vocabolario usato nel resto |
| [2. Lettura dei documenti](02-lettura-dei-documenti.md) | Sorveglianza della cartella, estrazione, ricerca, schede, albero dei riassunti, aggiornamenti |
| [3. Domande e risposte](03-domande-e-risposte.md) | L'agente, i suoi strumenti, gli esploratori, i limiti, un esempio seguito dall'inizio alla fine |
| [4. Verifica delle citazioni](04-verifica-delle-citazioni.md) | Decision model, giudice, ricontrollo, che cosa significano ✓ e ⚠ |
| [5. Modelli](05-modelli.md) | Come l'app parla con qualunque modello e che cosa fa quando a un modello manca una capacità |
| [6. Server, accessi e MCP](06-server-accessi-mcp.md) | Le rotte, chi può fare cosa, la condivisione in rete, il collegamento di altri modelli |
| [7. App, spazi e file](07-app-spazi-file.md) | Avvio dell'app, primo avvio, finestra, spazi, dove sta ogni file |
| [8. Impostazioni](08-impostazioni.md) | Tutte le voci di `wiki.toml`, con il valore predefinito e l'effetto |
| [9. Per chi sviluppa](09-sviluppo.md) | Mappa del codice, test, banco di prova, costruzione dell'installer |
| [10. Limiti noti](10-limiti-noti.md) | Che cosa l'app non fa o non garantisce oggi |
| [11. Quale modello locale usare](11-scelta-del-modello.md) | Il ragionamento per scegliere il modello su un dato PC, con i conti da rifare quando cambia l'hardware |
