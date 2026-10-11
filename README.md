# WhatsAppReader 2.0

Linux-native Python implementation of the legacy PowerShell WhatsAppReader. Development, source comments, UI, logs and Telegram messages are in English. The user-defined Gemini prompts may use any language.

## Components

- `collector.py`, `browser.py` and verbatim extracted `js/*.js`: WhatsApp DOM reading, incremental checkpoints, bounded history, image screenshots.
- `reader.py`: message identity and chronological checkpoint rules, independent of Selenium.
- `gemini.py`: text/image classification using Gemini Interactions API, limited retries.
- `telegram.py`: result and **explicit failure** notifications.
- `orchestrator.py`: **single scheduled/manual pipeline**, lock, failure routing, cleanup and log archive.
- `storage.py`: SQLite WAL, configuration, messages, analyses, checkpoints, run history and realtime logs.
- `cleanup.py`: separate retention settings and protection for pending messages and checkpoints.
- `web.py` and `templates/`: English web console; dashboard RUNNING/IDLE/FAILED, results, logs (SSE), configuration, QR recovery and manual browser test.
- `session.py`: finite QR/login mode using the proven persistent Chromium profile.
- `scripts/setup.sh`: OCI deployment, nginx, systemd, credentials and permissions.
- `scripts/apply_schedule.py`: safe, root-owned systemd timer update from web-edited configuration.
- `import_legacy.py`: once-only JSON migration (source data not present in supplied ZIP).

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest
python -m whatsappreader init
python -m whatsappreader web
python -m pytest -q
```

Web UI is served on `http://127.0.0.1:8765/whatsappreader/` by default. Environment variables `WA_ADMIN_USER`, `WA_ADMIN_PASSWORD` and `WA_CSRF_TOKEN` must be provided to authenticate and to save configuration. The production setup script configures these behind nginx HTTPS authentication.

## OCI installation

1. Upload/extract this repository to the existing OCI VM. **Do not replace** `/home/ubuntu/snap/chromium/common/whatsapp-profile`.
2. From the repository directory run `sudo bash scripts/setup.sh`.
3. Enter a strong administrator password at the prompt (first installation only).
4. Set `GEMINI_API_KEY` and `TELEGRAM_BOT_TOKEN` in `/etc/whatsappreader.env` (chmod 600); restart `whatsappreader-web.service` after changing web credentials.
5. Open `https://<your-server>/whatsappreader/`, set the WhatsApp group, topic, prompts and schedule in Configuration.
6. Verify browser-login status and perform the first run using the **Run Now** button.
7. Check `systemctl status whatsappreader.timer whatsappreader-web.service` and `journalctl -u whatsappreader.service`.

Before running the QR login command, stop any old `whatsapp_live.py` process that is still holding the Chromium profile.

Existing nginx is amended minimally by including `/etc/nginx/snippets/whatsappreader.conf` within the existing `/etc/nginx/sites-available/main-https` server block. A backup of that file is made. The existing `/whatsapp-qr/` website, self-signed TLS certificate and Chromium Snap installation are retained. No extra browser test runs are scheduled; browser maintenance can be invoked manually from the UI.

## Migrating existing data

The provided PowerShell code ZIP **does not include runtime JSON history/checkpoint files**. Export the current Windows `data` folder separately, then copy it to a staging directory on the VM. For example:

```bash
python -m whatsappreader import-legacy /home/ubuntu/windows-export
```

This importer maps PowerShell config keys, normalizes messages with the original SHA-256 identity, imports analysis results, and preserves the checkpoint from `state.json`. The importer is intended to run **before** the first production collection on Linux. Review imported settings and checkpoints before the first production run. If the exported `data/images` directory is present, the importer copies referenced images and rewrites their paths. Missing image files remain unavailable for analysis.

## Operational rules

- `image_max_attempts` defaults to **1** (first attempt only). Retries stay bounded across a run.
- The only scheduled job is the full orchestrator run. No independent periodic Gemini task or test browser session.
- When Gemini retries are exhausted, processing **stops**, error is logged, Telegram is notified and pending messages stay in SQLite. Manual admin run or next scheduled run is required.
- `model_blocked` is terminal for that particular message; no filter evasion or automatic rephrasing.
- QR/login and WhatsApp collection share an exclusive browser-profile lock.
- Every run writes logs into SQLite immediately and exports to flat `logs/run_YYYY-MM-DD_HHMMSS.log` at the end.
- Cleanup runs even on failure, with independent retention values for messages, analyses, database/file logs, reports, images, settings history and runs. Checkpoints and pending jobs are excluded from normal expiration.
- All user-editable runtime settings, including both Gemini prompts and the topic, are stored in SQLite and editable in the Web Console. Machine paths stay in `app.yaml`, and secrets in `/etc/whatsappreader.env`.
- `settings.py` contains only schema validation and generic defaults, not the real user-specific prompts. A previously initialized database retains its saved prompts until the administrator changes them in the UI.

## Public GitHub repository and configuration

It is safe to publish **source code** after reviewing the pending commit. Do not commit `app.yaml`, runtime SQLite databases, `.env`, API keys, logs, images or a Chromium profile. Never add real WhatsApp messages or user-specific Gemini prompts as sample data or code defaults.

In the Web Console, open **Configuration** to edit the WhatsApp group, topic, Gemini text/image prompts, relevance threshold, retry limits, Telegram options, schedule and all retention windows. Press **Validate & Save Settings**; updates persist to SQLite and are used by the next orchestrator run. The source files are unchanged. Prompts may be in any language. The configuration editor includes a raw JSON mode for advanced users.

`app.yaml` is a local deployment file and should be edited on the server when machine paths or the web bind address must change. API keys, administrator credentials and Telegram bot tokens remain in `/etc/whatsappreader.env`; they are never displayed by the configuration editor. There is no scheduled backup service in this design.

## Important limitations before production cutover

- WhatsApp selectors and the Gemini API payload are based on the supplied PowerShell source and server-tested QR script; **they still require end-to-end validation on the real OCI VM**.
- A first baseline run does not classify old WhatsApp history unless the legacy checkpoint is imported.
- The configured `gemini_model` from the original project is preserved, but its current availability has not been tested.
- The original PNG screenshots and Windows JSON state files are **not included** in the supplied code archive.
- Runtime SQLite, logs, reports and images are intentionally **not automatically backed up**. Deleting or losing the VM data directory loses stored messages, prior results, checkpoints and Web Console settings; a new installation will start from generic defaults.
- Disk permissions and TLS trust should be reviewed before going live.
