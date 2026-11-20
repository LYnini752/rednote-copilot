# Rednote Copilot · 0.1.0a1

**中文 README** | [English README](README.en.md)

本地运行的小红书创作助手：通过对话写稿、基于手动编辑稿继续修改、安全预览、导出/恢复草稿，并导入运营 CSV 复盘。

**这是软件 alpha，真实模型与账号功能尚未验收。** 默认离线模式是演示模板，不是 AI。本项目没有自动发布到小红书或读取后台的功能。

## 核心流程

1. 选写作模式，输入真实素材。离线模板可先验收流程；智能改写需配置自己的模型。
2. 在右侧改标题、正文和话题。下一轮生成以**当前编辑稿**为修改基准，而不是旧稿。
3. 查看安全文本预览、字数参考和待补充提醒；可复制文案不包含待补充问题。
4. 导出 ZIP（TXT、Markdown、JSON、发布清单），用户手动到小红书完成图片/封面和发布确认。
5. 刷新前导出；以后可从 ZIP 中取出 JSON 恢复草稿（恢复时清空旧对话）。
6. 导入 CSV 查看合计、加权互动比率、平均值、中位数与排行，可导出复盘 JSON。

预览不会执行 HTML、渲染外部图片或自动访问用户文案中的链接。它不是小红书最终排版的精确模拟。

## 安装和运行

Python **3.11–3.13**。已验证的版本与测试证据见 [验收说明](docs/acceptance.md)。不要使用相邻项目的虚拟环境。

### macOS / Linux

在本项目目录执行：

```bash
git clone https://github.com/LYnini752/rednote-copilot.git
cd rednote-copilot
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

默认只监听本机 `http://127.0.0.1:7863`，不创建公开分享链接，不修改系统 Python。若端口被占用，macOS / Linux 可以 `PORT=7864 .venv/bin/python app.py`；PowerShell 可先 `$env:PORT="7864"` 再运行。

> 仅供受信任用户在本机使用。不要在公网部署，不要改监听地址为 `0.0.0.0`。本 alpha 没有多用户认证/租户隔离的生产安全设计。

## 真实模型配置

选择“真实模型（OpenAI-compatible）”，展开配置栏，替换示例中的模型 ID 和 Base URL。

```json
{
  "name": "My model",
  "model": "your-model-id",
  "base_url": "https://your-provider.example/v1",
  "api_key_env": "OPENAI_API_KEY",
  "temperature": 0.4,
  "max_tokens": 1500,
  "timeout": 120
}
```

- Base URL 是基础路径；客户端会追加 `/chat/completions`。不要填写完整请求路径。
- HTTP 只允许 `localhost` / `127.0.0.1` / `::1` 的本机服务；远端必须 HTTPS。
- Key 只从运行应用进程的环境变量读取，不填在 JSON/自定义 headers 中。配置拒绝字面量 Key、Cookie、Authorization 等凭据。
- 设置环境变量后重新启动应用；可用“检查配置”验证格式和环境变量存在性，**该检查不请求模型、不证明权限或网络可用**。
- 本项目不自动加载 `.env` 文件；请用自己信任的终端方式设置 Key，不将真实值粘贴到聊天/源码/日志中。
- 模型需支持 Chat Completions 并输出草稿 JSON；不保证所有“compatible”供应商的特殊协议均可兼容。
- 无自动重试，避免重复计费。模型可能编造内容，即使系统提示要求不编造，也必须人工核对经历、效果和数据。

素材、近期对话及当前编辑稿会发送给**你配置的模型服务**。使用前确认服务的数据处理政策与素材可外发性。CSV 统计不调用模型。

离线演示不解释复杂修改指令：再次生成会保留当前稿件并将最新修改要求放在待补充区。真正的智能多轮修改需要真实模型。

## CSV 复盘口径

使用 UTF-8 或 UTF-8 BOM；每篇笔记仅一行**最新累计值**，不要把多天累计快照相加。

