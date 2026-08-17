from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="ai-job-application-agent",
    version="1.0.0",
    author="xing345",
    author_email="xing345@example.com",
    description="AI-Powered Job Application Assistant - 自动化求职助手",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/xing345/ai-job-application-agent",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Internet :: WWW/HTTP :: Browsers",
        "Topic :: Office/Business",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Systems Administration",
        "Topic :: Utilities",
    ],
    python_requires=">=3.11",
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=7.4.0",
            "pytest-asyncio>=0.21.0",
            "pytest-cov>=4.1.0",
            "black>=23.7.0",
            "isort>=5.12.0",
            "flake8>=6.0.0",
        ],
        "optional": [
            "Pillow>=10.0.0",
            "opencv-python>=4.8.0",
            "sqlalchemy>=2.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "ai-job-agent=main:main",
        ],
    },
    keywords="ai, job, application, automation, resume, career, langgraph, playwright",
    project_urls={
        "Bug Reports": "https://github.com/xing345/ai-job-application-agent/issues",
        "Source": "https://github.com/xing345/ai-job-application-agent",
        "Documentation": "https://github.com/xing345/ai-job-application-agent/blob/main/README.md",
    },
)