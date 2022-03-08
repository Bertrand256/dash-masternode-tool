# Installing and configuring a Dash node with manual steps
> The main purpose of this tutorial is educational, showing you all the steps you need to take manually to install the server part of the masternode service. Members of the Dash community have also created other tutorials that look at the problem from a slightly different perspective, allowing for more automation, for example: https://www.dash.org/forum/threads/system-wide-masternode-setup-with-systemd-auto-re-start-rfc.39460/.

## Scope of work
The goal is to run the official Dash daemon (`dashd`) software on a server (or a VPS service) whose IP address is visible on the Internet.

The minimum hardware requirements are: **2 GB RAM + 2 GB swap** and **60 GB of disk** space, with some provision to prevent running out of space which would result in the service stopping and a masternode falling out of the payment queue.

The most optimal solution these days is not to use a physical server, but instead to rent a service called VPS, which is basically a kind of virtual machine with a certain amount of hardware resources assigned to it. Some of these resources (such as RAM or disk space) are dedicated to your VPS, and some (such as CPU) are shared with other users of the platform.

Before you complete the following steps, you will need to choose and purchase a VPS service, as described in: [Choosing a VPS service](selecting-a-vps-service.md).

## Installation steps
After several minutes (up to an hour) after purchasing the VPS service you should receive an email from the provider with information about the IP address under which the service is available and the initial password set for the root user. The first steps to take are about securing the service. If you don't, your service may be taken over in such a way that you unknowingly make it available for botnet activities such as conducting DDOS attacks.

