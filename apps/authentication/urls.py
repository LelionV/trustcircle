from django.urls import path

from .views import (
    LoginView,
    LogoutView,
    OtpRequestView,
    OtpVerifyView,
    PasswordChangeView,
    PhoneView,
    RefreshView,
    RegisterView,
    VerifyView,
)

urlpatterns = [
    path("token/", LoginView.as_view(), name="token-obtain"),
    path("token/refresh/", RefreshView.as_view(), name="token-refresh"),
    path("token/verify/", VerifyView.as_view(), name="token-verify"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("register/", RegisterView.as_view(), name="register"),
    path("otp/request/", OtpRequestView.as_view(), name="otp-request"),
    path("otp/verify/", OtpVerifyView.as_view(), name="otp-verify"),
    path("phone/", PhoneView.as_view(), name="phone"),
    path("password/change/", PasswordChangeView.as_view(), name="password-change"),
]
