## Connection to a local Dash daemon
In this scenario, you will use your own _Dash daemon_ configured to serve JSON-RPC requests on your local network or any network you can access directly. The most convenient way to achieve this is to run a daemon on the same computer as the DMT application itself.

### 1. Install the Dash Core wallet
We will use the official Dash Core client as the _Dash daemon_ for this configuration. Install it now if now already installed. Binary installers for macOS, Linux and Windows can be downloaded from the [official site](https://www.dash.org/wallets), while documentation on the installation process is available on the [Dash Wiki](https://dashpay.atlassian.net/wiki/spaces/DOC/pages/1867921).

### 2. Enable JSON-RPC and "indexing" in Dash Core
####  2.1 Set the required parameters in the `dash.conf` file
The default Dash Core configuration does not include all of the required settings, so some changes to the `dash.conf` file are necessary. The location of this file varies depending on the operating system you are using and may be changed during installation, so paths will not be specified here due to possible confusion. Instead, select `Tools -> Open Wallet Configuration File` from the Dash Core menu. The `dash.conf` file will open in your default text editor.

Copy and paste the following parameters/values into the file, changing the `rpcuser` and `rpcpassword` values to your own unique values:
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

#### 2.1 Restart Dash Core

Close Dash Core by selecting `File -> Exit` from the menu, then open it again.

#### 2.2 Rebuild index
Setting parameters related to indexing and even restarting the application is not enough for Dash Core to entirely update its internal database to support indexing, so it is necessary to force the operation. Follow the following steps to do so:

 * Select the `Tools -> Wallet Repair` menu item.
 * Click the `Rebuild index` button in the Wallet Repair dialog box. 
    ![1](img/dashqt-rebuild-index.png)
 * Wait until the operation is complete. This step may take several hours.

### 3. Configure connection in the DMT
 * In the main application window click the `Configure` button. 
 * Choose the `Dashd network` tab.
 * Click the `+` (plus) button on the left side of the dialog.
 * Check the box `Enabled`.
 * Fill in the values:
   * `RPC host` to 127.0.0.1
   * `port` to 9998
   * `RPC username` to a value you've entered for `rpcuser` parameter in the `dash.conf` file.
   * `RPC password` to a value you've entered for `rpcpassword` parameter in the `dash.conf` file.
 * Make sure, that `Use SSH tunnel` and `SSL` checkboxes are unchecked. Also, if you decide to use only this connection, deactivate all other connections by unchecking their `Enabled` checkbox.  
    ![!](img/dmt-config-dlg-conn-direct.png)
 * Click the `Test connection` button. The successful connection test ends with the following message:  
    ![](img/dmt-conn-success.png)



