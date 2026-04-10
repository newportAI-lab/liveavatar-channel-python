import pytest
from liveavatar_channel_sdk.image_frame import ImageFrame


def test_round_trip_basic():
    frame = ImageFrame(
        format=0, quality=85, image_id=1, width=640, height=480,
        payload=b"jpeg_data",
    )
    assert ImageFrame.unpack(frame.pack()) == frame


def test_round_trip_png():
    frame = ImageFrame(
        format=1, quality=100, image_id=65535, width=1920, height=1080,
        payload=b"\x89PNG" + b"\x00" * 100,
    )
    assert ImageFrame.unpack(frame.pack()) == frame


def test_header_length():
    frame = ImageFrame(payload=b"img")
    packed = frame.pack()
    assert len(packed) == 12 + 3


def test_type_bits_fixed():
    """Type field must always be 0b10 for image frames."""
    frame = ImageFrame(payload=b"")
    packed = frame.pack()
    assert (packed[0] >> 6) == 0b10


def test_all_formats():
    for fmt in range(5):  # 0=JPG, 1=PNG, 2=WebP, 3=GIF, 4=AVIF
        frame = ImageFrame(format=fmt, payload=b"fmt")
        assert ImageFrame.unpack(frame.pack()).format == fmt


def test_quality_boundary_values():
    for q in (0, 128, 255):
        frame = ImageFrame(quality=q, payload=b"q")
        assert ImageFrame.unpack(frame.pack()).quality == q


def test_image_id_boundary():
    for img_id in (0, 1, 65535):
        frame = ImageFrame(image_id=img_id, payload=b"id")
        assert ImageFrame.unpack(frame.pack()).image_id == img_id


def test_max_dimensions():
    frame = ImageFrame(width=65535, height=65535, payload=b"big")
    unpacked = ImageFrame.unpack(frame.pack())
    assert unpacked.width == 65535
    assert unpacked.height == 65535


def test_empty_payload():
    frame = ImageFrame(payload=b"")
    unpacked = ImageFrame.unpack(frame.pack())
    assert unpacked == frame
    assert unpacked.payload == b""


def test_large_payload():
    payload = b"\xAB\xCD" * 10_000  # 20 000 bytes
    frame = ImageFrame(payload=payload)
    unpacked = ImageFrame.unpack(frame.pack())
    assert unpacked.payload == payload


def test_length_field_matches_payload():
    payload = b"0123456789"
    frame = ImageFrame(payload=payload)
    packed = frame.pack()
    # L field is the last 32 bits of the 12-byte header (bits 0-31)
    header_int = int.from_bytes(packed[:12], "big")
    length_field = header_int & 0xFFFFFFFF
    assert length_field == len(payload)


def test_wrong_type_raises():
    # Construct a frame with type bits set to 0b01 (audio) and try to unpack as image
    val = 0b01 << 94  # type = audio (in 96-bit space)
    data = val.to_bytes(12, "big") + b"payload"
    with pytest.raises(ValueError, match="Not an image frame"):
        ImageFrame.unpack(data)


def test_too_short_raises():
    with pytest.raises(ValueError, match="too short"):
        ImageFrame.unpack(b"\x00" * 11)
