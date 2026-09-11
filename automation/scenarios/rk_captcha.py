"""A single browser roundtrip for active CAPTCHA; ignore badges and hidden ancestors."""
CAPTCHA_VISIBLE = r"""
const visible = e => {
    const r=e.getBoundingClientRect();
    if (r.width<80 || r.height<30 || e.closest('.grecaptcha-badge')) return false;
    for (let p=e;p;p=p.parentElement) {
        const s=getComputedStyle(p);
        if (s.display==='none' || s.visibility==='hidden' || Number(s.opacity)<0.05) return false;
    }
    return true;
};
return [...document.querySelectorAll('.geetest_panel,.geetest_popup_wrap,.geetest_widget,.geetest_window,.captcha-container,.g-recaptcha,iframe[src*="captcha"],iframe[src*="geetest"],iframe[src*="recaptcha"]')].some(visible);
"""


def captcha_visible(driver) -> bool:
    return bool(driver.execute_script(CAPTCHA_VISIBLE))
