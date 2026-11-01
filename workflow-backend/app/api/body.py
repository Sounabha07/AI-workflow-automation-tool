from fastapi import HTTPException, Request

MAX_BODY_BYTES = 1024 * 1024  # 1 MB, for resume and webhook bodies


async def read_limited_body(request: Request, limit: int = MAX_BODY_BYTES) -> bytes:
    """The raw request body, or 413 once it passes `limit`. Checks
    Content-Length first, then counts while streaming, so a missing or
    lying header can't sneak a bigger body through."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail=f"Body is larger than {limit} bytes")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail=f"Body is larger than {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)
