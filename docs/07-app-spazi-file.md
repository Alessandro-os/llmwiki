# 7. App, spazi e file

[← Indice](README.md) · codice: `desktop.py`, `apphome.py`, `app.py`, `web/index.html`

## 7.1 Che cosa succede quando apri LLMWiki

`LLMWiki.exe` esegue questi passi, nell'ordine:

1. **Log.** Apre `%LOCALAPPDATA%\LLMWiki\logs\llmwiki.log` (al massimo 2 MB, con due copie
   precedenti).
2. **Chiavi.** Carica le chiavi salvate in `secrets.json`.
3. **Registro degli spazi.** Legge `app.json`: spazi conosciuti, spazio attivo, porta.
4. **È già aperta?** Chiede `/api/status` sulla porta salvata. Se risponde LLMWiki, porta in
   primo piano la finestra esistente e termina. Se non risponde ancora ma un'altra copia sta
   partendo in quel momento (per esempio l'installatore e un doppio clic insieme), lo capisce
   dal lucchetto sul file `llmwiki.lock`: aspetta che l'altra risponda, la porta in primo
   piano e termina. Non partono mai due copie.
5. **Primo avvio** (nessuno spazio): vedi 7.2.
6. **Apre lo spazio attivo.** Se la sua cartella è stata spostata o cancellata, apre il primo
   degli altri spazi che funziona e lo rende attivo. Se non se ne apre nessuno, mostra un
   messaggio con il motivo.
7. **Porta.** Usa quella salvata; se è occupata ne prende una libera e la salva.
8. **Indirizzo di ascolto.** Quello delle impostazioni, ma solo `127.0.0.1` se non esiste
   almeno una persona con un token.
9. **Server.** Lo avvia in un thread e aspetta fino a 40 secondi che risponda. Con il server
   partono la sorveglianza della cartella e l'aggiornamento dell'albero.
10. **Finestra.** Vedi 7.3.
11. **Icona vicino all'orologio**, con tre voci: Apri LLMWiki, Apri la cartella dei documenti,
    Esci.

Se uno di questi passi fallisce, compare una finestra con l'errore e il percorso del log:
un'app senza console non deve fallire in silenzio.

Chiudere la finestra non ferma l'app: resta l'icona e la lettura dei documenti continua. Si
chiude da "Esci" nell'icona o da Impostazioni → "Chiudi LLMWiki". Ciò che era in lettura
riprende al prossimo avvio.

Opzioni dell'eseguibile: `--port N`, `--no-window` (usata dall'avvio automatico con
Windows), `--no-tray`.

## 7.2 Primo avvio

1. L'app cerca un modello acceso sul computer (porte 8080, 11434, 1234, 8000).
2. Se lo trova, lo collega: stesso modello per risposte, riassunti e giudice, e due documenti
   in lettura alla volta. Se non lo trova, parte in modalità dimostrativa (risposte finte)
   finché non scegli un modello.
3. Crea lo spazio **Personale** in `Documenti\LLMWiki\Personale`.

La prima schermata mostra "Tre passi per cominciare", ognuno con il suo pulsante: collegare un
modello, scaricare il verificatore delle citazioni (1,1 GB, una volta sola), aggiungere
documenti. I passi fatti sono spuntati.

## 7.3 La finestra

La finestra è l'interfaccia web aperta in "modalità app" di un browser basato su Chromium:
una finestra propria, senza barra degli indirizzi.

1. Se una finestra LLMWiki esiste già, la riporta davanti.
2. Altrimenti prova, nell'ordine: il browser predefinito se è Edge, Chrome, Brave, Vivaldi o
   Chromium; poi Edge, Chrome e Brave nei percorsi consueti.
3. Dopo aver lanciato un browser **controlla che la finestra sia comparsa davvero** (cerca tra
   le finestre aperte, fino a 8 secondi). Se non c'è, prova il successivo.
4. Se nessuno ci riesce, apre una scheda normale nel browser predefinito.

Il controllo al punto 3 esiste perché su alcuni computer un browser parte e si chiude subito
senza aprire nulla.

L'icona della finestra, anche nella barra delle applicazioni, viene dalla pagina
(`/favicon.ico`, disegnata da `icon.py`): senza, Windows mostrerebbe quella del browser.

## 7.4 L'interfaccia

Tre sezioni nella barra laterale, il menu degli spazi in alto, lo stato della lettura in
basso (aggiornato ogni 3 secondi).

**Chiedi.** Campo della domanda, passi dell'agente mentre lavora, pulsante Ferma. Nella
risposta ogni citazione è un bottone con il suo segno (`1 ✓`, `2 ⚠`); cliccandolo si apre un
pannello con ciò che la risposta afferma, ciò che dice il documento e l'esito, più "Apri il
documento in questo punto". "Nuova conversazione" ricomincia da capo. Sotto il campo, a
destra, compare "È disponibile la versione … · Aggiorna" quando c'è una versione nuova (7.8).

**Documenti.** Area in cui trascinare i file (o sceglierli dal computer), con la cartella di
destinazione. Sotto, l'esplorazione dello spazio: cartelle, mappa, sintesi, scheda di ogni
documento, e il testo originale con le righe citate evidenziate.

