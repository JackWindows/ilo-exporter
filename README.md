# ilo-exporter
## Usage
```
ILO_HOST=<ip> ILO_PORT=443 ILO_USER=exporter ILO_PASSWORD=exporter LISTEN_PORT=9116 ilo_exporter/main.py
```
## Run in docker
1. Build
```
docker build -t ilo-exporter .
```
2. Run
```
docker run --rm \
    -e ILO_HOST=<ip> \
    -e ILO_USER=exporter \
    -e ILO_PASSWORD=exporter
    -p 9116:9116 \
    ilo-exporter
```
