"""Ant Select interaction scoped to the combobox and its associated popup."""
import time
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains


SNAPSHOT = r"""
const input = document.getElementById(arguments[0]);
const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
const visible = e => !!e && e.getBoundingClientRect().width > 0
    && e.getBoundingClientRect().height > 0 && getComputedStyle(e).display !== 'none'
    && getComputedStyle(e).visibility !== 'hidden';
const select = input?.closest('.ant-select-v2, .ant-select');
const rect = e => {const r=e.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height};};
if (!select) return {found:false, options:[]};
const owned = document.getElementById(input.getAttribute('aria-controls') || input.getAttribute('aria-owns'));
const roots = [...document.querySelectorAll('.ant-select-v2-dropdown,.ant-select-dropdown')].filter(visible);
let popup = owned?.closest('.ant-select-v2-dropdown,.ant-select-dropdown');
if (!visible(popup)) popup = null;
// Older Ant versions expose no usable listbox; accept only a unique nearby popup.
if (!popup && input.getAttribute('aria-expanded') === 'true') {
    const a=select.getBoundingClientRect();
    const nearby=roots.filter(root => {const b=root.getBoundingClientRect();
        return Math.min(a.right,b.right)>Math.max(a.left,b.left)
            && Math.min(Math.abs(b.top-a.bottom),Math.abs(a.top-b.bottom))<100;});
    if (nearby.length===1) popup=nearby[0];
}
const options=popup ? [...popup.querySelectorAll('.ant-select-v2-item-option,.ant-select-item-option')]
    .filter(visible).filter(e => e.getAttribute('aria-disabled') !== 'true'
        && !e.className.includes('disabled')) : [];
const inViewport = e => {if (!visible(e)) return false; const r=e.getBoundingClientRect();
    return r.bottom>0 && r.right>0 && r.top<innerHeight && r.left<innerWidth;};
const popupReady = inViewport(popup) && !/appear-prepare|enter-prepare/.test(popup.className);
return {found:true, input, popupReady, foreground:document.visibilityState === 'visible' && document.hasFocus(), trigger:select.querySelector('.ant-select-v2-selector,.ant-select-selector'),
    arrow:select.querySelector('.ant-select-v2-arrow,.ant-select-arrow'),
    selected:norm(select.querySelector('.ant-select-v2-selection-item,.ant-select-selection-item')?.textContent),
    expanded:input.getAttribute('aria-expanded'), rect:rect(select),
    options:options.map(e=>({element:e,text:norm(e.textContent),ready:popupReady && inViewport(e),active:e.className.includes('option-active')})),
    roots:roots.map(e=>({classes:e.className,rect:rect(e),text:norm(e.innerText).slice(0,500)}))};
"""


class RKDropdown:
    def __init__(self, driver, check_cancelled, debug, *, foreground_timeout=120):
        self.driver, self.check_cancelled, self.debug = driver, check_cancelled, debug
        self.foreground_timeout = foreground_timeout

    def _snapshot(self, input_id):
        self.check_cancelled()
        return self.driver.execute_script(SNAPSHOT, input_id) or {}

    def select(self, input_id: str, expected: str, step: str) -> str:
        expected = ' '.join(expected.lower().split())
        started = time.monotonic()
        last = self._snapshot(input_id)
        if last.get('selected') == expected:
            return expected
        for opening in range(3):
            if not last.get('options'):
                self._attempt('open_' + str(opening), lambda: self._open(last, opening), step)
                last = self._poll(input_id, expected, stop_on_options=True)
            if last.get('selected') == expected:
                return expected
            if last.get('options'):
                break
        if last.get('options') and not self._target(last, expected):
            self._fail(last, expected, step, 'configured_option_missing')
        # Each method is attempted once; native click never targets offscreen animation nodes.
        for method in ('native', 'keyboard', 'dom'):
            last = self._snapshot(input_id)
            if last.get('selected') == expected:
                return self._done(expected, step, started)
            target = self._target(last, expected)
            if target:
                self._attempt(method, lambda: self._choose(last, target, method, input_id, expected), step)
                last = self._poll(input_id, expected)
                if last.get('selected') == expected:
                    return self._done(expected, step, started)
        self.debug.warning('rk_foreground_required', field=input_id,
                           message='Open the AdsPower RK tab to continue selecting the document category.')
        deadline = time.monotonic() + self.foreground_timeout
        retries = 0
        while time.monotonic() < deadline:
            last = self._snapshot(input_id)
            if last.get('selected') == expected:
                self.debug.step('rk_foreground_resumed')
                return self._done(expected, step, started)
            if last.get('foreground') and retries < 2:
                retries += 1
                target = self._target(last, expected)
                if target and target.get('ready'):
                    self._attempt('foreground_click', target['element'].click, step)
                elif not last.get('options'):
                    self._attempt('foreground_open', lambda: self._open(last, 0), step)
            time.sleep(0.5)
        self._fail(last, expected, step, 'foreground_wait_timeout')

    @staticmethod
    def _target(snapshot, expected):
        return next((o for o in snapshot.get('options', []) if o['text'] == expected), None)

    def _choose(self, snapshot, target, method, input_id, expected):
        if method == 'native':
            if target.get('ready'):
                target['element'].click()
        elif method == 'keyboard':
            # Never press Enter until the active option matches the desired category.
            for _ in range(len(snapshot.get('options', [])) + 1):
                state = self._snapshot(input_id)
                active = next((o for o in state.get('options', []) if o.get('active')), None)
                if active and active['text'] == expected:
                    state['input'].send_keys(Keys.ENTER)
                    return
                state['input'].send_keys(Keys.ARROW_DOWN)
                time.sleep(0.1)
        else:
            # Trigger the site's own selection handler; do not assign the field value.
            self.driver.execute_script("arguments[0].click();", target['element'])

    def _attempt(self, method, action, step):
        self.check_cancelled()
        try:
            action()
            self.debug.step(step + '_interaction', method=method)
        except WebDriverException as exc:
            self.debug.warning(step + '_interaction_failed', method=method, error=type(exc).__name__)

    def _poll(self, input_id, expected, *, stop_on_options=False):
        deadline = time.monotonic() + 1.5
        state = {}
        while time.monotonic() < deadline:
            state = self._snapshot(input_id)
            if state.get('selected') == expected or (stop_on_options and state.get('options')):
                break
            time.sleep(0.15)
        return state

    def _done(self, expected, step, started):
        self.debug.step(step + '_done', selected=expected, elapsed_ms=round((time.monotonic()-started)*1000))
        return expected

    def _fail(self, last, expected, step, reason):
        safe = {k:v for k,v in last.items() if k not in {'input','trigger','arrow','options'}}
        safe['options'] = [o['text'] for o in last.get('options', [])]
        self.debug.warning(step + '_option_select_failed', reason=reason, snapshot=safe)
        self.debug.save_page_probe(self.driver, step + '_option_not_found.json')
        raise RuntimeError(f'Could not select {expected} in the RK form ({reason}).')

    def _open(self, snapshot, attempt):
        trigger = snapshot.get('trigger')
        if trigger is None:
            return
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", trigger)
        if attempt == 0:
            trigger.click()
        elif attempt == 1:
            ActionChains(self.driver).move_to_element(snapshot.get('arrow') or trigger).click().perform()
        else:
            snapshot['input'].send_keys(Keys.ARROW_DOWN)
