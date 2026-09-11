"""Only explicit form/server errors count as rejected submissions."""
import re

VALIDATION_ERRORS = r"""
const visible = e => {const r=e.getBoundingClientRect();const s=getComputedStyle(e);
    return r.width>0 && r.height>0 && s.display!=='none' && s.visibility!=='hidden';};
const errors = [...document.querySelectorAll('.ant-form-item-explain-error,.ant-message-error,.ant-notification-notice-error,.ant-alert-error,.ant-modal-confirm-error')]
    .filter(visible).map(e => ({text:(e.innerText||'').replace(/\s+/g,' ').trim(),
        field:e.closest('.ant-form-item')?.querySelector('input,textarea')?.id || ''}))
    .filter(e=>e.text).slice(0,10);
const headings = [...document.querySelectorAll('h1,h2,h3,[role="status"],[class*="title"],[class*="Title"]')]
    .filter(visible).filter(e => /^(?:(?:your )?(?:application|documents?|document verification|review) (?:was |has been )?(?:rejected|failed|not approved)|verification failed)[.!]?$/i
        .test((e.innerText||'').trim()));
for (const heading of headings) {
    const root = heading.closest('[role="dialog"],.ant-modal-content,.ant-modal-v2-content,[role="alert"]');
    errors.push({field:'document_review', text:((root || heading).innerText||'').replace(/\s+/g,' ').trim().slice(0,1000)});
}
return errors;
"""


class RKSubmissionRejected(RuntimeError):
    pass


class RKEmailCodeRejected(RKSubmissionRejected):
    pass


class RKSubmissionUnknown(RuntimeError):
    pass


def rejection_error(errors: list[dict]) -> RKSubmissionRejected | None:
    if not errors:
        return None
    messages = list(dict.fromkeys(e.get('text', '') for e in errors if e.get('text')))
    if not messages:
        return None
    email_only = all(
        ('emailcode' in e.get('field', '').lower() or re.search(r'(email|verification)\s+code', e.get('text', ''), re.I))
        and re.search(r'incorrect|invalid|expired|expire|wrong', e.get('text', ''), re.I)
        for e in errors
    )
    message = 'MEXC: ' + '; '.join(messages)
    return RKEmailCodeRejected(message) if email_only else RKSubmissionRejected(message)
