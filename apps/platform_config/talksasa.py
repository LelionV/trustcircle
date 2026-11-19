"""
TalkSasa bulk SMS over its REST API.

The base URL, sender ID and API key are set in Configuration > Payments & SMS.
Requests use the v3 API: POST <base_url>/sms/send with a bearer token and the
fields recipient, sender_id, type ("plain") and message. Check these names
against the API page in your TalkSasa dashboard before going live; the test
button in the admin screen sends one real message so you can confirm them.
"""
import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger("apps.sms")


class SmsError(RuntimeError):
    pass


def _post(cfg, path, payload):
    req = urllib.request.Request(
        cfg.base_url.rstrip("/") + "/" + path,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {cfg.key()}", "Accept": "application/json",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:  # noqa: S310 - base URL is set by an administrator
            return json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as exc:  # must come before OSError: HTTPError is a subclass of it
        raise SmsError(f"TalkSasa answered {exc.code}: {exc.read().decode(errors='replace')[:200]}") from exc
    except OSError as exc:
        raise SmsError(f"Couldn't reach TalkSasa: {exc}") from exc


def send_one(cfg, phone: str, message: str) -> dict:
    return _post(cfg, "sms/send", {
        "recipient": phone.lstrip("+"),
        "sender_id": cfg.sender_id,
        "type": "plain",
        "message": message,
    })


def send_bulk(cfg, phones, message: str) -> dict:
    """Send one message to many numbers. Failures are reported per number, not raised."""
    sent, failed = 0, []
    for phone in phones:
        try:
            send_one(cfg, phone, message)
            sent += 1
        except SmsError as exc:
            log.warning("TalkSasa send to %s failed: %s", phone, exc)
            failed.append({"phone": phone, "error": str(exc)})
    return {"sent": sent, "failed": failed}
