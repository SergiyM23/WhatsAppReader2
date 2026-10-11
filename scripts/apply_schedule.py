#!/usr/bin/env python3
"""Root-owned, fixed-purpose systemd timer updater; no arbitrary shell execution."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

DB='/opt/whatsappreader/data/whatsappreader.db'
TIMER='/etc/systemd/system/whatsappreader.timer'

def main():
    # The SQLite database is read-only. Only the timer unit is written as root.
    con=sqlite3.connect(f'file:{DB}?mode=ro',uri=True)
    result=con.execute("SELECT value_json FROM settings WHERE name='schedule'").fetchone()
    con.close()
    if not result:raise RuntimeError('No schedule configured.')
    schedule=json.loads(result[0])
    if not isinstance(schedule,str) or len(schedule)>150 or '\n' in schedule:
        raise RuntimeError('Invalid schedule value.')
    subprocess.run(['/usr/bin/systemd-analyze','calendar',schedule],check=True,timeout=10,
                   stdout=subprocess.DEVNULL)
    text='''# Managed by WhatsAppReader. Do not edit manually.
[Unit]
Description=WhatsAppReader scheduled processing
[Timer]
OnCalendar='''+schedule+'''
Persistent=true
Unit=whatsappreader.service
[Install]
WantedBy=timers.target
'''
    tmp=Path(TIMER+'.new');tmp.write_text(text,encoding='utf-8');os.chmod(tmp,0o644)
    os.replace(tmp,TIMER)
    subprocess.run(['/usr/bin/systemctl','daemon-reload'],check=True,timeout=10)
    subprocess.run(['/usr/bin/systemctl','enable','--now','whatsappreader.timer'],check=True,timeout=10)
    subprocess.run(['/usr/bin/systemctl','restart','whatsappreader.timer'],check=True,timeout=10)
    print('Updated WhatsAppReader schedule:',schedule)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Schedule update failed:',exc,file=sys.stderr)
        sys.exit(1)
