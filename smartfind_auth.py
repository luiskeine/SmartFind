"""Email verification and app-role resolution for the OIDC login flow."""
import hashlib
import secrets
import uuid


def create_guest_credentials():
    """Create a guest ID and a high-entropy recovery code; persist only its digest."""
    recovery_code = secrets.token_urlsafe(24)
    code_hash = hashlib.sha256(recovery_code.encode("ascii")).hexdigest()
    return uuid.uuid4().hex, recovery_code, code_hash


def guest_code_digest(recovery_code):
    """Return a recovery-code digest, rejecting malformed or implausible input."""
    code = str(recovery_code or "").strip()
    if not 30 <= len(code) <= 64 or not code.isascii() or not all(
            character.isalnum() or character in "-_" for character in code):
        return None
    return hashlib.sha256(code.encode("ascii")).hexdigest()

def resolve_role(email, email_verified, student_domains, admin_emails):
    """Return admin/student for an explicitly allowed, verified identity; else None."""
    normalized_email = str(email or "").strip().casefold()
    if not normalized_email or email_verified is not True or "@" not in normalized_email:
        return None

    admins = {str(value).strip().casefold() for value in admin_emails if str(value).strip()}
    if normalized_email in admins:
        return "admin"

    domain = normalized_email.rsplit("@", 1)[1]
    allowed_domains = {
        str(value).strip().lstrip("@").casefold()
        for value in student_domains
        if str(value).strip()
    }
    return "student" if domain in allowed_domains else None
