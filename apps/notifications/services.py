"""
notify(user, kind, title, body, link) — the one call every module uses.

* In-app: always (a Notification row; the web app polls the unread count).
* Push: sent to the user's registered phones when FCM is configured
  (settings.FCM_CREDENTIALS_FILE). Without it, push is skipped and logged.
* Email: for the kinds in EMAIL_KINDS when settings.NOTIFICATION_EMAILS is on.

Delivery problems never break the business action that triggered them:
push and email run after the database transaction commits, and errors are
logged rather than raised.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import DeviceToken, Notification

log = logging.getLogger(__name__)

EMAIL_KINDS = {
    "deposit_confirmed", "withdrawal_completed", "withdrawal_failed", "loan_disbursed", "loan_completed",
    "loan_defaulted", "guarantee_requested", "guarantee_claimed", "payment_overdue", "extension_decided",
    "dispute_updated", "kyc_decided",
}


def notify(user, kind, title, body, link="", *, dedupe_key=""):
    """Create an in-app notification (once per dedupe_key) and queue push/email."""
    if user is None:
        return None
    try:
        with transaction.atomic():
            note = Notification.objects.create(user=user, kind=kind, title=title[:120], body=body, link=link[:200],
                                               dedupe_key=dedupe_key[:120])
    except IntegrityError:
        return None  # already sent
    transaction.on_commit(lambda: _deliver(note.pk))
    return note


def _deliver(notification_id):
    note = Notification.objects.select_related("user").filter(pk=notification_id).first()
    if note is None:
        return
    try:
        send_push(note)
    except Exception:  # noqa: BLE001
        log.exception("Push notification %s failed", note.pk)
    if note.kind in EMAIL_KINDS and getattr(settings, "NOTIFICATION_EMAILS", False) and note.user.email:
        try:
            send_mail(note.title, f"{note.body}\n\n— P2P Lend", settings.DEFAULT_FROM_EMAIL, [note.user.email])
        except Exception:  # noqa: BLE001
            log.exception("Notification email %s failed", note.pk)


_fcm_app = None


def send_push(note):
    """
    Send to every registered device via Firebase Admin SDK. Needs
    `pip install firebase-admin` and FCM_CREDENTIALS_FILE (a service-account
    JSON). Without them push is skipped; in-app notifications still work.
    """
    global _fcm_app
    path = getattr(settings, "FCM_CREDENTIALS_FILE", "")
    tokens = list(DeviceToken.objects.filter(user=note.user).values_list("token", flat=True))
    if not path or not tokens:
        return 0
    try:
        import firebase_admin
        from firebase_admin import credentials, messaging
    except ImportError:
        log.warning("FCM_CREDENTIALS_FILE is set but firebase-admin isn't installed; push skipped.")
        return 0
    if _fcm_app is None:
        _fcm_app = firebase_admin.initialize_app(credentials.Certificate(path))
    message = messaging.MulticastMessage(
        tokens=tokens,
        notification=messaging.Notification(title=note.title, body=note.body[:240]),
        data={"kind": note.kind, "link": note.link, "id": str(note.pk)},
    )
    result = messaging.send_each_for_multicast(message)
    for token, resp in zip(tokens, result.responses):
        if not resp.success and "registration-token-not-registered" in str(resp.exception):
            DeviceToken.objects.filter(token=token).delete()
    return result.success_count


def notify_admins(permission, kind, title, body, link=""):
    """Tell every active staff member who holds `permission`."""
    from apps.accounts.models import Role, User
    from apps.accounts.permissions import has_permission

    for admin in User.objects.filter(role=Role.ADMIN, is_active=True):
        if has_permission(admin, permission):
            notify(admin, kind, title, body, link)


def unread_count(user):
    return Notification.objects.filter(user=user, is_read=False).count()


def mark_read(user, ids=None):
    qs = Notification.objects.filter(user=user, is_read=False)
    if ids is not None:
        qs = qs.filter(pk__in=ids)
    return qs.update(is_read=True, read_at=timezone.now())


def register_device(user, token, platform):
    DeviceToken.objects.filter(token=token).exclude(user=user).delete()
    obj, _ = DeviceToken.objects.update_or_create(token=token, defaults={"user": user, "platform": platform})
    return obj
