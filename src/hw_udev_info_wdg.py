#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2021-05

from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QWidget

from wallet_tools_common import ActionPageBase
from hw_intf import HWDevices


class WdgHwUdevRules(ActionPageBase, QWidget):
    def __init__(self, parent, hw_devices: HWDevices):
        ActionPageBase.__init__(self, parent, parent.app_config, hw_devices, 'Udev rules for hardware wallets')
        QWidget.__init__(self, parent=parent)
        self.setupUi(self)

    def setupUi(self, dlg):
        dlg.setObjectName("WdgHwUdevRules")
        dlg.resize(650, 500)
        self.vertical_layout = QtWidgets.QVBoxLayout(self)
        self.vertical_layout.setContentsMargins(0, 0, 0, 0)
        self.vertical_layout.setObjectName("verticalLayout")
        self.lbl_description = QtWidgets.QLabel(self)
        self.lbl_description.setWordWrap(True)
        self.lbl_description.setObjectName("lblDescription")
        self.vertical_layout.addWidget(self.lbl_description)
        self.text_udev_info = QtWidgets.QTextBrowser(self)
        self.text_udev_info.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        self.text_udev_info.setObjectName("textBrowser")
        self.vertical_layout.addWidget(self.text_udev_info)
        self.retranslateUi()
        t = """<h4>Trezor devices:</h4>
<pre>
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="534c", ATTR{idProduct}=="0001", MODE="0660", GROUP="plugdev", TAG+="uaccess", TAG+="udev-acl", SYMLINK+="trezor%n"' | sudo tee /etc/udev/rules.d/51-trezor-udev.rules
echo 'KERNEL=="hidraw*", ATTRS{idVendor}=="534c", ATTRS{idProduct}=="0001", MODE="0660", GROUP="plugdev", TAG+="uaccess", TAG+="udev-acl"' | sudo tee -a /etc/udev/rules.d/51-trezor-udev.rules
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="1209", ATTR{idProduct}=="53c0", MODE="0660", GROUP="plugdev", TAG+="uaccess", TAG+="udev-acl", SYMLINK+="trezor%n"' | sudo tee -a /etc/udev/rules.d/51-trezor-udev.rules
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="1209", ATTR{idProduct}=="53c1", MODE="0660", GROUP="plugdev", TAG+="uaccess", TAG+="udev-acl", SYMLINK+="trezor%n"' | sudo tee -a /etc/udev/rules.d/51-trezor-udev.rules
echo 'KERNEL=="hidraw*", ATTRS{idVendor}=="1209", ATTRS{idProduct}=="53c1", MODE="0660", GROUP="plugdev", TAG+="uaccess", TAG+="udev-acl"' | sudo tee -a /etc/udev/rules.d/51-trezor-udev.rules
sudo udevadm trigger
sudo udevadm control --reload-rules
</pre>
<h4>KeepKey devices:</h4>
<pre>
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="2b24", ATTR{idProduct}=="0001", MODE="0666", GROUP="plugdev", TAG+="uaccess", TAG+="udev-acl", SYMLINK+="keepkey%n"' | sudo tee /etc/udev/rules.d/51-usb-keepkey.rules
echo 'KERNEL=="hidraw*", ATTRS{idVendor}=="2b24", ATTRS{idProduct}=="0001",  MODE="0666", GROUP="plugdev", TAG+="uaccess", TAG+="udev-acl"' | sudo tee -a /etc/udev/rules.d/51-usb-keepkey.rules
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="2b24", ATTR{idProduct}=="0002", MODE="0666", GROUP="plugdev", TAG+="uaccess", TAG+="udev-acl", SYMLINK+="keepkey%n"' | sudo tee -a /etc/udev/rules.d/51-usb-keepkey.rules
echo 'KERNEL=="hidraw*", ATTRS{idVendor}=="2b24", ATTRS{idProduct}=="0002",  MODE="0666", GROUP="plugdev", TAG+="uaccess", TAG+="udev-acl"' | sudo tee -a /etc/udev/rules.d/51-usb-keepkey.rules
sudo udevadm trigger
sudo udevadm control --reload-rules
</pre>
<h4>Ledger Nano devices:</h4>
<pre>
echo 'SUBSYSTEMS=="usb", ATTRS{idVendor}=="2581", ATTRS{idProduct}=="1b7c|2b7c|3b7c|4b7c", TAG+="uaccess", TAG+="udev-acl"' | sudo tee /etc/udev/rules.d/20-hw1.rules
echo 'SUBSYSTEMS=="usb", ATTRS{idVendor}=="2c97", ATTRS{idProduct}=="0000|0000|0001|0002|0003|0004|0005|0006|0007|0008|0009|000a|000b|000c|000d|000e|000f|0010|0011|0012|0013|0014|0015|0016|0017|0018|0019|001a|001b|001c|001d|001e|001f", TAG+="uaccess", TAG+="udev-acl"' | sudo tee -a /etc/udev/rules.d/20-hw1.rules
echo 'SUBSYSTEMS=="usb", ATTRS{idVendor}=="2c97", ATTRS{idProduct}=="0001|1000|1001|1002|1003|1004|1005|1006|1007|1008|1009|100a|100b|100c|100d|100e|100f|1010|1011|1012|1013|1014|1015|1016|1017|1018|1019|101a|101b|101c|101d|101e|101f", TAG+="uaccess", TAG+="udev-acl"' | sudo tee -a /etc/udev/rules.d/20-hw1.rules
echo 'SUBSYSTEMS=="usb", ATTRS{idVendor}=="2c97", ATTRS{idProduct}=="0002|2000|2001|2002|2003|2004|2005|2006|2007|2008|2009|200a|200b|200c|200d|200e|200f|2010|2011|2012|2013|2014|2015|2016|2017|2018|2019|201a|201b|201c|201d|201e|201f", TAG+="uaccess", TAG+="udev-acl"' | sudo tee -a /etc/udev/rules.d/20-hw1.rules
echo 'SUBSYSTEMS=="usb", ATTRS{idVendor}=="2c97", ATTRS{idProduct}=="0003|3000|3001|3002|3003|3004|3005|3006|3007|3008|3009|300a|300b|300c|300d|300e|300f|3010|3011|3012|3013|3014|3015|3016|3017|3018|3019|301a|301b|301c|301d|301e|301f", TAG+="uaccess", TAG+="udev-acl"' | sudo tee -a /etc/udev/rules.d/20-hw1.rules
echo 'SUBSYSTEMS=="usb", ATTRS{idVendor}=="2c97", ATTRS{idProduct}=="0004|4000|4001|4002|4003|4004|4005|4006|4007|4008|4009|400a|400b|400c|400d|400e|400f|4010|4011|4012|4013|4014|4015|4016|4017|4018|4019|401a|401b|401c|401d|401e|401f", TAG+="uaccess", TAG+="udev-acl"' | sudo tee -a /etc/udev/rules.d/20-hw1.rules
sudo udevadm trigger
sudo udevadm control --reload-rules
</pre>
"""
        self.text_udev_info.setHtml(t)
        QtCore.QMetaObject.connectSlotsByName(self)

    def retranslateUi(self):
        _translate = QtCore.QCoreApplication.translate
        self.setWindowTitle(_translate("WdgHwUdevRules", "Form"))
        self.lbl_description.setText(
            _translate("WdgCreateRpcauth",
                       "<h3>Description</h3>\n"
                       "To make hardware wallets work on linux, you need to add the appropriate udev "
                       "rules. To do this, execute the commands for the selected device type from the linux terminal:"))

    def initialize(self):
        ActionPageBase.initialize(self)
        self.set_controls_initial_state_for_step()

    def set_controls_initial_state_for_step(self):
        self.set_btn_cancel_enabled(True)
        self.set_btn_back_enabled(True)
        self.set_btn_back_visible(True)
        self.set_btn_continue_visible(False)
        self.set_btn_close_visible(True)
        self.set_btn_close_enabled(True)

