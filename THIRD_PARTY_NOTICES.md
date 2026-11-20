# Third-party notices

本仓库许可证只覆盖本项目自有代码，不改变依赖项目各自许可证。以下版本与许可证取自本轮虚拟环境安装后的 package metadata。

| 包 | 本轮验证版本 | 用途 | 许可证 |
| --- | --- | --- | --- |
| gradio | 5.50.0 | 本地 UI、队列和 HTTP 服务 | Apache-2.0 |
| gradio_client | 1.14.0 | Gradio 传递依赖与 HTTP 集成测试客户端 | Apache-2.0 |
| pytest | 8.4.2 | 开发测试 | MIT |
| ruff | 0.17.3 | 开发静态检查与格式化 | MIT |

- 运行依赖位于 `requirements.txt`，开发依赖位于 `requirements-dev.txt`。
- 传递依赖包括 FastAPI、Starlette、Pydantic、HTTPX、NumPy、Pandas 等，均由包管理器安装。此表不是完整传递依赖许可证审计。
- 本仓库不打包或复制 Gradio 的第三方源码/前端静态包；它们随安装的发行包附带相应 notices。
- 若后续发布 wheel、二进制、Docker 镜像或前端 bundle，必须根据实际打包依赖重新生成完整 SBOM/许可证清单，不把本表当作完整合规证明。
- Python 标准库用于模型 HTTP 请求、JSON、CSV 和 ZIP；没有额外复制模型 SDK。
