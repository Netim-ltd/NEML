# NEML with an OpenClaw assistant

NEML gives an assistant two things, both documented in its own Swagger at
`https://api.neml.example.com/swagger`:

1. **A language model and embedder** (OpenAI compatible, `/v1`): the assistant's brain or its RAG.
2. **The lab** (`/api/v1/...`): design a robot, read the lab state and the build pack.

## 1. Model provider (`/v1`)

| | |
|---|---|
| Base URL | `https://api.neml.example.com/v1` |
| Key | `Authorization: Bearer <key>`: the second entry of `NEML_GATEWAY_KEYS` in `~/neml/deploy/vps/.env` on the server (`ssh neml 'grep NEML_GATEWAY_KEYS ~/neml/deploy/vps/.env'`; keys are comma separated, use the second one for OpenClaw) |
| Chat model id | `Qwen3-Next-80B-A3B-Instruct-Q4_K_M` (`GET /v1/models`) |
| Embedding model id | `neml-embed` (384 dimensions) |
| Limits | context 16K tokens, `max_tokens` capped at 2048, one outside request at a time, about 15 tokens/s |

Test it first, outside OpenClaw:

    curl -s https://api.neml.example.com/v1/models -H "Authorization: Bearer $KEY"

OpenClaw reads `~/.openclaw/openclaw.json`. A custom provider goes under `models.providers`, and the model must also be
allowlisted under the agent defaults ([haimaker.ai guide](https://haimaker.ai/blog/openclaw-custom-provider-setup/),
[Atlas Cloud guide](https://www.atlascloud.ai/blog/guides/openclaw-custom-api-setup)). Their field names, which I could not check
against OpenClaw's own docs, give this block:

    {
      "models": {
        "providers": {
          "neml": {
            "baseUrl": "https://api.neml.example.com/v1",
            "apiKey": "<key as a literal string>",
            "api": "openai-completions",
            "models": [
              { "id": "Qwen3-Next-80B-A3B-Instruct-Q4_K_M", "name": "NEML Qwen3-Next 80B", "contextWindow": 16384, "maxTokens": 2048 }
            ]
          }
        }
      },
      "agents": {
        "defaults": {
          "model": { "primary": "neml/Qwen3-Next-80B-A3B-Instruct-Q4_K_M" },
          "models": { "neml/Qwen3-Next-80B-A3B-Instruct-Q4_K_M": {} }
        }
      }
    }

Then `openclaw config validate` and `openclaw models list`. One guide
([General Compute](https://docs.generalcompute.com/openclaw.md)) says `openclaw config set` writes only the key, and that the key
should be a literal string rather than a `${...}` template. If a field name differs in your OpenClaw version, the values stay the same.

For a RAG, point the embedding settings at the same base URL and key with model `neml-embed`.

## 2. The lab as a skill

Copy `integrations/openclaw/neml/` into OpenClaw's skills folder (`~/.openclaw/workspace/skills/neml/`). It tells the
assistant how to sign in, read `GET /api/v1/bot/manifest`, ask for the lab state, and start a design.

The assistant signs in with a bot account (an operator login): the owner creates one in the panel's Bot page or with
`POST /api/v1/bot/accounts`, and gives the email and password to the assistant once. The bot can never decide a level 4
approval, and printing, ordering and robot motion wait for a human whatever it asks.

## Safety

- The gateway key is the only protection of `/v1`; it is long and random. Rotate it by editing `NEML_GATEWAY_KEYS` and
  `docker compose up -d gateway`.
- The assistant's text is untrusted input to the lab (spec 5.4); the lab never treats it as an instruction.
- The host's Caddy sends `/v1/*` of `api.neml.example.com` straight to the gateway on `127.0.0.1:8090` (the API itself has no
  route towards the lab, spec 3.1). A backup of the previous Caddyfile is `/etc/caddy/Caddyfile.bak`.
