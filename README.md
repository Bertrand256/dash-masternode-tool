# Dash Masternode Tool (DMT)

## Contents
 * [Masternodes](#masternodes)  
 * [DashMasternodeTool](#dashmasternodetool)  
   * [Features list](#features-list)
   * [Supported hardware wallets](#supported-hardware-wallets)
 * [Configuration](#configuration)
   * [Setting up the hardware wallet type](#setting-up-the-hardware-wallet-type)
   * [Connection setup](#connection-setup)
     * [Connection to a local node](doc/config-connection-direct.md)
     * [Connection to a remote node trough an SSH tunnel](doc/config-connection-ssh.md)
     * [Connection to "public" JSON-RPC nodes](doc/config-connection-proxy.md) 
   * [Masternode setup](#masternode-setup)
     * [Scenario A: movig masternode management from Dash Core](doc/config-masternodes-a.md)
     * [Scenario B: configuration of a new masternode](doc/config-masternodes-b.md)
   * [Commandline parameters](#commandline-parameters)
 * [Features](#features)
   * [Starting masternode](#starting-masternode)
   * [Transferring of masternode earnings](#transferring-of-masternode-earnings)
   * [Signing messages with hardware wallet](#signing-messages-with-hardware-wallet)
   * [Changing hardware wallet's PIN/passphrase](#changing-hardware-wallets-pinpassphrase)
   * [Proposals: browsing and voting on](doc/proposals.md)
 * [Downloads](https://github.com/Bertrand256/dash-masternode-tool/releases/latest)

## Masternodes
Dash masternodes are full-nodes which are incentivized by paying them a share of the block reward for the work they do for the network, from which the most important are participation in _InstantSend_ and _PrivateSend_ transactions. In order to run a masternode, apart from setting up a server wich runs the software, you must dedicate a 1000 Dash _collateral_, which is _"tied up"_ to your node as long as you want it to be considered a masternode. It's worth to mention, that the private key controlling the funds can (and for security reasons it should) be kept outside the masternode server itself. 

A server + installed _Dash daemon_ software make a Dash full-node, but before the rest of the network accepts it as a legitimate masternode, one more thing must happen: the person controlling the node must prove, that he/she is also in control of the private key of the node's 1000 Dash _collateral_. This is achieved by the requirement of sending to the network a special message (_start masternode_ message) signed by this private key.  

This action can be performed with the Dash reference software client - _Dash Core_. As can be expected, this requires sending of 1000 Dash to the address controlled by _Dash Core_ wallet. After the recent increase in the value of Dash and burst of the amount of malware distributed over the Internet, you do not have to be paranoid to say that keeping that amount of funds in a software wallet is not really secure. For these reasons, it's highly recommended to use a **hardware wallet** for this purpose.

## DashMasternodeTool
The main purpose of the application is to give masternode owners (MNOs) the ability to send _Start masternode_ command with easy to use a graphical interface if MN's collateral is controlled by a hardware wallet such as Trezor or Keepkey.

#### Features list
- Sending _Start masternode_ command if the collateral is controlled by a hardware wallet.
- Transfering masternode's earnings in a safe way - without touching collateral's 1000 Dash transaction.
- Signing messages with a hardware wallet.
- Voting on proposals (work in progress).

#### Supported hardware wallets
- [x] Trezor
- [x] KeepKey
- [x] Ledger Nano S (now only starting masternode feature)

Most ot the application features are accessible from the main program window:  
![Main window](doc/img/dmt-main-window.png)

## Configuration

### Setting up the hardware wallet type
 * Click the `Configure` button.
 * In the configuration dialog that will open, select the `Miscellaneous` tab.
 * Depending on the type of your hard ware wallet, select the `Trezor`, `Keepkey` or `Ledger Nano S` option.      
 ![1](doc/img/dmt-config-dlg-misc.png)

### Connection setup

Most of the application features involve exchanging data between the application itself and the Dash network. Thus, _DMT_ needs to connect to one of the full nodes that make up the network, more specifically - the one that handles JSON-RPC requests. For _DMT_ this node will be playing the role of a gateway to the Dash network. It does not matter which exactly this node is - for the Dash network all are equal and exchange information among themselves.

Depending on your preferences (and skills) you can choose one of three possible connection types:
 * [Direct connection to a local node](doc/config-connection-direct.md), for example to your _Dash Core_.
 * [Connection to a remote node through an SSH tunnel](doc/config-connection-ssh.md), if you'd like to work with remote Dash daemon (like your masternode) through an SSH tunnel.
 * [Connection to "public" JSON-RPC nodes](doc/config-connection-proxy.md), if you'd like to use nodes provided by the other users.

### Masternode setup
Here, I have to make the following assumptions:
  * You already have a server with a running Dash daemon software (_dashd_), that you want to use as a masternode. If you don't, you need to install and configure one, following the guidelines from Dashpay Atlassian Wiki: https://dashpay.atlassian.net/wiki/display/DOC/Set+Up.
  * A few times I will be referring to a _dashd_ configuration file, so I'm assuming here, that your _dashd_ works on linux OS, as the most popular and recommended OS for this purpose.
  * Your server has a public IP address that will be visible on the Internet.
  * You have set up a TCP port on which your _dashd_ listens for incoming connections (usually 9999). 
  
Further configuration steps depend on whether you already have a masternode controlled by _Dash Core_ and which you'd like to migrate to _DMT_ + Trezor tandem or you are just setting up a new one. 

[Scenario A - moving masternode management from Dash Core](doc/config-masternodes-a.md)  
[Scenario B - configuration of a new masternode](doc/config-masternodes-b.md)  

### Commandline parameters
Currently the application supports one command-line parameter: `--config`, which can be used to pass a non-standard path to a configuration file. Example:
```
DashMasternodeTool.exe --config=C:\dmt-configs\config1.ini 
```

## Features
### Starting Masternode
Once you set up the Dash daemon and perform the required _DMT_ configuration, you need to broadcast the `Start masternode` message to the Dash network, so that the other Dash nodes start to perceive your daemon as a masternode and add it to the payment queue.

To do this, click the `Start Masternode using Hardware Wallet` button.

### Sequence of actions
Below I present steps the application performs while starting the masternode and possible problems that may occur during the process. 

The steps are as follows:
  
1. Verification if all the required fields are filled with the correct values. These are the fields: `IP`, `port`, `MN private key`, `Collateral`, `Collateral TX ID` and `TX index`.  
An example message in case of errors:  
  ![1](doc/img/startmn-fields-validation-error.png)
  
2. Opening a connection to the Dash network and verifying if the Dash daemon to which it is connected is not synchronizing.  
Message in the case of failure:  
  ![1](doc/img/startmn-synchronize-warning.png)  
  
3. Verification if the masternode status is not _ENABLED_ or _PRE_ENABLED_. If it is, the following warning appears:  
  ![1](doc/img/startmn-state-warning.png)  
  If your masternode is running and you decide to send _Start masternode_ message anyway, your masternode's payment queue location will be reset. 
  
4. Opening a connection to the hardware wallet.  
Message in the case of failure:  
  ![1](doc/img/startmn-hw-error.png) 
  
5. If the `BIP32 path` value is empty, _DMT_ uses the _collateral address_ to read the BIP32 path from the hardware wallet. 
  
6. Retrieving the Dash address from the hardware wallet for the `BIP32 path` specified in the configuration. If it differs from the collateral address provided in the configuration, the following warning appears:  
  ![1](doc/img/startmn-addr-mismatch-warning.png)   
The most common reason for this error is mistyping the hardware wallet passphrase. Remember, that different passphrases result in different Dash addresses for the same BIP32 path.
  
7. Verification if the specified transaction ID exists, points to your collateral address, is unspent and equals to 1000 Dash.  
Messages in the case of failure:  
  ![1](doc/img/startmn-tx-warning.png)  
  ![1](doc/img/startmn-collateral-warning.png)  
  If you decide to continue anyway, you probably won't be able to successfully start masternode.
  
8. Verification on the Dash network level if the specified transaction id is valid.  
Message in the case of failure:  
![1](doc/img/startmn-incorrect-tx-error.png)

9. After completing all pre-verification, the application will ask you whether you want to continue:  
![1](doc/img/startmn-broadcast-query.png)  
This is the last moment when you can stop the process.

10. Sending the _start masternode_ message.  
Success will end with the following message:  
![1](doc/img/startmn-success.png)  
In the case of failure, the message text may vary, depending on the problem nature. Example:  
![1](doc/img/startmn-failed-error.png)
 


### Transferring of masternode earnings
Beginning with version 0.9.4 of DMT you can transfer your masternode earnings. Unlike other Dash wallets, DMT gives you a 100% control on which _unspent transaction outputs_ (utxo) you wish to transfer. This has the same effect as the _Coin control_ functionality implemented in _Dash Core wallet_. 

`Transfer funds` window shows all _UTXOs_ of a currently selected Masternode (mode 1), all Masternodes in current configuration (mode 2) or any address controlled by a hardware wallet (mode 3). All _UTXOs_, not used as collateral are initially checked. Additionally, collaterals' _UTXOs_ (1000 Dash) are initially hidden, just to avoid unintentional sending its funds and thus breaking MN. You can show those hidden entries by unchecking `Hide collateral utxos` option.

To show up the `Transfer funds` window, click the `Tools` button. Then, from popup menu choose:
 - `Transfer funds from current Masternode's address` (mode 1)
 - `Transfer funds from all Masternodes addresses` (mode 2)
 - `Transfer funds from any HW address` (mode 3) 

Sending masternodes' payouts:  
![1](doc/img/dmt-transfer-funds.png)

Transferring of funds from any address controlled by a hardware wallet:  
![1](doc/img/dmt-transfer-funds-any-address.png) 

Select all _UTXOs_ you wish to include in your transaction, verify transaction fee and click the `Send` button. After signing the transaction with your hardware wallet, application will ask you if you wish to broadcast it to the Dash network. 

![1](doc/img/dmt-transfer-funds-broadcast.png)

After clicking `Yes`, application broadcasts the transaction and then shows a message box with a transaction ID as a hyperlink directing to a Dash block explorer: 

![1](doc/img/dmt-transfer-funds-confirmation.png)


### Signing messages with hardware wallet
To sign a message with your hardware wallet click the `Tools` button and then select the `Sign message with HW for current Masternode's address` menu item. 
This will show the `Sign message` window:

![1](doc/img/dmt-hw-sign-message.png)

### Changing hardware wallet's PIN/passphrase
Click the `Tools` button and then `Hardware Wallet PIN/Passphrase configuration` item. This will show up the configuration window:
 
![1](doc/img/dmt-hardware-wallet-config.png)


### Downloads
This application is written in Python 3, but to run it requires several libraries, which in turn require an installation of the C++ compiler. All in all, preparation is not very trivial to non-technical people, especially in Linux OS (though it will be documented soon).

Therefore, in addition to providing source code in GitHub, I've also released binary versions for all three major operating systems - Mac OS, Windows (32 and 64-bit) and Linux. Applications are "compiled" and tested under the following OS distributions:
* Windows 7 64-bit
* Mac OSX El Capitan 10.11.6
* Linux Debian Jessie

Binary versions of the latest release can be downloaded from: https://github.com/Bertrand256/dash-masternode-tool/releases/latest.


