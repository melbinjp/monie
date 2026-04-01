# EC2 Remote Access & Data Retrieval Guide

This document contains the exact commands required to access your live Monie Trading Bot from anywhere in the world, inspect its logs, or download its internal database.

> [!CAUTION]
> **SECURITY WARNING**: Never upload your `monie-key.pem` private key file to GitHub. Anyone with that file and the IP address below can gain full administrative control over your server and the associated capital. Always store the `.pem` file securely on your physical device.

## Core Infrastructure Details
- **Instance IP**: `13.205.207.244`
- **Username**: `ubuntu`
- **Authentication Key**: `monie-key.pem` 
- **Bot Directory**: `/home/ubuntu/monie/`

---

## 1. How to Access the Live Server Terminal

To open an interactive terminal on the live AWS server from any computer (Windows Powerhsell, Mac, or Linux terminal), navigate to the folder containing your `monie-key.pem` file and run:

```bash
ssh -i monie-key.pem ubuntu@13.205.207.244
```

Once inside, you can check the live execution status of the bot using:
```bash
sudo systemctl status monie
```

---

## 2. How to Monitor Live Logs

If you want to watch the bot execute trades and process ticks in real-time, SSH into the machine (using the command above) and strictly tail the systemd journal:

```bash
# Watch live log stream (Press Ctrl+C to exit)
sudo journalctl -u monie -f

# View the last 100 lines of logs without streaming
sudo journalctl -u monie -n 100 --no-pager
```

---

## 3. How to Download Live Data / Memory

If you are traveling or on a new computer and simply want to download the bot's raw state (the SQLite database) or logs to your local machine for analysis, use the `scp` (Secure Copy) format. 

*Run these commands from your local computer's terminal, NOT from inside the EC2 server:*

### Download the SQLite Database (`monie_memory.db`)
```bash
scp -i monie-key.pem ubuntu@13.205.207.244:/home/ubuntu/monie/monie_memory.db ./monie_memory.db
```

### Download the .env Configuration
```bash
scp -i monie-key.pem ubuntu@13.205.207.244:/home/ubuntu/monie/.env ./.env_backup
```

### Upload a modified file back to the server
If you modify a Python script locally and need to force it onto the server without using Git:
```bash
scp -i monie-key.pem ./main.py ubuntu@13.205.207.244:/home/ubuntu/monie/main.py
```

---

## 4. Emergency Commands (Run Inside EC2 via SSH)

- **Restart the Bot Completely**: `sudo systemctl restart monie`
- **Stop the Bot Completely**: `sudo systemctl stop monie`
- **Update Code via GitHub**: 
  ```bash
  cd /home/ubuntu/monie
  git pull origin main
  sudo systemctl restart monie
  ```
