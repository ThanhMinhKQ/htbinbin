"""
Rate limiting & chống lạm dụng ở tầng ứng dụng (slowapi).

Lưu ý: đây KHÔNG phải lá chắn DoS lưu lượng lớn ở tầng mạng (việc đó cần
CDN/proxy như Cloudflare). Module này chặn brute-force login và lạm dụng
API phổ biến.

State lưu in-memory: reset khi restart và không chia sẻ giữa nhiều instance.
Với deploy 1 instance thì đủ; muốn mạnh hơn cần backend Redis.
"""
from starlette.requests import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _client_ip(request: Request) -> str:
    """
    Lấy IP thật của client. App chạy sau proxy (Render) nên ưu tiên
    X-Forwarded-For (IP đầu tiên là client gốc).
    """
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return get_remote_address(request)


# Giới hạn mặc định áp cho mọi request (chống flood cơ bản)
limiter = Limiter(
    key_func=_client_ip,
    default_limits=["200 per minute"],
)
