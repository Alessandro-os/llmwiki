# Componenti di terze parti

LLMWiki include o scarica i componenti qui sotto. La licenza di LLMWiki stesso non è ancora
stata scelta: va decisa prima di distribuirlo fuori dalla cerchia di chi lo sta provando.

## Inclusi nel pacchetto

| Componente | Licenza |
|---|---|
| Python | PSF License |
| FastAPI, Starlette, Pydantic, python-multipart | MIT, BSD-3-Clause, MIT, Apache-2.0 |
| Uvicorn, HTTPX | BSD-3-Clause |
| Anthropic SDK per Python | MIT |
| MCP SDK per Python | MIT |
| ONNX Runtime | MIT |
| Tokenizers (Hugging Face) | Apache-2.0 |
| NumPy | BSD-3-Clause |
| pypdf | BSD-3-Clause |
| pypdfium2 e PDFium (pagine PDF come immagini, per l'OCR) | Apache-2.0 o BSD-3-Clause; PDFium BSD-3-Clause |
| python-docx, lxml | MIT, BSD-3-Clause |
| Pillow | MIT-CMU |
| pystray | LGPL-3.0 (usata come libreria separata e sostituibile nella cartella dell'app) |

## Scaricato dall'app su richiesta

| Componente | Licenza | Origine |
|---|---|---|
| mDeBERTa-v3-base-xnli-multilingual-nli-2mil7 (decision model) | MIT | Hugging Face, `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`, revisione `b5113eb3` |
| MiniCPM-OCR 1.0, GGUF Q8_0 e parte visiva (OCR) | Apache-2.0 | Hugging Face, `openbmb/MiniCPM-OCR-1.0-gguf`, revisione `0133ad8d` |
| llama.cpp b12364, versione Vulkan (fa girare MiniCPM-OCR) | MIT | GitHub, `ggml-org/llama.cpp`, release `b12364` |

Gli OCR (Tesseract, Unlimited OCR o altri) non fanno parte di LLMWiki: l'app usa quelli già
installati o accesi sul computer, ognuno con la sua licenza.

I modelli linguistici (locali o di Anthropic) non fanno parte di LLMWiki: ognuno ha la sua
licenza e le sue condizioni d'uso.
