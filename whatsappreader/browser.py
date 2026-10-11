"""Linux-native Selenium browser, preserving the tested server settings and DOM scripts."""
from __future__ import annotations
import logging
import time
from pathlib import Path
from .settings import deployment

JS_PATH=Path(__file__).parent/'js'

def js(name):return (JS_PATH/(name+'.js')).read_text(encoding='utf-8')

def create_browser(profile=None):
    # Selenium is imported only when the browser is needed (the web UI needs none).
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    cfg=deployment()
    options=Options()
    options.binary_location=cfg['browser_binary']
    for arg in ('--headless=new','--disable-dev-shm-usage','--no-sandbox','--window-size=1920,1080'):
        options.add_argument(arg)
    # This UA was confirmed to work for WhatsApp Web on OCI ARM64.
    options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) '
                         'AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/154.0.0.0 Safari/537.36')
    options.add_argument('--user-data-dir='+str(profile or cfg['browser_profile']))
    return webdriver.Chrome(service=Service(executable_path=cfg['driver_binary']),options=options)

def dismiss_popup(driver):
    from selenium.webdriver.common.by import By
    for label in ('Continue','Продовжити','Продолжить'):
        xpath=f"//button[.//*[normalize-space()='{label}'] or normalize-space()='{label}']"
        for el in driver.find_elements(By.XPATH,xpath):
            if el.is_displayed():
                el.click()
                return True
    return False

class WhatsAppBrowser:
    def __init__(self,driver,logger=None):
        self.driver=driver
        self.log=logger or logging.getLogger(__name__)

    def is_authenticated(self):
        return bool(self.driver.execute_script('return !!(document.querySelector("#pane-side") || document.querySelector("#side"));'))

    def wait_ready(self,seconds=90):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            try:
                if self.is_authenticated():
                    dismiss_popup(self.driver)
                    return True
            except Exception:pass
            time.sleep(1)
        return False

    def open_chat(self,name):
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.common.action_chains import ActionChains

        field = self.driver.execute_script(js('search_box'))
        if field is None:
            raise RuntimeError('WhatsApp search input was not found.')
        field.click()
        field.send_keys(Keys.CONTROL, 'a')
        field.send_keys(name)
        time.sleep(2)

        # Inspect the search result without clicking it yet.
        # The legacy reader first sent Enter and only then tried a mouse fallback.
        found = self.driver.execute_script(r'''
          const wanted = String(arguments[0] || '').replace(/\s+/g, ' ').trim().toLowerCase();
          const pane = document.querySelector('#pane-side') || document.querySelector('#side') || document;
          return [...pane.querySelectorAll('[title]')].some(el => {
            const r = el.getBoundingClientRect();
            return r.width > 10 && r.height > 10 &&
              (el.getAttribute('title') || '').replace(/\s+/g, ' ').trim().toLowerCase() === wanted;
          });
        ''', name)
        if not found:
            raise RuntimeError(f'WhatsApp chat not found by exact name: {name}')

        def panel_open():
            for _ in range(12):
                if self.driver.execute_script('return !!document.querySelector("#main")'):
                    return True
                time.sleep(.5)
            return False

        # Primary strategy: native keyboard Enter, as in Common.ps1.
        ActionChains(self.driver).send_keys(Keys.ENTER).perform()
        if panel_open():
            return

        # Fallback: mouse-like event sequence on the matching result.
        self.driver.execute_script(r'''
          const wanted = String(arguments[0] || '').replace(/\s+/g, ' ').trim().toLowerCase();
          const pane = document.querySelector('#pane-side') || document.querySelector('#side') || document;
          const target = [...pane.querySelectorAll('[title]')].find(el =>
            (el.getAttribute('title') || '').replace(/\s+/g, ' ').trim().toLowerCase() === wanted &&
            el.getBoundingClientRect().width > 10
          );
          if (!target) return false;
          let clickable = target;
          for (let i = 0; i < 8 && clickable && clickable !== pane; i++, clickable = clickable.parentElement) {
            const role = clickable.getAttribute?.('role');
            const tab = clickable.getAttribute?.('tabindex');
            if (role === 'listitem' || role === 'row' || role === 'gridcell' || tab === '0') break;
          }
          if (!clickable || clickable === pane) clickable = target;
          clickable.scrollIntoView({block: 'center', inline: 'nearest'});
          const opts = {bubbles: true, cancelable: true, view: window};
          for (const type of ['pointerdown', 'mousedown', 'mouseup', 'click'])
            clickable.dispatchEvent(new MouseEvent(type, opts));
          return true;
        ''', name)
        if panel_open():
            return
        raise RuntimeError('WhatsApp chat panel did not open after Enter and click fallback.')

    def snapshot(self):return self.driver.execute_script(js('history_snapshot'))
    def read_batch(self,limit):return self.driver.execute_script(js('read_messages'),limit) or []

    def wheel(self,direction,amount=1200):
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.common.actions.wheel_input import ScrollOrigin
        position=self.driver.execute_script('''
        const r=(document.querySelector('#main')||document.body).getBoundingClientRect();
        return [Math.floor(r.left+r.width*.55),Math.floor(r.top+r.height*.45)];''')
        try:
            x,y=position
            ActionChains(self.driver).scroll_from_origin(ScrollOrigin.from_viewport(x,y),0,direction*amount).perform()
            return True
        except Exception as exc:
            self.log.warning('Native wheel scrolling failed: %s',exc)
            return False

    def scroll(self,direction):
        result=self.driver.execute_script(js('scroll_up' if direction<0 else 'scroll_down'))
        native=self.wheel(direction,1200 if direction<0 else 2200)
        return result or {}, native

    def latest(self,max_attempts=200):
        last=''; stable=0
        for attempt in range(max_attempts):
            result,native=self.scroll(1)
            if not result.get('success') and not native:raise RuntimeError('Failed to scroll to latest WhatsApp message.')
            time.sleep(.85)
            current=self.snapshot().get('latest','')
            if result.get('atBottom') and current and current==last:stable+=1
            else:stable=0
            if stable>=2:return current
            last=current
        raise RuntimeError('Latest WhatsApp message was not reached within safety limit.')

    def scroll_up_to(self,message,max_scrolls):
        args=(message['metadata'],message['text'])
        if self.driver.execute_script(js('message_visible'),*args):return True
        for _ in range(max_scrolls):
            before=self.snapshot()
            self.scroll(-1);time.sleep(.9)
            if self.driver.execute_script(js('message_visible'),*args):return True
            after=self.snapshot()
            if (before.get('earliest'),before.get('latest'))==(after.get('earliest'),after.get('latest')):
                self.wheel(-1,1800);time.sleep(.9)
                if self.driver.execute_script(js('message_visible'),*args):return True
        return False

    def screenshot_message(self,message,destination,max_scrolls):
        from selenium.common.exceptions import StaleElementReferenceException
        if not self.scroll_up_to(message,max_scrolls):
            raise RuntimeError('Image message was not found in scrollable history.')
        for i in range(3):
            try:
                element=self.driver.execute_script(js('locate_message'),message['metadata'],message['text'])
                if element is None:raise RuntimeError('Message bubble was not found for screenshot.')
                Path(destination).parent.mkdir(parents=True,exist_ok=True)
                element.screenshot(str(destination))
                return str(destination)
            except (StaleElementReferenceException,RuntimeError):
                if i==2:raise
                self.scroll_up_to(message,min(10,max_scrolls))
                time.sleep(.25)
        raise RuntimeError('Image screenshot failed.')
