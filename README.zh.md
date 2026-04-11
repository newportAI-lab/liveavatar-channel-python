# Live Avatar Channel SDK (Python)

[English](./README.md) | **中文**

一个用于 Live Avatar WebSocket 协议的 Python SDK，支持在你的服务器与实时数字人服务之间进行文本、音频和图像通信。

## 环境要求

- Python 3.9+
- `websockets >= 12`
- `sortedcontainers`

可选（参考服务器）：

- `fastapi >= 0.100`
- `uvicorn >= 0.20`

## 安装

```bash
# 以可编辑模式安装（包含开发依赖）
pip install -e ".[dev]"

# 同时安装服务器依赖
pip install -e ".[dev,server]"

# 或使用 uv
uv sync
```

## 快速开始

### 1. 实现监听器

继承 `AvatarChannelListenerAdapter`，只需覆盖你关心的事件：

```python
from liveavatar_channel_sdk import AvatarChannelListenerAdapter, SessionState

class MyListener(AvatarChannelListenerAdapter):
    async def on_session_init(self, session_id: str, user_id: str) -> None:
        print(f"会话已建立：{session_id}  用户：{user_id}")

    async def on_input_text(self, request_id: str, text: str) -> None:
        print(f"用户说：{text}")
        # 通过 client 发送流式响应 …

    async def on_chunk_received(self, request_id, response_id, seq, text) -> None:
        print(f"[{seq}] {text}", end="", flush=True)
```

### 2. 连接并发送消息

```python
import asyncio
from liveavatar_channel_sdk import AvatarWebSocketClient, MessageBuilder

async def main():
    listener = MyListener()
    client = AvatarWebSocketClient("ws://localhost:8080/avatar/ws", listener)

    # 可选：启用指数退避自动重连（1s → 60s）
    await client.enable_auto_reconnect()

    await client.connect()

    # 发送流式响应
    await client.send_response_start("req-1", "resp-1")
    await client.send_response_chunk("req-1", "resp-1", seq=0, timestamp=0, text="你好，")
    await client.send_response_chunk("req-1", "resp-1", seq=1, timestamp=40, text="世界！")
    await client.send_response_done("req-1", "resp-1")

    await asyncio.sleep(1)
    await client.disconnect()

asyncio.run(main())
```

### 3. 构建二进制帧

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
await client.send_binary(audio_bytes)

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
await client.send_binary(image_bytes)
```

## 启动参考服务器

```bash
uvicorn liveavatar_channel_server_example.main:app --host 0.0.0.0 --port 8080
```

服务器在 `ws://localhost:8080/avatar/ws` 上监听，将每条 `input.text` 消息逐词以流式方式 echo 回去。

## 启动客户端模拟器

在另一个终端（服务器运行时）：

```bash
python -m liveavatar_channel_sdk.example.live_avatar_service_simulator
```

模拟器连接到参考服务器并发送一系列脚本化的协议事件。

## 运行测试

```bash
pytest
# 显示详细输出
pytest -s -v
```

## 架构说明

```
应用层   (AvatarChannelListener 回调)
   ↓
协议层   (message.py / audio_frame.py / image_frame.py + event_type.py)
   ↓
传输层   (AvatarWebSocketClient，基于 websockets 库)
```

### 两种连接模式

| 模式 | 说明 |
|---|---|
| **出站模式（Outbound）** | 你的服务器暴露一个稳定的公网 WebSocket 端点，数字人服务主动连接。推荐用于生产环境。 |
| **入站模式（Inbound）** | 数字人服务提供 WebSocket 地址，你的服务器作为客户端主动连接。 |

### 核心类

| 类 | 用途 |
|---|---|
| `AvatarWebSocketClient` | 管理连接生命周期、发送 JSON 文本和二进制帧、分发协议事件 |
| `AvatarChannelListener` | 抽象基类，定义全部协议事件回调 |
| `AvatarChannelListenerAdapter` | 空实现基类，只需覆盖关心的方法 |
| `StreamingResponseHandler` | 对乱序到达的 `response.chunk` 进行缓冲，按序投递 |
| `MessageBuilder` | 所有 JSON 协议消息的工厂类 |
| `AudioFrameBuilder` | 9 字节头部二进制音频帧的流式构建器 |
| `ImageFrameBuilder` | 12 字节头部二进制图像帧的流式构建器 |
| `ExponentialBackoffStrategy` | 可选的自动重连（1s → 60s），默认关闭 |
| `SessionManager` | 服务端异步安全的会话注册表 |

## 协议概览

所有文本消息均为 JSON，事件类型遵循三段式命名规则：

```
<域>.<动作>[.<阶段>]
```

示例：`session.init`、`input.text`、`response.chunk`、`control.interrupt`

### 常用事件

| 事件 | 方向 | 说明 |
|---|---|---|
| `session.init` | 数字人 → 开发者 | 开启会话 |
| `session.ready` | 开发者 → 数字人 | 确认会话就绪 |
| `input.text` | 数字人 → 开发者 | 用户文字输入 |
| `response.chunk` | 开发者 → 数字人 | 流式文本片段（含 `seq`） |
| `response.done` | 开发者 → 数字人 | 流式响应结束 |
| `control.interrupt` | 开发者 → 数字人 | 中断当前播放 |
| `system.idleTrigger` | 数字人 → 开发者 | 数字人已空闲 |

完整协议参考请查阅 [`PROTOCOL.md`](PROTOCOL.md)。

## 代码规范

```bash
ruff check .
black .
```
