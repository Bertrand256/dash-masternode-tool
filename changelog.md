## [0.9.17] - 2018-01-25

**Fixed**

- Error when signing transactions with Keepkey hardware wallets: 'str' object has no attribute 'decode'.


## [0.9.16] - 2018-01-23

**Fixed**

- *[Errno 22] Invalid argument* on Windows when checking status of a masternode that has never previously received payment.
- Error in method computing the *months* and the *current_month* fields.


## [0.9.15] - 2018-01-18

**Added**

- Hardware wallets initialization and recovery for online/offline usage.
- Filtering by proposal name, title and owner in the `Proposals` window.
- Command line parameter `--data-dir` to change the default application data directory for log, cache and config files.

**Changed**

- Added a scroll area inside the `Vote` tab in the `Proposals` window to improve the visibility of proposals for users with several masternodes configured and low screen resolution.
- Moved to the official Trezor Insight API for Dash (https://dash-bitcore1.trezor.io/api/).
- Moved to the official (non-forked) KeepKey Python library after fixing KeepKey Python 3 support.
- Masternodes in the `Vote` tab in the `Proposals` window are now sorted according to the configuration file order (not randomly).

**Fixed**

- The connection was incorrectly shown as successful for proxy connections when nginx was running, but the Dash daemon was not.
- Workaround for an issue in the Trezor Python library causing normalization of "national" characters in passphrases (NFC instead of NFKD), resulting in incorrect addresses read from the device if the passphrase contains non-ASCII characters.
- Address inconsistency error while starting the masternode if the collateral address in the configuration contained spaces at the beginning or end of the collateral address.
- Properly take into account the user's time zone in the `Proposals` window when displaying the voting deadline.

**Backend changes**

- Changed the domain for "public" nodes to something more relevant: dash-masternode-tool.org.
- Changed the TCP port number for *alice* and *luna* "public" RPC nodes to 443 - the official HTTPS port.
- Added a new "public" RPC node: suzy.dash-masternode-tool.org:443.

**Known issues**

- *"QThread: Destroyed while thread is still runningAborted (core dumped)"* occurs under Linux in rare cases. If you encounter this error, try running the application several times. If that does not help, please contact the author.