# University Reminder

I made this so I could see my Canvas work on one calendar instead of clicking through every course. It runs on your own computer. Nothing gets written back to Canvas.

After you sync, you get a month view of what's due. There's also a plain list if you like that better. Click an assignment and you can make a simple study plan for it. If you already submitted something, it stays off the overdue list.

## Setup

1. Install everything:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

1. Open `.env` and add your Canvas URL and token (Canvas > Account > Settings > New Access Token):

```env
CANVAS_BASE_URL=https://yourschool.instructure.com
CANVAS_ACCESS_TOKEN=your_token
```

1. Make the app:

```bash
pyinstaller --onefile --noconsole --name UniMinder --distpath . --workpath build --specpath build launcher.py
```



## AI study plans (optional)

Works without AI. To use one, set these in `.env` and reopen the app.

**AI API key:**

```env
PLANNER_BACKEND=api
AI_API_KEY=your_ai_key
AI_MODEL=model_name
```

**Local model:** install [Ollama](https://ollama.com/), run `ollama pull model_name`, then:

```env
PLANNER_BACKEND=ollama
OLLAMA_MODEL=model_name
```

