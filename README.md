# **LANHUB**

## **Description**

## **Setup Steps**
### **1: Create a Server**
It is recommended to use a server OS, however, if wi-fi connection requires complicated captcha, it is best to use a desktop OS such as the __Ubuntu Desktop LTS (22.04 or 24.04)__.

This tutorial will show how to setup LANHUB for __linux-based OS__.

Make sure to set server/desktop OS to __autoconnect to a wi-fi network__.

#### **For Desktop OS Users**

In order to disable sleep/hibernation to keep the server running 24/7, you can run the following command line in your server:
```bash
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

To undo this, you use the following command line:
```bash
sudo systemctl unmask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

You can also save RAM and CPU (switching from GUI to CLI), by setting the default boot target:
```bash
sudo systemctl set-default multi-user.target
sudo reboot
```

To switch back to GUI mode:
```bash
sudo systemctl set-default graphical.target
sudo reboot
```
---

### 2: **Depoly LANHub App**

On the server console
Install Git if needed:

```bash
sudo apt install git
```

Clone the repository:

```bash
git clone https://github.com/theplatecrafter/LANHub
cd LANHub
```

Install Python + venv tools:

```bash
sudo apt install python3 python3-venv python3-pip
```

Create virtual environment:

```bash
python3 -m venv venv
```

Activate it:

```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r dependencies.txt
```

Do **not** run app.py yet.


---
### **3:Create systemd Service**
Create service file:

```bash
sudo nano /etc/systemd/system/lanhub.service
```

Paste (Make sure to replace ```<Ubuntu_username>``` and ```/.../``` appropriately):
```ini
[Unit]
Description=LANHub Server
After=network.target

[Service]
User=<Ubuntu_username>
WorkingDirectory=/home/<Ubuntu_username>/.../LANHub
ExecStart=/home/<Ubuntu_username>/.../LANHub/venv/bin/python app.py
Restart=always
RestartSec=5
Environment="PYTHONUNBUFFERED=1"
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```


Save and exit.

---

Reload systemd:

```bash
sudo systemctl daemon-reload
```

Enable auto-start on boot:

```bash
sudo systemctl enable lanhub
```

Start server:

```bash
sudo systemctl start lanhub
```

Check status:

```bash
sudo systemctl status lanhub
```

Stop for now:
```bash
sudo systemctl stop lanhub
```

---


### **4: Dynamic Redirector Setup**
This allows users to visit a set GitHub Pages URL to find your server.

Since the server updates GitHub automatically, you must use SSH keys to avoid "Authentication Failed" errors.

In your server console,
Generate a SSH key (remember to replace ```your_email@example.com```):
```bash
ssh-keygen -t ed25519 -C "your_email@example.com"
```
You can leave all prompts blank by pressing enter.

Copy your SSH key:
```bash
cat ~/.ssh/id_ed25519.pub
```
Copy from the first letter of the output string to the end of the key.

Goto your github **account settings**, then **SSH and GPG keys**
Click ```New SSH```, then paste your SSH key here and save it.

**Create a github repository**. You can name this whatever you want. **Add a README.md file** for simple initial branch creation This repository will be in charge of redirecting users to the ip address of the server so that even if the server's ip address changes, the LANHub page can be accessed using the same link.

In the repository settings, goto the **Pages** tab.
Under **Source**, select ```Deploy from branch```
Under **Branch**, select ```main``` and ```/root```, then hit save.


cd into the LANHub directory, then run the following command:
Make sure to replace ```<redirector-link>``` with the github link of the repository you just created.
```bash
sed -i 's#^REPO_URL = .*#REPO_URL = "<redirector-link>"#' configvars.py
```

Run the app:
```bash
python app.py
```
There should be some warnings or errors in the console or log, these will be resolved. If the app terminates due to program error, please contact me.
Exit out using ```Ctrl+C```

Run the following commands **in order**:
Make sure to replace ```<redirector-repo>``` with the name of the github repository you just created.
```bash
cd ./<redirector-repo>
git remote set-url origin git@github.com:theplatecrafter/<redirector-repo>.git
git push
```

now cd back:
```bash
cd ..
```
Run the app again:
```bash
python app.py
```
This should run properly

---


### Extra: **Open a SSH to the Server**
This opens a ssh to the server console that automatically opens when the server computer starts

In the server terminal:

```bash
sudo apt update
sudo apt install openssh-server
```

Enable SSH on boot:

```bash
sudo systemctl enable ssh
```

Start SSH now:

```bash
sudo systemctl start ssh
```

Check status:

```bash
sudo systemctl status ssh
```

You should see `active (running)`.

Use the following command to get the ip address of the server:
```bash
ip a
```

In another linux console in a diffrent computer, you can now access the server using:
```bash
ssh your_username@YOUR_SERVER_IP
```
where ```your_username``` is the username logged on the server.
You will need to type in the password you set for that username.
You are now remotely controlling your Ubuntu server.

You are now remotely controlling your server.



## **Commands for Updating and Server Control**
### **Updating**
In your server console, run the following to stop the systemctl:
```bash
sudo systemctl stop lanhub
```

Then cd into the LANHub repository, and run:
```bash
git pull
```

Then restart the systemctl:
```bash
sudo systemctl daemon-reload
sudo systemctl start lanhub
```

### **Looking at Logs**
cd into the LANHub repository

General app logs:
```bash
tail -f logs/app.log
```

Static github page redirector logs:
```bash
tail -f logs/github_sync.log
```

User access to server:
```bash
tail -f logs/access.log
```

Errors:
```bash
tail -f logs/error.log
```

Full Log:
```bash
journalctl -u lanhub -f
```

### **Stopping/Starting Server**
To stop the server:
```bash
sudo systemctl stop lanhub
```

To start the server:
```bash
sudo systemctl start lanhub
```