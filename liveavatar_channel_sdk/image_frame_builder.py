"""Fluent builder for binary image frames.

ImageFrameBuilder provides a fluent interface for constructing ImageFrame
objects with sensible defaults and method chaining.
"""

from liveavatar_channel_sdk.image_frame import ImageFrame


class ImageFrameBuilder:
    """Fluent builder for ImageFrame objects."""

    def __init__(self) -> None:
        self._format = 0  # 0=JPG, 1=PNG, 2=WebP, 3=GIF, 4=AVIF
        self._quality = 85  # 0–255
        self._image_id = 0  # 0–65535
        self._width = 0  # pixels
        self._height = 0  # pixels
        self._payload = b""

    def jpg(self) -> "ImageFrameBuilder":
        """Set format to JPG (0)."""
        self._format = 0
        return self

    def png(self) -> "ImageFrameBuilder":
        """Set format to PNG (1)."""
        self._format = 1
        return self

    def webp(self) -> "ImageFrameBuilder":
        """Set format to WebP (2)."""
        self._format = 2
        return self

    def gif(self) -> "ImageFrameBuilder":
        """Set format to GIF (3)."""
        self._format = 3
        return self

    def avif(self) -> "ImageFrameBuilder":
        """Set format to AVIF (4)."""
        self._format = 4
        return self

    def quality(self, q: int) -> "ImageFrameBuilder":
        """Set encode quality / compression level (0–255)."""
        self._quality = q & 0xFF
        return self

    def image_id(self, id_: int) -> "ImageFrameBuilder":
        """Set unique image ID for fragment reassembly (0–65535)."""
        self._image_id = id_ & 0xFFFF
        return self

    def size(self, width: int, height: int) -> "ImageFrameBuilder":
        """Set image dimensions in pixels (0–65535 each)."""
        self._width = width & 0xFFFF
        self._height = height & 0xFFFF
        return self

    def payload(self, data: bytes) -> "ImageFrameBuilder":
        """Set image payload."""
        self._payload = data
        return self

    def build(self) -> bytes:
        """Build and serialize the image frame to bytes (12-byte header + payload)."""
        frame = ImageFrame(
            format=self._format,
            quality=self._quality,
            image_id=self._image_id,
            width=self._width,
            height=self._height,
            payload=self._payload,
        )
        return frame.pack()
