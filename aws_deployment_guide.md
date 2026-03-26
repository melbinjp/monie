# AWS EC2 Deployment Guide (Project Monie)

### Prerequisites Check
- AWS Account active (with 6-months free trial).
- Logged into the AWS Management Console.

---

### Step 1: Set Your Region (Critical for Speed)
1. Look at the **top-right corner** of the AWS Console (next to your account name).
2. Click the region name (e.g., *N. Virginia* or *Global*).
3. Select **Asia Pacific (Mumbai) / `ap-south-1`**. 
   *This ensures millisecond latency to Upstox/Shoonya NSE servers.*

### Step 2: Launch the Server
1. In the top search bar, type **EC2** and click the first result.
2. Click the orange **Launch instance** button.
3. **Name**: Enter `MonieBot-Prod` (or whatever you prefer).

### Step 3: Choose the Operating System (AMI)
1. Under **Application and OS Images (Amazon Machine Image)**, select **Ubuntu**.
2. Leave the version as the default (*Ubuntu Server 24.04 LTS (HVM)* or *22.04 LTS*). 
3. *Note: Ensure it says "Free tier eligible" below it.*

### Step 4: Choose Instance Type
1. Under **Instance type**, select **t2.micro** or **t3.micro**. 
   *(Whichever one says "Free tier eligible").*

### Step 5: Create a Key Pair (Mandatory for Access)
1. Under **Key pair (login)**, click **Create new key pair**.
2. **Key pair name**: `monie-key`
3. **Key pair type**: `RSA`
4. **Private key file format**: `.pem` (if using Mac/Linux/Windows 10+ SSH) or `.ppk` (if you plan to use PuTTY on older Windows). Stick to `.pem` for modern terminals.
5. Click **Create key pair**. 
   *(⚠️ A file will download to your computer. Keep this safe! We need it to log in.)*

### Step 6: Configure Security Group (Firewall)
1. Under **Network settings**, leave the defaults (VPC, Subnet).
2. Ensure **Auto-assign public IP** is set to `Enable`.
3. Select **Create security group**.
4. Check the box for: **Allow SSH traffic from Anywhere (0.0.0.0/0)**.
   *(Since this is a backend bot, we don't need HTTP/HTTPS port 80/443 open. SSH is enough).*

### Step 7: Storage & Launch
1. Under **Configure storage**, leave it at `1x 8 GiB gp2` or `gp3` (up to 30GB is free, but 8GB is plenty for this bot).
2. Click the orange **Launch instance** button on the bottom right.

---

### Step 8: SSH In & Deploy

```bash
# Connect to your EC2 instance
ssh -i monie-key.pem ubuntu@<your-ec2-public-ip>

# Install dependencies
sudo apt update && sudo apt install python3-pip python3-venv -y

# Upload and set up
cd ~
git clone <your_repo_url> monie
cd monie
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
nano .env  # Add your credentials
```

### Step 9: SystemD Service (Auto-Start on Boot)

Create the service file:

```bash
sudo nano /etc/systemd/system/monie.service
```

Paste this content:

```ini
[Unit]
Description=Monie Trading Bot
After=network.target

[Service]
WorkingDirectory=/home/ubuntu/monie
Environment=PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
ExecStart=/home/ubuntu/monie/.venv/bin/python main.py
Restart=always
User=ubuntu

[Install]
WantedBy=multi-user.target
```

> **⚠️ IMPORTANT**: The `Environment=PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` line is **required** to prevent protobuf descriptor conflicts with the Upstox SDK. Do not remove it.

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable monie
sudo systemctl start monie
```

### Step 10: Verify & Monitor

```bash
# Check status
sudo systemctl status monie

# View live logs
sudo journalctl -u monie -f

# Or use Telegram /logs command for remote monitoring
```
