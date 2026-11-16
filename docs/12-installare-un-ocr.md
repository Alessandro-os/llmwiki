# 12. Installare un OCR

[← Indice](README.md)

Un OCR serve a leggere i PDF che non contengono testo: scansioni, foto, appunti scritti a mano.
I PDF fatti al computer (Word, slide, LaTeX) non ne hanno bisogno: l'app ne legge il testo
esatto. Come l'app sceglie fra testo esatto e OCR è spiegato in
[2.2.1](02-lettura-dei-documenti.md#221-pdf-con-locr).

LLMWiki **non scarica niente da sola**: l'OCR lo scarichi tu, una volta, e l'app lo trova e lo
accende quando serve. Funziona con qualunque OCR; qui sotto c'è quello consigliato.

## Quale OCR

**MiniCPM-OCR 1.0** (OpenBMB, licenza Apache 2.0). È gratuito, gira sul tuo computer e i
documenti non escono dal PC. Nel confronto del 16/11/2026 su 12 pagine vere di appunti è stato
il migliore tra gli OCR che non inventano:
- lo stampato lo legge quasi perfetto;
- la scrittura a mano circa a metà;
- quando non capisce scrive parole storpiate, che si riconoscono.

Velocità: 2-3 secondi a pagina con la scheda video libera, 30-50 secondi sul processore.

Servono circa 1,8 GB di spazio.

## Che cosa scaricare

Tutto va in una cartella sola. Quella più comoda è `%LOCALAPPDATA%\LLMWiki\ocr`, dove l'app
cerca da sola. Per aprirla, incolla questo indirizzo nella barra di Esplora file:

```
%LOCALAPPDATA%\LLMWiki\ocr
```

Se la cartella non esiste, creala.

**1. llama.cpp**, il programma che fa girare il modello.

Dalla pagina delle versioni, <https://github.com/ggml-org/llama.cpp/releases>, nella versione
più recente apri "Assets" e scegli lo zip per Windows adatto al tuo computer:

| Il tuo computer | Il file che contiene |
|---|---|
| Scheda video NVIDIA | `win-cuda` (con lo zip `cudart` della stessa versione, da estrarre nella stessa cartella) |
| Scheda video AMD o Intel | `win-vulkan` |
| Senza scheda video, o non sai | `win-cpu-x64` |

Estrai lo zip nella cartella. Dentro deve esserci `llama-server.exe`.

Per sapere quale scheda video hai: Gestione attività → Prestazioni → GPU.

**2. MiniCPM-OCR**, il modello.

Dalla pagina <https://huggingface.co/openbmb/MiniCPM-OCR-1.0-gguf>, scheda "Files", scarica due
file nella stessa cartella:
- `MiniCPM-OCR-1_0-Q8_0.gguf`: il modello, circa 0,8 GB;
- `mmproj-model-f16-4x.gguf`: la parte che guarda le immagini, circa 0,9 GB.

Su Hugging Face, accanto a ogni file, c'è la sua impronta SHA-256. Se vuoi essere sicuro che il
file sia arrivato intero, controllala in PowerShell:

```
Get-FileHash "$env:LOCALAPPDATA\LLMWiki\ocr\MiniCPM-OCR-1_0-Q8_0.gguf"
```

## Collegarlo a LLMWiki

1. Impostazioni → Lettura dei documenti → **Cerca gli OCR sul computer**.
2. Accanto a «MiniCPM-OCR (consigliato)» premi **Usa questo**.
3. Premi **Salva e prova**. La prima volta l'app accende l'OCR, che impiega qualche secondo,
   e gli fa leggere un'immagine di prova. Se legge, compare «✓ L'OCR funziona».

I PDF che aspettavano l'OCR ripartono da soli.

Se hai messo i file in un'altra cartella, scrivila in Opzioni avanzate → "Altre cartelle dove
cercare gli OCR" e ripeti la ricerca.

## Farsi aiutare da Claude

Se la pagina non trova nessun OCR, mostra il tasto **Copia il messaggio per Claude**. Copia una
richiesta d'aiuto già scritta, con la cartella giusta e i link, da incollare in una chat con
Claude o con un altro assistente. Ti guiderà passo passo, anche nella scelta dello zip giusto
per la tua scheda video.

## Altri OCR

Ogni OCR che vede le immagini può essere usato:

| Che cosa | Come |
|---|---|
| Un altro modello GGUF con la sua parte visiva (`mmproj`), per esempio PaddleOCR-VL | Metti i due file in una cartella dove l'app cerca: lo trova e lo accende come MiniCPM-OCR |
| Un OCR su un server (Unlimited OCR o DeepSeek-OCR con SGLang o vLLM, LM Studio, Ollama) | Accendilo e premi "Cerca": l'app lo prova con un'immagine. Se ha uno script che lo accende, scrivilo in Opzioni avanzate → "Comando che lo accende": l'app lo lancia quando serve |
| Tesseract | Installalo con la lingua italiana: la ricerca lo trova |

I modelli generici che vedono le immagini (come Strata) possono inventare frasi e numeri: per
questo l'app non li consiglia come OCR.

## Se non funziona

| Che cosa vedi | Che cosa fare |
|---|---|
| «manca llama-server» | Lo zip di llama.cpp non è nella cartella, o non è stato estratto |
| «non si è acceso» | Leggi `%LOCALAPPDATA%\LLMWiki\logs\ocr.log`. Con lo zip `win-cuda` mancano spesso i file `cudart`: prova lo zip `win-vulkan` |
| L'OCR non compare | Controlla che modello e `mmproj` siano nella **stessa** cartella |
| Lento (30-50 s a pagina) | La scheda video era occupata, per esempio dal modello che risponde, e l'OCR è partito sul processore. Funziona lo stesso |
