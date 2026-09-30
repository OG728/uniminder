# University Reminder

I made this so I could see my Canvas work on one calendar instead of clicking through every course. It runs on your own computer. Nothing gets written back to Canvas.

After you sync, you get a month view of what's due. There's also a plain list if you like that better. Click an assignment and you can make a simple study plan for it. If you already submitted something, it stays off the overdue list.

## Run

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

The key is in Canvas under Account, Settings, New Access Token
Put your school Canvas URL and API key in `.env`: 


```env
CANVAS_BASE_URL=https://yourschool.instructure.com
CANVAS_ACCESS_TOKEN=your_api_key
```



```bash
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and click Sync Now.

## AI study plans (optional)

Study plans work without any AI. If you want an AI to write them, pick one of these in `.env` and restart the app.

**AI API key**:

```env
PLANNER_BACKEND=api
AI_API_KEY=your_ai_key
AI_MODEL=model_name
```

For a different provider, also change `AI_BASE_URL` to their API address.

**Local model** (free, stays on your computer): install [Ollama](https://ollama.com/), run `ollama pull llama3.2`, then set:

```env
PLANNER_BACKEND=ollama
OLLAMA_MODEL=local_model_name
```

If you pulled a different model, put its name in `OLLAMA_MODEL` instead.

If the AI can't be reached, it just falls back to the normal planner.