```csv
note_id,title,views,likes,saves,comments
demo-a,合成示例A,100,10,5,2
demo-b,合成示例B,0,0,0,0
```

[example-metrics.csv](example-metrics.csv) 是合成示例，不代表真实运营表现。

- 必须有这些字段；额外命名列允许，但列数需与表头一致。
- 空 ID、重复 ID、空标题、重复表头、列数错误或畸形引号会报错，不默默计入。
- 数值必须是非负 ASCII 十进制整数，单字段最大为有符号 64 位整数；拒绝小数、科学计数、NaN/Infinity。
- UI 文件最多 **5,000,000 字节**、最多 **10000 篇**；核心解析函数上限 5 MiB，UI 更严格。
- 互动次数 = 点赞 + 收藏 + 评论；比率 = 互动次数 / 阅读次数，**不是独立用户转化率**，可以超过 100%。
- 零阅读比率为 `null`；总比率为合计分子 / 合计分母，不是逐行比率平均。
- 小分母、不同发布时长和观察窗口影响比较；只描述已导入数据，不推断因果、不预测流量。

## 测试与 CI

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
```

测试包括配置/响应安全、真实 loopback HTTP、CSV 边界、草稿导出/恢复，以及**启动真实 Gradio 服务并经 HTTP/队列调用的端到端流程**。`constraints.txt` 固定本轮验证的传递依赖版本，避免安装时随时间漂移；跨 Python/OS 的实际兼容性仍要通过各环境验证。Stub/loopback 是合成协议测试，不是实际模型质量验收，也不证明浏览器点击体验。

[CI](.github/workflows/ci.yml) 配置 Python 3.11 / 3.12 / 3.13，运行 lint、格式检查、依赖一致性、全部测试并保留 JUnit 结果。最新执行状态见仓库 Actions。

若本机使用代理，需允许 localhost 流量绕过代理。排查时只对本次进程设置，例如：

```bash
NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1 .venv/bin/python -m pytest -q
```

不要为解决代理问题关闭 TLS 校验或在源码写入凭据。

## 本地数据与清理

- 会话只保存在 Gradio 会话内存；页面刷新/进程重启会丢失未导出稿件。
- 新稿按钮清空当前稿件与对话，不删除已导出的文件。
- 内容包和复盘 JSON 保存在 `.local/exports/`，都含用户内容，不属于发布产物。
- 导出文件使用仅当前用户可读写的 POSIX 权限；Windows 权限由当地文件系统 ACL 决定。
- Gradio 还会在系统临时目录缓存上传/下载文件；退出后按本机隐私要求清理。
- `.gitignore` 排除本地环境、凭据配置、缓存、用户导出、JUnit 结果；**仍须检查待提交文件，忽略规则不是密钥泄露防护的替代品**。

## 验证边界

本项目发布为软件 alpha。自动测试覆盖离线写稿、手改上下文、导出/恢复、CSV、HTTP 协议和会话隔离；CI 结果见仓库 Actions。真实模型网络、付费额度及改写质量未验证，演示模板不等于 AI 改写。自动登录、发帖和读取后台未实现。

界面目前为中文，中英 README 提供相同的安装与使用指引。更多验证范围见 [验收说明](docs/acceptance.md)。

## 文件导航

- `app.py`：本地 UI、事件与队列；`workflows.py`：安全预览、配置、导入等纯逻辑。
- `copilot.py`：创作上下文、导出、CSV 分析；`provider.py`：标准库 HTTP 模型客户端。
- `tests/`：自动测试；`docs/`：能力核验与验收清单。
- [SECURITY.md](SECURITY.md)：本地使用安全边界；[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)：第三方依赖说明。

## 许可证

[MIT License](LICENSE)。模型服务和小红书账号服务仍遵守各自服务条款；本项目不提供 API 凭据或代替用户完成平台授权。

## 内置测试数据

见 [示例数据与来源说明](examples/README.md)：包含可以直接试用的输入、离线预览方式、许可证与限制，不附带 API 密钥。
