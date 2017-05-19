## Connection to remote Dash daemon through on SSH tunnel

### SSH tunnels
If you - as probably most masternode owners - have your masternode runnung under VPS service and you have access to it via SSH, then using it as a JSON-RPC gateway will probably be the best option for you. 

For security reasons, the TCP port used for JSON-RPC communication (9998 by dafault) should be blocked on Dash full-nodes. For this reason, you will not be able to connect to it directly over the Internet. However, if you have SSH access to this server, you can create a secure channel that connects the local machine to the remote JSON-RPC service so that the DMT application feels like the remote service was working locally. 

The communication is carried out as follows:
 * an SSH session with a remote server (Dash daemon) is created using its public IP and SSH port 
 * out of the pool of unused ports on your computer, a random is selected to play the role of the local channel's endpoint
 * within established SSH session a secure channel is created that connects local endpoint with the port on which the JSON-RPC service is listening on the remote server (127.0.0.1:9998)
 * DMT connects to the local endpoint and performs JSON-RPC requests as if the _Dash daemon_ was working locally
 

```
 Local computer ━━━━━━━━━━━━━━━━➜ SSH session ━━━━━━━━━━━━━━━━➜ remote_server:22
           ┃- connecting to 127.0.0.1:random local port           ┃ - listenning on 127.0.0.1:9998 
 DMT app ━━┛                                                      ┗━━━ Dash daemon JSON-RPC
```

### Configuration

#### 1. Enable JSON-RPC and "indexing" in the Dash daemon
The procedure is similar to the RPC/indexing [setup](config-connection-direct.md) in Dash Core application.
