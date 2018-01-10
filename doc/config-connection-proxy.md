## Connection to "public" nodes
This solution is designed for non-technical users who may have difficulty configuring their own JSON-RPC node, or for those who do not want to waste their time repeating what others have done before and have made publicly available :-)

From the user's point of view, the solution is based on several JSON-RPC nodes made available by the Dash community to the users of the *Dash Masternode Tool* and *dashmnb* apps. At the time of writing, one of the nodes (actually three, accessed under one shared IP address) was managed by @chaeplin, a very well-known Dash Core developer, and the other two by myself (@Bertrand256).

### Technical information
These nodes are based on the following components:
 * Dash daemon (*dashd*) processing JSON-RPC requests
 * *Nginx* web server, as a frontend serving SSL requests sent by the applications
 * A Lua script, as a broker between *nginx* and *dashd*

Configuration is based on ethereum-nginx-proxy, adapted to Dash requirements by @chaeplin: https://github.com/chaeplin/dash-ticker/tree/master/web/nginx

### Configuration
When version 0.9.5 or higher of the DMT application is run the first time, "public" connections will automatically be added to the configuration. Open DMT and click the `Configure` button. In the `Configuration` dialog you should see the following three connections:
 * https://alice.dash-dmt.eu:8080
 * https://luna.dash-dmt.eu:8080
 * https://test.stats.dash.org:8080

![1](img/dmt-config-dlg-public.png)


If you see connections and all three are checked (enabled) you don't need to do anything. If you see connections but they are not enabled, you just need to enable them. I also suggest deactivating all other connections, since these may be connections from an old configuration.

If any of the listed "predefined" nodes are missing or are incomplete, follow these steps:
 * Select all the text from the block below and copy to the clipboard (do not miss the square brackets at the beginning and the end of the text):
```﻿
[
    {
        "use_ssh_tunnel": false,
        "use_ssl": true,
        "port": "443",
        "username": "dmtuser",
        "host": "alice.dash-dmt.eu",
        "password": "674141414141425a4d5343545262596869657472393230696f3761674a6d30305261715f79656d45664a5559454b69587251482d3972473641623363353542647261704e735f4650313579584143776e704e7730444c6663556346397653576e58513d3d"
    },
    {
        "use_ssh_tunnel": false,
        "use_ssl": true,
        "port": "8080",
        "username": "dmtuser",
        "host": "luna.dash-dmt.eu",
        "password": "674141414141425a4d534354795549726a48735f4b6f3757585a743151533573735f354e58464a6b6f76766c705a472d4935726c4655456b7452686e356856416a385443446433496972485a4c4745354d3768745a6264424858537343466a6871773d3d"
    },
    {
        "use_ssh_tunnel": false,
        "use_ssl": true,
        "port": "8080",
        "username": "dashmnb",
        "host": "test.stats.dash.org",
        "password": "674141414141425a4d534354374f4757395062686a33346f445f71375a45306349514d72476b46746943716d376b4b556566764a326137586b42632d71564f71336a34516f586a472d73565258694c6d3246727a6f657951637435706f5f533857673d3d"
    }
]
```
 * Right-click on the `Connections` box.
 * From the popup menu choose the `Paste connection(s) from cliboard` action:
    ![1](img/dmt-config-dlg-public-recover.png)
 * Click `Yes` to the question whether you want to import connections.

All three connections should then be added to the configuration.

### Security
To perform its job, the application must send some data to the JSON-RPC node that may be perceived as sensitive. Specifically, these are the client's IP address and the JSON-RPC commands themselves, with their respective arguments.

For example, the action initiated by the `Get status` button sends the following data to the node:
```python
{"version": "1.1", "id": 2, "params": ["full", "19e7eba493a026f205078469566e4df6a5a4b1428965574b55bec2412ddc9c48-0"], "method": "masternodelist"}
```

To maximize user anonymity, all three published nodes have disabled logging of any information related to JSON-RPC commands. The logging configuration is exactly the same as the example scripts provided by @chaeplin here: [https://github.com/chaeplin/dash-ticker/tree/master/web/nginx](https://github.com/chaeplin/dash-ticker/tree/master/web/nginx).

Despite this, if you would prefer not to risk sharing this information, it is suggested to disable the configuration options for the "public" nodes and choose a different type of connection:

- [Connection to a local Dash daemon](config-connection-direct.md)
- [Connection to a remote Dash daemon through an SSH tunnel](config-connection-ssh.md)