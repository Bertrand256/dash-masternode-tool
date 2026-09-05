## New
- Added all remaining masternode configuration fields to the list of available columns on the "Masternode (config)" tab.
- Added support for retrieving EVO node-specific fields via "Fetch MN data".
- Updated the payment queue position calculation to reflect the current EVO node reward distribution mechanism.
- Added columns with next payment information to the "Masternodes (network)" tab.

## Changed
- Updated compatibility with the latest KeepKey firmware.
- Improved application startup performance on macOS (thanks to UdjinM6).

## Fixed
- Fixed the "Open log file" and "Open Application Data Folder" actions.
- Fixed the "QThread: Destroyed while thread is still running" error on exit (thanks to UdjinM6).
- Improved application cache robustness under concurrent access from multiple threads.
- Fixed executable stack issues in the Linux build.
