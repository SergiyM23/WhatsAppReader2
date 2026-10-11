"""Extract tested WhatsApp DOM JavaScript verbatim from PowerShell source."""
import re
import pathlib
import sys

source = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8-sig')
output = pathlib.Path(sys.argv[2])
functions = {
    'Find-WhatsAppSearchBox':'search_box',
    'Read-RecentWhatsAppMessages':'read_messages',
    'Get-WhatsAppHistorySnapshot':'history_snapshot',
    'Scroll-WhatsAppHistoryContainerUp':'scroll_up',
    'Scroll-WhatsAppHistoryContainerDown':'scroll_down',
    'Test-WhatsAppMessageVisible':'message_visible',
    'Capture-WhatsAppMessageScreenshot':'locate_message',
}
for func, name in functions.items():
    m = re.search(r'(?ms)^function ' + re.escape(func) + r'\s*\{(.*?)(?=^function [A-Z]|\Z)',source)
    if not m: raise SystemExit('Missing '+func)
    code = re.search(r"@'\s*\n(.*?)\n'@",m[1],re.S)
    if not code: raise SystemExit('No JS '+func)
    (output/(name+'.js')).write_text(code[1]+'\n',encoding='utf-8')
    print(name, len(code[1]))
