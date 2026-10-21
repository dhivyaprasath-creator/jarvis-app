# JARVIS Personal AI Assistant

Flask + SQLite + vanilla JS. Works offline with built-in commands; optional AI model.

## Run
```
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py        # open http://127.0.0.1:5000
```
## Optional AI
Copy `.env.example` to `.env`, set `AI_API_KEY` (Anthropic key; used server-side only), restart.
The header badge shows "AI mode: connected" only when a key is set. Replies are labelled "AI model" or "Built-in rules".

## Try
`help`, `add task buy milk`, `list tasks`, `complete task 1`, `note call mom`, `remind me to stretch in 1 minutes`, `12*(3+4)`, `what time is it`.

## Notes
- Voice input needs Chrome/Edge (Web Speech API) on localhost or HTTPS. Spoken replies use speechSynthesis.
- Data lives in `jarvis.db`. Chat never executes code or shell commands; math uses a whitelisted parser.
- Run tests: `python test_app.py`
