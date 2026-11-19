@echo off
setlocal EnableDelayedExpansion

echo ========================================================
echo   Baofeng UV-5RM Firmware ^& open-ht-tool Installer
echo ========================================================
echo.

cd /d "%~dp0"
set "TARGET_DIR=%~1"
if "!TARGET_DIR!"=="" set "TARGET_DIR=%CD%"
echo Install directory: !TARGET_DIR!

if not exist "!TARGET_DIR!" (
    mkdir "!TARGET_DIR!" || (
        echo [ERR] Could not create directory "!TARGET_DIR!".
        pause
        exit /b 1
    )
)

pushd "!TARGET_DIR!" >nul 2>&1 || (
    echo [ERR] Could not access directory "!TARGET_DIR!".
    pause
    exit /b 1
)
set "TARGET_DIR=%CD%"
popd >nul 2>&1

if "%BF_UV5RM_REPO%"=="" (
    set "REPO=Fuzion-Software/bf-uv-5rm"
) else (
    set "REPO=%BF_UV5RM_REPO%"
)

set "TAG=%BF_UV5RM_TAG%"
if "!TAG!"=="" (
    echo Checking latest release from !REPO!...
    for /f "delims=" %%U in ('curl.exe -fsSL -o NUL -w "%%{url_effective}" "https://github.com/!REPO!/releases/latest" 2^>nul') do (
        set "EFF_URL=%%U"
    )
    if defined EFF_URL (
        for %%A in ("!EFF_URL:/=" "!") do set "LAST_SEG=%%~A"
        if not "!EFF_URL:/releases/tag/=!"=="!EFF_URL!" (
            set "TAG=!LAST_SEG!"
        )
    )
)

if "!TAG!"=="" (
    echo [ERR] Could not determine latest release tag from https://github.com/!REPO!/releases
    pause
    exit /b 1
)

set "ZIP_NAME=windows-bf-uv-5rm-!TAG!.zip"
set "DOWNLOAD_URL=https://github.com/!REPO!/releases/download/!TAG!/!ZIP_NAME!"
set "TMP_ZIP=%TEMP%\!ZIP_NAME!"

echo.
echo Downloading !ZIP_NAME! (!TAG!)...
echo   URL: !DOWNLOAD_URL!
curl.exe -fL --progress-bar -o "!TMP_ZIP!" "!DOWNLOAD_URL!"
if errorlevel 1 (
    echo [ERR] Failed to download !DOWNLOAD_URL!
    pause
    exit /b 1
)

echo.
echo Extracting to !TARGET_DIR!...
tar.exe -xf "!TMP_ZIP!" -C "!TARGET_DIR!" 2>nul
if errorlevel 1 (
    powershell -NoProfile -Command "Expand-Archive -LiteralPath '!TMP_ZIP!' -DestinationPath '!TARGET_DIR!' -Force"
    if errorlevel 1 (
        echo [ERR] Failed to extract "!TMP_ZIP!".
        del /q "!TMP_ZIP!" >nul 2>&1
        pause
        exit /b 1
    )
)

del /q "!TMP_ZIP!" >nul 2>&1

echo.
echo [OK] Installed !ZIP_NAME! into:
echo      !TARGET_DIR!
echo.
echo You can now launch "!TARGET_DIR!\GUI_open-ht-tool.exe" or "!TARGET_DIR!\open-ht-tool.exe".
echo.
pause
exit /b 0
