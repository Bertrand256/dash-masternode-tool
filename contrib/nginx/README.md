This configuration is based on https://github.com/chaeplin/dash-ticker/tree/master/web/nginx

## Installation recommendations
Based on Ubuntu 20.04

```
apt-get install nginx nginx-extras apache2-utils luarocks
luarocks install lua-cjson

cp zcoin-jsonrpc-access.lua /usr/share/nginx/
cp default /etc/nginx/sites-available/
```

Restart nginx

firo.conf example
```
testnet=1
bind=127.10.10.1
port=18168
server=1
whitelist=127.0.0.1
txindex=1
addressindex=1
timestampindex=1
spentindex=1
zmqpubrawtx=tcp://127.0.0.1:28332
zmqpubhashblock=tcp://127.0.0.1:28332
rpcallowip=127.0.0.1
rpcuser=A unique user name
rpcpassword=A unique user password
rpcport=8888
uacomment=bitcore
```
