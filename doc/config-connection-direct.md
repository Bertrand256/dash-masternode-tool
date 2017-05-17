## Direct JSON RPC connection
In this scenario you are going to use your own _Dash daemon_ configured to serve JSON-RPC requests on your local network or on any network you have direct (non filtered) access to. The most convinient way to achieve this is to run a daemon on the same computer on which you run the DMT application. 

### 1. Install Dash-DQ software wallet
As a _Dash daemon_ you are going to use the Dash official client - Dash-QT. If you haven't installed this program before, do it now. Installer matching your operating system can be downloaded from the following page: https://www.dash.org/wallets.

### 2. Enable JSON-RPC and _indexing_ in the Dash-Qt
Default Dash-Qt configuration doesn't have any of the required settings, so it will be necessary to make some changes in the `dash.conf` file. Location of this file differs depending on the OS you are using and can be changed during installation process, so the easiest way of locating of its containing folder is to click the `Tools->Open Wallet Configuration File` menu item of the Dash-Qt application.  

After that `dash.conf` file will be open in default text editor. Paste the following parameters/values into the file, changing the `rpcuser` and `rpcpassword` values to your own:

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
  
#### 2.1 Restart Dash-Qt
#### 2.2 Rebuild index
 * Click the _Toools->Wallet Repair_ menu item.
 * In the _Tools_ window click the _Rebuild index_ menu item.
 ![1](dmt-config-rebuild-index.png)

 
### 3. Configure connection in the DMT app
 * In the main application window click `Configure` button. 
 * Choose the tab `Dashd network`
 * Click the `+` (plus) button on the left side of the dialog.
 * Fill in the values:
   * `RPC host` to 127.0.0.1
   * `port` to 9998
   * `RPC username` to a value you've entered for `rpcuser` parameter in the `dash.conf` file.
   * `RPC password` to a value you've entered for `rpcpassword` parameter in the `dash.conf` file.
 * Make sure, that `Use SSH tunnel` and `SSL` checkboxes are in unchecked state.
 * Click the `Test connection` button. The successful connection test ends with the following message:
 ![](dmt-conn-success.png)
 


## JSON-RPC connection through SSH tunnel

### 1. Configure connection in the DMT app

