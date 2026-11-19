"""
SMS delivery behind one function, so a real gateway can be added without
touching the verification code.

SMS_BACKEND = "console"  -> prints the message in the server log (development)
Add a branch here for a provider such as Africa's Talking when going live.
"""
import logging

from django.conf import settings

logger = logging.getLogger("apps.sms")


class SmsNotConfigured(RuntimeError):
    pass


def send_sms(phone: str, message: str) -> None:
    # An SMS account saved in Configuration > Payments & SMS takes priority (TalkSasa).
    from apps.platform_config.services import active_sms
    from apps.platform_config.talksasa import SmsError, send_one

    cfg = active_sms()
    if cfg is not None:
        try:
            send_one(cfg, phone, message)
        except SmsError as exc:
            logger.error("SMS to %s failed: %s", phone, exc)
            raise SmsNotConfigured(f"The text message couldn't be sent: {exc}") from exc
        return

    backend = getattr(settings, "SMS_BACKEND", "console")
    if backend == "console":
        logger.warning("SMS to %s: %s", phone, message)
        print(f"\n[SMS to {phone}] {message}\n", flush=True)
        return
    if backend == "locmem":  # tests
        outbox = getattr(send_sms, "outbox", [])
        outbox.append((phone, message))
        send_sms.outbox = outbox
        return
    raise SmsNotConfigured(f"SMS backend '{backend}' is not set up.")
