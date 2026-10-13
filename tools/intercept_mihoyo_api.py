"""拦截米哈游岗位列表API的请求和响应。"""
import asyncio
import json
import sys
sys.path.insert(0, r"D:\x\ai agent")

from src.browser.manager import get_browser, close_browser


async def main():
    print("=== 拦截米哈游岗位列表API ===")
    browser = await get_browser()
    page = browser.page

    api_request_data = None
    api_response_data = None

    async def on_request(request):
        nonlocal api_request_data
        if "ats-portal/v1/job/list" in request.url:
            try:
                api_request_data = {
                    'url': request.url,
                    'method': request.method,
                    'headers': dict(request.headers),
                    'post_data': request.post_data,
                }
            except Exception as e:
                print(f"请求拦截失败: {e}")

    async def on_response(response):
        nonlocal api_response_data
        if "ats-portal/v1/job/list" in response.url:
            try:
                body = await response.text()
                api_response_data = {
                    'status': response.status,
                    'url': response.url,
                    'body': body[:5000],  # 前5000字符
                }
            except Exception as e:
                print(f"响应拦截失败: {e}")

    page.on("request", on_request)
    page.on("response", on_response)

    await page.goto("https://jobs.mihoyo.com/#/campus/position", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(8000)

    # 打印请求参数
    print("\n=== API 请求参数 ===")
    if api_request_data:
        print(f"URL: {api_request_data['url']}")
        print(f"Method: {api_request_data['method']}")
        print(f"Post Data: {api_request_data['post_data']}")
        # 解析post_data
        if api_request_data['post_data']:
            try:
                post_json = json.loads(api_request_data['post_data'])
                print(f"Post JSON (格式化):")
                print(json.dumps(post_json, indent=2, ensure_ascii=False)[:2000])
            except Exception:
                pass
    else:
        print("未捕获到请求")

    # 打印响应数据
    print("\n=== API 响应数据 ===")
    if api_response_data:
        print(f"Status: {api_response_data['status']}")
        print(f"Body (前3000字符):")
        print(api_response_data['body'][:3000])
        # 尝试解析JSON
        try:
            resp_json = json.loads(api_response_data['body'])
            print(f"\n=== 响应JSON结构 ===")
            print(f"顶层keys: {list(resp_json.keys())}")
            if 'data' in resp_json:
                data = resp_json['data']
                print(f"data keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                if isinstance(data, dict) and 'list' in data:
                    job_list = data['list']
                    print(f"岗位数量: {len(job_list)}")
                    if job_list:
                        print(f"\n第一个岗位:")
                        print(json.dumps(job_list[0], indent=2, ensure_ascii=False)[:1500])
        except Exception as e:
            print(f"JSON解析失败: {e}")
    else:
        print("未捕获到响应")

    await close_browser()
    print("\n完成")


if __name__ == "__main__":
    asyncio.run(main())
