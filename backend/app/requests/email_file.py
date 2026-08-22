"""Read an email the auditor forwarded, rather than making them retype it.

Copy-pasting a chain out of Outlook loses the sender, the date, and — the part that actually
costs a round — the attachments. An auditor who forwards the taxpayer's reply is holding all
three; asking them to paste the words and then separately hunt down and upload the two
spreadsheets that came with it is asking them to do the filing by hand.

So: drop the `.eml` in, and the message goes on the chain while its attachments go on the round
as documents, read by the same extractor as any other upload. That is the whole feature.

`.eml` (RFC 5322) is parsed with the standard library, which is why this file has no
dependencies. `.msg` is Outlook's proprietary OLE format and needs a third-party library; when
that library is not installed we say so plainly rather than half-reading the file — an email
whose body was silently dropped is worse than one that was refused.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from email import message_from_bytes, policy
from email.utils import parsedate_to_datetime

# Attachment types worth putting on the case. An email signature's logo is not evidence, and
# filing it as a received document would put "image001.png" in the completeness check.
TABULAR = (".xlsx", ".xlsm", ".xls", ".csv", ".tsv")
DOCUMENTS = TABULAR + (".pdf", ".doc", ".docx")


@dataclass
class ParsedEmail:
    subject: str = ""
    sender: str = ""
    recipient: str = ""
    sent_at: str = ""
    body: str = ""
    attachments: list[tuple[str, bytes]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)   # inline images, signatures, oddities
    note: str = ""

    @property
    def ok(self) -> bool:
        # Headers, not just content. Python's email parser is permissive enough to read a block
        # of arbitrary bytes as a body with no headers at all, and filing that as something the
        # taxpayer wrote would put binary noise on the case file in their name. Every real
        # message carries at least one of these.
        addressed = any((self.sender, self.recipient, self.subject, self.sent_at))
        return addressed and bool(self.body.strip() or self.attachments)


def is_email_file(filename: str) -> bool:
    return (filename or "").lower().rsplit(".", 1)[-1] in ("eml", "msg")


def _text_of(msg) -> str:
    """The readable body: plain text where it exists, HTML stripped where it does not."""
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    text = part.get_content()
    if part.get_content_subtype() == "html":
        import re

        text = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
        text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                    .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
        text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse(filename: str, data: bytes) -> ParsedEmail:
    """Never raises: an email we cannot read is a note on the case, not a 500."""
    ext = (filename or "").lower().rsplit(".", 1)[-1]
    if ext == "msg":
        return _parse_msg(data)
    try:
        msg = message_from_bytes(data, policy=policy.default)
    except Exception as exc:                        # noqa: BLE001 - report, do not crash
        return ParsedEmail(note=f"Could not be read as an email: {type(exc).__name__}.")

    sent = ""
    raw_date = msg.get("Date")
    if raw_date:
        try:
            sent = parsedate_to_datetime(raw_date).date().isoformat()
        except (TypeError, ValueError):
            sent = ""

    out = ParsedEmail(
        subject=str(msg.get("Subject") or "").strip(),
        sender=str(msg.get("From") or "").strip(),
        recipient=str(msg.get("To") or "").strip(),
        sent_at=sent,
        body=_text_of(msg),
    )
    for part in msg.iter_attachments():
        name = part.get_filename() or ""
        if not name:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        if name.lower().endswith(DOCUMENTS):
            out.attachments.append((name, payload))
        else:
            out.skipped.append(name)
    if out.skipped:
        out.note = (f"{len(out.skipped)} attachment"
                    f"{'' if len(out.skipped) == 1 else 's'} not filed as documents "
                    f"({', '.join(out.skipped[:4])}) — signatures and images are not evidence.")
    return out


def _parse_msg(data: bytes) -> ParsedEmail:
    """Outlook's own format. Honest about needing a library rather than half-reading it."""
    try:
        import extract_msg                          # type: ignore
    except ImportError:
        return ParsedEmail(
            note="This is an Outlook .msg file, which needs a reader this deployment does not "
                 "have installed. Save it as .eml from Outlook, or paste the chain instead.")
    import io

    try:
        m = extract_msg.Message(io.BytesIO(data))
        out = ParsedEmail(subject=m.subject or "", sender=m.sender or "",
                          recipient=m.to or "", sent_at=str(m.date or "")[:10],
                          body=(m.body or "").strip())
        for att in m.attachments:
            name = att.longFilename or att.shortFilename or ""
            if name.lower().endswith(DOCUMENTS):
                out.attachments.append((name, att.data))
            elif name:
                out.skipped.append(name)
        return out
    except Exception as exc:                        # noqa: BLE001
        return ParsedEmail(note=f"Could not be read as an Outlook message: {type(exc).__name__}.")
