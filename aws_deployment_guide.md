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

### Next Steps...
Once you hit "Launch", let me know. 
I will give you the command to log into this new computer from your terminal and we will upload the Monie bot!
