"""Write a controlled input and require its value to survive blur/render."""
import time
from selenium.webdriver.common.keys import Keys
from automation.operation_control import OperationCancelled


def fill_verified(driver, element, value, *, locate=None):
    element_id = element.get_attribute('id')
    def current():
        if locate:
            return locate()
        if element_id:
            return driver.execute_script('return document.getElementById(arguments[0])', element_id)
        return element
    for attempt in range(2):
        target = current()
        if target is None:
            raise RuntimeError('Поле введення зникло зі сторінки')
        try:
            if attempt == 0:
                target.click()
                target.send_keys(Keys.CONTROL, 'a')
                target.send_keys(Keys.BACKSPACE)
                target.send_keys(value)
            else:
                driver.execute_script('''
                    const e=arguments[0];
                    const proto=e.tagName==='TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                    Object.getOwnPropertyDescriptor(proto,'value').set.call(e,arguments[1]);
                    e.dispatchEvent(new Event('input',{bubbles:true}));
                    e.dispatchEvent(new Event('change',{bubbles:true}));
                ''', target, value)
            driver.execute_script('arguments[0].blur()', target)
            stable = True
            for _ in range(3):
                time.sleep(0.15)
                found = current()
                if found is None or driver.execute_script('return arguments[0].value', found) != value:
                    stable = False
                    break
            if stable:
                return
        except OperationCancelled:
            raise
        except Exception:
            continue
    raise RuntimeError('Не вдалося підтвердити значення поля після введення')
