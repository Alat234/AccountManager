import imaplib
import email
import email.header
import email.utils
import datetime
import logging
import re
import ssl
import os
import sys
import certifi  # Додаємо цей пакет

logger = logging.getLogger(__name__)
DEFAULT_SCAN_LIMIT = 25
GMAIL_SPAM_FOLDER = "[Gmail]/Spam"


def decode_str(header_value):
    if not header_value: return ""
    from email.header import decode_header
    try:
        decoded_list = decode_header(header_value)
        res = ""
        for decoded_bytes, charset in decoded_list:
            if isinstance(decoded_bytes, bytes):
                res += decoded_bytes.decode(charset or 'utf-8', errors='ignore')
            else:
                res += str(decoded_bytes)
        return res
    except:
        return str(header_value)


def _extract_code_from_message(msg, target_lower):
    """Повертає 6-значний код MEXC з листа або None. Логіка розпізнавання незмінна."""
    # Заголовки
    msg_subject = decode_str(msg.get("Subject", "")).lower()
    msg_to = str(msg.get("To", "")).lower()
    msg_from = str(msg.get("From", "")).lower()
    msg_delivered = str(msg.get("Delivered-To", "")).lower()

    is_exchange_header = 'mexc' in msg_subject or 'mexc' in msg_from
    is_for_target_header = (target_lower in msg_to) or (target_lower in msg_delivered)

    # 1. Швидка перевірка теми
    if is_exchange_header and is_for_target_header:
        match_subj = re.search(r'(?<![#a-zA-Z0-9])\d{6}(?![a-zA-Z0-9])', msg_subject)
        if match_subj:
            return match_subj.group(0)

    # 2. Повна перевірка тіла
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() in ["text/plain", "text/html"]:
                try:
                    body += part.get_payload(decode=True).decode('utf-8', errors='ignore')
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
        except Exception:
            pass

    body_lower = body.lower()
    is_exchange = is_exchange_header or ('mexc' in body_lower)
    is_for_target = is_for_target_header or (target_lower in body_lower)

    if is_exchange and is_for_target:
        clean_body = re.sub(r'<[^>]+>', ' ', body)
        clean_body = re.sub(r'#[a-fA-F0-9]{6}', ' ', clean_body)
        match_body = re.search(r'(?<![#a-zA-Z0-9])\d{6}(?![a-zA-Z0-9])', clean_body)
        if match_body:
            return match_body.group(0)
    return None


def _format_date(msg):
    try:
        timestamp = _message_timestamp(msg)
        if timestamp is None:
            return "Невідомо"
        local_date = datetime.datetime.fromtimestamp(timestamp)
        return local_date.strftime("%d.%m %H:%M")
    except Exception:
        return "Невідомо"


def _message_timestamp(msg):
    try:
        parsed = email.utils.parsedate_to_datetime(msg.get("Date", ""))
        if parsed is None:
            return None
        return parsed.timestamp()
    except Exception:
        return None


def _mask_email(email_value):
    if not email_value or "@" not in email_value:
        return "***"
    name, domain = email_value.split("@", 1)
    if len(name) <= 1:
        return f"{name}***@{domain}"
    return f"{name[0]}***{name[-1]}@{domain}"


def _connect_mail(imap_server, user, password):
    os.environ['SSL_CERT_FILE'] = certifi.where()
    context = ssl.create_default_context(cafile=certifi.where())
    mail = imaplib.IMAP4_SSL(imap_server, port=993, ssl_context=context)
    mail.login(user, password)
    return mail


def _decode_imap_text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def _extract_folder_name(list_item):
    decoded = _decode_imap_text(list_item).strip()
    match = re.search(r'"[^"]*"\s+(?P<name>.+)$', decoded)
    if not match:
        return decoded.strip('"')

    name = match.group("name").strip()
    if name.startswith('"') and name.endswith('"'):
        name = name[1:-1].replace(r'\"', '"').replace(r"\\", "\\")
    return name


def _extract_folder_flags(list_item):
    decoded = _decode_imap_text(list_item)
    match = re.match(r'\((?P<flags>[^)]*)\)', decoded)
    if not match:
        return []
    return [flag.strip().lower() for flag in match.group("flags").split() if flag.strip()]


def _discover_imap_folders(mail):
    status, folder_data = mail.list()
    if status != "OK":
        logger.warning("IMAP LIST failed with status=%s", status)
        return []

    folders = []
    for item in folder_data or []:
        if not item:
            continue
        name = _extract_folder_name(item)
        flags = _extract_folder_flags(item)
        folders.append({"name": name, "flags": flags})

    logger.info("IMAP folders discovered: %s", folders)
    return folders


def _folder_priority(folder):
    name = folder["name"].lower()
    flags = folder["flags"]
    if folder["name"].lower() == "inbox":
        return 0
    if "\\junk" in flags or name == GMAIL_SPAM_FOLDER.lower() or "spam" in name:
        return 1
    if "junk" in name or "bulk" in name:
        return 2
    if "\\trash" in flags or "trash" in name:
        return 3
    if "\\all" in flags or "all mail" in name:
        return 4
    return 99


