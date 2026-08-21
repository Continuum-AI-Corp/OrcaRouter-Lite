# Google Gemini SDK → OrcaRouter Lite

Lite serves the Gemini API natively (AI Studio style, `/v1beta`), so the
official `google-genai` SDK connects without changes.

## google-genai (Python)

```python
from google import genai
from google.genai.types import HttpOptions

client = genai.Client(
    api_key="sk-orca-...",                                  # your Lite key
    http_options=HttpOptions(base_url="http://localhost:8000"),
)

resp = client.models.generate_content(
    model="auto",                       # or any catalog model
    contents="Hello!",
)
print(resp.text)

# streaming
for chunk in client.models.generate_content_stream(
    model="gemini-1.5-flash", contents="Tell me a story",
):
    print(chunk.text, end="")
```

## curl

```bash
# blocking
curl "http://localhost:8000/v1beta/models/auto:generateContent" \
  -H "x-goog-api-key: sk-orca-..." \
  -H "content-type: application/json" \
  -d '{"contents":[{"role":"user","parts":[{"text":"Hello!"}]}]}'

# streaming (SSE)
curl -N "http://localhost:8000/v1beta/models/auto:streamGenerateContent?alt=sse" \
  -H "x-goog-api-key: sk-orca-..." \
  -H "content-type: application/json" \
  -d '{"contents":[{"role":"user","parts":[{"text":"Hello!"}]}]}'
```

Auth is accepted as `x-goog-api-key` (preferred) or `?key=` — note the
query-param form puts the key in URLs, which typically end up in access
logs; the header form doesn't.

## Known limitations (v1)

- `candidateCount > 1`, `cachedContent`, Files API (`fileData`), and
  server-side tools (`googleSearch`, `codeExecution`, `urlContext`)
  return 400. Function declarations are fully supported (uppercase proto
  type enums are normalized automatically).
- `safetySettings`, `thinkingConfig`, and `topK` are dropped.
- `responseMimeType: "application/json"` maps to JSON mode;
  `responseSchema` itself is not yet enforced.
- `streamGenerateContent` without `?alt=sse` returns the full JSON array
  in one response (the SDKs all use `alt=sse`).