**Impostazioni** (solo dal computer dell'app). Modello; Controllo delle citazioni; Spazi;
Usarla con altre persone; Lettura dei documenti (con l'elenco dei file non letti e il
motivo); Chiudere l'app. Le voci tecniche stanno sotto "Opzioni avanzate".

L'aspetto chiaro o scuro segue quello del sistema.

## 7.5 Spazi

Uno spazio è una cartella autonoma:

```
Documenti\LLMWiki\Personale\
├── wiki.toml          impostazioni dello spazio (modello, soglie, persone e token)
├── documenti\         i tuoi file: qui si aggiungono, si spostano, si cancellano
└── .indice\           tutto ciò che l'app costruisce
    ├── text\          testo estratto a righe numerate, un .txt per documento
    ├── summaries\     schede, un .md per documento
    ├── tree\          sintesi di gruppo (L1-0000.md…) e mappe (_map.md), per cartella
    └── state.db       stato dei documenti, nodi dell'albero, indice di ricerca, cronologia
```

- Puoi mettere i file in `documenti\` da Esplora file, senza passare dall'app: se ne accorge
  entro 20 secondi.
- Uno spazio si copia, si sposta o si salva in backup copiando la cartella.
- Cancellando `.indice\` ad app chiusa, al prossimo avvio l'app rilegge tutto da capo. I
  documenti non vengono toccati; la cronologia delle domande, che sta in `state.db`, si perde.
- Schede, sintesi e mappe sono file markdown leggibili con qualunque editor.
- Un nuovo spazio nasce con le stesse impostazioni di modello di quello attivo.
- Togliere uno spazio dall'app lo toglie dall'elenco; la cartella resta dov'è.
- L'app tiene aperto uno spazio alla volta: cambiando spazio, la lettura dei documenti
  dell'altro si ferma e riprende quando ci torni.

### Copia di sicurezza

In Impostazioni → Spazi, "Fai una copia di sicurezza" scrive un file zip in
`Documenti\LLMWiki\Copie di sicurezza\<spazio>-<data>.zip` (`backup.py`). Dentro ci sono i
documenti, l'indice (schede, mappe, stato: rifarli può costare ore di modello) e `wiki.toml`,
quindi anche i token degli utenti creati per la condivisione. Non ci sono le chiavi dei servizi
online, che stanno fuori dagli spazi. La copia si può fare mentre l'app legge.

Lo zip è già uno spazio completo. "Ripristina da una copia" lo estrae in una cartella nuova e
lo apre come spazio nuovo: non sovrascrive mai uno spazio esistente, e rifiuta uno zip che non
è una copia di LLMWiki o che contiene percorsi fuori dalla cartella.

## 7.6 Che cosa sta fuori dagli spazi

```
%LOCALAPPDATA%\LLMWiki\
├── app.json           elenco degli spazi, spazio attivo, porta
├── llmwiki.lock       tenuto dalla copia aperta, perché non ne parta una seconda
├── secrets.json       chiavi dei servizi online
├── models\mdeberta-v3-nli\   decision model (model.onnx, tokenizer.json)
├── aggiornamenti\     installatore della versione nuova, finché non è installata
├── ocr\              cartella consigliata per gli OCR che scarichi tu (docs/12): l'app ci cerca da sola
└── logs\llmwiki.log, logs\ocr.log   (ocr.log: i messaggi di llama-server quando l'app accende l'OCR)
```

Il decision model è uno solo per tutti gli spazi e resta caricato in memoria una volta sola
anche cambiando spazio.

**Installazione portatile.** Con la variabile d'ambiente `LLMWIKI_HOME` tutto questo, e anche
gli spazi nuovi (in una sottocartella `spazi`), finisce nella cartella indicata. I test la
usano per non toccare mai il profilo vero.

## 7.7 Installazione

L'installer (`LLMWiki-<versione>-setup.exe`) installa per l'utente corrente in
`%LOCALAPPDATA%\Programs\LLMWiki`, senza chiedere diritti di amministratore. Offre l'icona
sul desktop e, non spuntato, l'avvio con Windows (in quel caso l'app parte senza finestra e
resta nell'icona). La disinstallazione toglie il programma; spazi, chiavi e decision model
restano.

In alternativa c'è lo zip: si estrae dove si vuole e si apre `LLMWiki.exe`.

Senza firma del codice, al primo avvio su un altro PC Windows mostra l'avviso SmartScreen.

## 7.8 Aggiornamenti

A ogni avvio l'app desktop chiede a GitHub, in sottofondo, l'ultima versione pubblicata di
`Alessandro-os/llmwiki` (`update.py`). Se è più nuova di quella installata, sotto il campo della
domanda, a destra, compare "È disponibile la versione … · Aggiorna" (solo dal computer
dell'app). Premendolo, e confermando:

1. scarica `LLMWiki-<versione>-setup.exe` in `%LOCALAPPDATA%\LLMWiki\aggiornamenti`,
   riprendendo da dove si era fermato se la rete cade;
2. ne controlla l'impronta SHA-256 con quella pubblicata da GitHub. Se è diversa cancella il
   file e non installa niente;
3. avvia l'installatore senza finestre e si chiude;
4. l'installatore toglie la cartella dei componenti della versione vecchia (`_internal`),
   copia la nuova e riapre l'app;
5. al primo avvio la versione nuova cancella l'installatore scaricato.

Documenti, spazi, impostazioni, chiavi e decision model non si toccano. Senza rete, o se
GitHub non risponde, il tasto non compare e non c'è nessun messaggio di errore.
