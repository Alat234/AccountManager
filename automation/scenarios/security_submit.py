"""Locate Submit relative to the active verification field, not the whole page."""
import time


def click_code_submit(driver, texts=('submit', 'confirm', 'next'), field_id=None, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        button = driver.execute_script('''
            // Ant's enter preparation may never advance while requestAnimationFrame
            // is throttled in a hidden tab. Settle only dialog entrance animations.
            if(document.visibilityState==='hidden') {
                for(const dialog of document.querySelectorAll('[role="dialog"],.ant-modal-content,.ant-modal-v2-content')) {
                    for(const animation of dialog.getAnimations()) {
                        try { animation.finish(); } catch (_) {}
                    }
                    for(const cls of [...dialog.classList]) {
                        if(/^ant-zoom-(appear|enter)(-(prepare|start|active))?$/.test(cls))
                            dialog.classList.remove(cls);
                    }
                }
            }
            const visible=e=>{
                if(!e) return false;
                const r=e.getBoundingClientRect();
                for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);
                    if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)<.05)return false;}
                return r.width>0&&r.height>0;
            };
            const ids=arguments[1]?(Array.isArray(arguments[1])?arguments[1]:[arguments[1]]):['googleAuthCode','validationCode','emailCode'];
            const input=ids.flatMap(id=>[...document.querySelectorAll('[id]')].filter(e=>e.id===id)).find(visible);
            if(!input)return false;
            // MEXC places the modal footer beside the inner form, not inside it.
            const dialog=input.closest('[role="dialog"],.ant-modal-content,.ant-modal-v2-content');
            for(let root=input.parentElement;root&&root!==document.body;root=root.parentElement){
                const candidates=[...root.querySelectorAll('button,[role="button"]')].filter(visible)
                    .filter(b=>arguments[0].includes((b.textContent||'').trim().toLowerCase()));
                if(candidates.length===1){
                    const b=candidates[0];
                    if(b.disabled||b.getAttribute('aria-disabled')==='true')return false;
                    return b;
                }
                if(root===dialog || (!dialog && root.matches('form')))return false;
            }
            return false;
        ''', list(texts), field_id)
        if button:
            # Native pointer events in foreground; DOM activation avoids hidden-tab
            # coordinate/animation dependence. No retry after an uncertain click.
            background = driver.execute_script("return document.visibilityState==='hidden' || !document.hasFocus()")
            if background:
                driver.execute_script('arguments[0].click();', button)
            else:
                button.click()
            return True
        time.sleep(.2)
    return False