You will log into the VPS service from an **SSH terminal** running on your local computer. If your operating system is Windows, the best choice is to install **Putty** (https://www.ssh.com/academy/ssh/putty/download). If you use macOS or Linux, you don't need to install anything, because `ssh` program is installed by default.

> **Important**: Keep in mind, that in case you lose the ability to connect your VPS via SSH, you can always log in to a VPS management console from your VPS provider's control panel, and then you can fix the problem. This method will work, even if you accidentally put a firewall-level block on SSH communication.
> 
> To open the VPS text console in Linode, follow these steps:
> - log into the WEB management panel
> - click on `Linodes` on the top left side
> - click on the link with three dots on the right side of the selected VPS
> - from the menu that will appear click on the link "Launch LISH Console"
> - your VPS terminal will open in the new window

### 1. Update the operating system and install the software required
* Log in to your VPS service using an SSH terminal (Putty on Windows) with the IP address and root password you received from your provider
* Change the password for the root user:
  ```
  passwd root
  ```
* Install necessary packages and update the operating system:   
  ```
  apt update
  apt install -y ufw python virtualenv git unzip pv jq
  apt -y upgrade
  ```  
* Check if reboot is required after the update:
  ```
  cat /var/run/reboot-required
  ```
  if you see something like this as a result: `cat: /var/run/reboot-required: No such file or directory` then rebooting is not required, but if you see a message similar to this: `*** System restart required ***`, then issue the server reboot command:
  ```
  reboot
  ```
  > Note: after rebooting the server you need to log in again with an SSH terminal.

### 2. Creating a new Linux account that owns the Dash software
* Create a new linux user which will run the dash daemon. You will also use this account from now on to log in to your VPS via SSH. The name can be anything, so let's assume it is *dash*:  
  ```
  adduser dash
  ```
  The command will prompt you for a password (which you must enter) and some other information (which you can skip):  
  ```
  root@localhost:~# adduser dash
  Adding user `dash' ...
  Adding new group `dash' (1000) ...
  Adding new user `dash' (1000) with group `dash' ...
  Creating home directory `/home/dash' ...
  Copying files from `/etc/skel' ...
  New password:
  Retype new password:
  passwd: password updated successfully
  Changing the user information for dash
  Enter the new value, or press ENTER for the default
      Full Name []:
      Room Number []:
      Work Phone []:
      Home Phone []:
      Other []:
  Is the information correct? [Y/n] y
  ```
* Add the *dash* account to the sudo group, which will allow you to execute administrative commands from it:
  ```
  usermod -aG sudo dash
  ```
* Log out of the SSH terminal:
  ```
  exit
  ```

### 3. Generating private-public key pairs (done on your client computer)
The SSH protocol allows you to authenticate using a username and password, and that's what you'll do initially, right after setting up the VPS service. However, password based authenticated method is not considered secure (it allows relatively easy brute-force password cracking), so one of the first things you should do on the server is to change the authentication method to one that uses a public-private key pair.

> **Important:** This step should be done on your computer from which you connect via SSH to the VPS. It only needs to be done once, so if you already have an SSH key pair generated, you should skip the step.

- To generate private-public SSH keys on **Windows** follow the steps described here: https://www.ssh.com/academy/ssh/putty/windows/puttygen  
  During the procedure you will be given an SSH public key which you need to copy because you will need on further steps


- To generate private-public SSH keys on **Linux/macOS**, run the following command from your terminal application:
  ```
  ssh-keygen
  ```
  Your public key (needed in the next steps) can be displayed this way:
  ```
  cat ~/.ssh/id_rsa.pub
  ```
 
### 4. Copying your SSH public key to the server
* Log in to your VPS service with an SSH terminal
* Create the `.ssh` directory:
  ```
  mkdir -p ~/.ssh
  ```
* Open the `~/.ssh/authorized_keys` in your preferred editor (let's assume it's *nano*)
  ```
  nano ~/.ssh/authorized_keys
  ```
* In the editor, add a line containing the ssh public key obtained in the previous step. It should look more or less like this:
  ```
  ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQDssQzeLI6+OLXBROVqIPPAXzcgPR67R247TKZwrobZZAqQp27uwcNK/ClAGWenW1L/X3XG2KWomP/5nqaAHCTv4IZgOcZzjV/S+yAjFHlt6q4ZMoM8SWwWvpUzHgqSUIjyaFvNSpaXAEHMfRdVRKqiOUrjT3Atf1vts1t+NGRlULbiX+loh5MnrPvfVnDvhMcNIeZPlzzi634+Gvox8UOk28fR62roBuiY9FVweLmmiYYaQdiruzAl/K7rg8aVymp51vKa+M7rWt74HDvEl8sYqffqmFQe1pG13L1I2fUhRRnng/tE2rVvB403gnifo/bB7qpI3wcYV+28My45sfn70UKuCXev9ZEMEAJuH/aZ5pK/qEv2kdwcnMfyX1Gc0UJ7ZMPv350WDwR+jdrpzo659rZLUUqwcttkeKDmfSmj1zsU7rA1f7YHqCTz3g+Wk53dXembygpJlwEIJIDs7P6/ZmEWAAOVAcjKbEAzwui83l/NBp0fI1X2CuBjLt9dIKM= myuser@mycomputer
  ```
* Save your changes (Ctrl+O then ENTER) and close the editor (Ctrl+X)
* Test if authentication with SSH public key works by logging off of SSH client and logging on again with the `dash` user. You should now be able to log in without a password or with the password you set up for your SSH private key (which I recommend).

### 5. Secure your SSH server by disabling root logins and password authentication
* Open the SSH server configuracion file in a text editor:
  ```
  sudo nano /etc/ssh/sshd_config
  ```
  Now, find a line starting with the `PasswordAuthentication` parameter and set its value to `no`. If the line starts with a comment character (i.e. '#'), remove it (the '#' character). The line should look like this:
  ```
  PasswordAuthentication no
  ```
  In a similar manner, set the value `no` for the `PermitRootLogin` parameter:
  ```
  PermitRootLogin no
  ```
* Save your changes (Ctrl+O then ENTER) and close the editor (Ctrl+X)
* Restart the SSH service:
  ```
  sudo service sshd restart
  ```
* Test if you can log in with SSH session after the configuration changes by logging of and logging in again using the `dash` account

### 6. Configure the VPS firewall
To ensure your server security, you need to restrict incoming network traffic to only those ports that are necessary for its correct operation i.e.: 9999 and 22 TCP.

Login in to `dash` with your SSH terminal and execute:
  ````
  sudo ufw default deny incoming
  sudo ufw default allow outgoing
  sudo ufw allow 9999/tcp
  sudo ufw allow 22/tcp
  sudo ufw limit 22/tcp
  sudo ufw logging on
  sudo ufw enable
  ````
The following warning will be shown when the last command is run: `Command may disrupt existing ssh connections. Proceed with operation (y|n)?` to chich you should reply by typing: y.

### 7. Configure swap space
From your SSH terminal execute the following commands:
  ```
  sudo fallocate -l 4G /var/swapfile
  sudo chmod 600 /var/swapfile
  sudo mkswap /var/swapfile
  sudo swapon /var/swapfile
  ```

Configure a new swap file to be automatically enabled after reboot
* Open the `/etc/fstab` file in a text editor (e.g. nano):
  ```
  sudo nano /etc/fstab
  ```
* Add the following line to the end of the file:
  ```
  /var/swapfile none swap sw 0 0
  ```
* Save your changes and close the editor (Ctrl+O, ENTER, Ctrl+X)
* Restart VPS:
  ```
  sudo reboot
  ```

### 8. Import GPG public keys, so you can verify the authenticity of the Dash software you will download:
  
  ```
  curl https://keybase.io/codablock/pgp_keys.asc | gpg --import
  curl https://keybase.io/pasta/pgp_keys.asc | gpg --import
  ```  
  
  Source: [Veryfing Dash Core](https://docs.dash.org/en/stable/wallets/dashcore/installation-linux.html?#verifying-dash-core)

### 9. Download and configure Dash software
* Log in to your VPS using an SSH terminal with the `dash` linux account
* Download and configure the Dash software:
  ```
  mkdir -p ~/.dashcore
  cd ~/.dashcore
  ```
* Download the latest stable binaries for x86 64-bit platform: 
  ```
  platform=x86_64-linux
  for URL in $(curl -s https://api.github.com/repos/dashpay/dash/releases/latest | jq -r ".assets[] | select(.name | test(\"${platform}\")) | .browser_download_url")
  do
    echo Downloading $URL
    wget "$URL"
    gpg --verify *.asc
  done
  ```
The above commands should download two files: `dashcore-X.XX.X.X-x86_64-linux-gnu.tar.gz` and `dashcore-X.XX.X.X-x86_64-linux-gnu.tar.asc` (where X.XX.X.X are the current version number) and validate validity of the binary, which should result in a message like this:

```
gpg: assuming signed data in 'dashcore-0.17.0.3-x86_64-linux-gnu.tar.gz'
gpg: Signature made Mon 07 Jun 2021 05:38:40 PM UTC
gpg:                using RSA key 29590362EC878A81FD3C202B52527BEDABE87984
gpg: Good signature from "Pasta <pasta@dashboost.org>" [unknown]
gpg: WARNING: This key is not certified with a trusted signature!
gpg:          There is no indication that the signature belongs to the owner.
Primary key fingerprint: 2959 0362 EC87 8A81 FD3C  202B 5252 7BED ABE8 7984
```

If it doesn't happen, open the following address in your web browser: https://github.com/dashpay/dash/releases, find the latest stable release and copy the links to the above-mentioned files. Finally, run the `wget` command passing the URL as an argument. You should download files which names end with tar.gz and asc.
 
* Unpack the binary files and move the reqired ones to the current directory:
  ```
  tar xvf *.tar.gz && \
  mv dashcore*/bin/dash-cli ~/.dashcore/ && \
  mv dashcore*/bin/dashd ~/.dashcore/ && \
  rm -r dashcore*
  ```
  You should now have two files in the current directory: `dashd` and `dash-cli` and that's all you need to run a masternode.

### 10. Add the path to the Dash binaries in the .profile file
* Open the `~/.profile` in a text editor:
  ```
  nano ~/.profile
  ```
* Add the following line to the end of the file:
  ```
  export PATH=$PATH:~/.dashcore
  ```
* Save your changes (Ctrl+O, ENTER) and exit from the editor (Ctrl+X)
* Apply the new values:
  ```
  source ~/.profile
  ```
### 11. Create a configuration file with the initial settings for the Dash daemon
* Open the `~/.dashcore/dash.conf` file in a text editor:
  ```
  nano ~/.dashcore/dash.conf
  ```
* Paste the following contents into the file:
  ```
  rpcuser=USERNAME_FOR_RPC_INTERFACE
  rpcpassword=PASSWORD_FOR_RPC_INTERFACE
  rpcallowip=127.0.0.1
  port=9999
  listen=1
  server=1
  daemon=1
  externalip=ENTER_YOUR_VPS_EXTERNAL_IP
  ```
    - replace the string USERNAME_FOR_RPC_INTERFACE with the username for RPC interface, e.g. username00388775893245
    - replace the string PASSWORD_FOR_RPC_INTERFACE with the password for RPC intereface, e.g. passs899879824398543
    - replace the string ENTER_YOUR_VPS_EXTERNAL_IP with the external IP address of your VPS (you can get it with the `ip addr` command)

  What values you choose for USERNAME_FOR_RPC_INTERFACE and PASSWORD_FOR_RPC_INTERFACE is completely irrelevant.

### 12. Installing *sentinel*
Sentinel is an additional program that must be installed for the masternode to perform all necessary operations. It is a program written in Python and its installation basically consists of downloading the source code from GitHub and preparing the runtime environment.

The next steps will be performed from the SSH terminal after logging in to the dash user.

* Download the sentinel source code and create the runtime environment:
  ```
  cd ~/.dashcore
  git clone https://github.com/dashpay/sentinel
  cd sentinel
  virtualenv venv
  venv/bin/pip install -r requirements.txt
  venv/bin/py.test test 
  venv/bin/python bin/sentinel.py
  ```

  If your node is not completely synchronized with the network, you will see the appropriate message. If everything is ok, the last command will return nothing.

* Configure sentinel execution

  Sentinel is a script that needs to be run periodically (once per minute) so now you need to add a proper cron job.
  
  Run the cron configuration editor:
  ```
  crontab -e
  ```
  > **Note**. If this is the first time you are running crontab, you will be asked which editor to use for this. If you are not an advanced Linux user I suggest you choose the nano editor.
  
  Add the following line:
  ```
  * * * * * cd ~/.dashcore/sentinel && ./venv/bin/python bin/sentinel.py 2>&1 >> sentinel-cron.log
  ```

* Save your changes (CTRL+O, ENTER) and exit the editor (CTRL+X)

### 13. Start the dashd program and wait for the blockchain synchronization to complete
```
~/.dashcore/dashd
```

From that point on, a copy of the Dash blockchain will be downloaded to the server, which may take several hours. To find out the current status of the operation run the `dash-cli mnsync status` command periodically, which prints something like this:
```
{
  "AssetID": 1,
  "AssetName": "MASTERNODE_SYNC_BLOCKCHAIN",
  "AssetStartTime": 1645525803,
  "Attempt": 0,
  "IsBlockchainSynced": false,
  "IsSynced": false
}
```

The whole operation is complete if the *AssetName* field has the value *MASTERNODE_SYNC_FINISHED*:
```
{
  "AssetID": 999,
  "AssetName": "MASTERNODE_SYNC_FINISHED",
  "AssetStartTime": 1645483294,
  "Attempt": 0,
  "IsBlockchainSynced": true,
  "IsSynced": true
}
```

## Troubleshooting
### Problem 1: `error code: -28` after executing the `dash-cli` command
**Reason**: your *dashd* haven't finished reading all the required local files.

**Resolution**: give the *Dash daemon* a few minutes more time to read all the data it needs and then reissue the command.

### Problem 2: `error: Could not connect to the server 127.0.0.1:9998` after executing `dash-cli`
**Reason**: it is likely that the *dashd* process has shut down due to some error.

**Resolution**: print the last several dozen lines of the Dash daemon debug file, where you are likely to find details of the problem. To do this, execute the following command `tail -50 ~/.dashcore/debug.log`.

Example output:
```
2022-02-22T10:07:47Z Using obfuscation key for /home/dash/.dashcore/chainstate: 17bf71958bfd9538
2022-02-22T10:07:47Z Loaded best chain: hashBestChain=000000000000001171930700a469c3beef8ac9ab5cf0d1bfb2f32a1c867bc150 height=1626315 date=2022-02-22T09:59:01Z progress=0.999996
2022-02-22T10:07:47Z CQuorumBlockProcessor::UpgradeDB -- Upgrading DB...
2022-02-22T10:10:08Z CQuorumBlockProcessor::UpgradeDB -- Upgrade done...
2022-02-22T10:10:08Z init message: Verifying blocks...
2022-02-22T10:10:08Z Verifying last 6 blocks at level 3
2022-02-22T10:10:08Z [0%]...*** Found EvoDB inconsistency, you must reindex to continue
2022-02-22T10:10:08Z Error: Error: A fatal internal error occurred, see debug.log for details
2022-02-22T10:10:08Z ERROR: VerifyDB(): *** irrecoverable inconsistency in block data at 1626315, hash=000000000000001171930700a469c3beef8ac9ab5cf0d1bfb2f32a1c867bc150
2022-02-22T10:10:08Z Shutdown requested. Exiting.
2022-02-22T10:10:08Z PrepareShutdown: In progress...
2022-02-22T10:10:08Z RenameThread: thread new name dash-shutoff
2022-02-22T10:10:08Z cl-schdlr thread exit
2022-02-22T10:10:08Z scheduler thread interrupt
2022-02-22T10:10:08Z Shutdown: done
```

The actucal resolution depends on the nature of the problem. In our case, the problematic line is: `Found EvoDB inconsistency, you must reindex to continue`, which also suggests about the possible resolution, which in this case is reindexing. You can initiate it by executing:
```
~/.dashcore/dashd -reindex
```
> Note: reindexing is a time-consuming process, so it's likely that you will have to wait a few hours to complete. The status of the operation can be checked by executing the `dash-cli mnsync status` command.
