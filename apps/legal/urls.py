from django.urls import path

from . import views

urlpatterns = [
    path("legal/current/", views.CurrentTermsView.as_view(), name="legal-current"),
    path("legal/accept/", views.AcceptTermsView.as_view(), name="legal-accept"),
    path("admin/terms/", views.AdminTermsView.as_view(), name="admin-terms"),
]
