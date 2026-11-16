# Cose da fare

Elenco unico delle cose rimaste in sospeso. Quelle in alto aspettano una tua azione o una tua
decisione; quelle in basso sono sviluppi possibili.

## Aspettano te

- [ ] **Scegliere la licenza del software** (per esempio MIT se vuoi che chiunque possa usarlo,
  oppure nessuna licenza se resta tuo). Il repository ora è pubblico: senza licenza chiunque
  può leggere il codice ma nessuno ha il diritto di riusarlo. Vedi `LICENSES.md` per i
  componenti di terze parti. Nota: nei commit pubblici si vede il tuo indirizzo email.
- [ ] **Firma dell'eseguibile.** Senza un certificato di firma del codice, sugli altri PC
  Windows mostra l'avviso SmartScreen al primo avvio. Il certificato si compra da un'autorità
  di certificazione; serve solo se lo distribuisci a persone che non ti conoscono.
- [ ] **Dare un'occhiata all'interfaccia nuova.** L'ho ridisegnata e controllata a schermo
  (tema scuro e chiaro, primo avvio, impostazioni, documenti, risposta, fonte), ma il giudizio
  che conta è il tuo e quello di chi non l'ha mai vista: testi, colori, cosa non si capisce.
- [ ] **Provare un servizio online** (Claude, OpenAI, Gemini, OpenRouter, Mistral, Groq): serve
  la chiave del servizio, da incollare in Impostazioni. Il codice è provato contro server
  finti che ne imitano i comportamenti, non contro i servizi veri. Il più economico per una
  prova è OpenRouter, che con una chiave dà accesso a molti modelli.

- [ ] **Decidere se passare Strata a IQ2_XS per sempre.** Nel confronto del 15 novembre ha
  risposto bene come IQ3_S (24 su 24, nessuna citazione non confermata), in 16 secondi invece
  di 186, e ha fatto l'indice in 18 minuti invece di 47. Le risposte sono un po' meno ricche.
  Vale anche per opencode e pi, che usano lo stesso Strata: prima di decidere va provato nel
  lavoro vero con loro. Dopo la prova Strata è tornato su IQ3_S. Il comando per il cambio è in
  [docs/11](docs/11-scelta-del-modello.md#passo-5-verificare-prima-di-decidere).

## Consigli per lo sviluppo

In ordine di importanza, secondo me.

1. **Fallo usare a tre persone vere prima di aggiungere altro.** Una che studia, una che
   lavora con contratti, una che non sa cosa sia un modello. Guardale mentre lo usano senza
   aiutarle: dove si fermano è il prossimo lavoro da fare, più di qualunque idea nostra.
2. **Tieni il banco di prova come cancello.** Ogni modifica a prompt, verifica o ricerca si
   misura con `evals/run.py` prima e dopo. Senza numeri, con i modelli ci si convince
   facilmente di aver migliorato qualcosa che è peggiorato.
3. **Allarga il banco di prova con domande tue.** Le mie sono inventate. Venti domande vere
   sui tuoi documenti, con la risposta giusta scritta da te, valgono più di tutte le mie.
4. **La velocità è il limite più sentito.** Con 48 GB di RAM la leva più grande è un modello
   che entri tutto in memoria: Strata IQ2_XS risponde in 16 secondi invece di 186 (misura del
   15 novembre). Poi vengono il ragionamento ridotto e, per chi può mandare fuori i dati, un
   servizio online.
5. **Decidi presto a chi è rivolto.** Studente singolo e azienda hanno bisogni diversi:
   l'azienda chiederà permessi per cartella, HTTPS, copie di sicurezza, un registro di chi ha
   chiesto cosa. Meglio farne bene uno che a metà tutti e due.
6. **Prima di esporlo in rete fuori casa: HTTPS.** Oggi i token viaggiano in chiaro; va bene
   su una rete fidata, non altrove.
7. **Non aggiungere la ricerca per significato finché una misura non la chiede.** Sulla
   raccolta difficile la ricerca per parole ha trovato il documento giusto 24 volte su 24.
8. **Scegli licenza e nome definitivo prima di pubblicare**, e firma l'eseguibile se andrà a
   persone che non ti conoscono.

## Sviluppi possibili

- [ ] Ricerca per significato oltre che per parole (embedding): richiede di scaricare un
  secondo modello. Per ora non serve: nella raccolta difficile (64 documenti molto simili) la
  ricerca per parole più la navigazione ha trovato il documento giusto 24 volte su 24. Da
  riconsiderare con raccolte di migliaia di documenti.
- [ ] **Domande senza risposta nei documenti: l'agente non sa quando smettere.** Con tutti i
  modelli è la domanda più lenta: da 78 secondi (IQ2_XS) a 37 minuti (IQ3_S), con 24-36 passi
  contro i 4-5 delle altre. Si potrebbe fermare la ricerca dopo qualche passo senza niente di
  nuovo e far rispondere "non c'è" con ciò che ha trovato. La modifica va misurata con il banco
  di prova, perché non deve far arrendere l'agente sulle domande difficili che hanno una risposta.
- [ ] **"Poco" nelle Impostazioni non funziona con llama.cpp.** Lì il valore "low" viene
  ignorato e solo "none" ha effetto, ma spegne del tutto il ragionamento. Senza ragionamento
  le risposte sono più veloci, però l'agente si perde sulle domande senza risposta (vedi sopra).
  Proposta: per llama.cpp spegnere il ragionamento solo per le schede, dove la misura dà un
  indice 5 volte più veloce e nessun errore. Oppure dire nell'interfaccia che l'opzione vale
  solo per Strata.
- [ ] **Il banco di prova non riconosce le formule.** "5/2" scritto `\frac{5}{2}` e "0,40"
  scritto `0{,}40` contano come risposte sbagliate. È capitato 3 volte nel confronto del 15
  novembre: le risposte erano giuste.
- [ ] **Livelli di approfondimento della risposta** (idea tua, da fare dopo il confronto dei
  modelli, che dirà quanto costa ogni livello):
  - *Base*: la risposta secca (sì/no, il numero, la data) con la citazione del documento e poco
    altro, il più veloce possibile;
  - *Medio*: spiega anche il perché e il come;
  - *Avanzato*: nella risposta ci sono già dei punti premibili che aprono un approfondimento
    su ciascun argomento (per esempio, in una dimostrazione, il teorema da cui dipendono le
    ipotesi), così si segue ogni biforcazione che serve.
- [ ] Modalità "interrogami": l'app genera domande dagli appunti di una cartella e controlla
  le tue risposte sui testi.
- [ ] **Provare la versione Vulkan di llama.cpp** che l'app scarica per MiniCPM-OCR: velocità
  sulla scheda video rispetto alla versione CUDA misurata (2-3 s a pagina). Non l'ho potuta
  provare: scaricare ed eseguire il programma era bloccato nella sessione di sviluppo.
- [ ] **Scrittura a mano:** MiniCPM-OCR ne legge circa metà. Da riprovare quando escono OCR
  migliori; Unlimited OCR non è stato misurato a mano (si è incastrato sulla prima pagina).
