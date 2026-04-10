"""
Audio binary frame for the Live Avatar Channel WebSocket protocol.

Header layout (9 bytes / 72 bits, big-endian, MSB first):

  Bits 70-71 : T  (Type)       – fixed 0b01 for audio
  Bit  69    : C  (Channel)    – 0=Mono, 1=Stereo
  Bit  68    : K  (Key)        – keyframe / Opus resync flag
  Bits 56-67 : S  (Seq)        – wrapping 0–4095
  Bits 36-55 : TS (Timestamp)  – ms, wrapping 0–1,048,575
  Bits 34-35 : SR (SampleRate) – 00=16 kHz, 01=24 kHz, 10=48 kHz
  Bits 22-33 : F  (Samples)    – samples per frame (e.g. 640 @ 16 kHz/40 ms)
  Bits 20-21 : Codec           – 00=PCM, 01=Opus
  Bits 16-19 : R  (Reserved)   – must be 0000
  Bits  0-15 : L  (Length)     – payload byte length
"""

from __future__ import annotations

from dataclasses import dataclass, field

_AUDIO_TYPE = 0b01
_HEADER_SIZE = 9


def _pack_header(
    channel: int,
    key: int,
    seq: int,
    timestamp: int,
    sample_rate: int,
    samples: int,
    codec: int,
    length: int,
) -> bytes:
    val = 0
    val |= (_AUDIO_TYPE & 0x3) << 70
    val |= (channel & 0x1) << 69
    val |= (key & 0x1) << 68
    val |= (seq & 0xFFF) << 56
    val |= (timestamp & 0xFFFFF) << 36
    val |= (sample_rate & 0x3) << 34
    val |= (samples & 0xFFF) << 22
    val |= (codec & 0x3) << 20
    # reserved bits 16-19 remain 0
    val |= (length & 0xFFFF)
    return val.to_bytes(_HEADER_SIZE, "big")


def _unpack_header(data: bytes) -> dict:
    if len(data) < _HEADER_SIZE:
        raise ValueError(
            f"Audio frame too short: expected at least {_HEADER_SIZE} bytes, got {len(data)}"
        )
    val = int.from_bytes(data[:_HEADER_SIZE], "big")
    return {
        "type_": (val >> 70) & 0x3,
        "channel": (val >> 69) & 0x1,
        "key": (val >> 68) & 0x1,
        "seq": (val >> 56) & 0xFFF,
        "timestamp": (val >> 36) & 0xFFFFF,
        "sample_rate": (val >> 34) & 0x3,
        "samples": (val >> 22) & 0xFFF,
        "codec": (val >> 20) & 0x3,
        "length": val & 0xFFFF,
    }


@dataclass
class AudioFrame:
    """Represents a single binary audio frame (9-byte header + payload)."""

    channel: int = 0       # 0=Mono, 1=Stereo
    key: int = 0           # keyframe / Opus resync flag
    seq: int = 0           # wrapping 0–4095
    timestamp: int = 0     # ms, wrapping 0–1,048,575
    sample_rate: int = 0   # 0=16 kHz, 1=24 kHz, 2=48 kHz
    samples: int = 0       # samples per frame
    codec: int = 0         # 0=PCM, 1=Opus
    payload: bytes = field(default=b"")

    def pack(self) -> bytes:
        """Serialise frame to bytes (9-byte header + payload)."""
        header = _pack_header(
            channel=self.channel,
            key=self.key,
            seq=self.seq,
            timestamp=self.timestamp,
            sample_rate=self.sample_rate,
            samples=self.samples,
            codec=self.codec,
            length=len(self.payload),
        )
        return header + self.payload

    @classmethod
    def unpack(cls, data: bytes) -> "AudioFrame":
        """Deserialise bytes into an AudioFrame.

        The payload length is taken from the header L field; any trailing
        bytes beyond header + L are ignored.
        """
        fields = _unpack_header(data)
        if fields["type_"] != _AUDIO_TYPE:
            raise ValueError(
                f"Not an audio frame: type bits = {fields['type_']:#04b}, expected 0b01"
            )
        length = fields["length"]
        payload = data[_HEADER_SIZE: _HEADER_SIZE + length]
        return cls(
            channel=fields["channel"],
            key=fields["key"],
            seq=fields["seq"],
            timestamp=fields["timestamp"],
            sample_rate=fields["sample_rate"],
            samples=fields["samples"],
            codec=fields["codec"],
            payload=payload,
        )
