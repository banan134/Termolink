"""Operator settings API — docs/04 §Ustawienia (superadmin only)."""

from typing import Any

from django.core.mail import EmailMessage
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import audit
from apps.tenants.permissions import IsSuperadmin, current_user

from . import mail
from .exceptions import ApiError
from .models import MailSettings


def payload(row: MailSettings) -> dict[str, Any]:
    return {
        "enabled": row.enabled,
        "host": row.host,
        "port": row.port,
        "username": row.username,
        "has_password": bool(row.password_enc),
        "use_tls": row.use_tls,
        "use_ssl": row.use_ssl,
        "from_email": row.from_email,
        "timeout_s": row.timeout_s,
        "updated_at": row.updated_at,
        "last_test_at": row.last_test_at,
        "last_test_ok": row.last_test_ok,
        "last_test_error": row.last_test_error,
    }


class MailSettingsSerializer(serializers.Serializer[dict[str, Any]]):
    enabled = serializers.BooleanField(required=False)
    host = serializers.CharField(required=False, allow_blank=True, max_length=253)
    port = serializers.IntegerField(required=False, min_value=1, max_value=65535)
    username = serializers.CharField(required=False, allow_blank=True, max_length=200)
    password = serializers.CharField(
        required=False, allow_blank=True, max_length=500, trim_whitespace=False
    )
    use_tls = serializers.BooleanField(required=False)
    use_ssl = serializers.BooleanField(required=False)
    from_email = serializers.CharField(required=False, allow_blank=True, max_length=200)
    timeout_s = serializers.IntegerField(required=False, min_value=3, max_value=120)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("use_tls") and attrs.get("use_ssl"):
            raise ApiError(
                "validation_error",
                "Wybierz STARTTLS albo SSL, nie oba.",
                fields={"use_ssl": ["STARTTLS albo SSL"]},
            )
        return attrs


class MailSettingsView(APIView):
    permission_classes = [IsSuperadmin]

    @extend_schema(responses={200: None})
    def get(self, request: Request) -> Response:
        return Response(payload(MailSettings.load()))

    @extend_schema(request=MailSettingsSerializer, responses={200: None})
    def put(self, request: Request) -> Response:
        row = MailSettings.load()
        data = MailSettingsSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        for field in (
            "enabled",
            "host",
            "port",
            "username",
            "use_tls",
            "use_ssl",
            "from_email",
            "timeout_s",
        ):
            if field in v:
                setattr(row, field, v[field])
        if "password" in v:  # empty string clears; omitted keeps the stored one
            mail.set_password(row, v["password"])
        if row.enabled and not row.host:
            raise ApiError(
                "validation_error", "Podaj host SMTP.", fields={"host": ["wymagany, gdy włączone"]}
            )
        row.updated_at = timezone.now()
        row.save()
        mail.invalidate()
        audit(
            "settings.mail.updated",
            request=request._request,
            user=current_user(request),
            details={"host": row.host, "enabled": row.enabled},
        )
        return Response(payload(row))


class MailTestSerializer(serializers.Serializer[dict[str, str]]):
    to = serializers.EmailField()


class MailTestView(APIView):
    """Sends a test message with the *saved* settings; records the outcome on the row."""

    permission_classes = [IsSuperadmin]

    @extend_schema(request=MailTestSerializer, responses={200: None})
    def post(self, request: Request) -> Response:
        data = MailTestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = MailSettings.load()
        backend = mail.backend_for(row if row.enabled else None, fail_silently=False)
        message = EmailMessage(
            subject="Termolink — test poczty",
            body=(
                "To jest wiadomość testowa z Termolink. Jeśli ją widzisz, serwer pocztowy "
                "jest skonfigurowany poprawnie.\n\nTermolink · Wodmiar"
            ),
            from_email=(row.from_email or None) if row.enabled else None,
            to=[data.validated_data["to"]],
        )
        try:
            sent = backend.send_messages([message]) or 0
            ok, error = sent > 0, "" if sent > 0 else "serwer nie przyjął wiadomości"
        except Exception as exc:  # noqa: BLE001 — surfaced to the operator
            ok, error = False, f"{type(exc).__name__}: {exc}"[:500]
        row.last_test_at = timezone.now()
        row.last_test_ok = ok
        row.last_test_error = error
        row.save(update_fields=["last_test_at", "last_test_ok", "last_test_error"])
        audit(
            "settings.mail.tested",
            request=request._request,
            user=current_user(request),
            details={"to": data.validated_data["to"], "ok": ok, "error": error},
        )
        return Response({"ok": ok, "error": error, **payload(row)})
