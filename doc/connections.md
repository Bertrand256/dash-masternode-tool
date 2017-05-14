## Direct JSON RPC connection
In this scenario you are going to use your own _Dash daemon_ configured to serve JSON-RPC requests on your local network or on any network you have direct (non filtered) access to. The most convinient way to achieve this is to run the daemon on the same computer on which you run the DMT application. 

### 1. Install Dash-DQ software wallet
As a _Dash daemon_ you are going to use the Dash official client - Dash-QT. If you haven't installed this program before, do it now, by downloading installer that matches your operating system from the following URL: https://www.dash.org/wallets.

### 2. Enable JSON-RPC and _indexing_ in the Dash-Qt
Default configuration of Dash-Qt doesn't have any of the required settings, so editing its configuration file (dash.conf) will be necessary. Location of `dash.conf` file is different on each OS and can also be changed during installation process, so the easiest way to locate this file is to click the `Tools->Open Wallet Configuration File` menu item of the Dash-Qt application.  

After that, the `dash.conf` file will open in the default text editor. Paste the following parameters/values into the file, changing the `rpcuser` and `rpcpassword` values to your own:

```ini
rpcuser=any_alphanumeric_string_as_a_username
rpcpassword=any_alphanumeric_string_as_a_password
rpcport=9998
rpcallowip=127.0.0.1
server=1
addressindex=1
spentindex=1
timestampindex=1
txindex=1
```
  
#### 2.1 Restart Dash-Qt.
#### 2.2 Rebuild index
 * Click the _Toools->Wallet Repair_ menu item.
 * In the _Tools_ window click the _Rebuild index_ menu item.
 ![](dmt-config-rebuild-index.png)

 
### 3. Configure connection in the DMT app
In the main window click "Configure" button.
Choose tab "Dashd direct RPC" if your Dash daemon works on your local network or has exposed RPC port on the Internet (not recomended). In this mode dialog's parameters are self explanatory.

If your Dash daemon works on remote server and according to most recomendations, has no RPC port exposed to the Internet, but on the other hand has open SSH port (22), second mode, activated by clicking "Dashd RPC over SSH tunnel", is for you.

Enter values in the "SSH host", "port" and "SSH username" editboxes.
Now, you can click "Read RPC configuration from SSH host" button to automatically read dashd.conf file from your remote server and then extract parameters related to RPC configuration. This option requires that provided username has privileges to read dash.conf file. This step is not required - you can enter that values manually.

Click "Test connection" to check if RPC communication works as expected.

## JSON-RPC connection through SSH tunnel

### 1. Configure connection in the DMT app

