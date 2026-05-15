# Live Avatar Channel SDK (Python)

[English](./README.md) | **中文**

用于 Live Avatar WebSocket 协议的 Python SDK。将你的 AI 后端连接到实时数字人服务，支持文本、音频和图像通信。

**版本 0.2.0** —— 简化的 Agent API，仅需 3 个公开类型。

## 环境要求

- Python 3.9+
- `websockets >= 12`
- `httpx >= 0.25`

无其他运行时依赖。

## 安装

```bash
# 以可编辑模式安装（包含所有开发依赖）
pip install -e ".[dev]"

# 或使用 uv
uv sync
```

## 快速开始

SDK 提供三种核心类型：

| 类型 | 用途 |
|---|---|
| `AvatarAgent` | 单一入口 —— 生命周期（start/stop）和全部 17 个 `send_*()` 方法 |
| `AgentListener` | 回调接口 —— 覆盖你关心的事件（所有方法默认空实现） |
| `AvatarAgentConfig` | 配置数据类 —— `api_key`、`avatar_id`、`base_url`、`sandbox`、`timeout`、`developer_tts`、`developer_asr`、`voice_id`、`reconnect` |

### 1. 实现监听器

```python
from liveavatar_channel_sdk import AgentListener

class MyAgent(AgentListener):
    async def on_text_input(self, text: str, request_id: str) -> None:
        """核心回调：收到用户文本消息。"""
        reply = await my_ai.chat(text)

        # 流式返回响应
        await self.agent.send_response_start(request_id, "resp-1")
        await self.agent.send_response_chunk(
            request_id, "resp-1", seq=0, timestamp=0, text=reply,
        )
        await self.agent.send_response_done(request_id, "resp-1")

    async def on_session_init(self, session_id: str, user_id: str) -> None:
        print(f"会话已建立：{session_id}  用户：{user_id}")
```

### 2. 创建 Agent 并启动

```python
import asyncio
from liveavatar_channel_sdk import AvatarAgent, AvatarAgentConfig

async def main():
    listener = MyAgent()
    config = AvatarAgentConfig(
        api_key="sk-...",
        avatar_id="avatar-123",
        # base_url 默认为 https://facemarket.ai/vih/dispatcher
        # sandbox=True   # 添加 X-Env-Sandbox 请求头
    )
    agent = AvatarAgent(config, listener)
    listener.agent = agent   # 双向引用

    result = await agent.start()   # REST + WS + 自动发送 session.ready
    print(f"Session: {result.session_id}")
    print(f"User token: {result.user_token}")
    print(f"SFU URL: {result.sfu_url}")

    # ... 等待回调 ...

    await agent.stop()   # 幂等 —— 关闭 WS + 调用 /session/stop

asyncio.run(main())
```

这就是完整的模式。`start()` 会阻塞直到 `session.init` 握手完成（或超时）。`session.ready` 由 SDK 自动发送，无需手动处理。

## 构建二进制帧

仅在**开发者 TTS**模式（`AudioFrame`）或**多模态图像输入**（`ImageFrame`）时需要二进制帧。

```python
from liveavatar_channel_sdk import AudioFrameBuilder, ImageFrameBuilder

# 16 kHz 单声道 PCM 音频（640 个采样点 / 40 ms）
audio_bytes = (
    AudioFrameBuilder()
    .mono()
    .sample_rate_16k()
    .pcm()
    .seq(0)
    .timestamp(0)
    .samples(640)
    .payload(pcm_data)
    .build()
)
await agent.send_audio_frame(audio_bytes)

# JPEG 图像帧
image_bytes = (
    ImageFrameBuilder()
    .jpeg()
    .quality(85)
    .image_id(1)
    .size(1280, 720)
    .payload(jpeg_data)
    .build()
)
```

`AudioFrame` 数据类也可用于直接构造：

```python
from liveavatar_channel_sdk import AudioFrame

frame = AudioFrame(
    channel=0, seq=100, timestamp=5000,
    sample_rate=0, samples=640, codec=0,
    payload=pcm_data,
)
packed = frame.pack()   # bytes（9 字节头部 + 负载）
```

## 发送方法

所有发送方法均位于 `AvatarAgent` 上，按协议角色分组。

### Platform TTS（默认 —— 平台从文本渲染音频）

| 方法 | 事件 | 说明 |
|---|---|---|
| `send_response_start(request_id, response_id, *, speed, volume, mood)` | `response.start` | 可选：在流式传输前配置 TTS 参数 |
| `send_response_chunk(request_id, response_id, seq, timestamp, text)` | `response.chunk` | 流式文本片段 |
| `send_response_done(request_id, response_id)` | `response.done` | 流式响应结束 |
| `send_response_cancel(response_id)` | `response.cancel` | 取消进行中的响应流 |

