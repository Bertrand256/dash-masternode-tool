## [0.9.17] - 2018-01-25

**Fixed**

- Error when signing transactions with Keepkey hardware wallets: 'str' object has no attribute 'decode'.


## [0.9.16] - 2018-01-23

**Fixed**

- *[Errno 22] Invalid argument* on Windows when checking status of a masternode that never received payment.
- Error in method computing the *months* and the *current_month* fields.


## [0.9.15] - 2018-01-18

**Added**

- Hardware wallets initialization and recovery for online/offline usage.
- Filtering by the proposal name, title, owner in the `Proposals` window.
- The command line parameter `--data-dir` for changing the default application's data folder for logs, cache and config files.

**Changed**

- Added a scroll area inide the `Vote` tab in the `Proposals` window to improve the visibility of proposls for users with several masternodes in the configuration and low screen resolution.
- Moved to the official Trezor insight API for Dash (https://dash-bitcore1.trezor.io/api/).
- Moved to the official (non-forked) Keepkey Python library after fixing by Keepkey Python 3 support.
- Masternodes in the `Vote` tab in the `Proposals` window are now sorted according to the configuration file (not randomly).

**Fixed**

- The connection was incorrectly shown as successful for proxy connections when nginx is running, but the Dash daemon does not.
- Workaround of the Trezor Python library issue with normalizing "national" characters in passphrases (NFC instead of NFKD) resulting in incorrect addresses read from the device, if a passphrase contains non-ASCII characters.
- Address inconsistency error while starting masternode if the collateral address in the configuration contained spaces at the beginning or end of the collateral address.
- Taking into account the user's time zone in the `Proposals` window when dispalying the voting deadline.

**Backend changes**

- Changed the domain for "public" nodes to more relevant: dash-masternode-tool.org.
- Changed the TCP port number for *alice* and *luna* "public" RPC nodes to 443 - the official port for HTTPS.
- Added a new "public" RPC node: suzy.dash-masternode-tool.org:443.

**Known issues**

- *"QThread: Destroyed while thread is still runningAborted (core dumped)"* on Linux in rare cases. If you encounter this error, try several times to run the application. If that does not help, contact me.