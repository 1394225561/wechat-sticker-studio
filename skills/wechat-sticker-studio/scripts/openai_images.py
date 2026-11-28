"""Submit one image request using the synchronous OpenAI Images protocol."""

import base64
import binascii
import json
import os
import re
import socket
import ssl
import uuid
from contextlib import closing
from dataclasses import dataclass
from http.client import HTTPSConnection, HTTPException
from ipaddress import ip_address, ip_network
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_IMAGE_BYTES = 24 * 1024 * 1024
MAX_RESPONSE_BYTES = MAX_IMAGE_BYTES * 2
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
NAT64_NETWORKS = (ip_network("64:ff9b::/96"), ip_network("64:ff9b:1::/48"))
REJECTED_REQUESTS = {400, 401, 403, 404, 405, 413, 415, 422, 429}


@dataclass(frozen=True)
class Profile:
    base_url: str
    model: str
    api_key_env: str
    reference_images: int
    transparent_background: bool


class ImageRequestError(ValueError):
    def __init__(self, message, *, rejected=False, request_id=None):
        super().__init__(message)
        self.rejected = rejected
        self.request_id = request_id


def parse_profile(data):
    if data.get("adapter") != "openai-images":
        raise ValueError("expected image service adapter openai-images")
    required = ("baseUrl", "model", "apiKeyEnv", "referenceImages", "transparentBackground")
    missing = [field for field in required if data.get(field) is None or data[field] == ""]
    if missing:
        raise ValueError("fill in the image service configuration fields: " + ", ".join(missing))
    base_url, model, key_env = (data.get(name) for name in ("baseUrl", "model", "apiKeyEnv"))
    reference_images = data.get("referenceImages")
    transparency = data.get("transparentBackground")
    if not isinstance(base_url, str) or any(char.isspace() for char in base_url):
        raise ValueError("expected an image service baseUrl")
    try:
        url = urlsplit(base_url)
        local = url.hostname in {"localhost", "127.0.0.1", "::1"}
        secure = url.scheme == "https" or (local and url.scheme == "http")
        url.port  # Validate an explicit port.
    except ValueError:
        raise ValueError("invalid image service baseUrl") from None
    if not secure or not url.hostname or url.username is not None or url.query or url.fragment:
        raise ValueError("baseUrl requires HTTPS or loopback HTTP, with no credentials, query or fragment")
    if not isinstance(model, str) or not model.strip() or "\r" in model or "\n" in model:
        raise ValueError("expected a model name")
    if not isinstance(key_env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_env):
        raise ValueError("apiKeyEnv must be an environment variable name")
    if type(reference_images) is not int or not 0 <= reference_images <= 16:
        raise ValueError("referenceImages must be an integer from 0 to 16")
    if type(transparency) is not bool:
        raise ValueError("transparentBackground must be true or false")
    return Profile(base_url.rstrip("/"), model, key_env, reference_images, transparency)


def make_request(profile, prompt, references):
    if len(references) > profile.reference_images:
        raise ValueError("the configured model cannot accept the requested reference images")
    key = os.environ.get(profile.api_key_env, "")
    if not key or not key.isascii() or not key.isprintable() or any(char.isspace() for char in key):
        raise ValueError(
            f"{profile.api_key_env} is missing or invalid in this process. "
            "Set it privately in the terminal that starts the Agent or runs generate."
        )
    if sum(map(len, references)) > MAX_IMAGE_BYTES:
        raise ValueError("reference images exceed the request byte limit")
    fields = {"model": profile.model, "prompt": prompt, "size": "1024x1024", "output_format": "png"}
    if profile.transparent_background:
        fields["background"] = "transparent"
    if references:
        endpoint = "edits"
        boundary = uuid.uuid4().hex
        content_type = f"multipart/form-data; boundary={boundary}"
        parts = []
        for name, value in fields.items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
            )
        for index, reference in enumerate(references, 1):
            parts.extend([
                (f'--{boundary}\r\nContent-Disposition: form-data; name="image[]"; '
                 f'filename="reference-{index}.png"\r\nContent-Type: image/png\r\n\r\n').encode(),
                reference, b"\r\n",
            ])
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
    else:
        endpoint = "generations"
        content_type = "application/json"
        body = json.dumps(fields, ensure_ascii=False).encode()
    return Request(
        f"{profile.base_url}/images/{endpoint}", data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": content_type},
    )


class RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_id(headers, request):
    value = headers.get("x-request-id", "")
    key = request.get_header("Authorization").removeprefix("Bearer ")
    return value if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) and key not in value else None


def public_address(value):
    address = ip_address(value)
    if not address.is_global or address.is_multicast or address.is_reserved:
        return False
    return address.version == 4 or not (
        address.is_site_local or address.ipv4_mapped or address.sixtofour or address.teredo
        or any(address in network for network in NAT64_NETWORKS)
    )


class PublicImageConnection(HTTPSConnection):
    def __init__(self, host):
        self.tls_context = ssl.create_default_context()
        super().__init__(host, port=443, timeout=30, context=self.tls_context)

    def connect(self):
        endpoints = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        if not endpoints or any(not public_address(endpoint[4][0]) for endpoint in endpoints):
            raise ValueError("image download host must resolve to public IP addresses")
        last_error = None
        for family, kind, protocol, _, address in endpoints:
            sock = socket.socket(family, kind, protocol)
            try:
                sock.settimeout(self.timeout)
                # Connect to the validated IP while checking TLS for the URL's hostname.
                sock.connect(address)
                self.sock = self.tls_context.wrap_socket(sock, server_hostname=self.host)
                return
            except OSError as exc:
                sock.close()
                last_error = exc
        raise last_error


def download_image(value):
    if (not isinstance(value, str) or not value.isascii() or not value.isprintable()
            or len(value) > 16384 or any(char.isspace() for char in value)):
        raise ValueError("image download URL is invalid")
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.username is not None
                or "#" in value or "%" in url.hostname or url.port not in (None, 443)):
            raise ValueError
    except ValueError:
        raise ValueError("image download requires an HTTPS URL on port 443 without credentials or fragments") from None
    target = url.path or "/"
    if url.query:
        target += "?" + url.query
    try:
        # Direct GET to the validated host. No redirects, proxy or generation credentials.
        with closing(PublicImageConnection(url.hostname)) as connection:
            connection.request("GET", target, headers={"Accept": "image/png"})
            with connection.getresponse() as response:
                if response.status != 200:
                    raise ValueError(f"image download returned HTTP {response.status}")
                image = response.read(MAX_IMAGE_BYTES + 1)
    except (OSError, HTTPException):
        raise ValueError("image download connection failed or timed out") from None
    if len(image) > MAX_IMAGE_BYTES or not image.startswith(PNG_SIGNATURE):
        raise ValueError("image download did not return a PNG within the byte limit")
    return image


def receive_image(request):
    identifier = None
    try:
        with build_opener(RejectRedirects()).open(request, timeout=120) as response:
            identifier = request_id(response.headers, request)
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        status = exc.code
        identifier = request_id(exc.headers, request)
        exc.close()
        detail = f" (request ID {identifier})" if identifier else ""
        raise ImageRequestError(f"image service returned HTTP {status}{detail}", rejected=status in REJECTED_REQUESTS,
                                request_id=identifier) from None
    except (URLError, OSError, ValueError, HTTPException):
        raise ImageRequestError("image service connection failed or timed out", request_id=identifier) from None
    try:
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError
        items = json.loads(payload)["data"]
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
            raise ValueError
        item = items[0]
    except (ValueError, TypeError, KeyError):
        raise ImageRequestError("image service did not return one image result", request_id=identifier) from None
    encoded = item.get("b64_json")
    if encoded is not None and encoded != "":
        try:
            image = base64.b64decode(encoded, validate=True)
            if not image or len(image) > MAX_IMAGE_BYTES:
                raise ValueError
            return image, identifier
        except (binascii.Error, ValueError, TypeError):
            raise ImageRequestError("image service did not return one valid Base64 image", request_id=identifier) from None
    if item.get("url"):
        try:
            return download_image(item["url"]), identifier
        except ValueError as exc:
            raise ImageRequestError(str(exc), request_id=identifier) from None
    raise ImageRequestError("image service did not return b64_json or an image URL", request_id=identifier)
