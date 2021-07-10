import contextlib


async def read_fd(fd, chunk_size=524288):
    with contextlib.closing(fd):
        while True:
            chunk = fd.read(chunk_size)
            if not chunk:
                break
            yield chunk
