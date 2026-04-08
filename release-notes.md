### New
- Added the option to hide “dust” UTXOs in the wallet window.
- Added binaries for macOS (Apple Silicon) and Linux (AppImage).
- Added automated builds via GitHub Actions.

### Fixed
- Fixed the “XXXX function is not supported by the RPC node you are connected to” error when using a custom RPC node.
- Fixed the “DMTENCRYPTEDV1” error that could occur during `protx` calls when a connection issue happened (e.g., a timeout).
- Optimized address balance fetching by batching requests, reducing redundant API calls.
- Wallet: the "tree_id is empty" error when the "Masternode Address" view is active.
