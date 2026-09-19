# Codex Guidelines for Auto Job Agent Project

## Project Overview
This is an automated job application agent written in Python 3.11+. 
It uses browser-use, Playwright, Tavily API, and LangGraph.

## Terminal Commands
- Run test script: `python -m src.parsers.resume_parser`
- Install dependencies: `pip install -r requirements.txt`

## Code Conventions
- ALWAYS use `async/await` for IO-bound and browser automation operations.
- ALWAYS use Pydantic v2 for data validation and schemas.
- Place environment variables in `.env` and load them via `python-dotenv`. NEVER hardcode credentials.
- Follow modular architecture: keep `parsers`, `search`, `automation`, and `models` strictly separated.

## Safety & Operating Rules
- Browser automation MUST NOT auto-click the final 'Submit' application button. Always interrupt and wait for Human-in-the-Loop (HITL).
- If encountering a login wall, CAPTCHA, or any page the AI cannot operate, STOP and report the exact problem to the user in the terminal. Wait for the user to manually resolve it in the visible browser, then resume from the breakpoint (do not silently skip or guess). Use `src/search/hitl.py` `BlockHandler` for this; it only blocks when interactive and non-headless.
- Job discovery must traverse the official career site's category/navigation (e.g. 技术类/产品类) and paginate the job list page by page — do NOT rely on keyword search. First match job titles against the resume/profile, then open only relevant detail pages and match full JD requirements. Tavily keyword search is off by default (`search.use_tavily_search`).