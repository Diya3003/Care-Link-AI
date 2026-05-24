# Elder Care App

A family coordination app with an elder-facing view, caregiver dashboard, and AI cooking assistant.

## Folder Structure

```
elder_care_app/
├── app.py              # Flask backend — all API routes
├── gemini_client.py    # Gemini AI integration (chat, expiry, insights)
├── requirements.txt    # Python dependencies
├── state.json          # Persistent app state (auto-created on first run)
├── .env                # Your API keys (copy from .env.example)
├── .env.example        # Template for environment variables
└── templates/          # Flask HTML templates (must be in this folder)
    ├── elder.html      # Elder-facing view: groceries, timer, medications
    ├── family.html     # Caregiver dashboard: monitoring, notes, insights
    └── chatbot.html    # AI cooking assistant chat interface
```

## Setup

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Add your Gemini API key**
   ```bash
   cp .env.example .env
   # Edit .env and paste your GEMINI_API_KEY
   ```
   Get a key at: https://aistudio.google.com/app/apikey

3. **Run the app**
   ```bash
   python app.py
   ```

4. **Open in browser**
   - Elder view:    http://localhost:5001/elder
   - Family view:   http://localhost:5001/
   - Chatbot:       http://localhost:5001/chatbot

## Pages

| URL | Who uses it | What it does |
|-----|------------|--------------|
| `/` | Caregiver | Dashboard: grocery list, medications, stove monitor, activity, notes, AI insights |
| `/elder` | Elder | Simplified view: shopping list, stove timer, medication status, chat button |
| `/chatbot` | Elder | AI cooking & grocery assistant powered by Gemini |

## Notes

- The app saves state to `state.json` — don't delete this while the app is running.
- Gemini features (chat, eat-by dates, meal insights) require a valid `GEMINI_API_KEY`.
- The chatbot uses `gemini-2.0-flash`. The elder and family pages work without an API key (groceries, timer, and medications still function).
