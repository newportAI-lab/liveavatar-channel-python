"""Fluent builder for binary audio frames.

AudioFrameBuilder provides a fluent interface for constructing AudioFrame
objects with sensible defaults and method chaining.
"""

from liveavatar_channel_sdk.audio_frame import AudioFrame


class AudioFrameBuilder:
    """Fluent builder for AudioFrame objects."""

    def __init__(self) -> None:
        self._channel = 0  # 0=Mono, 1=Stereo
        self._key = 0  # keyframe / Opus resync flag
        self._seq = 0  # wrapping 0–4095
        self._timestamp = 0  # ms, wrapping 0–1,048,575
        self._sample_rate = 0  # 0=16 kHz, 1=24 kHz, 2=48 kHz
        self._samples = 0  # samples per frame
        self._codec = 0  # 0=PCM, 1=Opus
        self._payload = b""

    def mono(self) -> "AudioFrameBuilder":
        """Set channel to mono (0)."""
        self._channel = 0
        return self

    def stereo(self) -> "AudioFrameBuilder":
        """Set channel to stereo (1)."""
        self._channel = 1
        return self

    def keyframe(self) -> "AudioFrameBuilder":
        """Set key flag to 1 (keyframe / Opus resync)."""
        self._key = 1
        return self

    def seq(self, seq: int) -> "AudioFrameBuilder":
        """Set sequence number (0–4095, wrapping)."""
        self._seq = seq & 0xFFF
        return self

    def timestamp(self, ts: int) -> "AudioFrameBuilder":
        """Set timestamp in milliseconds (0–1,048,575, wrapping)."""
        self._timestamp = ts & 0xFFFFF
        return self

    def sample_rate_16k(self) -> "AudioFrameBuilder":
        """Set sample rate to 16 kHz (0)."""
        self._sample_rate = 0
        return self

    def sample_rate_24k(self) -> "AudioFrameBuilder":
        """Set sample rate to 24 kHz (1)."""
        self._sample_rate = 1
        return self

    def sample_rate_48k(self) -> "AudioFrameBuilder":
        """Set sample rate to 48 kHz (2)."""
        self._sample_rate = 2
        return self

    def samples(self, n: int) -> "AudioFrameBuilder":
        """Set samples per frame (0–4095)."""
        self._samples = n & 0xFFF
        return self

    def pcm(self) -> "AudioFrameBuilder":
        """Set codec to PCM (0)."""
        self._codec = 0
        return self

    def opus(self) -> "AudioFrameBuilder":
        """Set codec to Opus (1)."""
        self._codec = 1
        return self

    def payload(self, data: bytes) -> "AudioFrameBuilder":
        """Set audio payload."""
        self._payload = data
        return self

    def build(self) -> bytes:
        """Build and serialize the audio frame to bytes (9-byte header + payload)."""
        frame = AudioFrame(
            channel=self._channel,
            key=self._key,
            seq=self._seq,
            timestamp=self._timestamp,
            sample_rate=self._sample_rate,
            samples=self._samples,
            codec=self._codec,
            payload=self._payload,
        )
        return frame.pack()
