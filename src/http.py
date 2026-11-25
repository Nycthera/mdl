"""Compatibility facade for the focused HTTP implementation in ``src.network``."""
# ruff: noqa: F401

from src.network.client import (
    DEFAULT_CONNECTOR_KWARGS,
    DEFAULT_TIMEOUT,
    HEAD_TIMEOUT,
    build_session,
    get_default_timeout,
    set_default_timeout,
)
from src.network.downloads import (
    CHUNK_SIZE,
    _append_chunk_sync,
    _write_file_sync,
    download_image_streaming,
    make_request,
)
from src.network.retry import (
    _CF_BODY_KEYWORDS,
    _CF_ORIGIN_STATUSES,
    HostConcurrencyCap,
    classify_failure,
    compute_backoff,
    get_host_cap,
)
from src.network.urls import PublicAddressResolver, redirect_target, validate_http_url
