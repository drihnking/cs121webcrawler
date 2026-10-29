import requests
import cbor

from utils.response import Response

MAX_RESPONSE_BYTES = 10 * 1024 * 1024


def download(url, config, logger=None):
    host, port = config.cache_server

    try:
        with requests.get(
            f"http://{host}:{port}/",
            params=[
                ("q", url),
                ("u", config.user_agent)
            ],
            stream=True,
            timeout=(10, 60)
        ) as resp:

            content_length = resp.headers.get("Content-Length")

            if content_length:
                try:
                    if int(content_length) > MAX_RESPONSE_BYTES:
                        raise ValueError("Response exceeds size limit")
                except ValueError as e:
                    if str(e) == "Response exceeds size limit":
                        raise

            chunks = []
            total = 0

            for chunk in resp.iter_content(chunk_size=65536):
                if not chunk:
                    continue

                total += len(chunk)

                if total > MAX_RESPONSE_BYTES:
                    raise ValueError("Response exceeds size limit")

                chunks.append(chunk)

            body = b"".join(chunks)

            if body:
                return Response(cbor.loads(body))

            raise ValueError("Empty response")

    except (requests.RequestException, EOFError, ValueError, MemoryError) as e:
        if logger:
            logger.error("Download error for %s: %s", url, e)

        return Response({
            "error": str(e),
            "status": 0,
            "url": url
        })