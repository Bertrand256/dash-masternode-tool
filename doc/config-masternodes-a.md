## Moving masternode management from Dash Core
This scenario is dedicated for those who already have a running masternode controlled by _Dash Core_ software wallet and who are willing to move its management to a higher level of security provided by hardware wallets. 

In the old configuration _Dash Core_ controls the private key of the 1000 Dash collateral and is used to send _start masternode_ command. In contrast, in the target configuration, 1000 Dash collateral is controlled by a hardware wallet (like Trezor) but the _start masternode_ command is invoked by _DashMasternodeTool_ application.

The procedure described below boils down to sending 1000 Dash funds from your _Dash Core_ wallet to a new address controlled by a hardware wallet and setting up a masternode configuration in the _DMT_. You will not be changing any of the _dashd_ configuration parameters, so you will not need to restart it at the end of the sequence. You must be aware though, that sending a _start masternode_ message will reset the masternode's location in the payment queue. For this reason, the best moment for this type of reconfiguration is when you receive your last payment.  


#### Sending 1000 Dash to the address controlled by your hardware wallet
 Each of the hardware wallet types has its own native client app for performing transactions - in the following steps I will not cover all of them, but instead I'll use Trezor and his native WEB aplication as an example. 
 
##### Step 1
 Open Trezor's native wallet in Chrome browser: https://wallet.trezor.io, enter your pin/passphrase if enabled (I strongly recommend enabling both).
  
##### Step 2
Use the first **empty** account and dedicate it for your masternode. If you don't separate your daily accounts from your masternode account, then you may have a problem maintaining your 1000 Dash transaction intact and this will end up with kicking your node off from masternodes list. The reason is that the wallet.trezor.io does not have a _coin control_ feature which allows blocking certain transactions from being used when making day-to-day operations.  
  ![1](img/conf-masternodes-a-1.png)  
  This is your new masternode **collateral address**.
   
##### Step 3
Open _Dash Core_ wallet and send exactly 1000 Dash to your **collateral address**.

#### Moving masternode parameters from Dash Core to DashMasternodeTool

##### Step 4
Click the `Tools->Open Masternode Configuration File` menu item in the _Dash Core_. This will open the `masternode.conf` file in your default text editor. This file contains your existing masternode configuration of which parts will be used in your target configuration.  
Each masternode entry occupies one line as shown in the screenshot below (the line is wrapped):  
  ![1](img/conf-masternodes-a-2.png)  
  
    Each line consists of five to six sections (in the screenshot surrounded by green/red rectangles):  
    A. masternode name  
    B. masternode IP:port  
    C. masternode private key    
    D. 1000 Dash transaction id  
    E. 1000 Dash transaction index  
    F. masternode's collateral address (not mandatory)  
  Only the first three - labeled as _A_, _B_ and _C_ - will be reused in the target configuration.
  
##### Step 5
Run the _DashMasternodeTool_ application and click the `New` button to enter into the _new masternode_ mode. If you don't have any masternode entries in the current configuration, the _new masternode_ mode is activated automatically.
  
##### Step 6
Copy the _name_ (you can change it - it's just a label), the _IP:port_ and the _private key_ to the corresponding fields in the _DMT_.  
  ![1](img/conf-masternodes-a-3.png) 

#### Entering the collateral related information

##### Step 7
Enter your **collateral addres** obtained in the [Step 2](#step-2) into the `Collateral` edit box, then click the little tiny botton on its right (with the icon of the right arrow on it) to retrieve the BIP32 path related to the **collateral address**.  
  ![1](img/conf-masternodes-a-4.png) 

##### Step 8
To fill in the id/index of your 1000 Dash transaction (which you have sent in [Step 3](#step-3)) click on the `Lookup` button. Assuming that transaction has been processed without any problems, one transaction should appear in the dialog that will show up:  
  ![1](img/conf-masternodes-a-5.png)  
Select the transaction and click `OK`.  

##### Step 9
You should see the `Collateral TX ID` and `TX index` fields filled with the relevant data:  
  ![1](img/conf-masternodes-a-6.png)
  
Click the `Save configuration` button.
  
#### Next steps
Before you go to the last step of the whole configuration (sending _start masternode_ message), make sure that the number of confirmations of the collateral transaction is greater or equal to 15 (this can be verified in the _Lookup_ dialog). Without this, starting masternode will not be successful. When fulfilling this requirement, you can go on and perform the [start masternode](../README.md#starting-masternode) operation. 