# 协议综述
websocket服务地址需要开发者提供，data channel 由livekit提供。

websocket通道处理文本/音频/视频（其实是图片,协议暂时不包含这部分）

data channel 只处理文本， 音频由 audio track 处理， 视频由video track处理（这三个通道都是livekit提供的）

## 场景支持考量
1. websocket和webrtc  data channel 使用的文本协议格式保持一致（除了心跳部分）。
2. 消息类型语义化，方便理解。
3. 支持流式数据传输。
4. 抗乱序。
5. 支持对多用户房间扩展。

## 文本消息类型命名规范
我们用event 来指代消息类型，为了防止消息类型增长过程中出现的混乱，需要定制一系列规范。

### 三段式语义
<domain>.<action>[.<stage>]

#### 1️⃣ 第一层：Domain（领域分类）
| Domain | 含义 |
| --- | --- |
| session | 会话生命周期 |
| input | 用户输入 |
| response | 模型输出 |
| control | 控制信号 |
| system | 系统行为 |
| error | 错误 |
| tool（未来） | 工具调用 |


---

#### 2️⃣ 第二层：Action（动作）
描述“做什么”

| Action | 示例 |
| --- | --- |
| init | session.init |
| ready | session.ready |
| text | input.text |
| asr | input.asr |
| chunk | response.chunk |
| done | response.done |
| interrupt | control.interrupt |
| prompt | system.prompt |
| idle trigger | system.idleTrigger |


---

#### 3️⃣ 第三层：Stage（阶段，可选）
用于“流式/状态”

| Stage | 示例 |
| --- | --- |
| partial | input.asr.partial |
| final | input.asr.final |
| chunk | response.chunk |
| done | response.done |
| cancel | response.cancel |


# 文本协议分场景协议设计
## WebSocket inbound/outbound模式。
### inbound模式
inbound 模式是指数字人服务提供webscoket服务地址，开发者服务来请求数字人服务提供的websocket服务。

它的整体执行时序如下：

