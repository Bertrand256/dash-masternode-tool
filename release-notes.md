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

## App blocked from opening on macOS or Windows
The release binaries are not signed with trusted code-signing certificates, so macOS Gatekeeper or Microsoft Defender SmartScreen may prevent the application from opening. Only proceed if you downloaded the application from the project's official release page and trust the file.

- **macOS**: If macOS reports that the developer cannot be verified or Apple cannot check the app for malicious software, first try opening the app, then go to **System Settings > Privacy & Security**, scroll down to **Security**, and click **Open Anyway**. Authenticate if prompted, then confirm by clicking **Open**. See [Apple's instructions](https://support.apple.com/en-gb/102445). A message that the app is damaged or will damage your computer should not be assumed to be caused solely by a missing signature; download a fresh copy from the official release page and report the issue if it persists.

  If the GUI method does not work and you trust the downloaded application, copy the app from the `.dmg` disk image to **Applications**, then open **Terminal** and run:

  ```sh
  xattr -dr com.apple.quarantine "/Applications/DashMasternodeTool.app"
  ```

  Replace the path with the actual path to the installed `.app` bundle (you can drag the app from Finder into Terminal to insert its path). This removes the quarantine attribute from the app and its contents. Try opening the app again. If the command fails due to insufficient permissions, run it again with `sudo` before `xattr` and enter your administrator password when prompted.

- **Windows**: If Microsoft Defender SmartScreen displays **Windows protected your PC**, click **More info**, then **Run anyway**, if available. This option may be unavailable due to administrator policies. Windows 11's **Smart App Control** is a separate protection feature and may also block the app; these SmartScreen steps do not override it. See [Microsoft's explanation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation).
