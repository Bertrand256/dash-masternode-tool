# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file ui_masternode_details_wdg.ui
#
# Created by: PyQt5 UI code generator
#
# WARNING: Any manual changes made to this file will be lost when pyuic5 is
# run again.  Do not edit this file unless you know what you are doing.


from PyQt5 import QtCore, QtGui, QtWidgets


class Ui_WdgMasternodeDetails(object):
    def setupUi(self, WdgMasternodeDetails):
        WdgMasternodeDetails.setObjectName("WdgMasternodeDetails")
        WdgMasternodeDetails.resize(700, 471)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(WdgMasternodeDetails.sizePolicy().hasHeightForWidth())
        WdgMasternodeDetails.setSizePolicy(sizePolicy)
        WdgMasternodeDetails.setMinimumSize(QtCore.QSize(700, 0))
        WdgMasternodeDetails.setStyleSheet("")
        self.verticalLayout_2 = QtWidgets.QVBoxLayout(WdgMasternodeDetails)
        self.verticalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.verticalLayout_2.setSpacing(0)
        self.verticalLayout_2.setObjectName("verticalLayout_2")
        self.widget_2 = QtWidgets.QWidget(WdgMasternodeDetails)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.widget_2.sizePolicy().hasHeightForWidth())
        self.widget_2.setSizePolicy(sizePolicy)
        self.widget_2.setObjectName("widget_2")
        self.verticalLayout = QtWidgets.QVBoxLayout(self.widget_2)
        self.verticalLayout.setContentsMargins(0, 0, 0, 0)
        self.verticalLayout.setSpacing(6)
        self.verticalLayout.setObjectName("verticalLayout")
        self.horizontalLayout_12 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_12.setObjectName("horizontalLayout_12")
        self.lblUserRole = QtWidgets.QLabel(self.widget_2)
        self.lblUserRole.setMinimumSize(QtCore.QSize(170, 0))
        self.lblUserRole.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.lblUserRole.setObjectName("lblUserRole")
        self.horizontalLayout_12.addWidget(self.lblUserRole)
        self.chbRoleOwner = QtWidgets.QCheckBox(self.widget_2)
        self.chbRoleOwner.setChecked(True)
        self.chbRoleOwner.setObjectName("chbRoleOwner")
        self.horizontalLayout_12.addWidget(self.chbRoleOwner)
        self.chbRoleOperator = QtWidgets.QCheckBox(self.widget_2)
        self.chbRoleOperator.setChecked(True)
        self.chbRoleOperator.setObjectName("chbRoleOperator")
        self.horizontalLayout_12.addWidget(self.chbRoleOperator)
        self.chbRoleVoting = QtWidgets.QCheckBox(self.widget_2)
        self.chbRoleVoting.setChecked(True)
        self.chbRoleVoting.setObjectName("chbRoleVoting")
        self.horizontalLayout_12.addWidget(self.chbRoleVoting)
        spacerItem = QtWidgets.QSpacerItem(40, 0, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout_12.addItem(spacerItem)
        self.verticalLayout.addLayout(self.horizontalLayout_12)
        self.horizontalLayout_2 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_2.setObjectName("horizontalLayout_2")
        self.lblName = QtWidgets.QLabel(self.widget_2)
        self.lblName.setMinimumSize(QtCore.QSize(170, 0))
        self.lblName.setLayoutDirection(QtCore.Qt.LeftToRight)
        self.lblName.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.lblName.setObjectName("lblName")
        self.horizontalLayout_2.addWidget(self.lblName)
        self.edtName = QtWidgets.QLineEdit(self.widget_2)
        self.edtName.setObjectName("edtName")
        self.horizontalLayout_2.addWidget(self.edtName)
        self.verticalLayout.addLayout(self.horizontalLayout_2)
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.lblMasternodeType = QtWidgets.QLabel(self.widget_2)
        self.lblMasternodeType.setMinimumSize(QtCore.QSize(170, 0))
        self.lblMasternodeType.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.lblMasternodeType.setObjectName("lblMasternodeType")
        self.horizontalLayout.addWidget(self.lblMasternodeType)
        self.rbMNTypeRegular = QtWidgets.QRadioButton(self.widget_2)
        self.rbMNTypeRegular.setChecked(True)
        self.rbMNTypeRegular.setObjectName("rbMNTypeRegular")
        self.horizontalLayout.addWidget(self.rbMNTypeRegular)
        self.rbMNTypeEvo = QtWidgets.QRadioButton(self.widget_2)
        self.rbMNTypeEvo.setObjectName("rbMNTypeEvo")
        self.horizontalLayout.addWidget(self.rbMNTypeEvo)
        spacerItem1 = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout.addItem(spacerItem1)
        self.verticalLayout.addLayout(self.horizontalLayout)
        self.horizontalLayout_3 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_3.setObjectName("horizontalLayout_3")
        self.lblIP = QtWidgets.QLabel(self.widget_2)
        self.lblIP.setMinimumSize(QtCore.QSize(170, 0))
        self.lblIP.setLayoutDirection(QtCore.Qt.LeftToRight)
        self.lblIP.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.lblIP.setObjectName("lblIP")
        self.horizontalLayout_3.addWidget(self.lblIP)
        self.edtIP = QtWidgets.QLineEdit(self.widget_2)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.edtIP.sizePolicy().hasHeightForWidth())
        self.edtIP.setSizePolicy(sizePolicy)
        self.edtIP.setMinimumSize(QtCore.QSize(170, 0))
        self.edtIP.setClearButtonEnabled(True)
        self.edtIP.setObjectName("edtIP")
        self.horizontalLayout_3.addWidget(self.edtIP)
        self.lblPort = QtWidgets.QLabel(self.widget_2)
        self.lblPort.setObjectName("lblPort")
        self.horizontalLayout_3.addWidget(self.lblPort)
        self.edtPort = QtWidgets.QLineEdit(self.widget_2)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.edtPort.sizePolicy().hasHeightForWidth())
        self.edtPort.setSizePolicy(sizePolicy)
        self.edtPort.setMaximumSize(QtCore.QSize(150, 16777215))
        self.edtPort.setClearButtonEnabled(True)
        self.edtPort.setObjectName("edtPort")
        self.horizontalLayout_3.addWidget(self.edtPort)
        self.btnGetMNDataByIP = QtWidgets.QToolButton(self.widget_2)
        self.btnGetMNDataByIP.setMaximumSize(QtCore.QSize(16777215, 16777215))
        self.btnGetMNDataByIP.setObjectName("btnGetMNDataByIP")
        self.horizontalLayout_3.addWidget(self.btnGetMNDataByIP)
        spacerItem2 = QtWidgets.QSpacerItem(0, 0, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout_3.addItem(spacerItem2)
        self.horizontalLayout_3.setStretch(1, 1)
        self.verticalLayout.addLayout(self.horizontalLayout_3)
        self.horizontalLayout_5 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_5.setObjectName("horizontalLayout_5")
        self.lblCollateral = QtWidgets.QLabel(self.widget_2)
        self.lblCollateral.setMinimumSize(QtCore.QSize(170, 0))
        self.lblCollateral.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.lblCollateral.setObjectName("lblCollateral")
        self.horizontalLayout_5.addWidget(self.lblCollateral)
        self.edtCollateralAddress = QtWidgets.QLineEdit(self.widget_2)
        self.edtCollateralAddress.setClearButtonEnabled(True)
        self.edtCollateralAddress.setObjectName("edtCollateralAddress")
        self.horizontalLayout_5.addWidget(self.edtCollateralAddress)
        self.btnLocateCollateral = QtWidgets.QToolButton(self.widget_2)
        self.btnLocateCollateral.setMaximumSize(QtCore.QSize(16777215, 16777215))
        self.btnLocateCollateral.setObjectName("btnLocateCollateral")
        self.horizontalLayout_5.addWidget(self.btnLocateCollateral)
        self.btnBip32PathToAddress = QtWidgets.QToolButton(self.widget_2)
        self.btnBip32PathToAddress.setObjectName("btnBip32PathToAddress")
        self.horizontalLayout_5.addWidget(self.btnBip32PathToAddress)
        self.lblCollateralPath = QtWidgets.QLabel(self.widget_2)
        self.lblCollateralPath.setObjectName("lblCollateralPath")
        self.horizontalLayout_5.addWidget(self.lblCollateralPath)
        self.edtCollateralPath = QtWidgets.QLineEdit(self.widget_2)
        self.edtCollateralPath.setMaximumSize(QtCore.QSize(16777215, 16777215))
        self.edtCollateralPath.setClearButtonEnabled(True)
        self.edtCollateralPath.setObjectName("edtCollateralPath")
        self.horizontalLayout_5.addWidget(self.edtCollateralPath)
        self.btnShowCollateralPathAddress = QtWidgets.QToolButton(self.widget_2)
        self.btnShowCollateralPathAddress.setMaximumSize(QtCore.QSize(16777215, 21))
        self.btnShowCollateralPathAddress.setText("")
        self.btnShowCollateralPathAddress.setObjectName("btnShowCollateralPathAddress")
        self.horizontalLayout_5.addWidget(self.btnShowCollateralPathAddress)
        self.horizontalLayout_5.setStretch(1, 2)
        self.horizontalLayout_5.setStretch(5, 1)
        self.verticalLayout.addLayout(self.horizontalLayout_5)
        self.horizontalLayout_6 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_6.setObjectName("horizontalLayout_6")
        self.lblCollateralTxHash = QtWidgets.QLabel(self.widget_2)
        self.lblCollateralTxHash.setMinimumSize(QtCore.QSize(170, 0))
        self.lblCollateralTxHash.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.lblCollateralTxHash.setObjectName("lblCollateralTxHash")
        self.horizontalLayout_6.addWidget(self.lblCollateralTxHash)
        self.edtCollateralTxHash = QtWidgets.QLineEdit(self.widget_2)
        self.edtCollateralTxHash.setClearButtonEnabled(True)
        self.edtCollateralTxHash.setObjectName("edtCollateralTxHash")
        self.horizontalLayout_6.addWidget(self.edtCollateralTxHash)
        self.lblCollateralTxIndex = QtWidgets.QLabel(self.widget_2)
        self.lblCollateralTxIndex.setObjectName("lblCollateralTxIndex")
        self.horizontalLayout_6.addWidget(self.lblCollateralTxIndex)
        self.edtCollateralTxIndex = QtWidgets.QLineEdit(self.widget_2)
        self.edtCollateralTxIndex.setMaximumSize(QtCore.QSize(50, 16777215))
        self.edtCollateralTxIndex.setObjectName("edtCollateralTxIndex")
        self.horizontalLayout_6.addWidget(self.edtCollateralTxIndex)
        self.verticalLayout.addLayout(self.horizontalLayout_6)
        self.horizontalLayout_10 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_10.setObjectName("horizontalLayout_10")
        self.lblDMNTxHash = QtWidgets.QLabel(self.widget_2)
        self.lblDMNTxHash.setMinimumSize(QtCore.QSize(170, 0))
        self.lblDMNTxHash.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.lblDMNTxHash.setObjectName("lblDMNTxHash")
        self.horizontalLayout_10.addWidget(self.lblDMNTxHash)
        self.edtDMNTxHash = QtWidgets.QLineEdit(self.widget_2)
        self.edtDMNTxHash.setClearButtonEnabled(True)
        self.edtDMNTxHash.setObjectName("edtDMNTxHash")
        self.horizontalLayout_10.addWidget(self.edtDMNTxHash)
        self.btnCopyProtxHash = QtWidgets.QToolButton(self.widget_2)
        self.btnCopyProtxHash.setMaximumSize(QtCore.QSize(16777215, 21))
        self.btnCopyProtxHash.setText("")
        self.btnCopyProtxHash.setObjectName("btnCopyProtxHash")
        self.horizontalLayout_10.addWidget(self.btnCopyProtxHash)
        self.verticalLayout.addLayout(self.horizontalLayout_10)
        self.horizontalLayout_7 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_7.setObjectName("horizontalLayout_7")
        self.lblOwnerKey = QtWidgets.QLabel(self.widget_2)
        self.lblOwnerKey.setMinimumSize(QtCore.QSize(170, 0))
        self.lblOwnerKey.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.lblOwnerKey.setObjectName("lblOwnerKey")
        self.horizontalLayout_7.addWidget(self.lblOwnerKey)
        self.verticalLayout_6 = QtWidgets.QVBoxLayout()
        self.verticalLayout_6.setObjectName("verticalLayout_6")
        self.horizontalLayout_16 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_16.setObjectName("horizontalLayout_16")
        self.edtOwnerKey = QtWidgets.QLineEdit(self.widget_2)
        self.edtOwnerKey.setEchoMode(QtWidgets.QLineEdit.Password)
        self.edtOwnerKey.setClearButtonEnabled(True)
        self.edtOwnerKey.setObjectName("edtOwnerKey")
        self.horizontalLayout_16.addWidget(self.edtOwnerKey)
        self.btnCopyOwnerKey = QtWidgets.QToolButton(self.widget_2)
        self.btnCopyOwnerKey.setMaximumSize(QtCore.QSize(16777215, 21))
        self.btnCopyOwnerKey.setText("")
        self.btnCopyOwnerKey.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.btnCopyOwnerKey.setObjectName("btnCopyOwnerKey")
        self.horizontalLayout_16.addWidget(self.btnCopyOwnerKey)
        self.btnShowOwnerPrivateKey = QtWidgets.QToolButton(self.widget_2)
        self.btnShowOwnerPrivateKey.setMaximumSize(QtCore.QSize(16777215, 21))
        self.btnShowOwnerPrivateKey.setText("")
        self.btnShowOwnerPrivateKey.setCheckable(True)
        self.btnShowOwnerPrivateKey.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        self.btnShowOwnerPrivateKey.setObjectName("btnShowOwnerPrivateKey")
        self.horizontalLayout_16.addWidget(self.btnShowOwnerPrivateKey)
        self.btnGenerateOwnerPrivateKey = QtWidgets.QToolButton(self.widget_2)
        self.btnGenerateOwnerPrivateKey.setMaximumSize(QtCore.QSize(16777215, 16777215))
        self.btnGenerateOwnerPrivateKey.setObjectName("btnGenerateOwnerPrivateKey")
        self.horizontalLayout_16.addWidget(self.btnGenerateOwnerPrivateKey)
        self.verticalLayout_6.addLayout(self.horizontalLayout_16)
        self.lblOwnerKeyMsg = QtWidgets.QLabel(self.widget_2)
        self.lblOwnerKeyMsg.setObjectName("lblOwnerKeyMsg")
        self.verticalLayout_6.addWidget(self.lblOwnerKeyMsg)
        self.horizontalLayout_7.addLayout(self.verticalLayout_6)
        self.verticalLayout.addLayout(self.horizontalLayout_7)
        self.horizontalLayout_8 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_8.setObjectName("horizontalLayout_8")
        self.lblOperatorKey = QtWidgets.QLabel(self.widget_2)
        self.lblOperatorKey.setMinimumSize(QtCore.QSize(170, 0))
        self.lblOperatorKey.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.lblOperatorKey.setObjectName("lblOperatorKey")
        self.horizontalLayout_8.addWidget(self.lblOperatorKey)
        self.verticalLayout_5 = QtWidgets.QVBoxLayout()
        self.verticalLayout_5.setObjectName("verticalLayout_5")
        self.horizontalLayout_15 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_15.setObjectName("horizontalLayout_15")
        self.edtOperatorKey = QtWidgets.QLineEdit(self.widget_2)
        self.edtOperatorKey.setEchoMode(QtWidgets.QLineEdit.Password)
        self.edtOperatorKey.setClearButtonEnabled(True)
        self.edtOperatorKey.setObjectName("edtOperatorKey")
        self.horizontalLayout_15.addWidget(self.edtOperatorKey)
        self.btnCopyOperatorKey = QtWidgets.QToolButton(self.widget_2)
        self.btnCopyOperatorKey.setMaximumSize(QtCore.QSize(16777215, 21))
        self.btnCopyOperatorKey.setText("")
        self.btnCopyOperatorKey.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.btnCopyOperatorKey.setObjectName("btnCopyOperatorKey")
        self.horizontalLayout_15.addWidget(self.btnCopyOperatorKey)
        self.btnShowOperatorPrivateKey = QtWidgets.QToolButton(self.widget_2)
        self.btnShowOperatorPrivateKey.setMaximumSize(QtCore.QSize(16777215, 21))
        self.btnShowOperatorPrivateKey.setText("")
        self.btnShowOperatorPrivateKey.setCheckable(True)
        self.btnShowOperatorPrivateKey.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        self.btnShowOperatorPrivateKey.setObjectName("btnShowOperatorPrivateKey")
        self.horizontalLayout_15.addWidget(self.btnShowOperatorPrivateKey)
        self.btnGenerateOperatorPrivateKey = QtWidgets.QToolButton(self.widget_2)
        self.btnGenerateOperatorPrivateKey.setMaximumSize(QtCore.QSize(16777215, 16777215))
        self.btnGenerateOperatorPrivateKey.setObjectName("btnGenerateOperatorPrivateKey")
        self.horizontalLayout_15.addWidget(self.btnGenerateOperatorPrivateKey)
        self.verticalLayout_5.addLayout(self.horizontalLayout_15)
        self.lblOperatorKeyMsg = QtWidgets.QLabel(self.widget_2)
        self.lblOperatorKeyMsg.setObjectName("lblOperatorKeyMsg")
        self.verticalLayout_5.addWidget(self.lblOperatorKeyMsg)
        self.horizontalLayout_8.addLayout(self.verticalLayout_5)
        self.verticalLayout.addLayout(self.horizontalLayout_8)
        self.horizontalLayout_9 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_9.setObjectName("horizontalLayout_9")
        self.lblVotingKey = QtWidgets.QLabel(self.widget_2)
        self.lblVotingKey.setMinimumSize(QtCore.QSize(170, 0))
        self.lblVotingKey.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.lblVotingKey.setObjectName("lblVotingKey")
        self.horizontalLayout_9.addWidget(self.lblVotingKey)
        self.verticalLayout_4 = QtWidgets.QVBoxLayout()
        self.verticalLayout_4.setObjectName("verticalLayout_4")
        self.horizontalLayout_14 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_14.setObjectName("horizontalLayout_14")
        self.edtVotingKey = QtWidgets.QLineEdit(self.widget_2)
        self.edtVotingKey.setEchoMode(QtWidgets.QLineEdit.Password)
        self.edtVotingKey.setClearButtonEnabled(True)
        self.edtVotingKey.setObjectName("edtVotingKey")
        self.horizontalLayout_14.addWidget(self.edtVotingKey)
        self.btnCopyVotingKey = QtWidgets.QToolButton(self.widget_2)
        self.btnCopyVotingKey.setMaximumSize(QtCore.QSize(16777215, 21))
        self.btnCopyVotingKey.setText("")
        self.btnCopyVotingKey.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.btnCopyVotingKey.setObjectName("btnCopyVotingKey")
        self.horizontalLayout_14.addWidget(self.btnCopyVotingKey)
        self.btnShowVotingPrivateKey = QtWidgets.QToolButton(self.widget_2)
        self.btnShowVotingPrivateKey.setMaximumSize(QtCore.QSize(16777215, 21))
        self.btnShowVotingPrivateKey.setText("")
        self.btnShowVotingPrivateKey.setCheckable(True)
        self.btnShowVotingPrivateKey.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        self.btnShowVotingPrivateKey.setObjectName("btnShowVotingPrivateKey")
        self.horizontalLayout_14.addWidget(self.btnShowVotingPrivateKey)
        self.btnGenerateVotingPrivateKey = QtWidgets.QToolButton(self.widget_2)
        self.btnGenerateVotingPrivateKey.setMaximumSize(QtCore.QSize(16777215, 16777215))
        self.btnGenerateVotingPrivateKey.setObjectName("btnGenerateVotingPrivateKey")
        self.horizontalLayout_14.addWidget(self.btnGenerateVotingPrivateKey)
        self.verticalLayout_4.addLayout(self.horizontalLayout_14)
        self.lblVotingKeyMsg = QtWidgets.QLabel(self.widget_2)
        self.lblVotingKeyMsg.setObjectName("lblVotingKeyMsg")
        self.verticalLayout_4.addWidget(self.lblVotingKeyMsg)
        self.horizontalLayout_9.addLayout(self.verticalLayout_4)
        self.verticalLayout.addLayout(self.horizontalLayout_9)
        self.horizontalLayout_11 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_11.setObjectName("horizontalLayout_11")
        self.lblPlatformNodeKey = QtWidgets.QLabel(self.widget_2)
        self.lblPlatformNodeKey.setMinimumSize(QtCore.QSize(170, 0))
        self.lblPlatformNodeKey.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.lblPlatformNodeKey.setObjectName("lblPlatformNodeKey")
        self.horizontalLayout_11.addWidget(self.lblPlatformNodeKey)
        self.verticalLayout_3 = QtWidgets.QVBoxLayout()
        self.verticalLayout_3.setObjectName("verticalLayout_3")
        self.horizontalLayout_4 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_4.setObjectName("horizontalLayout_4")
        self.edtPlatformNodeKey = QtWidgets.QLineEdit(self.widget_2)
        self.edtPlatformNodeKey.setEchoMode(QtWidgets.QLineEdit.Normal)
        self.edtPlatformNodeKey.setClearButtonEnabled(True)
        self.edtPlatformNodeKey.setObjectName("edtPlatformNodeKey")
        self.horizontalLayout_4.addWidget(self.edtPlatformNodeKey)
        self.btnCopyPlatformNodeKey = QtWidgets.QToolButton(self.widget_2)
        self.btnCopyPlatformNodeKey.setMaximumSize(QtCore.QSize(16777215, 21))
        self.btnCopyPlatformNodeKey.setText("")
        self.btnCopyPlatformNodeKey.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.btnCopyPlatformNodeKey.setObjectName("btnCopyPlatformNodeKey")
        self.horizontalLayout_4.addWidget(self.btnCopyPlatformNodeKey)
        self.btnShowPlatformNodeKey = QtWidgets.QToolButton(self.widget_2)
        self.btnShowPlatformNodeKey.setMaximumSize(QtCore.QSize(16777215, 21))
        self.btnShowPlatformNodeKey.setText("")
        self.btnShowPlatformNodeKey.setCheckable(True)
        self.btnShowPlatformNodeKey.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        self.btnShowPlatformNodeKey.setObjectName("btnShowPlatformNodeKey")
        self.horizontalLayout_4.addWidget(self.btnShowPlatformNodeKey)
        self.btnGeneratePlatformNodePrivateKey = QtWidgets.QToolButton(self.widget_2)
        self.btnGeneratePlatformNodePrivateKey.setMaximumSize(QtCore.QSize(16777215, 16777215))
        self.btnGeneratePlatformNodePrivateKey.setObjectName("btnGeneratePlatformNodePrivateKey")
        self.horizontalLayout_4.addWidget(self.btnGeneratePlatformNodePrivateKey)
        self.verticalLayout_3.addLayout(self.horizontalLayout_4)
        self.lblPlatformNodeMsg = QtWidgets.QLabel(self.widget_2)
        self.lblPlatformNodeMsg.setObjectName("lblPlatformNodeMsg")
        self.verticalLayout_3.addWidget(self.lblPlatformNodeMsg)
        self.horizontalLayout_11.addLayout(self.verticalLayout_3)
        self.verticalLayout.addLayout(self.horizontalLayout_11)
        self.horizontalLayout_13 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_13.setObjectName("horizontalLayout_13")
        self.lblPlatformP2PPort = QtWidgets.QLabel(self.widget_2)
        self.lblPlatformP2PPort.setMinimumSize(QtCore.QSize(170, 0))
        self.lblPlatformP2PPort.setAlignment(QtCore.Qt.AlignRight|QtCore.Qt.AlignTrailing|QtCore.Qt.AlignVCenter)
        self.lblPlatformP2PPort.setObjectName("lblPlatformP2PPort")
        self.horizontalLayout_13.addWidget(self.lblPlatformP2PPort)
        self.edtPlatformP2PPort = QtWidgets.QLineEdit(self.widget_2)
        self.edtPlatformP2PPort.setMaximumSize(QtCore.QSize(100, 16777215))
        self.edtPlatformP2PPort.setClearButtonEnabled(True)
        self.edtPlatformP2PPort.setObjectName("edtPlatformP2PPort")
        self.horizontalLayout_13.addWidget(self.edtPlatformP2PPort)
        self.btnPlatformP2PPortSetDefault = QtWidgets.QToolButton(self.widget_2)
        self.btnPlatformP2PPortSetDefault.setMaximumSize(QtCore.QSize(16777215, 21))
        self.btnPlatformP2PPortSetDefault.setText("")
        self.btnPlatformP2PPortSetDefault.setObjectName("btnPlatformP2PPortSetDefault")
        self.horizontalLayout_13.addWidget(self.btnPlatformP2PPortSetDefault)
        self.lblPlatformHTTPPort = QtWidgets.QLabel(self.widget_2)
        self.lblPlatformHTTPPort.setObjectName("lblPlatformHTTPPort")
        self.horizontalLayout_13.addWidget(self.lblPlatformHTTPPort)
        self.edtPlatformHTTPPort = QtWidgets.QLineEdit(self.widget_2)
        self.edtPlatformHTTPPort.setMaximumSize(QtCore.QSize(100, 16777215))
        self.edtPlatformHTTPPort.setClearButtonEnabled(True)
        self.edtPlatformHTTPPort.setObjectName("edtPlatformHTTPPort")
        self.horizontalLayout_13.addWidget(self.edtPlatformHTTPPort)
        self.btnPlatformHTTPPortSetDefault = QtWidgets.QToolButton(self.widget_2)
        self.btnPlatformHTTPPortSetDefault.setMaximumSize(QtCore.QSize(16777215, 21))
        self.btnPlatformHTTPPortSetDefault.setText("")
        self.btnPlatformHTTPPortSetDefault.setObjectName("btnPlatformHTTPPortSetDefault")
        self.horizontalLayout_13.addWidget(self.btnPlatformHTTPPortSetDefault)
        spacerItem3 = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout_13.addItem(spacerItem3)
        self.verticalLayout.addLayout(self.horizontalLayout_13)
        self.verticalLayout_2.addWidget(self.widget_2)

        self.retranslateUi(WdgMasternodeDetails)
        QtCore.QMetaObject.connectSlotsByName(WdgMasternodeDetails)
        WdgMasternodeDetails.setTabOrder(self.edtName, self.edtIP)
        WdgMasternodeDetails.setTabOrder(self.edtIP, self.edtPort)
        WdgMasternodeDetails.setTabOrder(self.edtPort, self.edtCollateralAddress)
        WdgMasternodeDetails.setTabOrder(self.edtCollateralAddress, self.edtCollateralPath)
        WdgMasternodeDetails.setTabOrder(self.edtCollateralPath, self.edtCollateralTxHash)
        WdgMasternodeDetails.setTabOrder(self.edtCollateralTxHash, self.edtCollateralTxIndex)
        WdgMasternodeDetails.setTabOrder(self.edtCollateralTxIndex, self.edtDMNTxHash)
        WdgMasternodeDetails.setTabOrder(self.edtDMNTxHash, self.chbRoleOwner)
        WdgMasternodeDetails.setTabOrder(self.chbRoleOwner, self.chbRoleOperator)
        WdgMasternodeDetails.setTabOrder(self.chbRoleOperator, self.chbRoleVoting)

    def retranslateUi(self, WdgMasternodeDetails):
        _translate = QtCore.QCoreApplication.translate
        WdgMasternodeDetails.setWindowTitle(_translate("WdgMasternodeDetails", "Form"))
        self.lblUserRole.setText(_translate("WdgMasternodeDetails", "User role"))
        self.chbRoleOwner.setText(_translate("WdgMasternodeDetails", "Owner"))
        self.chbRoleOperator.setText(_translate("WdgMasternodeDetails", "Operator"))
        self.chbRoleVoting.setText(_translate("WdgMasternodeDetails", "Voting"))
        self.lblName.setText(_translate("WdgMasternodeDetails", "Name"))
        self.lblMasternodeType.setText(_translate("WdgMasternodeDetails", "Masternode type"))
        self.rbMNTypeRegular.setText(_translate("WdgMasternodeDetails", "Regular (1000 Dash)"))
        self.rbMNTypeEvo.setText(_translate("WdgMasternodeDetails", "Evolution (4000 Dash)"))
        self.lblIP.setText(_translate("WdgMasternodeDetails", "IP"))
        self.lblPort.setText(_translate("WdgMasternodeDetails", "port"))
        self.btnGetMNDataByIP.setToolTip(_translate("WdgMasternodeDetails", "Fetch public masternode data from network"))
        self.btnGetMNDataByIP.setText(_translate("WdgMasternodeDetails", "Fetch MN data"))
        self.lblCollateral.setText(_translate("WdgMasternodeDetails", "Collateral address"))
        self.btnLocateCollateral.setToolTip(_translate("WdgMasternodeDetails", "Search collateral address in your hardware wallet"))
        self.btnLocateCollateral.setText(_translate("WdgMasternodeDetails", "Locate collateral"))
        self.btnBip32PathToAddress.setToolTip(_translate("WdgMasternodeDetails", "Convert BIP32 path to address"))
        self.btnBip32PathToAddress.setText(_translate("WdgMasternodeDetails", "<<"))
        self.lblCollateralPath.setText(_translate("WdgMasternodeDetails", "path"))
        self.btnShowCollateralPathAddress.setToolTip(_translate("WdgMasternodeDetails", "Show Dash address for the entered BIP32 path"))
        self.lblCollateralTxHash.setText(_translate("WdgMasternodeDetails", "Collateral TX hash"))
        self.lblCollateralTxIndex.setText(_translate("WdgMasternodeDetails", "index"))
        self.lblDMNTxHash.setText(_translate("WdgMasternodeDetails", "Protx hash"))
        self.btnCopyProtxHash.setToolTip(_translate("WdgMasternodeDetails", "Copy protx hash to clipboard"))
        self.lblOwnerKey.setText(_translate("WdgMasternodeDetails", "Owner private key"))
        self.btnCopyOwnerKey.setToolTip(_translate("WdgMasternodeDetails", "Copy key to clipboard"))
        self.btnShowOwnerPrivateKey.setToolTip(_translate("WdgMasternodeDetails", "Show/hide private key"))
        self.btnGenerateOwnerPrivateKey.setToolTip(_translate("WdgMasternodeDetails", "Generate a new owner private key"))
        self.btnGenerateOwnerPrivateKey.setText(_translate("WdgMasternodeDetails", "Generate new"))
        self.lblOwnerKeyMsg.setText(_translate("WdgMasternodeDetails", "..."))
        self.lblOperatorKey.setText(_translate("WdgMasternodeDetails", "Operator private key"))
        self.btnCopyOperatorKey.setToolTip(_translate("WdgMasternodeDetails", "Copy key to clipboard"))
        self.btnShowOperatorPrivateKey.setToolTip(_translate("WdgMasternodeDetails", "Show/hide private key"))
        self.btnGenerateOperatorPrivateKey.setToolTip(_translate("WdgMasternodeDetails", "Generate a new operator private key (BLS)"))
        self.btnGenerateOperatorPrivateKey.setText(_translate("WdgMasternodeDetails", "Generate new"))
        self.lblOperatorKeyMsg.setText(_translate("WdgMasternodeDetails", "..."))
        self.lblVotingKey.setText(_translate("WdgMasternodeDetails", "Voting private key"))
        self.btnCopyVotingKey.setToolTip(_translate("WdgMasternodeDetails", "Copy key to clipboard"))
        self.btnShowVotingPrivateKey.setToolTip(_translate("WdgMasternodeDetails", "Show/hide private key"))
        self.btnGenerateVotingPrivateKey.setToolTip(_translate("WdgMasternodeDetails", "Generate a new voting private key"))
        self.btnGenerateVotingPrivateKey.setText(_translate("WdgMasternodeDetails", "Generate new"))
        self.lblVotingKeyMsg.setText(_translate("WdgMasternodeDetails", "..."))
        self.lblPlatformNodeKey.setText(_translate("WdgMasternodeDetails", "Platform Node key"))
        self.btnCopyPlatformNodeKey.setToolTip(_translate("WdgMasternodeDetails", "Copy Platform Node ID to clipboard"))
        self.btnGeneratePlatformNodePrivateKey.setToolTip(_translate("WdgMasternodeDetails", "Generate a new Platform Node key (Ed25519 private key)"))
        self.btnGeneratePlatformNodePrivateKey.setText(_translate("WdgMasternodeDetails", "Generate new"))
        self.lblPlatformNodeMsg.setText(_translate("WdgMasternodeDetails", "..."))
        self.lblPlatformP2PPort.setText(_translate("WdgMasternodeDetails", "Platform P2P port"))
        self.btnPlatformP2PPortSetDefault.setToolTip(_translate("WdgMasternodeDetails", "Set default value for Platform P2P port"))
        self.lblPlatformHTTPPort.setText(_translate("WdgMasternodeDetails", "Platform HTTP port"))
        self.btnPlatformHTTPPortSetDefault.setToolTip(_translate("WdgMasternodeDetails", "Set default value for Platform HTTP port"))
