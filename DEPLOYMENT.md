# cPanel Deployment

## Updating an existing server

Use `macro-predictor-server-update.zip` for an existing installation. Upload it to the current application root and extract it there, allowing the application files to be overwritten. It contains the updated backend and `dist/` frontend assets, but intentionally does not include `.env`, `passenger_wsgi.py`, `.htaccess`, the database, or the calendar cache. Those server-specific files and saved data will remain untouched.

Do not replace or delete the cPanel Python application, its virtual environment, or its existing environment variables. If `requirements.txt` has changed, install its dependencies using that application's existing virtual environment, then restart the Python application. Otherwise, extract the files and restart the application.

After updating, visit `https://titanfxsage.omubedhe.com/api/health` to verify the app is responding.

## Fresh installation

This archive is for cPanel hosting with **Setup Python App** (Passenger) enabled. The Python application root is a private application folder; the Application URL maps that app to `titanfxsage.omubedhe.com`.

1. In cPanel **Domains**, make sure `titanfxsage.omubedhe.com` exists as a domain/subdomain on this hosting account.
2. In **Setup Python App**, choose Python 3.11 or newer, set the application root to a private folder named `titanfxsage.omubedhe.com` (outside `public_html`), and select `https://titanfxsage.omubedhe.com` as the Application URL with no extra URI path. Note the virtual environment cPanel creates.
3. Upload this ZIP into the application root and extract it there. The files should sit directly in the root, with `passenger_wsgi.py` and `dist/` visible (not inside another `macro-predictor/` folder).
4. Install dependencies with `pip install -r requirements.txt` using the application's virtual environment.
5. In **Environment variables**, add `FRED_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and `ALERT_HOURS_BEFORE` (use `2` for the last value). Enter your own credentials; do not share them. Alternatively, create `.env` in the application root from `.env.example`.
6. Set the startup file to `passenger_wsgi.py`, the entry point to `application`, then restart the Python application.
7. Visit `https://titanfxsage.omubedhe.com/api/health` to verify the app is responding.

If the Application URL selector says **No result found**, leave setup and add the subdomain under cPanel **Domains** first, then return to **Setup Python App** and refresh. If the subdomain already appears under Domains but not in the selector, ask the host to enable/map Python Selector (Passenger) for that subdomain. If the Python version list is empty, the hosting plan does not currently offer Python apps; the host must enable it or the app needs a VPS/Python-capable host.

Keep the application root writable: SQLite data and the calendar cache are stored there. Do not delete `macro_predictor.db` after the app has started, or its saved predictions will be lost. Do not place backend source or `.env` in the public document root.

This setup keeps the web app running under Passenger, but shared-hosting providers may suspend or restart Python processes and may not guarantee background scheduler uptime. For dependable 24/7 scheduled alerts, use a VPS or a hosting plan that guarantees persistent Python workers, and configure a single application worker so the in-process scheduler is not duplicated.