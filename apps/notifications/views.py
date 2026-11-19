from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.views import APIView

from apps.common.api import ok, paginated, validated
from apps.common.permissions import HasPlatformPermission

from . import services
from .models import DeviceToken, Notification


def row(n):
    return {"id": n.pk, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link, "is_read": n.is_read,
            "created_at": n.created_at}


class NotificationsView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "notifications.view"

    @extend_schema(tags=["notifications"])
    def get(self, request):
        qs = Notification.objects.filter(user=request.user)
        if request.query_params.get("unread") == "1":
            qs = qs.filter(is_read=False)
        return paginated(self, request, qs, row)


class UnreadCountView(APIView):
    """Cheap endpoint the web app polls for the bell and chat badges."""

    permission_classes = [HasPlatformPermission]
    required_permission = "notifications.view"

    @extend_schema(tags=["notifications"])
    def get(self, request):
        from apps.accounts.permissions import has_permission

        chat = 0
        if has_permission(request.user, "chat.use") or has_permission(request.user, "admin.support.chat"):
            from apps.chat.services import unread_total

            chat = unread_total(request.user)
        return ok({"notifications": services.unread_count(request.user), "chat": chat})


class MarkReadView(APIView):
    permission_classes = [HasPlatformPermission]
    required_permission = "notifications.view"

    class Input(serializers.Serializer):
        ids = serializers.ListField(child=serializers.IntegerField(), required=False)

    @extend_schema(tags=["notifications"], request=Input)
    def post(self, request):
        d = validated(self.Input, request.data)
        n = services.mark_read(request.user, d.get("ids"))
        return ok({"marked": n, "unread": services.unread_count(request.user)})


class DeviceView(APIView):
    """The Flutter app registers its FCM token here after sign-in; DELETE on sign-out."""

    permission_classes = [HasPlatformPermission]
    required_permission = "notifications.view"

    class Input(serializers.Serializer):
        token = serializers.CharField(max_length=255)
        platform = serializers.ChoiceField(choices=["android", "ios", "web"])

    @extend_schema(tags=["notifications"], request=Input)
    def post(self, request):
        d = validated(self.Input, request.data)
        services.register_device(request.user, d["token"], d["platform"])
        return ok({"registered": True}, status=201)

    @extend_schema(tags=["notifications"], request=Input)
    def delete(self, request):
        token = request.data.get("token") or request.query_params.get("token", "")
        DeviceToken.objects.filter(user=request.user, token=token).delete()
        return ok({"registered": False})
