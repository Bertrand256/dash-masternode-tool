## Running DMT on an offline Linux system
For security reasons, some scenarios presented above require DMT to be run on an offline computer. Ubuntu Linux is perfectly suitable for this purpose, because the standard desktop system image can be run from a DVD or USB media (without installing it to your hard drive), and no sensitive information is left on the computer after performing the hardware wallet recovery/initialization. Follow these instructions first to create a Linux bootable DVD/USB: https://help.ubuntu.com/community/LiveCD

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
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="534c", ATTR{idProduct}=="0001", MODE="0660", GROUP="plugdev", TAG+="uaccess", TAG+="udev-acl", SYMLINK+="trezor%n"' | sudo tee /etc/udev/rules.d/51-trezor-udev.rules
echo 'KERNEL=="hidraw*", ATTRS{idVendor}=="534c", ATTRS{idProduct}=="0001", MODE="0660", GROUP="plugdev", TAG+="uaccess", TAG+="udev-acl"' | sudo tee -a /etc/udev/rules.d/51-trezor-udev.rules
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="1209", ATTR{idProduct}=="53c0", MODE="0660", GROUP="plugdev", TAG+="uaccess", TAG+="udev-acl", SYMLINK+="trezor%n"' | sudo tee -a /etc/udev/rules.d/51-trezor-udev.rules
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="1209", ATTR{idProduct}=="53c1", MODE="0660", GROUP="plugdev", TAG+="uaccess", TAG+="udev-acl", SYMLINK+="trezor%n"' | sudo tee -a /etc/udev/rules.d/51-trezor-udev.rules
echo 'KERNEL=="hidraw*", ATTRS{idVendor}=="1209", ATTRS{idProduct}=="53c1", MODE="0660", GROUP="plugdev", TAG+="uaccess", TAG+="udev-acl"' | sudo tee -a /etc/udev/rules.d/51-trezor-udev.rules
sudo udevadm trigger
sudo udevadm control --reload-rules
```

**For KeepKey hardware wallets:**
```
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="2b24", ATTR{idProduct}=="0001", MODE="0666", GROUP="plugdev", TAG+="uaccess", TAG+="udev-acl", SYMLINK+="keepkey%n"' | sudo tee /etc/udev/rules.d/51-usb-keepkey.rules
echo 'KERNEL=="hidraw*", ATTRS{idVendor}=="2b24", ATTRS{idProduct}=="0001",  MODE="0666", GROUP="plugdev", TAG+="uaccess", TAG+="udev-acl"' | sudo tee -a /etc/udev/rules.d/51-usb-keepkey.rules
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="2b24", ATTR{idProduct}=="0002", MODE="0666", GROUP="plugdev", TAG+="uaccess", TAG+="udev-acl", SYMLINK+="keepkey%n"' | sudo tee -a /etc/udev/rules.d/51-usb-keepkey.rules
echo 'KERNEL=="hidraw*", ATTRS{idVendor}=="2b24", ATTRS{idProduct}=="0002",  MODE="0666", GROUP="plugdev", TAG+="uaccess", TAG+="udev-acl"' | sudo tee -a /etc/udev/rules.d/51-usb-keepkey.rules
sudo udevadm trigger
sudo udevadm control --reload-rules
```

**For Ledger hardware wallets:**
```
echo 'SUBSYSTEMS=="usb", ATTRS{idVendor}=="2581", ATTRS{idProduct}=="1b7c|2b7c|3b7c|4b7c", TAG+="uaccess", TAG+="udev-acl"' | sudo tee /etc/udev/rules.d/20-hw1.rules
echo 'SUBSYSTEMS=="usb", ATTRS{idVendor}=="2c97", ATTRS{idProduct}=="0000|0000|0001|0002|0003|0004|0005|0006|0007|0008|0009|000a|000b|000c|000d|000e|000f|0010|0011|0012|0013|0014|0015|0016|0017|0018|0019|001a|001b|001c|001d|001e|001f", TAG+="uaccess", TAG+="udev-acl"' | sudo tee -a /etc/udev/rules.d/20-hw1.rules
echo 'SUBSYSTEMS=="usb", ATTRS{idVendor}=="2c97", ATTRS{idProduct}=="0001|1000|1001|1002|1003|1004|1005|1006|1007|1008|1009|100a|100b|100c|100d|100e|100f|1010|1011|1012|1013|1014|1015|1016|1017|1018|1019|101a|101b|101c|101d|101e|101f", TAG+="uaccess", TAG+="udev-acl" | sudo tee -a /etc/udev/rules.d/20-hw1.rules
echo 'SUBSYSTEMS=="usb", ATTRS{idVendor}=="2c97", ATTRS{idProduct}=="0002|2000|2001|2002|2003|2004|2005|2006|2007|2008|2009|200a|200b|200c|200d|200e|200f|2010|2011|2012|2013|2014|2015|2016|2017|2018|2019|201a|201b|201c|201d|201e|201f", TAG+="uaccess", TAG+="udev-acl" | sudo tee -a /etc/udev/rules.d/20-hw1.rules
echo 'SUBSYSTEMS=="usb", ATTRS{idVendor}=="2c97", ATTRS{idProduct}=="0003|3000|3001|3002|3003|3004|3005|3006|3007|3008|3009|300a|300b|300c|300d|300e|300f|3010|3011|3012|3013|3014|3015|3016|3017|3018|3019|301a|301b|301c|301d|301e|301f", TAG+="uaccess", TAG+="udev-acl" | sudo tee -a /etc/udev/rules.d/20-hw1.rules
echo 'SUBSYSTEMS=="usb", ATTRS{idVendor}=="2c97", ATTRS{idProduct}=="0004|4000|4001|4002|4003|4004|4005|4006|4007|4008|4009|400a|400b|400c|400d|400e|400f|4010|4011|4012|4013|4014|4015|4016|4017|4018|4019|401a|401b|401c|401d|401e|401f", TAG+="uaccess", TAG+="udev-acl" | sudo tee -a /etc/udev/rules.d/20-hw1.rules
sudo udevadm trigger
sudo udevadm control --reload-rules
```
