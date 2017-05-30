## Configuration procedure for a new masternode
This procedure is for people who are configuring their masternode from the beginning (are not transfering the existing configuration).

Before covering the individual steps, I will briefly describe the prerequisites:
  * You have a server with an IP address available from the Internet on which you have installed _Dash daemon_ (_dashd_) software.
  
  * You have access to the server with an SSH terminal.
  
  * The operating system you are using on your server is Linux. I won't describe all possible OS-es on which you can run a masternode, but instead, I assume that you are using the most popular one for this purpose.
  
  * _dashd_ has been installed in the home directory of the user to which you log on to the server.
  
#### Sending 1000 Dash to the address controlled by your hardware wallet
##### Step 1
The procedure is described [here](config-masternodes-a.md#sending-1000-dash-to-the-address-controlled-by-your-hardware-wallet).

#### Filling in the masternode configuration fields

##### Step 2
Run DashMasternodeTool application.
  
##### Step 3
Click the `New` button. This will activate the editing mode. If you don't have any masternode configured, the editing mode will be invoked automatically just after starting the application.
  
##### Step 4
Fill in the fields:
  * `Name`: name/label of your masternode (it can be any alphanumeric string).
  
  * `IP`: the _dashd_ server's IP address.
  
  * `port`: the TCP port number on which _dashd_ is listening for incoming connections. You should use the `rpcport` parameter's value from `dash.conf` file. 
  
##### Step 5
Click the `Generate new` button on the right side of the `MN private key` field to generate a new masternode _private key_.
  
  > Masternode **private keys**. Some users think that the masternode private key is somehow associated with the private key of the 1000-Dash collateral, but in fact, they have no relationship. The masternode private key is generated independently and is only used in the process of signing _start masternode_ message and voting on proposals and as such it is not particularly dangerous for him to get into the wrong hands. Therefore, the application gives the possibility of generating it by simple button-click and thus avoiding using _Dash Core_ for this purpose. From a technical point of view, a masternode private key in a normal _Dash WiF uncompressed_ format.
   
##### Step 6
Enter the collateral related information as described [here](config-masternodes-a.md#entering-the-collateral-related-information).


![1](img/conf-masternodes-b-1.png)  

#### Changing the configuration of your Dash daemon
During the procedure described in section 2, you have generated a new masternode private key, which has to be transferred to your _Dash daemon_ config file.
  
##### Step 7
Log in to the server running _Dash daemon_ software with your preferred SSH terminal client (for example putty on Windows OS), and:
  
  * open the `~/.dashcore/dash.conf` file with your preferred linux text editor, for example: `vi ~/.dashcore/dash.conf`
  
  * set the `masternodeprivkey` parameter with the masternode private key you have generated in [Step 5](#step-5)  
  ![1](img/conf-masternodes-b-2.png)
   
  * save the file and exit the editor
  
  * restart the _Dash daemon_:
  ```bash
   $ cd ~
   $ ./dash-cli stop
   $ ./dashd
  ```
  
#### 4. Next steps
Before you go to the last step of the whole procedure, which is sending a [start masternode](../README.md#starting-masternode) message, you have to wait until the collateral's transaction has at least 15 confirmations ([look here](config-masternodes-a.md#next-steps)).

