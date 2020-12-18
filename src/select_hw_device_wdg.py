import logging

from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QWidget

import app_defs
from wallet_tools_common import HardwareWalletList


class SelectHwDeviceWdg(QWidget):
    def __init__(self, parent, hw_devices: HardwareWalletList):
        QWidget.__init__(self, parent=parent)
        self.hw_devices = hw_devices
        self.setupUi(self)

    def setupUi(self, dlg):
        dlg.setObjectName("SelectHwDeviceWdg")
        # SelectHwDeviceWdg.resize(444, 16)
        self.layout_main = QtWidgets.QHBoxLayout(dlg)
        self.layout_main.setContentsMargins(0, 0, 0, 0)
        self.layout_main.setSpacing(24)
        self.layout_main.setObjectName("horizontalLayout")
        self.lbl_hw_instance = QtWidgets.QLabel(dlg)
        self.lbl_hw_instance.setObjectName("lblHwInstance")
        self.layout_main.addWidget(self.lbl_hw_instance)
        self.lbl_hw_type = QtWidgets.QLabel(dlg)
        self.lbl_hw_type.setObjectName("lblHwType")
        self.layout_main.addWidget(self.lbl_hw_type)
        spacer = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.layout_main.addItem(spacer)

        self.retranslateUi(dlg)
        QtCore.QMetaObject.connectSlotsByName(dlg)

    def retranslateUi(self, SelectHwDeviceWdg):
        _translate = QtCore.QCoreApplication.translate
        SelectHwDeviceWdg.setWindowTitle(_translate("SelectHwDeviceWdg", "Form"))
        self.lbl_hw_instance.setText(_translate("SelectHwDeviceWdg", "Device selected:"))
        self.lbl_hw_type.setText(_translate("SelectHwDeviceWdg", "Device type:"))

    def update(self):
        try:
            devices = self.hw_devices.get_hw_instances(False)
            dev_sel = self.hw_devices.get_hw_instance_selected()

            if dev_sel and devices:
                if len(devices) == 1:
                    # there is only one device connected to the computer
                    lbl = 'Device connected: <b>' + dev_sel.device_label + '</b>'
                else:
                    # there is more than one device connected
                    lbl = 'Device connected: <b>' + dev_sel.device_label + '</b> (<a href="select-hw-device">change</a>)'
            else:
                lbl = 'Plug in your hardware wallet device'

            self.lbl_hw_instance.setText(lbl)

            lbl = 'Device type: <b>' + app_defs.HWType.get_desc(self.hw_devices.hw_type) + \
                  '</b> (<a href="change-hw-type">change</a>) </span>'
            self.lbl_hw_type.setText(lbl)

        except Exception as e:
            logging.exception(str(e))
