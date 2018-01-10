## Connection to "public" nodes

This solution is designed for non-technical users who may have difficulty configuring their own JSON-RPC node, or for those who do not want to waste their time repeating what others have done before and have made publicly available :-)

From the user's point of view, the solution is based on several JSON-RPC nodes made available by the Dash community to the users of the *Dash Masternode Tool* and *dashmnb* apps. At the time of writing, one of the nodes (actually three, accessed under one shared IP address) was managed by @chaeplin, a very well-known Dash Core developer, and the other three by myself (@Bertrand256).

### Technical information

These nodes are based on the following components:
 * Dash daemon (*dashd*) processing JSON-RPC requests
 * *Nginx* web server, as a frontend serving SSL requests sent by the applications
 * A Lua script, as a broker between *nginx* and *dashd*

Configuration is based on ethereum-nginx-proxy, adapted to Dash requirements by @chaeplin: https://github.com/chaeplin/dash-ticker/tree/master/web/nginx

### Configuration

When version 0.9.5 or higher of the DMT application is run the first time, "public" connections will automatically be added to the configuration. Open DMT and click the `Configure` button. In the `Configuration` dialog you should see the following three connections:
 * https://alice.dash-masternode-tool.org:443
 * https://luna.dash-masternode-tool.org:443
 * https://suzy.dash-masternode-tool.org:443
 * https://test.stats.dash.org:8080

![Public connection configuration window](img/dmt-config-dlg-public.png)

If you see connections and all three are checked (enabled) you don't need to do anything. If you see connections but they are not enabled, you just need to enable them. I also suggest deactivating all other connections, since these may be connections from an old configuration.

If any of the listed "predefined" nodes are missing or are incomplete, follow these steps:
 * Select all the text from the block below and copy to the clipboard (do not miss the square brackets at the beginning and the end of the text):
```﻿
[
    {
        "use_ssh_tunnel": false,
        "host": "alice.dash-masternode-tool.org",
        "port": "443",
        "username": "dmtuser",
        "password": "6741414141414261574c7443574d303967325967653459306a634d3631784a6c496236513268526d6658437952675837506272442d7345326c717a72426b37416b4644665651366676545537435a6c4a4345395f6655494f4b486f5f5f63326761413d3d",
        "use_ssl": true
    },
    {
        "use_ssh_tunnel": false,
        "host": "luna.dash-masternode-tool.org",
        "port": "443",
        "username": "dmtuser",
        "password": "6741414141414261574c7443423764302d6655786749634e7264586a7647386e306b454c646c6538654e644f5865746878647839324172702d426d4b5446614349566a346a5670456c4c704f6238666e635a5648765331524252487955646e765a413d3d",
        "use_ssl": true
    },
    {
        "use_ssh_tunnel": false,
        "host": "suzy.dash-masternode-tool.org",
        "port": "443",
        "username": "dmtuser",
        "password": "6741414141414261574c7443534d343635444e415259447538496f4b6b64455670376c4c614250705f4d3274495f62436d5430475649417933414a59564f56315430314c51515875536c54374a4b54754e3042627a7a48337835527a654e664e66413d3d",
        "use_ssl": true
    },
    {
        "use_ssh_tunnel": false,
        "host": "test.stats.dash.org",
        "port": "8080",
        "username": "dashmnb",
        "password": "674141414141425a454375364c477053456746506a7759345166693547595574506330616550636c6e6f77426c36487276586a56345962494e527a79464e54676937716f6958706a6a377348387a32736d423271304d354e4f754a595449796a56413d3d",
        "use_ssl": true
    }
]
```
 * Right-click on the `Connections` box.
 * From the popup menu choose the `Paste connection(s) from cliboard` action:
    ![Paste connections from clipboard](img/dmt-config-dlg-public-recover.png)
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
