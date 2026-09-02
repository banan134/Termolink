"""Auth API — docs/04 §Auth. Views validate input and call services."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from . import services
from .models import UiTheme, User


class LoginThrottle(AnonRateThrottle):
    scope = "login"


class LoginSerializer(serializers.Serializer[dict[str, str]]):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False)
    totp = serializers.CharField(required=False, allow_blank=True, max_length=16)


class MeSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    role = serializers.CharField()
    tenant = serializers.DictField(allow_null=True)
    totp_enabled = serializers.BooleanField()
    allowed_tenants = serializers.ListField(child=serializers.UUIDField())
    ui_theme = serializers.ChoiceField(choices=UiTheme.choices)


class MePatchSerializer(serializers.Serializer[dict[str, str]]):
    ui_theme = serializers.ChoiceField(choices=UiTheme.choices)


class PasswordChangeSerializer(serializers.Serializer[dict[str, str]]):
    old_password = serializers.CharField(trim_whitespace=False)
    new_password = serializers.CharField(trim_whitespace=False)

    def validate_new_password(self, value: str) -> str:
        user = self.context.get("user")
        try:
            validate_password(value, user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value


class ReauthSerializer(serializers.Serializer[dict[str, str]]):
    password = serializers.CharField(trim_whitespace=False)
    totp = serializers.CharField(required=False, allow_blank=True, max_length=16)


class TotpSetupSerializer(serializers.Serializer[dict[str, str]]):
    secret = serializers.CharField()
    otpauth_url = serializers.CharField()


class TotpEnableSerializer(serializers.Serializer[dict[str, str]]):
    code = serializers.CharField(max_length=16)


class TotpBackupCodesSerializer(serializers.Serializer[dict[str, object]]):
    backup_codes = serializers.ListField(child=serializers.CharField())


class TotpDisableSerializer(serializers.Serializer[dict[str, str]]):
    password = serializers.CharField(trim_whitespace=False)
    code = serializers.CharField(max_length=16)


class ResetRequestSerializer(serializers.Serializer[dict[str, str]]):
    email = serializers.EmailField()


class NewPasswordMixin(serializers.Serializer[dict[str, str]]):
    def validate_password(self, value: str) -> str:
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value


class ResetSerializer(NewPasswordMixin):
    token = serializers.CharField(max_length=128)
    password = serializers.CharField(trim_whitespace=False)


class InvitationAcceptSerializer(NewPasswordMixin):
    token = serializers.CharField(max_length=128)
    password = serializers.CharField(trim_whitespace=False)


class PasswordResetThrottle(AnonRateThrottle):
    scope = "password_reset"


class SessionSerializer(serializers.Serializer[dict[str, object]]):
    id = serializers.UUIDField()
    ip = serializers.IPAddressField(allow_null=True)
    user_agent = serializers.CharField()
    created_at = serializers.DateTimeField()
    last_seen_at = serializers.DateTimeField()
    current = serializers.BooleanField()


class LoginView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    @extend_schema(request=LoginSerializer, responses={200: MeSerializer}, auth=[])
    def post(self, request: Request) -> Response:
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = services.login_user(
            request._request,
            email=data.validated_data["email"],
            password=data.validated_data["password"],
            totp_code=data.validated_data.get("totp") or None,
        )
        return Response({"user": services.me_payload(request._request, user)})


class LogoutView(APIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        services.logout_user(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    @extend_schema(responses=MeSerializer)
    def get(self, request: Request) -> Response:
        return Response(services.me_payload(request._request, _user(request)))

    @extend_schema(request=MePatchSerializer, responses=MeSerializer)
    def patch(self, request: Request) -> Response:
        data = MePatchSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = services.update_profile(_user(request), ui_theme=data.validated_data["ui_theme"])
        return Response(services.me_payload(request._request, user))


class PasswordChangeView(APIView):
    @extend_schema(request=PasswordChangeSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        user = _user(request)
        data = PasswordChangeSerializer(data=request.data, context={"user": user})
        data.is_valid(raise_exception=True)
        services.change_password(
            request._request,
            user,
            old=data.validated_data["old_password"],
            new=data.validated_data["new_password"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class SessionListView(APIView):
    @extend_schema(responses=SessionSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response({"results": services.list_sessions(request._request, _user(request))})


class SessionDetailView(APIView):
    @extend_schema(responses={204: None})
    def delete(self, request: Request, session_id: str) -> Response:
        services.revoke_session(request._request, _user(request), session_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReauthView(APIView):
    @extend_schema(request=ReauthSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        data = ReauthSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.reauth(
            request._request,
            _user(request),
            password=data.validated_data["password"],
            totp_code=data.validated_data.get("totp") or None,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class TotpSetupView(APIView):
    @extend_schema(request=None, responses=TotpSetupSerializer)
    def post(self, request: Request) -> Response:
        return Response(services.totp_setup(request._request, _user(request)))


class TotpEnableView(APIView):
    @extend_schema(request=TotpEnableSerializer, responses=TotpBackupCodesSerializer)
    def post(self, request: Request) -> Response:
        data = TotpEnableSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        codes = services.totp_enable(
            request._request, _user(request), code=data.validated_data["code"]
        )
        return Response({"backup_codes": codes})


class TotpDisableView(APIView):
    @extend_schema(request=TotpDisableSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        data = TotpDisableSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.totp_disable(
            request._request,
            _user(request),
            password=data.validated_data["password"],
            code=data.validated_data["code"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetRequestView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetThrottle]

    @extend_schema(request=ResetRequestSerializer, responses={204: None}, auth=[])
    def post(self, request: Request) -> Response:
        data = ResetRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.request_password_reset(data.validated_data["email"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(request=ResetSerializer, responses={204: None}, auth=[])
    def post(self, request: Request) -> Response:
        data = ResetSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.reset_password(
            token=data.validated_data["token"], new_password=data.validated_data["password"]
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvitationAcceptView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]

    @extend_schema(request=InvitationAcceptSerializer, responses={200: MeSerializer}, auth=[])
    def post(self, request: Request) -> Response:
        data = InvitationAcceptSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = services.accept_invitation(
            request._request,
            token=data.validated_data["token"],
            password=data.validated_data["password"],
        )
        return Response({"user": services.me_payload(request._request, user)})


def _user(request: Request) -> User:
    user = request.user
    assert isinstance(user, User)
    return user
