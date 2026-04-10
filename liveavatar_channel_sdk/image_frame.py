"""
Image binary frame for the Live Avatar Channel WebSocket protocol (multimodal input).

Header layout (12 bytes / 96 bits, big-endian, MSB first):

  Bits 94-95 : T  (Type)    – fixed 0b10 for image
  Bits 92-93 : V  (Version) – 0b00 (reserved)
  Bits 88-91 : F  (Format)  – 0=JPG, 1=PNG, 2=WebP, 3=GIF, 4=AVIF
  Bits 80-87 : Q  (Quality) – 0–255 encode quality / compression level
  Bits 64-79 : ID (ImageId) – 0–65535 unique ID for fragment reassembly
  Bits 48-63 : W  (Width)   – pixels 0–65535
  Bits 32-47 : H  (Height)  – pixels 0–65535
  Bits  0-31 : L  (Length)  – payload byte length 0–4,294,967,295
"""

from __future__ import annotations

from dataclasses import dataclass, field

_IMAGE_TYPE = 0b10
_VERSION = 0b00
_HEADER_SIZE = 12


def _pack_header(
    format_: int,
    quality: int,
    image_id: int,
    width: int,
    height: int,
    length: int,
) -> bytes:
    val = 0
    val |= (_IMAGE_TYPE & 0x3) << 94
    val |= (_VERSION & 0x3) << 92
    val |= (format_ & 0xF) << 88
    val |= (quality & 0xFF) << 80
    val |= (image_id & 0xFFFF) << 64
    val |= (width & 0xFFFF) << 48
    val |= (height & 0xFFFF) << 32
    val |= (length & 0xFFFFFFFF)
    return val.to_bytes(_HEADER_SIZE, "big")


def _unpack_header(data: bytes) -> dict:
    if len(data) < _HEADER_SIZE:
        raise ValueError(
            f"Image frame too short: expected at least {_HEADER_SIZE} bytes, got {len(data)}"
        )
    val = int.from_bytes(data[:_HEADER_SIZE], "big")
    return {
        "type_": (val >> 94) & 0x3,
        "version": (val >> 92) & 0x3,
        "format_": (val >> 88) & 0xF,
        "quality": (val >> 80) & 0xFF,
        "image_id": (val >> 64) & 0xFFFF,
        "width": (val >> 48) & 0xFFFF,
        "height": (val >> 32) & 0xFFFF,
        "length": val & 0xFFFFFFFF,
    }


@dataclass
class ImageFrame:
    """Represents a single binary image frame (12-byte header + payload)."""

    format: int = 0       # 0=JPG, 1=PNG, 2=WebP, 3=GIF, 4=AVIF
    quality: int = 85     # 0–255
    image_id: int = 0     # 0–65535
    width: int = 0        # pixels
    height: int = 0       # pixels
    payload: bytes = field(default=b"")

    def pack(self) -> bytes:
        """Serialise frame to bytes (12-byte header + payload)."""
        header = _pack_header(
            format_=self.format,
            quality=self.quality,
            image_id=self.image_id,
            width=self.width,
            height=self.height,
            length=len(self.payload),
        )
        return header + self.payload

    @classmethod
    def unpack(cls, data: bytes) -> "ImageFrame":
        """Deserialise bytes into an ImageFrame.

        The payload length is taken from the header L field; any trailing
        bytes beyond header + L are ignored.
        """
        fields = _unpack_header(data)
        if fields["type_"] != _IMAGE_TYPE:
            raise ValueError(
                f"Not an image frame: type bits = {fields['type_']:#04b}, expected 0b10"
            )
        length = fields["length"]
        payload = data[_HEADER_SIZE: _HEADER_SIZE + length]
        return cls(
            format=fields["format_"],
            quality=fields["quality"],
            image_id=fields["image_id"],
            width=fields["width"],
            height=fields["height"],
            payload=payload,
        )
