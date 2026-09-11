"""Locate only the final RK confirmation dialog, never the underlying form."""

CONFIRMATION_BUTTON = r"""
const visible = e => {
    if (!e || !e.getBoundingClientRect().width || !e.getBoundingClientRect().height) return false;
    for (let n=e; n; n=n.parentElement) {
        const s=getComputedStyle(n);
        if (s.display==='none' || s.visibility==='hidden' || Number(s.opacity)===0) return false;
    }
    return true;
};
const norm = e => (e.textContent || '').replace(/\s+/g,' ').trim().toLowerCase();
const dialogs = [...document.querySelectorAll('[role="dialog"],.ant-modal-content,.ant-modal-v2-content')]
    .filter(visible).filter(e => [...e.querySelectorAll('h1,h2,h3,div,span')]
        .some(n => visible(n) && norm(n)==='confirm application details'));
const buttons = [...new Set(dialogs.flatMap(e => [...e.querySelectorAll('button,[role="button"]')]))]
    .filter(e => visible(e) && norm(e)==='submit application' && !e.disabled
        && e.getAttribute('aria-disabled')!=='true' && !String(e.className).includes('loading'));
return buttons.length===1 ? buttons[0] : null;
"""
