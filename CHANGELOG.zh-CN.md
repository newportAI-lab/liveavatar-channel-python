# 更新记录

本文件记录本 SDK 的主要变化。日期为发布日期。

## [0.4.4] - 2026-10-23

- Fixed: `AudioFrame.unpack()` 和 `ImageFrame.unpack()` 现在会拒绝 payload 被截断的帧，不再静默返回不完整的帧数据。

## [0.4.3] - 2026-10-22

1. Added: `send_external_playback(request_id, response_id, frames)` 在平台 TTS 会话中把开发者 PCM 当人声轮播放。它发送 `response.audio.start` 和 `response.audio.finish`，`data.purpose` 为 `external`，随后发送现有二进制音频帧。SDK 不重采样。这不是 `send_external_audio`；后者仍是伴奏，不会替换口播。start 之后如果某一帧发送失败，仍会发送 `response.audio.finish`。平台 Dispatcher 必须已经接受 `purpose=external`。

## [0.4.2] - 2026-10-20

- Fixed: `AvatarAgentConfig` 默认开启自动重连，可显式设置 `reconnect=False` 关闭。

## [0.4.1] - 2026-10-15

1. Added: `AvatarAgentConfig` 新增可选参数 `external_audio_config`。`sampleRate`：`0` 或不填表示跟随本次语音格式，其他值只能是 16000、24000、44100 或 48000。`channels`：`0` 或不填表示跟随本次语音格式，其他值为 1 或 2。其余取值会被拒绝。开播时以 `externalAudioConfig` 发送。
2. Added: `send_external_audio(pcm, timestamp_us=0)` 是新增方法。`pcm` 为 16 位小端 PCM。`timestamp_us` 为 `0` 时由平台填写呈现时间。这段音频不驱动口型。不要用 `response.audio.*`。采样率和声道必须与 `external_audio_config` 一致；未设置该参数时，必须与本次会话的 TTS 音频格式一致。单个二进制帧含协议头后不得超过 65536 字节。后续包要在已发送音频播完前送到，第一包可以比后面的包更长，但仍不能超过该限制。
3. Added: `send_interrupt` 新增字符串参数 `interrupt_scope`。不传、空字符串和 `VOICE_ONLY` 只停止语音播放。`BGM_ONLY` 只清除尚未播放的外部音频。`VOICE_AND_ACCOMPANIMENT` 停止语音播放，并清除尚未播放的外部音频。取值前后的空格会被去掉，其他取值在发送前被拒绝。该参数的值写入事件 `control.interrupt` 的 `data.interruptScope`。底板视频中的音频不会被清除。
4. Fixed: 响应生命周期回调现在可以再次调用 SDK，不会死锁，也不会被当成重入而拒绝。
5. Changed: 协议文档里的 `response.state` 说明已整理。运行行为没有变化。
6. Changed: 开播字段 `onceVideoIds`、`loopVideoIds`，以及 `scene.switchVideo` 的 `onceVideos`、`loopVideos`、`videoChoreographyGroups`，原先每项只能是 resourceId。现在也可以是该数字人底板视频的 alias。alias 长度为 3 到 32，以字母开头，只含小写字母、数字和下划线，且不能以下划线结尾。SDK 原样传递。平台在播放前把 alias 换成 resourceId。

## [0.4.0] - 2026-09-10

### Added

- 支持响应生命周期。

## [0.3.0] - 2026-09-04

### Added

- 支持响应流生命周期。

## [0.2.7] - 2026-08-06

### Added

- 资源切换消息。

## [0.2.6] - 2026-07-10

### Added

- `scene.ready` 事件。

## [0.2.5] - 2026-07-09

### Added

- 智能体消息支持 metadata。

## [0.2.4] - 2026-06-28

### Added

- 智能体配置支持 mode 参数。

## [0.2.3] - 2026-06-25

### Added

- 声音配置。

## [0.2.0] - 2026-05-15

### Changed

- 发行包中移除了服务端依赖和示例包。

## [0.1.0] - 2026-04-10

### Added

- SDK 首次发布。
