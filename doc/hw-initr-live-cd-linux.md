## Running DMT on an offline Linux system
For security reasons, some of the scenarios presented above require DMT to be run on an offline computer. Ubuntu Linux is perfectly suitable for this purpose, because the standard desktop system image can be run from a DVD or USB media (without installing it to your hard drive), and no sensitive information is left on the computer after performing the hardware wallet recovery/initialization. Follow these instructions first to create a Linux bootable DVD/USB: https://help.ubuntu.com/community/LiveCD

1. Boot your computer from the LiveCD or LiveUSB media. It is recommended to use a computer without any hard drives installed (or at least physically disconnecting any drives) and to use wired Ethernet instead of Wi-Fi for your network connection.
  Once your system boots, select the `Try Ubuntu` option:  
  ![Ubuntu - boot](img/hwri/ubuntu-live-cd-boot.png)
2. On the running Linux system, download the latest [Dash Masternode Tool archived binary](https://github.com/Bertrand256/dash-masternode-tool/releases) (.tar.gz) from the project page, or copy the file to the system in some other way.
3. Decompress the file by double-clicking it.
4. Disconnect the computer from the network (unplug the cable) and remove all unnecessary USB media.
5. Launch DMT.
6. Open the `Hardware wallet initialization/recovery` dialog from the `Tools` menu.
7. Add the appropriate udev rules to make your hardware wallet visible on the system. For more information on how to do this, click the `see the details` link as shown in the screenshot below:  
  ![Ubuntu - boot](img/hwri/ubuntu-live-cd-udev.png)  
  The following help window will appear:  
  ![Ubuntu - boot](img/hwri/ubuntu-live-cd-udev-help.png)  
  Copy the commands appropriate to your hardware wallet type and execute them one-by one in a terminal window:  
  ![Ubuntu - boot](img/hwri/ubuntu-live-cd-udev-exec.png)
8. Perform the desired hardware wallet procedure (initialization or recovery).
9. Shut down the system.

**A copy of the commands to create the udev rules required by hardware wallets supported by DMT appears below**

**For Trezor hardware wallets:**
```
echo "SUBSYSTEM==\"usb\", ATTR{idVendor}==\"534c\", ATTR{idProduct}==\"0001\", TAG+=\"uaccess\", TAG+=\"udev-acl\", SYMLINK+=\"trezor%n\"" | sudo tee /etc/udev/rules.d/51-trezor-udev.rules
sudo udevadm trigger
sudo udevadm control --reload-rules
```

**For KeepKey hardware wallets:**
```
echo "SUBSYSTEM==\"usb\", ATTR{idVendor}==\"2b24\", ATTR{idProduct}==\"0001\", MODE=\"0666\", GROUP=\"dialout\", SYMLINK+=\"keepkey%n\"" | sudo tee /etc/udev/rules.d/51-usb-keepkey.rules
echo "KERNEL==\"hidraw*\", ATTRS{idVendor}==\"2b24\", ATTRS{idProduct}==\"0001\", MODE=\"0666\", GROUP=\"dialout\"" | sudo tee -a /etc/udev/rules.d/51-usb-keepkey.rules
sudo udevadm trigger
sudo udevadm control --reload-rules
```

**For Ledger hardware wallets:**
```
echo "SUBSYSTEMS==\"usb\", ATTRS{idVendor}==\"2581\", ATTRS{idProduct}==\"1b7c\", MODE=\"0660\", GROUP=\"plugdev\"" | sudo tee /etc/udev/rules.d/20-hw1.rules
echo "SUBSYSTEMS==\"usb\", ATTRS{idVendor}==\"2581\", ATTRS{idProduct}==\"2b7c\", MODE=\"0660\", GROUP=\"plugdev\"" | sudo tee -a /etc/udev/rules.d/20-hw1.rules
echo "SUBSYSTEMS==\"usb\", ATTRS{idVendor}==\"2581\", ATTRS{idProduct}==\"3b7c\", MODE=\"0660\", GROUP=\"plugdev\"" | sudo tee -a /etc/udev/rules.d/20-hw1.rules
echo "SUBSYSTEMS==\"usb\", ATTRS{idVendor}==\"2581\", ATTRS{idProduct}==\"4b7c\", MODE=\"0660\", GROUP=\"plugdev\"" | sudo tee -a /etc/udev/rules.d/20-hw1.rules
echo "SUBSYSTEMS==\"usb\", ATTRS{idVendor}==\"2581\", ATTRS{idProduct}==\"1807\", MODE=\"0660\", GROUP=\"plugdev\"" | sudo tee -a /etc/udev/rules.d/20-hw1.rules
echo "SUBSYSTEMS==\"usb\", ATTRS{idVendor}==\"2581\", ATTRS{idProduct}==\"1808\", MODE=\"0660\", GROUP=\"plugdev\"" | sudo tee -a /etc/udev/rules.d/20-hw1.rules
echo "SUBSYSTEMS==\"usb\", ATTRS{idVendor}==\"2c97\", ATTRS{idProduct}==\"0000\", MODE=\"0660\", GROUP=\"plugdev\"" | sudo tee -a /etc/udev/rules.d/20-hw1.rules
echo "SUBSYSTEMS==\"usb\", ATTRS{idVendor}==\"2c97\", ATTRS{idProduct}==\"0001\", MODE=\"0660\", GROUP=\"plugdev\"" | sudo tee -a /etc/udev/rules.d/20-hw1.rules
sudo udevadm trigger
sudo udevadm control --reload-rules
```
