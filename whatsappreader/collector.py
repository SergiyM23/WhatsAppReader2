"""Incremental WhatsApp collection with bounded history, checkpoints and image capture."""
import time
from .browser import WhatsAppBrowser,create_browser
from .locks import exclusive_lock
from .reader import boundary,chronological,new_since,normalize
from .settings import data_path


def collect(store,run_id,config,logger):
    chat=config['group_name'].strip()
    if not chat:raise ValueError('WhatsApp group name is missing in configuration.')
    logger.info('Starting WhatsApp collection for chat: %s', chat)
    with exclusive_lock('browser.lock'):
        return _collect_locked(store,run_id,config,logger,chat)


def _collect_locked(store,run_id,config,logger,chat):
    logger.info('Starting Chromium...')
    driver=create_browser()
    try:
        logger.info('Chromium started. Loading WhatsApp Web...')
        browser=WhatsAppBrowser(driver,logger)
        driver.get('https://web.whatsapp.com/')
        logger.info('Waiting for WhatsApp Web to become ready...')
        if not browser.wait_ready():raise RuntimeError('WhatsApp is not authenticated or did not become ready.')
        logger.info('WhatsApp Web ready. Opening chat: %s',chat)
        browser.open_chat(chat)
        logger.info('Chat opened. Navigating to the latest messages...')
        browser.latest()
        logger.info('Latest messages reached. Scanning history for checkpoint...')
        checkpoint=store.get_checkpoint(chat)
        batches=[]; mode=None; stagnant=0
        scanned_keys=set()
        last_progress=time.monotonic()
        max_scrolls=config['max_scrolls']
        for scroll in range(max_scrolls+1):
            time.sleep(.75)
            batch=[normalize(x) for x in browser.read_batch(config['batch_limit'])]
            batches.append(batch)
            scanned_keys.update(message['key'] for message in batch)
            mode=boundary(batch,checkpoint)
            if mode:
                logger.info('History boundary found: %s (scrolls=%d, unique_messages=%d).',
                            mode,scroll,len(scanned_keys))
                break
            if scroll==max_scrolls:
                mode='bounded';logger.warning('Bounded catch-up: history older than collected window is skipped.')
                break
            before=browser.snapshot()
            result,native=browser.scroll(-1)
            if not result.get('success') and not native:
                raise RuntimeError('WhatsApp history scrolling failed; checkpoint was not advanced.')
            time.sleep(.9)
            after=browser.snapshot()
            if (before.get('earliest'),before.get('latest'))==(after.get('earliest'),after.get('latest')):
                browser.wheel(-1,2200)
                time.sleep(1)
                strong=browser.snapshot()
                stagnant = stagnant+1 if (before.get('earliest'),before.get('latest'))==(strong.get('earliest'),strong.get('latest')) else 0
            else:stagnant=0
            if stagnant>=config['max_stagnant_scrolls']:
                raise RuntimeError('WhatsApp history stalled; checkpoint was not advanced.')
            if time.monotonic()-last_progress>=10:
                logger.info('Scanning history: scrolls=%d, unique_messages=%d; searching for checkpoint...',
                            scroll+1,len(scanned_keys))
                last_progress=time.monotonic()
        all_messages=chronological(batches)
        if not all_messages:raise RuntimeError('WhatsApp returned no messages; checkpoint was not advanced.')
        new=new_since(all_messages,checkpoint,mode)
        logger.info('History scan complete: collected=%d, new=%d, boundary=%s.',
                    len(all_messages),len(new),mode)
        if mode=='timestamp':logger.warning('Exact checkpoint missing; timestamp fallback may repeat same-minute messages.')
        if mode=='baseline':logger.info('First run: establishing initial checkpoint without processing existing history.')
        if new:
            images=[m for m in new if m['hasImage']]
            if images:
                logger.info('Starting image capture: %d image(s).',len(images))
                saved_images=0
                try:browser.latest(max(100,max_scrolls+20))
                except Exception as exc:
                    logger.warning('Unable to return to latest before screenshots: %s',exc)
                for index,message in enumerate(reversed(images),start=1):
                    path=data_path('images')/(message['key']+'.png')
                    for attempt in range(1,config['image_max_attempts']+1):
                        message['imageAttempts']=attempt
                        logger.info('Capturing image %d/%d (attempt %d/%d)...',
                                    index,len(images),attempt,config['image_max_attempts'])
                        try:
                            message['imagePath']=browser.screenshot_message(message,path,max_scrolls)
                            message['imageCaptureError']=''
                            saved_images+=1
                            logger.info('Image %d/%d saved.',index,len(images))
                            break
                        except Exception as exc:
                            message['imageCaptureError']=str(exc)
                            logger.warning('Image capture attempt %d/%d failed: %s',attempt,
                                           config['image_max_attempts'],exc)
                            if attempt<config['image_max_attempts']:
                                try:browser.latest(max(100,max_scrolls+20))
                                except Exception:pass
                    # Reset browser position for the next image after an error.
                    if message['imageCaptureError']:
                        try:browser.latest(max(100,max_scrolls+20))
                        except Exception:pass
                logger.info('Image capture complete: %d/%d saved.',saved_images,len(images))
        logger.info('Saving messages and checkpoint to SQLite...')
        store.save_scan(chat,new,all_messages[-1],run_id)
        logger.info('WhatsApp scan complete: collected=%d new=%d boundary=%s',len(all_messages),len(new),mode)
        return len(new)
    finally:
        logger.info('Closing Chromium session.')
        driver.quit()
