"""Transactional e-mails (Polish UI language). Links point at the SPA routes from docs/09."""

from django.conf import settings
from django.core.mail import send_mail


def _url(path: str) -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}{path}"


def send_password_reset(email: str, token: str) -> None:
    link = _url(f"/reset?token={token}")
    send_mail(
        subject="Termolink — reset hasła",
        message=(
            "Otrzymaliśmy prośbę o zresetowanie hasła do Termolink.\n\n"
            f"Ustaw nowe hasło: {link}\n\n"
            "Link jest ważny 30 minut i działa jednorazowo. Jeśli to nie Ty, zignoruj tę wiadomość."
        ),
        from_email=None,
        recipient_list=[email],
    )


def send_invitation(email: str, token: str, *, tenant_name: str | None) -> None:
    link = _url(f"/invite/{token}")
    where = f"do portalu klienta „{tenant_name}”" if tenant_name else "jako operator"
    send_mail(
        subject="Termolink — zaproszenie",
        message=(
            f"Zostałeś(-aś) zaproszony(-a) {where} w Termolink.\n\n"
            f"Załóż hasło i aktywuj konto: {link}\n\n"
            "Zaproszenie jest ważne 72 godziny i działa jednorazowo."
        ),
        from_email=None,
        recipient_list=[email],
    )
