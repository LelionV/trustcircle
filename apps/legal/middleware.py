"""
Blocks signed-in users from using the API until they accept the current terms.

Only the calls needed to sign in, read the terms, accept them, and load the
profile (so the apps know to show the terms) are allowed through.
"""
from django.http import JsonResponse
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError

from .services import pending_terms_for

API_PREFIX = "/api/v1/"
EXEMPT_PREFIXES = (
    "/api/v1/auth/",       # sign in, register, refresh, sign out
    "/api/v1/legal/",      # read and accept the terms
    "/api/v1/health/",
    "/api/v1/accounts/me/",
)


class TermsGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if (path.startswith(API_PREFIX) and not path.startswith(EXEMPT_PREFIXES)
                and request.META.get("HTTP_AUTHORIZATION", "").startswith("Bearer ")):
            pending = self._pending(request)
            if pending is not None:
                return JsonResponse({"error": {
                    "code": "terms_not_accepted",
                    "message": "Please read and accept the current terms and conditions to continue.",
                    "details": {"terms_version": pending.version, "terms_title": pending.title},
                    "request_id": getattr(request, "request_id", None),
                }}, status=403)
        return self.get_response(request)

    @staticmethod
    def _pending(request):
        try:
            result = JWTAuthentication().authenticate(request)
        except (AuthenticationFailed, TokenError):
            return None  # invalid tokens are rejected by the view's own authentication (InvalidToken is an AuthenticationFailed)
        if result is None:
            return None
        user, _token = result
        if not user.is_active:
            return None
        return pending_terms_for(user)
