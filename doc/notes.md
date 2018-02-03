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