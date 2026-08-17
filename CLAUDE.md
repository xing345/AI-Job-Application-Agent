# Claude Code Guidelines for Auto Job Agent Project

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
- If encountering CAPTCHA during browser automation, pause execution and prompt user in terminal.