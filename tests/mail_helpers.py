"""
Helpers shared by the tests that need mail messages and mailboxes (spec 007).

Messages are built with ``email.message.EmailMessage`` and mailboxes are messages joined with
separator lines, so nothing here is a real message. Addresses are invented (``example.org``,
``example.com``; RNF-06).
"""

from __future__ import annotations

from email.message import EmailMessage

# The separator line Thunderbird writes between the messages of a mailbox.
_SEPARATOR = b"From - Tue Oct 28 10:00:00 2025\n"


def build_eml(*attachments: tuple[str | None, str, bytes]) -> bytes:
    """
    Build a mail message that carries attachments, the way a provider's report mail does.

    Args:
        *attachments (tuple[str | None, str, bytes]): For each attachment, its file name (``None``
            for a part with no name), the subtype of its ``application/*`` content type and its
            bytes. None at all gives a plain message.

    Returns:
        bytes: The message as stored in an ``.eml``.
    """
    message = EmailMessage()
    message["From"] = "noreply@example.org"
    message["To"] = "dmarc@example.com"
    message["Subject"] = "Report domain: example.com"
    message.set_content("The aggregate report is attached.")
    for name, subtype, data in attachments:
        message.add_attachment(data, maintype="application", subtype=subtype, filename=name)
    return message.as_bytes()


def build_mbox(*messages: bytes) -> bytes:
    """
    Join messages into a mailbox, each one after a separator line.

    Args:
        *messages (bytes): The messages, each ending in a line break.

    Returns:
        bytes: The mailbox.
    """
    return b"".join(_SEPARATOR + message for message in messages)
