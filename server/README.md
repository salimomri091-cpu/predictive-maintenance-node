# Serveur de supervision

Pile Docker : Mosquitto (MQTT), Telegraf, InfluxDB 2, Grafana.

| Étape | Commande (depuis `server/`) |
|-------|-----------------------------|
| Créer la configuration | `cp .env.example .env` puis modifier `.env` |
| Démarrer | `docker compose up -d` |
| Vérifier | `docker compose ps` |
| Arrêter | `docker compose down` |

Grafana : http://localhost:3000 — InfluxDB : http://localhost:8086 — MQTT : localhost:1883

Le nom du bucket (`vibration`) est repris dans le tableau de bord : s'il change dans `.env`, il faut aussi le changer dans `grafana/dashboards/`.
