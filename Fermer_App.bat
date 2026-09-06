@echo off
title Arret SFE ETL App
echo ===================================================
echo     Arret des conteneurs Docker en cours...
echo ===================================================

docker-compose down

echo.
echo Application arretee avec succes !
timeout /t 3 > NUL