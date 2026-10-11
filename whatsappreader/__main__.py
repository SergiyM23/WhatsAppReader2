"""Commands: init, run, web, login, browser-test, cleanup, export-logs, import-legacy."""
import argparse
import os
import sys
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description='WhatsAppReader 2.0')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('init');run=sub.add_parser('run');run.add_argument('--trigger',default='scheduled',choices=['scheduled','manual'])
    sub.add_parser('web');login=sub.add_parser('login');login.add_argument('--timeout',type=int,default=300)
    sub.add_parser('browser-test');sub.add_parser('cleanup');sub.add_parser('export-logs')
    imp=sub.add_parser('import-legacy');imp.add_argument('directory',type=Path)
    args=parser.parse_args()
    from .storage import Store
    from .settings import deployment
    store=Store();store.initialize()
    if args.command=='init':
        print('Database initialized:',store.path)
    elif args.command=='run':
        from .orchestrator import execute
        try:status,run_id=execute(args.trigger,store=store)
        except Exception as exc:
            print('Failed to start run:',exc,file=sys.stderr);return 2
        print(f'Run #{run_id}: {status}')
        return 0 if status=='SUCCESS' else 1
    elif args.command=='web':
        import uvicorn
        cfg=deployment()
        uvicorn.run('whatsappreader.web:app',host=cfg['web_host'],port=cfg['web_port'],proxy_headers=True,
                    forwarded_allow_ips='127.0.0.1')
    elif args.command=='login':
        from .session import login
        login(args.timeout)
    elif args.command=='browser-test':
        import tempfile
        from .browser import create_browser
        with tempfile.TemporaryDirectory(prefix='wa-driver-test-',
                dir=str(Path(deployment()['browser_profile']).parent)) as profile:
            driver=create_browser(profile)
            try:
                driver.get('https://example.com')
                print('Browser test result:',driver.title)
                assert 'Example Domain' in driver.title
            finally:driver.quit()
    elif args.command=='cleanup':
        import logging
        from .cleanup import cleanup
        print(cleanup(store,store.settings(),logging.getLogger(__name__),force=True))
    elif args.command=='export-logs':
        from .logging_service import export_log
        for run in store.recent_runs(500):
            print(export_log(store,run['id'],run['started_at']))
    elif args.command=='import-legacy':
        from .import_legacy import import_legacy
        print(import_legacy(store,args.directory))
    return 0

if __name__=='__main__':sys.exit(main())