### Developer TTS（你直接提供音频帧）

| 方法 | 事件 | 说明 |
|---|---|---|
| `send_response_audio_start(request_id, response_id)` | `response.audio.start` | 表示音频输出开始 |
| `send_audio_frame(frame: AudioFrame)` | *(二进制)* | 发送二进制音频帧（9 字节头部 + PCM/Opus） |
| `send_response_audio_finish(request_id, response_id)` | `response.audio.finish` | 表示音频输出结束 |
| `send_prompt_audio_start()` | `response.audio.promptStart` | 空闲提示音频开始 |
| `send_prompt_audio_finish()` | `response.audio.promptFinish` | 空闲提示音频结束 |

### Developer ASR / Omni（你在原始音频上运行 ASR + VAD）

| 方法 | 事件 | 说明 |
|---|---|---|
| `send_voice_start(request_id)` | `input.voice.start` | 检测到语音活动 |
| `send_asr_partial(request_id, text, seq)` | `input.asr.partial` | 流式 ASR 结果（部分） |
| `send_voice_finish(request_id)` | `input.voice.finish` | 语音活动结束 |
| `send_asr_final(request_id, text)` | `input.asr.final` | 最终 ASR 结果 |

### 控制

| 方法 | 事件 | 说明 |
|---|---|---|
| `send_interrupt(request_id=None)` | `control.interrupt` | 主动的业务逻辑打断。可选 `request_id` 实现精确目标 |
| `send_prompt(text)` | `system.prompt` | 推送空闲唤醒文本触发 TTS 播放 |

### 错误

| 方法 | 事件 | 说明 |
|---|---|---|
| `send_error(code, message, request_id=None)` | `error` | 向平台报告错误 |

## 监听器回调

在 `AgentListener` 上覆盖这些方法。所有方法都是 `async` 且默认空实现。

| 回调 | 触发时机 | 何时覆盖 |
|---|---|---|
| `on_text_input(text, request_id)` | 收到用户文本（输入或平台 ASR 结果） | **核心** —— 在这里回复用户消息 |
| `on_session_init(session_id, user_id)` | 握手完成 | 日志、监控 |
| `on_session_state(state: SessionState)` | 会话状态改变 | UI 同步、调试 |
| `on_session_closing(reason)` | 平台即将关闭连接 | 优雅关闭 |
| `on_idle_trigger(reason, idle_time_ms)` | 用户长时间不活跃 | 发送空闲唤醒提示 |
| `on_audio_frame(frame: AudioFrame)` | 来自平台的原始二进制音频 | 仅开发者 ASR 模式 |
| `on_error(code, message)` | 来自平台或传输层的错误 | 错误处理/降级 |
| `on_closed(code, reason)` | WebSocket 连接关闭 | 清理、重连逻辑 |

## AvatarAgentConfig

| 字段 | 默认值 | 说明 |
|---|---|---|
| `api_key` | *(必填)* | 平台 API Key（仅服务端使用） |
| `avatar_id` | *(必填)* | 唯一数字人标识符 |
| `base_url` | `https://facemarket.ai/vih/dispatcher` | 平台基础 URL |
| `sandbox` | `False` | 启用沙箱模式（添加 `X-Env-Sandbox` 请求头） |
| `timeout` | `30.0` | HTTP 请求 + 握手超时（秒） |
| `developer_tts` | `False` | 当你提供 TTS 音频帧时设为 `True` |
| `developer_asr` | `True` | 默认由开发者运行 ASR + VAD；设为 `False` 使用平台 ASR |
| `voice_id` | `None` | 覆盖数字人的默认音色 |
| `reconnect` | `False` | 断开时启用自动重连 |
| `reconnect_base_delay` | `1.0` | 指数退避的基础延迟（秒） |
| `reconnect_max_delay` | `60.0` | 指数退避的最大延迟（秒） |

## 架构说明

```
开发者代码（实现 AgentListener，调用 agent.start() / agent.send_*()）
    |
    v
AvatarAgent（单一入口：生命周期、REST、WS、事件分发）
    |         内部：_AvatarWsClient / MessageBuilder / AudioFrameBuilder
    v
平台（Live Avatar Service）
```

SDK 在 `start()` 内部自动完成以下步骤：

1. 使用你的 API Key 创建 HTTPX 客户端。
2. 使用你的 `avatar_id` 调用 `POST /v1/session/start`。
3. 通过 WebSocket 连接到返回的 `agentWsUrl`。
4. 等待 `session.init` 并自动回复 `session.ready`。
5. 将入站事件分发到你的 `AgentListener` 回调。
6. `stop()` 断开 WebSocket 并调用 `POST /v1/session/stop`。

