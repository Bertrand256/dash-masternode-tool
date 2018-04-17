## Note DMTN0001
Keepkey hardware wallets have a certain - probably unplanned - trait, that required a 
dedicated support in the DMT application. Namely, the passphrase encoding type 
used by KeepKey (NFC) is different than the encoding described in the BIP-39 standard (NFKD), 
which btw is used by Trezor. As a result, using national (non-ASCII) characters 
in passphrase in Keepkey will result in different Dash addresses than those that would 
generate Trezor for the same seed.

This issue results in confusion, especially when exchanging devices between KeepKey and 
those, that conform the BIP-39 standard. To help in such cases, DMT gives you control over 
what exactly encoding will be used for KeepKey devices;
 * NFC, compatible with the official KeepKey client
 * NFKD, compatible with the BIP-39 standard and Trezor

Keep in mind that the choice of encoding type affects the Dash addresses generated for the 
same BIP32 path and password. So, if you consider using the same seed with KeepKey and 
let's say Trezor, choose NFKD. On the other hand, if you'd like to have address-compatibility 
between DMT and the KeepKey official client app, use NFC. 

## Note DMT0002
Current versions of the all three hardware wallets supported by the application do not support Dash TESTNET. It is possible though, making a few modifications to the firmware source code of Trezor and KeepKey devices, to make them support Testnet. 

For those who do not want to do it on their own, I have prepared firmware for Trezor One and for KeepKey with that support. It's available for manual download from the following url: https://github.com/Bertrand256/dash-masternode-tool/tree/master/hardware-wallets/firmware, but it can also be automatically downloaded and installed using the [Hardware wallet initialization/recovery](hw-initialization-recovery.md) window`.  

**Important:** due tu a bug in the latest Trezor bootloader, custom firmwares can't be executed, To avoid users' confusion, custom firmware for this device with Testnet support isn't currently shown by DMT app, nor is visible on the project website.

## Note DMT0003
Remember to close other applications connected to the same hardware wallet device DMT 
communicates with, for example web browsers with open online wallet apps, Chrome wallet apps, etc. 
Communication with the device by these applications may distort data exchanged by DMT, which 
may result in unexpected bahavior like returning different Dash address than the one for which 
the query was sent.