def _select_mexc_code_folders(discovered_folders):
    selected = []
    seen = set()

    def add_folder(name, flags=None):
        if not name:
            return
        key = name.lower()
        if key in seen:
            return
        seen.add(key)
        selected.append({"name": name, "flags": flags or []})

    add_folder("inbox")
    add_folder(GMAIL_SPAM_FOLDER, ["\\junk"])

    for folder in sorted(discovered_folders, key=_folder_priority):
        if _folder_priority(folder) < 99:
            add_folder(folder["name"], folder["flags"])

    logger.info("IMAP folders selected for MEXC code scan: %s", selected)
    return selected


def _select_folder(mail, folder):
    candidates = [folder]
    if not (folder.startswith('"') and folder.endswith('"')):
        candidates.append(f'"{folder}"')

    for candidate in candidates:
        try:
            status, _ = mail.select(candidate, readonly=True)
        except imaplib.IMAP4.error:
            continue
        if status == "OK":
            return True
    return False


def _fetch_mexc_codes_from_selected_folder(
    mail,
    target_email,
    scan_limit=DEFAULT_SCAN_LIMIT,
    not_before_ts=None,
    ignored_codes=None,
):
    status, messages = mail.search(None, 'ALL')
    if status != "OK" or not messages or not messages[0]:
        return {"data": [], "checked": 0}

    mail_ids = messages[0].split()
    if not mail_ids:
        return {"data": [], "checked": 0}

    latest_ids = mail_ids[-scan_limit:]
    target_lower = target_email.lower()

    res, msg_data = mail.fetch(b','.join(latest_ids), '(BODY.PEEK[])')
    if res != "OK":
        return {"data": [], "checked": len(latest_ids)}

    messages_parsed = []
    for part in msg_data:
        if isinstance(part, tuple):
            try:
                messages_parsed.append(email.message_from_bytes(part[1]))
            except Exception:
                pass

    ignored_codes = set(ignored_codes or [])
    skipped_old = 0
    skipped_ignored = 0
    for msg in reversed(messages_parsed):
        msg_ts = _message_timestamp(msg)
        if not_before_ts is not None and (msg_ts is None or msg_ts < not_before_ts):
            skipped_old += 1
            continue
        code = _extract_code_from_message(msg, target_lower)
        if code and code in ignored_codes:
            skipped_ignored += 1
            continue
        if code:
            return {
                "data": [{
                    "code": code,
                    "time": _format_date(msg),
                    "timestamp": msg_ts,
                }],
                "checked": len(latest_ids),
                "skipped_old": skipped_old,
                "skipped_ignored": skipped_ignored,
            }

    return {
        "data": [],
        "checked": len(latest_ids),
        "skipped_old": skipped_old,
        "skipped_ignored": skipped_ignored,
    }


def fetch_mexc_codes(
    imap_server,
    user,
    password,
    target_email,
    limit=1,
    folder='inbox',
    scan_limit=DEFAULT_SCAN_LIMIT,
    not_before_ts=None,
    ignored_codes=None,
):
    mail = None
    try:
        mail = _connect_mail(imap_server, user, password)
        if not _select_folder(mail, folder):
            return {"data": []}
        result = _fetch_mexc_codes_from_selected_folder(
            mail,
            target_email,
            scan_limit=scan_limit,
            not_before_ts=not_before_ts,
            ignored_codes=ignored_codes,
        )
        return {"data": result.get("data", [])[:limit]}

    except Exception as e:
        # Виводимо ТИП помилки для діагностики
        return {"error": f"Помилка {type(e).__name__}: {str(e)}"}
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass


def fetch_mexc_codes_all_folders(
    imap_server,
    user,
    password,
    target_email,
    limit=1,
    scan_limit=DEFAULT_SCAN_LIMIT,
    not_before_ts=None,
    ignored_codes=None,
):
    mail = None
    errors = []
    checked_folders = []

    try:
        mail = _connect_mail(imap_server, user, password)
        discovered = _discover_imap_folders(mail)
        folders = _select_mexc_code_folders(discovered)

        for folder in folders:
            name = folder["name"]
            if not _select_folder(mail, name):
                logger.info("IMAP folder unavailable for MEXC scan: %s", name)
                continue

            result = _fetch_mexc_codes_from_selected_folder(
                mail,
                target_email,
                scan_limit=scan_limit,
                not_before_ts=not_before_ts,
                ignored_codes=ignored_codes,
            )
            checked = result.get("checked", 0)
            checked_folders.append({
                "folder": name,
                "checked": checked,
                "skipped_old": result.get("skipped_old", 0),
                "skipped_ignored": result.get("skipped_ignored", 0),
            })
            logger.info(
                "MEXC code scan folder=%s checked=%s skipped_old=%s skipped_ignored=%s target=%s found=%s",
                name,
                checked,
                result.get("skipped_old", 0),
                result.get("skipped_ignored", 0),
                _mask_email(target_email),
                bool(result.get("data")),
            )
            if result.get("data"):
                return {
                    "data": result["data"][:limit],
                    "folders_checked": checked_folders,
                }

        return {"data": [], "folders_checked": checked_folders}
    except Exception as e:
        errors.append(f"Помилка {type(e).__name__}: {str(e)}")
        return {"error": "\n".join(errors), "folders_checked": checked_folders}
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass
