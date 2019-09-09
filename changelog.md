## [0.9.26-hotfix2] - 2019-09-09

**Fixed**
- Fixed an issue with saving the ssh authentication method.

## [0.9.26-hotfix1] - 2019-08-20

**Fixed**
- Proposals: remove votes from the cache that no longer exist on the network.

## [0.9.26] - 2019-08-19
**Added**
- Commandline parameters for changing the sig_time random offset range.
- Ability to explicitly specify the authentication methods for an SSH tunnel from: username/password, RSA private key 
pair and ssh agent.
- Workaround for Trezor connection issues (LIBUSB) after Windows update #1903.
- Showing a message if duplicate masternode information in the configuration may prevent voting. 

**Fixed**
- Issue "'WalletDlg' object has no attribute 'config'" when signing message from the wallet dialog.

## [0.9.25-hotfix2] - 2019-07-15

**Fixed**
- Issue "'WalletDlg' object has no attribute 'config'" when signing message from the wallet dialog.

## [0.9.25-hotfix1] - 2019-07-12

**Fixed**
- Issue with calculating the next payment block when a masternode received PoSeBan in the past and its PoSeRevivedBlock 
is less than the last payment block.

## [0.9.25] - 2019-07-01
**Added**
- Support for the KeepKey v6.x firmware.
- Possibility to limit the Trezor transport methods using commandline parameters.
- Signing messages with owner/voting key.
- Export/import of the configuration.

**Fixed**
- A bug related to access to uninitialized variable.

## [0.9.24] - 2019-05-24

**Added**
- Support for the "update service" feature (mn IP/port, operator payout address).
- Support for the "revoke operator" feature.
- Additional encryption (RSA) of data sent over the Internet for protx RPC calls.

**Changed**
- Additional information in the status area, mainly concerning diagnosis of problems with masternode.


## [0.9.23-hotfix3] - 2019-05-08

**Fixed**
- Malfunctioning/incorrect "details" link in the "Update payout address" dialog (the manual commands area).
- Issue occurring during sending a transaction after switching hw identities (an empty message box).

**Changed**
- Extended information about transaction recipients in the transaction window.

## [0.9.23-hotfix2] - 2019-05-03

**Fixed**
- Fix of the "invalid operator public key" error occurring in the
"Update operator key" window when using the public key option (Kudos to 
@Thiagokroger from Node40 for precise hints).

## [0.9.23-hotfix1] - 2019-05-02

**Fixed**
- Issue with "Locate collateral" feature (an empty error message).
- Switching the active RPC connection to another after encountering "Unknown error" and "401 Unauthorized" 
errors.

## [0.9.23] - 2019-04-27

**Added**
- The feature of restoring configuration from backup.
- GUI for update_registrar (changing payout address, operator/voting key).
- Extending the status area with additional information, including
the estimated date of the next payment.

**Changed**
- Removed the pre-spork 15 code.
- Fixes in the proposals dialog: support for v0.14-beta, issues with number of payment cycles. 
- Clearing the pre-spork 15 voting results from the app cache to suggest 
users the need to re-submit their votes.
- Fixed some stability issues in the wallet dialog.

## [0.9.22] - 2019-02-24

**Added**
- DML registration wizard: the possibility of using public keys 
for the operator and Dash addresses for the owner and voting.
- Main window: the possibility of displaying private keys in the form 
of: Dash address, public key and public key hash (for diagnostics).
- Wallet: the possibility of adding/hiding any BIP44 account (use 
context menu). Please note, that if there is a gap between the account 
added and the last one used (having a transaction history), the 
official client app for a given hardware wallet (eg Trezor online 
wallet) will not show it.
- Wallet: the possibility o hiding accounts.
- Wallet: signing messages with any address.
- Wallet: showing incoming and not yet confirmed UTXOs (from mempool).
- Wallet: initially select the masternode address ("Masternode address" 
mode) that is currently selected in the main window.

**Changed**
- Main window: the user's role is morphed into three independent 
roles - owner, operator and voter - one can choose any combination of 
them.
- DML registration wizard: support for the 'feeSourceAddress' field 
in the `protx prepare` call (added in Dash Core rc11).
- Main window: suport for deterministic masternodes in the masternode 
status area.
- Main window: the visibility of the buttons associated with starting 
masternodes depends on the status of DIP3 and Spork 15.
- Wallet: improved refreshing of the UTXO list as a result of reading 
new transactions.

**Fixed**
- Proposals: fixed an issue that caused some proposals to not be 
displayed. 
- Wallet: issues with fetching transactions and showing UTXOs for 
BIP44 accounts that are beyond the scope of the standard BIP44 
account discovery method.
- Fixed several other minor issues.

## [0.9.21] - 2019-01-13

**Added**
- Support for Dash v13 - Deterministic Masternode List (protocol 70213)

**Changed**
- Wallet dialog: major redesign


## [0.9.20] - 2018-06-18

**Added**
- Dash daemon v12.3 support (protocol 70209/70210)
- Default protocol version is now stored in the project GitHub repo

**Fixed**
- vote timespamp fix when casting series of subsequent votes for the same proposal/masternode and the random offset option

## [0.9.19] - 2018-05-13

**Added**
- InstantSend support in the payment window
- Duplicate masternode feature (main window)

**Fixed**
- Deselecting proposals after casting votes
- Data validation error in the payment window
- Filter by text issue in the proposals window

## [0.9.18] - 2018-04-17

**Added**
- Support for Dash Testnet
- Support for Trezor T hardware wallet
- Switching between different configurations
- Config files encryption with hardware wallets
- Toolbar and main menu in the main app window
- Transaction preview window
- Uploading firmware to hardware wallets (dedicated mainly to upload a custom firmware with testnet support)

**Changed**
- Improvements in payment window: added multiple recipients, improved UTXO selection, saving recipient list in an
external file (can be encrypted with hardware wallet)
- Proposal window: additional filtering ("Only new", "Not voted"), voting on multiple proposals at once

**Fixed**
- "400 Bad request" error when sending transactions with more than 35 inputs (reconfiguration of the "public" RPC nodes)
- A few rare errors when connecting to a remote node via SSH tunnel
- QThread: Destroyed while thread is still runningAborted (core dumped)

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