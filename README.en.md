# Rednote Copilot (alpha)

[中文 README](README.md) | **English README**

A local-only copilot for drafting Xiaohongshu posts: chat to draft/revise, edit with a safe preview, export/restore drafts, and import a CSV to review note performance.

This repository is a **software alpha**. The UI is Chinese; this English README provides setup and usage instructions. See [acceptance notes](docs/acceptance.md) and repository Actions for validation scope.

## What it does today

- Draft or revise a note through chat
- Treat the **current manual editor content** as the authoritative baseline for the next revision
- Safe text preview (no HTML execution, no remote images/links activation)
- Export a content bundle (TXT / Markdown / JSON / publish checklist)
- Restore a draft from the exported JSON
- Import a per-note cumulative metrics CSV and compute basic descriptive stats + ranking

## Explicit non-goals (alpha)

- No automatic login
- No automatic publishing
- No automatic reading of creator-console/back-office data
- No storing of API keys/cookies in the repo

Official capability notes: see `docs/official-capability-notes.md` (only based on public docs).

---

## Quick start

### Requirements

- Python 3.11–3.13
- Recommended: a project-local venv `.venv`

### Install and run

macOS / Linux:

```bash
git clone https://github.com/LYnini752/rednote-copilot.git
cd rednote-copilot
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

Windows (PowerShell):

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

Default URL: `http://127.0.0.1:7863`.

If the port is already taken:

```bash
PORT=7865 .venv/bin/python app.py
```

This alpha **binds to 127.0.0.1** and **does not create a public share link**.

---

## Offline demo vs Real model

### Offline demo (not AI)

- Mode name: **Demo mode**
- No network calls, no model inference
- Used to accept/verify the UI flow
- On revision: keeps your current manual draft and records your latest revision request in “Missing info”

### Real model (OpenAI-compatible)

- Mode name: **OpenAI-compatible**
- Sends your materials + recent chat turns + current editor draft to your configured model endpoint
- The model must return a JSON object with: `title` (string), `body` (string), `tags` (string[]), `missing_info` (string[])

This repository does **not** ship any key, endpoint, or default remote provider.

---

## Real model configuration

In the UI, open “Real model config” and paste a JSON spec (example file: `config.real.example.json`).

```json
{
  "name": "My model",
  "model": "your-model-id",
  "base_url": "https://your-provider.example/v1",
  "api_key_env": "OPENAI_API_KEY",
  "temperature": 0.4,
  "max_tokens": 1500,
  "timeout": 120
}
```

Notes:

- `base_url` is a base path; the client appends `/chat/completions`.
- HTTP is only allowed for `localhost/127.0.0.1/::1`; remote endpoints must be HTTPS.
- The key must come from an env var (`api_key_env`). Literal keys and credential-like headers are rejected.
- “Check config” validates JSON + env var presence only. It **does not** prove model permission or quality.

---

## Writing workflow (manual edit → rewrite → export/restore)

1. Enter materials in the left text box and click “Generate / revise”.
2. Edit title/body/tags on the right.
3. For the next revision, type your change request and click “Generate / revise” again. The request is applied **based on your current editor draft**, not the old model output.
4. Export a content bundle ZIP:
   - `*.txt` (copy/paste to the creator console)
   - `*.md` (for local preview/review)
   - `*.json` (for restore)
   - `publish-checklist.md`
5. Restore: pick the JSON file from an exported ZIP, upload it, then click “Restore”.

This app does not publish; you manually paste the content in Xiaohongshu and confirm before posting.

---

## CSV review (metrics)

Input CSV: one row per note, representing the **latest cumulative totals**.

```csv
note_id,title,views,likes,saves,comments
```

Rules & limits (strict on purpose):

- Required named columns must be present; extra named columns are allowed. Each row must match the header column count.
- `note_id` must be non-empty and unique; `title` must be non-empty.
- Numbers must be plain base-10 integers (no floats / scientific notation / negatives).
- Each numeric field range: `0` to `9223372036854775807`.
- Up to 10,000 notes; the UI accepts at most 5,000,000 bytes (the core parser limit is 5 MiB).

Computed metrics:

- Interactions = likes + saves + comments
- Per-note rate = interactions / views
  - views == 0 → `null`
- Overall rate is weighted: sum(interactions) / sum(views)
  - This is *not* a conversion rate and can exceed 100% (e.g. when views is a small denominator)

It is descriptive only: no causal claims, no forecasting.

---

## Privacy, local data, and cleanup

- Drafts are in-memory per browser session; refresh/restart drops unsaved drafts.
- Exports and metric JSON are stored under `.local/exports/` (contains user content).
- Uploaded files may be cached under the system temp directory by Gradio.

Suggested cleanup after use:

- Remove `.local/exports/` if it contains sensitive drafts
- Remove the `.venv/` if you no longer need the environment

---

## Troubleshooting

### Port already in use

Set another port:

```bash
PORT=7865 .venv/bin/python app.py
```

### Corporate proxy breaks localhost requests

Run with localhost bypass (for this process only):

```bash
NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1 .venv/bin/python app.py
```

### Real model errors

- Missing env var: set the environment variable named by `api_key_env` (for example, `OPENAI_API_KEY`), then restart the app. The project does not automatically load `.env` files.
- Invalid endpoint: check `base_url` and whether it supports Chat Completions

---

## Unverified / not yet accepted

- Real model quality & behavior (no credentials provided)
- Any official API for publishing or reading back-office metrics (not implemented)
- Public deployment hardening (auth, multi-user isolation, auditing)

---

## Development

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m pytest -q
```

CI config: `.github/workflows/ci.yml`.

`constraints.txt` pins the transitive dependency set validated in this alpha to reduce install drift.

## License

MIT, see `LICENSE`.
