"""Send refund request notifications through the CoordinAIte support mailbox."""

import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import Settings
from app.db.models import RefundRequest, User


def send_refund_request_email(
    request: RefundRequest,
    user: User,
    settings: Settings,
) -> bool:
    """Return False when SMTP is not configured; never spoof the customer's From address."""
    if not settings.smtp_username or not settings.smtp_password:
        return False

    message = EmailMessage()
    message["Subject"] = f"CoordinAIte refund request #{request.id}"
    message["From"] = settings.support_email
    message["To"] = settings.support_email
    message["Reply-To"] = user.email
    message["X-CoordinAIte-Account-ID"] = str(user.id)
    message.set_content(
        "A user submitted a Tier 2 refund request for owner review.\n\n"
        f"Request ID: {request.id}\n"
        f"Account ID: {user.id}\n"
        f"Username: {user.username}\n"
        f"Registered email: {user.email}\n"
        f"Submitted at (UTC): {request.created_at.isoformat() if request.created_at else 'unknown'}\n\n"
        "Reason provided by the user:\n"
        f"{request.reason}\n\n"
        "Review and approve or deny the request from the owner-only Users page in CoordinAIte."
    )

    context = ssl.create_default_context()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=12) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)
    return True
