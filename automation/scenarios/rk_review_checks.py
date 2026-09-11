"""Positive, section-scoped RK prerequisite checks."""

REVIEW_CHECKS_SCRIPT = r"""
const visible = e => !!e && e.getBoundingClientRect().width > 0
    && e.getBoundingClientRect().height > 0 && getComputedStyle(e).visibility !== 'hidden'
    && getComputedStyle(e).display !== 'none';
const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
function check(title) {
    const label = [...document.querySelectorAll('label')].find(e => visible(e)
        && norm(e.textContent) === title);
    const root = label?.closest('[class*="fileWrapper"]');
    if (!root) return {found: false, checked: false, hasStartButton: false};
    const hasStartButton = [...root.querySelectorAll('button,a,[role="button"]')]
        .some(e => visible(e) && /\b(start|begin|verify|complete|retry)\b/.test(norm(e.textContent)));
    const markers = [...root.querySelectorAll(
        'input[type="checkbox"], [role="checkbox"], [class*="statusTag"], '
        + '.ant-tag-v2-success, .ant-tag-success, svg[data-icon]')];
    const checked = markers.some(e => {
        if (!visible(e)) return false;
        if (e.matches('input[type="checkbox"]')) return e.checked;
        if (e.getAttribute('role') === 'checkbox') return e.getAttribute('aria-checked') === 'true';
        const text = norm(e.textContent);
        if (/\b(not|incomplete|pending|failed|unverified)\b/.test(text)) return false;
        const icon = e.matches('svg') ? e : e.querySelector('svg');
        const isCheck = /check/i.test(icon?.getAttribute('data-icon') || '');
        const successTag = e.classList.contains('ant-tag-v2-success') || e.classList.contains('ant-tag-success');
        return successTag && (isCheck || /^(completed|verified|passed|successful|success)$/.test(text));
    });
    return {found: true, checked: checked && !hasStartButton, hasStartButton};
}
return {facial: check('complete facial recognition'), kyc: check('complete advanced kyc verification')};
"""


def require_review_checks(checks: dict, *, enforce_facescan: bool = True) -> None:
    facial = checks.get('facial') or {}
    if enforce_facescan and not facial.get('found'):
        raise RuntimeError('Не вдалося підтвердити зелений чекбокс Facescan. Сценарій зупинено.')
    if enforce_facescan and (facial.get('hasStartButton') or not facial.get('checked')):
        raise RuntimeError('Facescan не пройдено: немає зеленого чекбокса. Спочатку завершіть розпізнавання обличчя.')
    kyc = checks.get('kyc') or {}
    if kyc.get('found') and (kyc.get('hasStartButton') or not kyc.get('checked')):
        raise RuntimeError('Advanced KYC не завершено: немає зеленого чекбокса.')
