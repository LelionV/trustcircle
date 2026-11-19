"""
Private document uploads (KYC, loan documents).

Files are stored under PRIVATE_MEDIA_ROOT, which is never served directly.
They are only returned through views that check permissions. Each upload is
checked by size and by its first bytes (not just its name), and stored under
a random name.
"""
import os
import uuid

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from rest_framework import serializers

SIGNATURES = {
    b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", ".png"),
    b"%PDF-": ("application/pdf", ".pdf"),
}


def private_storage():
    """Callable so migrations don't record a machine-specific path."""
    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT, base_url=None)


def sniff(file):
    """Return (content_type, extension) from the file's first bytes, or (None, None)."""
    position = file.tell() if hasattr(file, "tell") else 0
    head = file.read(16)
    file.seek(position)
    for magic, info in SIGNATURES.items():
        if head.startswith(magic):
            return info
    return None, None


def random_path(folder, owner, filename):
    """e.g. kyc/<user id>/<random>.jpg — original names are never kept."""
    ext = os.path.splitext(filename)[1].lower()[:5] or ".bin"
    return f"{folder}/{owner}/{uuid.uuid4().hex}{ext}"


class PrivateDocumentField(serializers.FileField):
    """A FileField that only accepts JPEG, PNG or PDF under the size limit."""

    default_error_messages = {
        "too_large": "This file is larger than {max_mb} MB.",
        "bad_type": "Upload a JPG, PNG or PDF file.",
    }

    def to_internal_value(self, data):
        file = super().to_internal_value(data)
        limit = getattr(settings, "UPLOAD_MAX_BYTES", 5 * 1024 * 1024)
        if file.size > limit:
            self.fail("too_large", max_mb=limit // (1024 * 1024))
        content_type, ext = sniff(file)
        if content_type not in getattr(settings, "UPLOAD_ALLOWED_TYPES", ()):
            self.fail("bad_type")
        file.name = f"upload{ext}"
        return file