![](https://cdn.nlark.com/yuque/__mermaid_v3/6efaa31059f5d813f560496dba52dffb.svg)

### outbound模式
outbound 模式是指开发者服务提供webscoket服务地址, 数字人服务来请求开发者服务提供的websocket服务。

它的整体执行时序如下：

![](https://cdn.nlark.com/yuque/__mermaid_v3/de757efe651bd0744c875a353d4e9673.svg)

### 两种模式的适用场景
+ 如果你的业务对**极低延迟和大规模并发稳定性**有要求，且你有成熟的运维团队能暴露稳定的公网端点，**Outbound** 在架构美感和资源受控度上更优。
+ 如果你追求**快速交付、内网安全**，且不希望处理复杂的防火墙穿透问题，**Inbound** 带来的微小性能损失在 Java 异步框架（如 Netty/WebFlux）下几乎可以忽略不计。

## 场景一：WebSocket 全流程（标准路径）
### 1️⃣ 建立连接
#### Client (数字人服务)→ Server（开发者服务）
```plain
{
  "event": "session.init",
  "data": {
    "sessionId": "sess_123",
    "userId": "u_1"
  }
}
```

---

#### （开发者服务） → Client (数字人服务)
```plain
{
  "event": "session.ready"
}
```

---

### 2️⃣ 心跳
依靠 WebSocket 协议标准控制帧。

遵循标准 WebSocket 协议（RFC 6455）：

+ **Ping (0x9)**：服务器可能会向客户端发送 Ping 帧。
+ **Pong (0xA)**：客户端收到 Ping 帧后，必须自动回复 Pong 帧。

---

### 3️⃣ 用户输入文本
数字人服务发送文本输入消息

```plain
{
  "event": "input.text",
  "requestId": "req_1",
  "data": {
    "text": "你叫什么名字"
  }
}
```

---

### 4️⃣ 开发者服务流式输出
#### 输出开始（文本）
可选的事件，如果你需要对数字人服务提供的TTS进行语速，音量，情绪等的控制，可以在发送chunk事件前发送该消息。

```plain
{
  "event": "response.start",
  "requestId": "req_1",
  "responseId": "res_1",
  "data": {
    "audioConfig": {
      "speed": 1.0,
      "volume": 1.0,
      "mood": "neutral"
    }
  }
}
```



**Speed取值对照表**

| 值 | 含义 |
| --- | --- |
| 1.0 | 正常语速 |
| 0.5 | 很慢（适合教学/老人） |
| 0.8 | 稍慢 |
| 1.2 | 稍快 |
| 1.5 | 很快 |
| 2.0 | 极限快（不保证清晰） |


**volume取值对照表**

| **值** | **含义** |
| --- | --- |
| **0.0** | **静音** |
| **0.5** | **较小** |
| **1.0** | **标准** |
| **1.2** | **偏大** |
| **1.5** | **最大（可能爆音）** |


**mood可选取值(可扩展)**

+ neutral
+ happy
+ sad
+ angry
+ excited
+ calm
+ serious

#### chunk（文本）
```plain
{
  "event": "response.chunk",
  "requestId": "req_1",
  "responseId": "res_1",
  "seq": 12,
  "timestamp": 1710000000000,
  "data": {
    "text": "你好"
  }
}
```

---

#### done（文本）
```plain
{
  "event": "response.done",
  "requestId": "req_1",
  "responseId": "res_1"
}
```

---

requestId → responseId = 1:N

seq = response 内递增。

response  可以是多个agent回复的。



### 5️⃣ 状态同步（数字人服务发送）
```plain
{
  "event": "session.state",
  "seq": 12,
  "timestamp": 1710000000000,
  "data": {
    "state": "SPEAKING"
  }
}
```

seq = session 内递增。

state 所有的值（后续可能扩展）

| **<font style="color:rgb(31, 31, 31);">状态</font>** | **<font style="color:rgb(31, 31, 31);">谁在说话</font>** | **<font style="color:rgb(31, 31, 31);">系统行为</font>** |
| --- | --- | --- |
| **<font style="color:rgb(31, 31, 31);">IDLE</font>** | <font style="color:rgb(31, 31, 31);">无</font> | <font style="color:rgb(31, 31, 31);">等待输入</font> |
| **<font style="color:rgb(31, 31, 31);">LISTENING</font>** | <font style="color:rgb(31, 31, 31);">用户</font> | <font style="color:rgb(31, 31, 31);">ASR 收音</font> |
| **<font style="color:rgb(31, 31, 31);">THINKING</font>** | <font style="color:rgb(31, 31, 31);">系统 (脑)</font> | <font style="color:rgb(31, 31, 31);">LLM/TTS 准备</font> |
| **<font style="color:rgb(31, 31, 31);">STAGING</font>** | <font style="color:rgb(31, 31, 31);">系统 (身)</font> | <font style="color:rgb(31, 31, 31);">准备生成数字人</font> |
| **<font style="color:rgb(31, 31, 31);">SPEAKING</font>** | <font style="color:rgb(31, 31, 31);">系统 (身)</font> | <font style="color:rgb(31, 31, 31);">数字人正常回答输出</font> |
| **<font style="color:rgb(31, 31, 31);">PROMPT_THINKING</font>** | <font style="color:rgb(31, 31, 31);">系统 (脑)</font> | <font style="color:rgb(31, 31, 31);">准备提醒话术</font> |
| **<font style="color:rgb(31, 31, 31);">PROMPT_STAGING</font>** | <font style="color:rgb(31, 31, 31);">系统 (身)</font> | <font style="color:rgb(31, 31, 31);">准备生成数字人</font> |
| **<font style="color:rgb(31, 31, 31);">PROMPT_SPEAKING</font>** | <font style="color:rgb(31, 31, 31);">系统 (身)</font> | <font style="color:rgb(31, 31, 31);">数字人播报提醒语音</font> |


---

### 6️⃣ 打断（开发者服务发送）
```plain
{
  "event": "control.interrupt",
  "requestId":req_2"
}
```

<font style="color:rgb(51, 51, 51);">开发者服务发起的信号。</font>

<font style="color:rgb(51, 51, 51);">数字人服务只负责执行中断动作。 对文本输入和音频输入都是同样逻辑，区别在于 开发者服务判定中断的策略： 文本输入 → 立即触发。 音频输入 → 依赖 VAD 或策略判定。</font>

<font style="color:rgb(51, 51, 51);">打断时传入requestId可以帮助精准打断指定的对话，避免因为网络抖动导致误打断，也可以不填。</font>

为了方便理解，我们提供打断执行的时序图

![](https://cdn.nlark.com/yuque/__mermaid_v3/1769342f8157412036e9cbe336423435.svg)

---

###  7️⃣ 即将关闭连接（数字人服务发送）
```plain
{
  "event": "session.closing",
  "data": {
    "reason": "timeout" 
  }
}
```

这种消息一般是系统判定超时前主动发送的。

## 场景二：ASR + 实时语音 （开发者服务发送）
---

### ASR识别(ASR由谁来提供，消息就由谁来发送)
#### 用户说话文本识别（流式）
```plain
{
  "event": "input.asr.partial",
  "requestId": "req_2",
  "seq": 3,
  "data": {
    "text": "你叫",
    "final": false
  }
}
```

---

#### 用户说话文本识别（最终结果）
```plain
{
  "event": "input.asr.final",
  "requestId": "req_2",
  "data": {
    "text": "你叫什么名字"
  }
}
```

---

### 语音输入开始/结束检测(ASR由谁来提供，消息谁来发送)
#### 检测到语音输入开始
```plain
{
  "event": "input.voice.start",
  "requestId": "req_1"
}
```

#### 检测到语音输入结束
```plain
{
  "event": "input.voice.finish",
  "requestId": "req_1"
}
```

可以只发input.asr.final这个event，input.asr.partial 属于optional类消息 

👉 后续流程同 text



### 语音输入开始/结束检测(TTS由谁来提供，消息谁来发送)
#### **语音输出开始**
```plain
{
  "event": "response.audio.start",
  "requestId": "req_1",
  "responseId": "res_1"
}
```

#### **语音输出结束**
```plain
{
  "event": "response.audio.finish",
  "requestId": "req_1",
  "responseId": "res_1"
}
```

**TTS由开发者提供的情况**:

发送语音输出开始消息后开发者服务推送对应的语音数据，语音数据推送完毕再发送语音输出结束消息.

**TTS由数字人服务提供的情况**:

发送语音输出开始消息后数字人服务推送对应的语音数据，语音数据推送完毕再发送语音输出结束消息.

---

## 场景三：服务端主动驱动（冷场唤醒）
### **1️⃣**** 闲置事件（数字人服务发）**
```plain
{
  "event": "system.idleTrigger",
  "data": {
    "reason": "user_idle",
    "idleTimeMs": 120000
  }
}
```

系统检测到数字人已经闲置了较长时间了。

### 2️⃣  **闲置提醒文本消息**（开发者服务发）
```plain
{ 
  "event": "system.prompt",
  "data": {
    "text": "Are you still there?"
  }
}
```

---

数字人服务收到这个消息后会使用配置好的TTS驱动数字人说指定的内容。

prompt文本不参与用户闲置累计计时。

### 3️⃣ **闲置提醒开始语音消息**（开发者服务发）
```plain
{
  "event": "response.audio.promptStart"
}
```

### 4️⃣ **闲置提醒结束语音消息（开发者服务发）**
```plain
{
  "event": "response.audio.promptFinish"
}
```

发送闲置提醒开始消息后开发者服务推送对应的提醒语音，prompt音频推送完毕再发送闲置提醒结束消息。

prompt音频不参与用户闲置累计计时。

## 场景四：LiveKit DataChannel（低延迟路径）
👉 核心原则：

**除了ping/pong请求不再需要，其它协议格式完全一样，只是走 RTC**

---

## 场景五：异常处理（optional）
---

### 错误（开发者服务发送）
```plain
{
  "event": "error",
  "requestId": "req_1",
  "data": {
    "code": "ASR_FAIL",
    "message": "audio decode error"
  }
}
```

---

### 流取消（开发者服务发送）
```plain
{
  "event": "response.cancel",
  "responseId": "response_1"
}
```



# 音频协议设计（仅websocket通道）
音频是二进制数据，每一个音频包都会封装成以下数据结构

## 📦 数据结构
```plain
| Header (9 bytes) | Audio Payload |
```

---

## 🧠 Header 位定义
总共8*9=72位

按照顺序，每一个字段占的位数。

| 字段 | 位数 | 位偏移（高→低） | 范围/取值 | 说明 |
| --- | --- | --- | --- | --- |
| **T (Type)** | 2 | 70–71 | `01` | 固定为音频帧 |
| **C (Channel)** | 1 | 69 | 0 / 1 | 0=Mono, 1=Stereo |
| **K (Key)** | 1 | 68 | 0 / 1 | 关键帧（首帧 / Opus重同步） |
| **S (Seq)** | 12 | 56–67 | 0–4095 | 序号（循环） |
| **TS (Timestamp)** | 20 | 36–55 | 0–1,048,575 | 时间戳（ms，循环）） |
| **SR (SampleRate)** | 2 | 34–35 | 00/01/10 | 00=16kHz, 01=24kHz, 10=48kHz |
| **F (Samples)** | 12 | 22–33 | 0–4095 | 每帧采样数（如 24k/40ms=960） |
| **Codec** | 2 | 20–21 | 00/01 | 00=PCM, 01=Opus |
| **R (Reserved)** | 4 | 16–19 | 0000 | 保留位 |
| **L (Length)** | 16 | 0–15 | 0–65535 | Payload 字节长度 |


seq 和 TS都是递增的，但是它们位数有限，因此需要支持循环。

### wrap 规则
TS 和 Seq 均为循环计数器，接收端必须使用模运算进行比较，禁止直接使用大小判断。

###  jitter buffer 必须基于 TS（不是 Seq）
排序优先级：  
1. TS（主排序）  
2. Seq（辅助去重）

###  丢包/乱序窗口
最大乱序窗口 ≈ 200~500ms

## 🧠 Audio Payload
 真正的音频二进制数据，里面是pcm/opus格式的二进制数据。

无论数字人服务发送给开发者的音频数据还是开发者发给数字人服务的音频数据都必须遵循这个格式。

# 图片协议设计(仅websocket通道)
图片是二进制数据，每一张图片包都会封装成以下数据结构（仅用于多模态图片流输入场景）

## 📦 数据结构
```plain
| Header (12 bytes) | Audio Payload |
```

## 🧠 Header 位定义
总共8*12=96位

按照顺序，每一个字段占的位数。

| 字段 | 位数 | 位偏移（高→低） | 范围/取值 | 说明 |
| --- | --- | --- | --- | --- |
| **T (Type)** | 2 | 94–95 | `10` | 固定为图片帧标识 |
| **V (Version)** | 2 | 92–93 | `00` | 协议版本（预留扩展） |
| **F (Format)** | 4 | 88–91 | 0–4 | 0=JPG, 1=PNG, 2=WebP, 3=GIF, 4=AVIF |
| **Q (Quality)** | 8 | 80–87 | 0–255 | 图片质量（编码质量/压缩等级） |
| **ID (ImageId)** | 16 | 64–79 | 0–65535 | 图片唯一标识（用于分片/重组） |
| **W (Width)** | 16 | 48–63 | 0–65535 | 图片宽度（像素） |
| **H (Height)** | 16 | 32–47 | 0–65535 | 图片高度（像素） |
| **L (Length)** | 32 | 0–31 | 0–4,294,967,295 | Payload 字节长度 |

