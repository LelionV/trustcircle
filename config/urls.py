from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

admin.site.site_header = "P2P Lending Administration"
admin.site.site_title = "P2P Lending Admin"

api_v1 = [
    path("", include("apps.common.urls")),
    path("auth/", include("apps.authentication.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.loans.urls")),
    path("", include("apps.kyc.urls")),
    path("", include("apps.engine_urls")),
    path("", include("apps.money_urls")),
    path("admin/", include("apps.administration.urls")),
    path("", include("apps.legal.urls")),
    path("", include("apps.platform_config.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include((api_v1, "api"), namespace="v1")),
    # OpenAPI / Swagger
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    # Web application (single page, consumes /api/v1 like the mobile app)
    path("", include("apps.web.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
