from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView

# The web app is plain ES modules + CSS: no inline scripts or styles, so a
# strict Content-Security-Policy is possible and blunts XSS.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data: blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)


class WebAppView(TemplateView):
    """Serves the single-page web app shell. All data comes from /api/v1/."""

    template_name = "web/index.html"

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        response["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response["Referrer-Policy"] = "same-origin"
        response["X-Content-Type-Options"] = "nosniff"
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


web_app = never_cache(WebAppView.as_view())
