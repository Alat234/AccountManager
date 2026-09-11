"""Choose once through CDP, then retain the scenario's browser tab."""
from urllib.parse import urlparse


def is_mexc(url):
    return urlparse(url).hostname in ('www.mexc.com', 'mexc.com', 'www.mexc.co', 'mexc.co')


def pin_mexc_tab(driver, preferred_path=''):
    handles = driver.window_handles
    initial = driver.current_window_handle
    targets = driver.execute_cdp_cmd('Target.getTargets', {}).get('targetInfos', [])
    candidates = [t for t in targets if t.get('type') == 'page' and is_mexc(t.get('url', ''))]
    candidates.sort(key=lambda t: preferred_path not in t.get('url', ''))
    selected = None
    for target in candidates:
        selected = next((h for h in handles if h in (target['targetId'], 'CDwindow-' + target['targetId'])), None)
        if selected:
            break
    if not selected and is_mexc(driver.current_url):
        selected = initial
    if not selected:
        driver.switch_to.new_window('tab')
        selected = driver.current_window_handle
    elif selected != initial:
        driver.switch_to.window(selected)
    driver._mexc_owned_handle = selected
    return {'initial_handle': initial, 'owned_handle': selected, 'switched': selected != initial}
