## Connection to "public" nodes
This solution is dedicated for non-technical users who may not be able to properly configure the JSON-RPC node or for those who do not want to waste their time on what others have done before and have made available :-) 

From the user's point of view, the solution is based on several JSON-RPC nodes made available to the users of the _DashMasternodeTool_ and _dashmnb_ apps, by other users of the Dash community. At the time of writing, one of the nodes (actually three, accessed by one IP address) was shared by @chaeplin, a very well-known member of the Dash community, and the other two by me (@Bertrand256).

### Technical information
These nodes are based on the following components:
 * _Dash daemon_ processing JSON-RPC requests
 * _Nginx_ web server, as a frontend for serving SSL requests sent by the applications
 * A Lua script, as a broker between _nginx_ and _dashd_ 

Configuration is based on ethereum-nginx-proxy, adapted to Dash requirements by @chaeplin: 
 https://github.com/chaeplin/dash-ticker/tree/master/web/nginx

### Configuration
When version >= 0.9.5 of DMT application will be run the first time, _"public"_ connections will automatically be added to the configuration. In the _Configuration_ dialog you should see the following three connections:
 * https://alice.dash-dmt.eu:8080
 * https://luna.dash-dmt.eu:8080
 * https://test.stats.dash.org:8080

![1](img/dmt-config-dlg-public.png)  


If you see connections and all three are checked (enabled) you don't need to do anything. If you see connections but they are not enabled, you just need to enable them. I also suggest deactivating all other connections, if any  - these may be connections from the old configuration.
 
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
 
As a result, all three connections should be added to the configuration.

### Security
To perform its job, the application must send some data to the JSON-RPC node that may be percieved as sensitive. These are: the client's IP address and the JSON-RPC command themselves with their arguments. 

For example, action initiated by the `Get status` button sends the following data to the node: 
```python
{"version": "1.1", "id": 2, "params": ["full", "19e7eba493a026f205078469566e4df6a5a4b1428965574b55bec2412ddc9c48-0"], "method": "masternodelist"}
```

To maximize user anonymity, all three published nodes don't have enabled logging of any information related to JSON-RPC commands. The logging configuration is exactly the same as in the example scripts provided by @chaeplin: https://github.com/chaeplin/dash-ticker/tree/master/web/nginx.

If despite this, you would prefer not to risk sharing this information, I suggest you disabling the configuration of the "public" nodes and choosing a different connection type: [connection to a local Dash daemon](config-connection-direct.md) or [connection to a remote Dash daemon through an SSH tunnel](config-connection-ssh.md).