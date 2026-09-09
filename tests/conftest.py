"""
pytest 公共配置:
- asyncio_mode=auto: 让 async test_* 函数真正被 await 执行(pytest-asyncio)
- network / browser 标记: 默认跳过需要真实 LLM 联网或真实浏览器的用例,
  通过 pytest --run-network / --run-browser 显式开启。
"""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="运行需要真实 LLM API / 联网的测试",
    )
    parser.addoption(
        "--run-browser",
        action="store_true",
        default=False,
        help="运行需要真实浏览器(Playwright)的测试",
    )


def pytest_collection_modifyitems(config, items):
    run_network = config.getoption("--run-network")
    run_browser = config.getoption("--run-browser")

    for item in items:
        if not run_network and "network" in item.keywords:
            item.add_marker(pytest.mark.skip(reason="需要真实 LLM/联网, 使用 --run-network 开启"))
        if not run_browser and "browser" in item.keywords:
            item.add_marker(pytest.mark.skip(reason="需要真实浏览器, 使用 --run-browser 开启"))
