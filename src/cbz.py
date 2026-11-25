"""Compatibility facade for the focused ``src.archives`` package."""
# ruff: noqa: F401

from src.archives.metadata import _comic_info, update_cbz
from src.archives.operations import (
    CLEAN_OUTPUT,
    IMAGE_EXTENSIONS,
    _chapter_archive_files,
    _remove_archived_image_folders,
    _remove_empty_chapter_folders,
    create_cbz_for_all,
    create_cbz_per_chapter,
    index_cbz_pages,
    set_clean_output,
)
from src.archives.ordering import _natural_key
