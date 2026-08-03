# X-Security AI Backend

This folder is the separate Python codebase for the AI layer of the X-Security Command Center.

## Setup
1. Copy `.env.example` to a new file named `.env`.
2. Put your Groq key in `.env`:
   `GROQ_API_KEY=your_key_here`
3. Install dependencies:
   `pip install -r requirements.txt`
4. Start the API:
   `uvicorn app:app --reload --port 8000`

## What it does
- `GET /health` checks whether the API and Groq key are ready.
- `POST /api/recommendation` accepts one target record and returns a lead score, lifecycle stage, next action, and outreach draft.
- Without a key, it safely returns a baseline recommendation.
- `data/internal.md` is the AI's learning-memory template. Add real outreach outcomes there or connect a database later.

## Important
Keep `.env` private. Do not upload it to GitHub or paste the key into the HTML dashboard.

