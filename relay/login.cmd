@echo off
rem Cloudflare'ga ulanish (bir marta). Brauzer ochiladi — "Allow" ni bosing.
rem NODE_OPTIONS: bu kompyuterda Node IPv6'da osilib qoladi — IPv4 majburlanadi.
cd /d "%~dp0"
set NODE_OPTIONS=--require %~dp0force-ipv4.cjs
call npx wrangler login
echo.
call npx wrangler whoami
pause
