@echo off
setlocal

:: --- CONFIGURATION ---
set SERVER_USER=root
set SERVER_IP=72.56.80.56
set REMOTE_DIR=/home/linux_dist
set SERVER_PORT=22
:: --- END CONFIGURATION ---

echo [DEPLOY] Target: %SERVER_USER%@%SERVER_IP%:%REMOTE_DIR%
echo [INFO] You may be prompted for the server password multiple times.

:: 1. Cleanup Remote (Remove deleted files and potential cache issues)
echo [1/4] Cleaning up remote files...
ssh -p %SERVER_PORT% -o PreferredAuthentications=password -o PubkeyAuthentication=no %SERVER_USER%@%SERVER_IP% "rm -f %REMOTE_DIR%/bot_app/integrations/groq_client.py"

:: 2. Upload Code
echo [2/4] Uploading new files...
:: Upload bot_app directory (recursively updates changed files)
scp -P %SERVER_PORT% -o PreferredAuthentications=password -o PubkeyAuthentication=no -r bot_app %SERVER_USER%@%SERVER_IP%:%REMOTE_DIR%

:: Upload root configuration files
scp -P %SERVER_PORT% -o PreferredAuthentications=password -o PubkeyAuthentication=no Dockerfile docker-compose.yml requirements.txt start.py %SERVER_USER%@%SERVER_IP%:%REMOTE_DIR%

:: 3. Remote Restart
echo [3/4] Rebuilding and restarting container on remote server...
:: We use 'build' to ensure new requirements are installed
ssh -p %SERVER_PORT% -o PreferredAuthentications=password -o PubkeyAuthentication=no %SERVER_USER%@%SERVER_IP% "cd %REMOTE_DIR% && docker-compose down && docker-compose build && docker-compose up -d"

echo [4/4] Deployment Complete!
echo ----------------------------------------------------------------
echo REMINDER: Ensure you update the .env file on the server with:
echo AI_API_KEY=...
echo AI_MODEL=chutes-llama-3.3-70b
echo AI_BASE_URL=https://chutes.ai/api/v1
echo ----------------------------------------------------------------
pause