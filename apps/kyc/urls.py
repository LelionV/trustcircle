from django.urls import path

from . import views

urlpatterns = [
    path("kyc/me/", views.MyKycView.as_view(), name="kyc-me"),
    path("kyc/submissions/<uuid:pk>/files/<str:field>/", views.KycFileView.as_view(), name="kyc-file"),
    path("admin/kyc/", views.AdminKycListView.as_view(), name="admin-kyc"),
    path("admin/kyc/<uuid:pk>/", views.AdminKycDetailView.as_view(), name="admin-kyc-detail"),
    path("admin/kyc/<uuid:pk>/approve/", views.AdminKycApproveView.as_view(), name="admin-kyc-approve"),
    path("admin/kyc/<uuid:pk>/reject/", views.AdminKycRejectView.as_view(), name="admin-kyc-reject"),
]