### 会话状态

平台通过 `session.state` 事件同步状态。状态定义在 `SessionState` 中：

| 状态 | 说话者 | 系统行为 |
|---|---|---|
| `IDLE` | -- | 等待输入 |
| `LISTENING` | 用户 | ASR 激活 |
| `THINKING` | 系统（大脑） | LLM / TTS 准备中 |
| `STAGING` | 系统（身体） | 数字人渲染准备中 |
| `SPEAKING` | 系统（身体） | 数字人正在输出响应 |
| `PROMPT_THINKING` | 系统（大脑） | 准备空闲唤醒脚本 |
| `PROMPT_STAGING` | 系统（身体） | 数字人渲染准备中（提示） |
| `PROMPT_SPEAKING` | 系统（身体） | 数字人播放空闲唤醒音频 |

## 运行示例

SDK 包含一个模拟器，演示完整的 Agent 模式。

你需要一个运行中的平台端点。本地测试时可指向任何实现了 Live Avatar WebSocket 协议的服务器。

```bash
# 设置你的平台信息
PLATFORM_URL=http://localhost:8080 \
API_KEY=sk-local-test-key \
AVATAR_ID=default-avatar \
python -m liveavatar_channel_sdk.example.live_avatar_service_simulator
```

模拟器（`live_avatar_service_simulator.py`）展示完整流程：创建 `AgentListener`、连接 `AvatarAgent`、启动会话、逐词回显用户输入、最后优雅关闭。

## 协议概览

所有文本消息均为 JSON，事件类型遵循三段式命名规则：

```
<域>.<动作>[.<阶段>]
```

示例：`session.init`、`input.text`、`response.chunk`、`control.interrupt`

### 接收的事件（通过 AgentListener 回调）

| 事件 | 回调 | 说明 |
|---|---|---|
| `session.init` | `on_session_init` | 开启会话（SDK 自动回复 `session.ready`） |
| `session.state` | `on_session_state` | 状态同步（含 `seq` 和 `timestamp`） |
| `session.closing` | `on_session_closing` | 平台即将关闭（如超时） |
| `input.text` | `on_text_input` | 用户文本输入或平台 ASR 最终结果 |
| `system.idleTrigger` | `on_idle_trigger` | 数字人空闲（`reason`、`idle_time_ms`） |
| `error` | `on_error` | 平台错误 |
| *(二进制音频)* | `on_audio_frame` | 原始音频帧（仅开发者 ASR 模式） |

### 发送的事件（通过 agent.send_*() 方法）

| 事件 | 发送方法 | 说明 |
|---|---|---|
| `response.start` | `send_response_start` | 可选：配置 TTS 速度/音量/语气 |
| `response.chunk` | `send_response_chunk` | 流式文本片段 |
| `response.done` | `send_response_done` | 流式响应结束 |
| `response.cancel` | `send_response_cancel` | 取消进行中的流 |
| `response.audio.start` | `send_response_audio_start` | 开发者 TTS：音频开始 |
| `response.audio.finish` | `send_response_audio_finish` | 开发者 TTS：音频结束 |
| `response.audio.promptStart` | `send_prompt_audio_start` | 空闲提示音频开始 |
| `response.audio.promptFinish` | `send_prompt_audio_finish` | 空闲提示音频结束 |
| `input.voice.start` | `send_voice_start` | 开发者 ASR：语音活动开始 |
| `input.voice.finish` | `send_voice_finish` | 开发者 ASR：语音活动结束 |
| `input.asr.partial` | `send_asr_partial` | 开发者 ASR：部分识别结果 |
| `input.asr.final` | `send_asr_final` | 开发者 ASR：最终识别结果 |
| `control.interrupt` | `send_interrupt` | 主动打断（业务逻辑驱动） |
| `system.prompt` | `send_prompt` | 推送空闲唤醒文本 |
| `error` | `send_error` | 错误报告 |

> **双向事件：** `input.asr.*` / `input.voice.*` 由 ASR 提供方发送（Omni 模式下由开发者发送，否则由平台发送）。SDK 同时提供监听器回调（接收）和发送辅助方法（发送）。当你的代码运行 ASR 时，在配置中设置 `developer_asr=True`。

完整协议规范请参见 [`PROTOCOL.zh.md`](PROTOCOL.zh.md)。

### 心跳

WebSocket 原生 ping/pong 控制帧（RFC 6455，`0x9` / `0xA`）由 `websockets` 库自动处理，`ping_interval=5` 秒。

## 运行测试

```bash
pytest
# 显示详细输出
pytest -s -v
```

## 代码规范

```bash
ruff check .
black .
```
