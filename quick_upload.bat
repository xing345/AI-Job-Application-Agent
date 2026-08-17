@echo off
echo 🚀 开始上传 AI Job Application Agent 到 GitHub...
echo.

:: 检查Git是否安装
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Git 未安装，请先安装 Git
    pause
    exit /b 1
)

:: 初始化仓库
echo 📦 初始化 Git 仓库...
git init

:: 添加远程仓库
echo 🔗 添加远程仓库...
git remote add origin https://github.com/xing345/ai-job-application-agent.git

:: 添加所有文件
echo 📝 添加所有文件...
git add .

:: 提交
echo 💾 创建提交...
git commit -m "feat: 初始化项目 - AI Job Application Agent

- 实现基于 LangGraph 的求职自动化系统
- 包含简历解析、职位搜索、自动申请等功能
- 支持 Human-in-the-Loop 机制
- 完整的测试和文档"

:: 推送到GitHub
echo 🚀 推送到 GitHub...
git branch -M main
git push -u origin main

:: 完成
echo.
echo ✅ 上传完成！
echo 📂 仓库地址: https://github.com/xing345/ai-job-application-agent
echo.
pause