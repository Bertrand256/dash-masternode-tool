## Hardware wallet recovery - safe mode

For Trezor and Keepkey wallets, this is a standard recovery scenario. Its characteristic trait is that the user enters individual words composing the *recovery seed* in a random order, while the number of the word to be entered is shown only on the screen of the device. So one could say that it’s safe even on computers where malware is listening to everything we type on a keyboard. In this case it would be able to capture individual words, but not their order in the complete set, making it useless.

##### Step 1. On the first page of the wizard, select the right hardware wallet type.  
![Select hardware wallet type](img/hwri/rec-hwtype.png)

##### Step 2. Select the option *Recover hardware wallet from seed words – safe*.  
![Select action](img/hwri/rec-action-safe.png)

##### Step 3. Select the number of words in your recovery seed.   
![Number of words](img/hwri/rec-number-of-words.png)

##### Step 4. Define hardware wallet configuration options.  
Enter the device label and decide whether or not you wish to use a PIN and/or a passphrase.  
![Choose hw options](img/hwri/rec-options-safe.png)

##### Step 5 (optional). Select the device instance.  
This step will only be shown when there are more devices of the same type connected to the computer. 
 
![Select device instance](img/hwri/rec-init-hw-instance.png)

##### Step 6 (optional). Confirm wiping the device.  
If the device is already initialized (it contains previously generated keys), it will ask you if you are certain it should be “wiped”. In order to confirm, you need to use appropriate buttons on the device.  

![Wipe trezor](img/hwri/trezor-wipe.jpg)
![Wipe trezor](img/hwri/keepkey-wipe.jpg) 

##### Step 7. Enter new PIN according to the matrix displayed on the device screen.  
The device will ask you to provide your PIN twice to verify that it’s correct.  

![Enter PIN Trezor](img/hwri/trezor-pin.jpg)
![Enter PIN Keepkey](img/hwri/keepkey-pin.jpg) 

##### Step 8. Enter words composing the recovery seed.  
The number of the word the user should enter will be presented on the screen of the hardware wallet - as mentioned before, for security reasons the order will be random.  

![Recover word Trezor](img/hwri/trezor-recover-word.jpg)
![Recover word Keepkey](img/hwri/keepkey-recover-word.jpg)  

At the same time DMT will ask you to enter the word:  

![Input word DMT](img/hwri/rec-word-input.png)  

You will see requests for individual words as many times as the number of words in your recovery seed. The last word acts as a checksum – a mechanism that verifies whether both the words and their order are correct. In case of an error, the below alert will appear:  

![Checksum error](img/hwri/rec-checksum-error.png)  

In such case, you need to start the procedure again.  
Successful completion of the process will be announced with a message as shown below:  

![Recovery success](img/hwri/rec-init-success.png)

