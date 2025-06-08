# AI Appointment Agent (ai_ehx)

This project implements a chat based appointment assistant built with FastAPI and Google Gemini. It demonstrates how to combine a language model with domain specific API calls to schedule, check, and cancel medical appointments.

## Features

- **FastAPI HTTP API** with endpoints to start a session and send chat messages.
- **Google Gemini integration** via `agent/llm_handler.py` for natural language understanding.
- **Tool calling**: the LLM can trigger Python functions defined in `tools/implementations.py` which call the patient and appointment services.
- **In‑memory sessions** stored in `sessions/store.py` so each conversation keeps context.
- **Quick reply and form hints** returned using tags like `[quick_replies]` or `[required_fields]` so a UI can render buttons or input forms.

## Getting Started

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
2. **Configure environment variables** (or create a `.env` file):
   - `GEMINI_API_KEY` – API key for Google Gemini
   - `PATIENT_SERVICE_URL` – base URL of your patient service (default `http://localhost:8080`)
   - `APPOINTMENT_SERVICE_URL` – base URL of your appointment service (default `http://localhost:8081`)
   - `DEBUG_MODE` – set to `true` to include session data in responses
3. **Run the server**
   ```bash
   uvicorn main:app --reload --port 8083
   ```
   Use `GET /health` to verify configuration.

## API Overview

- `POST /session/start` → creates a new session and returns a `session_id`.
- `POST /session/{sid}/message` → send a message as JSON `{ "message": "..." }` and receive a structured `MessageResponse`.

The assistant greets the user on the first turn, then analyses each message. It may request additional information or call tools (for example `list_available_doctors`) to fulfil the task. The response can include lists of doctors, available slots or quick replies which your frontend can render.

## Code Structure

- `main.py` – FastAPI application exposing the HTTP endpoints.
- `config.py` – loads settings from environment variables using Pydantic.
- `agent/core.py` – conversation loop. Builds prompts, calls the LLM, executes tools and updates the session state.
- `agent/llm_handler.py` – wrapper around Google Gemini APIs.
- `services/` – simple clients for the patient and appointment REST services.
- `tools/definitions.py` and `tools/implementations.py` – list of functions the LLM can call.
- `models/` – Pydantic models for API payloads and session storage.
- `sessions/store.py` – in‑memory implementation of a session store.

## How It Works

1. A client starts a session using `/session/start`.
2. Every user message is sent to `/session/{sid}/message`.
3. `agent/core.py` loads the session, builds a directive prompt using `agent/prompt_builder.py`, and calls Gemini with the conversation history.
4. Gemini may request a tool call (for example to look up doctors). The agent executes the corresponding Python function and appends the result to the history.
5. The loop continues until the model returns a final text reply which is parsed by `agent/ui_parser.py` to extract quick replies or form hints.
6. The updated session is saved and the structured response is returned to the client.

This repository provides a minimal but complete example of orchestrating a language model with domain APIs. It stores sessions in memory for simplicity and does not include authentication, so it is intended for experimentation and learning rather than production use.

