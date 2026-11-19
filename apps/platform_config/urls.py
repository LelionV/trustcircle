from django.urls import path

from . import views

urlpatterns = [
    path("admin/integrations/", views.IntegrationsView.as_view(), name="admin-integrations"),
    path("admin/integrations/gateways/<str:code>/", views.GatewayView.as_view(), name="admin-integration-gateway"),
    path("admin/integrations/sms/", views.SmsView.as_view(), name="admin-integration-sms"),
    path("admin/integrations/sms/test/", views.SmsTestView.as_view(), name="admin-integration-sms-test"),
]
