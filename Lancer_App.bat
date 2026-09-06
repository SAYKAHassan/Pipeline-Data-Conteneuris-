@echo off
title Démarrage SFE ETL App
echo ===================================================
echo     Lancement de l'application SFE (Docker)...
echo ===================================================

docker-compose up -d

echo.
echo En attente du demarrage du serveur Dash...

timeout /t 6 /nobreak > NUL

start http://localhost:8050

echo.
echo Application lancee ! Vous pouvez fermer cette fenetre.
timeout /t 3 > NUL