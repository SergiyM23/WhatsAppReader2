"""Verified WhatsApp QR screenshot workflow integrated as a finite login/recovery mode."""
import os
import time
from pathlib import Path
from .browser import create_browser,WhatsAppBrowser,dismiss_popup
from .locks import exclusive_lock
from .settings import deployment
from .storage import Store,utcnow


def set_state(store,value):
    with store.connect() as db:
        db.execute("INSERT INTO housekeeping(name,value) VALUES('login_status',?) "
                   'ON CONFLICT(name) DO UPDATE SET value=excluded.value',(value,))


def login(timeout_seconds=300):
    store=Store();store.initialize()
    with exclusive_lock('browser.lock'):
        # Shared browser lock is also used by the normal collector.
        driver=None
        set_state(store,'STARTING')
        screenshot=Path(deployment()['qr_screenshot'])
        screenshot.parent.mkdir(parents=True,exist_ok=True)
        try:
            driver=create_browser()
            driver.get('https://web.whatsapp.com')
            set_state(store,'WAITING_FOR_QR')
            deadline=time.monotonic()+timeout_seconds
            browser=WhatsAppBrowser(driver)
            while time.monotonic()<deadline:
                try:
                    if browser.is_authenticated():
                        dismiss_popup(driver)
                        set_state(store,'CONNECTED')
                        return
                    tmp=screenshot.with_name('whatsapp-live.tmp.png')
                    driver.save_screenshot(str(tmp))
                    tmp.replace(screenshot)
                except Exception:
                    pass
                time.sleep(2)
            set_state(store,'TIMED_OUT')
            raise TimeoutError('WhatsApp QR login timed out. Start a new login session.')
        except Exception:
            set_state(store,'FAILED')
            raise
        finally:
            if driver:driver.quit()
            # Avoid displaying an obsolete screenshot as an active QR code.
            if screenshot.exists():screenshot.unlink()
