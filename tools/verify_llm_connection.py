"""验证 API Key 配置和 LLM 连接。"""
import os
import sys
sys.path.insert(0, r"D:\x\ai agent")

from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv("OPENAI_API_KEY", "")
configured = bool(api_key) and api_key != "your_api_key_here"
print(f"API Key configured: {configured}")
if configured:
    print(f"Key prefix: {api_key[:10]}...")
print(f"Base URL: {os.getenv('OPENAI_BASE_URL')}")
print(f"Model: {os.getenv('OPENAI_MODEL')}")

if configured:
    print("\nTesting LLM connection...")
    import asyncio
    from src.llm.client import chat

    async def test():
        try:
            result = await chat(
                messages=[{"role": "user", "content": "请回复'连接成功'三个字"}],
                temperature=0.1,
            )
            print(f"LLM response: {result}")
            print("LLM connection: OK")
        except Exception as e:
            print(f"LLM connection FAILED: {e}")

    asyncio.run(test())
