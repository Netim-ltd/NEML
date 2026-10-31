# NEML gateway: use the lab's model and embedder from another system

OpenAI-compatible, so a RAG framework only needs a base URL and a key.

| Call | What it does |
|---|---|
| `GET /v1/models` | names the chat model and `neml-embed` |
| `POST /v1/chat/completions` | the lab's language model (streaming works, `max_tokens` capped at 2048) |
| `POST /v1/embeddings` | 384-dimension vectors (`input` is a string or up to 64 strings) |

One outside request runs at a time, so the lab's own designs keep their share. The model is the one resident
model (Qwen3-Next-80B on CPU, roughly 15 tokens/s): keep retrieved context short.

## Reach it

The gateway listens on the server's `127.0.0.1:8090`; the host Caddy publishes it as `https://api.neml.example.com/v1` (see `docs/OPENCLAW.md`). Without the public URL:

    ssh -N -L 8090:127.0.0.1:8090 neml

then use `http://127.0.0.1:8090/v1` as the base URL. To publish it, add a Caddy site on the host that proxies to
`127.0.0.1:8090` (your DNS, your decision); the key is the only protection, so use a long one.

## Key

Set `NEML_GATEWAY_KEYS` in `~/neml/deploy/vps/.env` on the server (comma separated, 16+ characters each), then
`docker compose up -d gateway`.

## Example

    from openai import OpenAI
    c = OpenAI(base_url="http://127.0.0.1:8090/v1", api_key="<key>")
    c.embeddings.create(model="neml-embed", input=["bir cümle"])
    c.chat.completions.create(model="x", messages=[{"role": "user", "content": "merhaba"}])

## Limits per customer and product

Every key belongs to a client with its own limits (`/var/lib/neml/gateway/clients.json` in the gateway container, re-read when it
changes, no restart needed):

| Field | Meaning |
|---|---|
| `max_tokens` | the longest single answer; the request's own `max_tokens` is cut to it |
| `daily_tokens` | prompt + answer tokens per UTC day, `0` = unlimited; past it the client gets HTTP 429 until 00:00 UTC |
| `priority` | who goes first when several wait for the model (lower first); the model serves one outside call at a time |

Manage clients on the server:

    docker exec neml-gateway-1 python -m neml_brain.gateway_clients list
    docker exec neml-gateway-1 python -m neml_brain.gateway_clients set customer-a --max-tokens 512 --daily 100000 --priority 5
    docker exec neml-gateway-1 python -m neml_brain.gateway_clients set neml --max-tokens 16000
    docker exec neml-gateway-1 python -m neml_brain.gateway_clients set customer-a --new-key
    docker exec neml-gateway-1 python -m neml_brain.gateway_clients remove customer-a

A new client's key is printed once. `GET /v1/usage` (with the client's own key) shows its limits and today's use.

A long answer is slow: about 15 tokens/s, so 8192 tokens take roughly 9 minutes, and a client waits behind earlier ones. For a
long answer use `"stream": true`, which keeps the connection alive. The model's context is 16K tokens in all (prompt + answer).
