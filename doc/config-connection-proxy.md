## Connection to a "public" node
This solution is dedicated for non-technical users who may not be able to properly configure the JSON-RPC node or for those who do not want to waste their time on what others have done before and have made available :-) 

From the user's point of view, the solution is based on several JSON-RPC nodes made available to the users of the _DashMasternodeTool_ and _dashmnb_ apps, by other users of the Dash community. 

### Technical details
These nodes consist of:
 * _Dash daemon_ processing JSON-RPC requests
 * _Nginx_ web server, as a frontend for serving SSL requests sent by the applications
 * A Lua script, as a broker between _nginx_ and _dashd_ 

Configuration is based on ethereum-nginx-proxy, adapted to Dash by the user @chaeplin: 
 https://github.com/chaeplin/dash-ticker/tree/master/web/nginx

_Will be completed soon..._
 