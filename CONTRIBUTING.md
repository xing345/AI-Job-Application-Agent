# 贡献指南

感谢您对 AI Job Application Agent 项目的关注！我们欢迎各种形式的贡献。

## 🤝 如何贡献

### 报告问题
如果您发现了 bug 或者有功能建议，请通过 [GitHub Issues](https://github.com/xing345/ai-job-application-agent/issues) 提交。

### 提交代码
1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 进行更改并提交 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

## 📝 开发规范

### 代码风格
- 遵循 PEP 8 代码规范
- 使用 Black 进行代码格式化
- 使用 isort 进行导入排序

### 注释要求
- 所有函数和类都需要文档字符串
- 复杂逻辑需要添加注释
- 示例代码要有清晰说明

### 测试要求
- 新功能需要添加相应的测试
- 确保所有测试通过 (`pytest`)
- 保持测试覆盖率不低于 80%

### 提交规范
- 使用清晰的提交信息
- 遵循 "类型: 描述" 的格式
- 类型包括：feat, fix, docs, style, refactor, test, chore

## 🏗️ 项目架构

### 目录结构
```
src/
├── models/          # 数据模型
├── parsers/         # 解析器
├── search/          # 搜索模块
├── automation/      # 自动化
├── notifications/    # 通知服务
└── orchestrator/    # 流程编排
```

### 核心模块说明
- **models**: 定义所有数据结构
- **parsers**: 负责简历和文档解析
- **search**: 职位搜索和匹配
- **automation**: Web 自动化操作
- **notifications**: 邮件和通知服务
- **orchestrator**: 状态机和流程控制

## 🧪 测试指南

### 运行测试
```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/integration/test_full_pipeline.py

# 生成覆盖率报告
pytest --cov=src --cov-report=html
```

### 测试类型
- **单元测试**: 测试单个模块功能
- **集成测试**: 测试模块间协作
- **端到端测试**: 测试完整流程

## 📚 文档贡献

### 更新文档
- 修改功能时更新相应文档
- 添加新功能时添加使用示例
- 保持 README 的更新

### 文档格式
- 使用 Markdown 格式
- 代码块使用正确的语法高亮
- 添加必要的截图或图表

## 🎯 功能建议

### 我们欢迎的功能
1. **新招聘网站支持**
   - 添加新的招聘网站适配
   - 优化现有网站的解析逻辑

2. **AI 能力增强**
   - 更智能的匹配算法
   - 支持更多 LLM 模型

3. **用户体验改进**
   - Web 界面
   - 移动端支持
   - 更好的错误提示

4. **扩展功能**
   - 简历优化建议
   - 面试准备助手
   - 薪资谈判工具

## 🔄 代码审查流程

1. 提交 Pull Request
2. 自动化检查通过
3. 至少一名维护者审查
4. 根据反馈修改
5. 合并到主分支

## 📞 联系方式

- GitHub Issues: [问题追踪](https://github.com/xing345/ai-job-application-agent/issues)
- Discussions: [技术讨论](https://github.com/xing345/ai-job-application-agent/discussions)
- Email: xing345@example.com

## 📄 许可证

贡献者需要同意项目的 MIT 许可证。详细信息请查看 [LICENSE](LICENSE) 文件。

感谢您的贡献！🎉