# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file ui_app_main_view_wdg.ui
#
# Created by: PyQt5 UI code generator
#
# WARNING: Any manual changes made to this file will be lost when pyuic5 is
# run again.  Do not edit this file unless you know what you are doing.


from PyQt5 import QtCore, QtGui, QtWidgets


class Ui_WdgAppMainView(object):
    def setupUi(self, WdgAppMainView):
        WdgAppMainView.setObjectName("WdgAppMainView")
        WdgAppMainView.resize(840, 460)
        self.verticalLayout_6 = QtWidgets.QVBoxLayout(WdgAppMainView)
        self.verticalLayout_6.setContentsMargins(0, 0, 0, 0)
        self.verticalLayout_6.setSpacing(6)
        self.verticalLayout_6.setObjectName("verticalLayout_6")
        self.pnlNavigation = QtWidgets.QFrame(WdgAppMainView)
        self.pnlNavigation.setStyleSheet("QLabel#lblNavigation1, QLabel#lblNavigation2, QLabel#lblNavigation3 {\n"
"  padding: 2px;\n"
"  border: 1px solid lightgray;\n"
"  border-radius: 2px;\n"
"  background-color: lightgray;\n"
"}")
        self.pnlNavigation.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.pnlNavigation.setFrameShadow(QtWidgets.QFrame.Raised)
        self.pnlNavigation.setObjectName("pnlNavigation")
        self.horizontalLayout = QtWidgets.QHBoxLayout(self.pnlNavigation)
        self.horizontalLayout.setContentsMargins(0, 0, 0, 0)
        self.horizontalLayout.setSpacing(4)
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.lblNavigation1 = QtWidgets.QLabel(self.pnlNavigation)
        self.lblNavigation1.setStyleSheet("")
        self.lblNavigation1.setText("")
        self.lblNavigation1.setOpenExternalLinks(False)
        self.lblNavigation1.setObjectName("lblNavigation1")
        self.horizontalLayout.addWidget(self.lblNavigation1)
        self.lblNavigation2 = QtWidgets.QLabel(self.pnlNavigation)
        self.lblNavigation2.setStyleSheet("")
        self.lblNavigation2.setText("")
        self.lblNavigation2.setOpenExternalLinks(False)
        self.lblNavigation2.setObjectName("lblNavigation2")
        self.horizontalLayout.addWidget(self.lblNavigation2)
        self.lblNavigation3 = QtWidgets.QLabel(self.pnlNavigation)
        self.lblNavigation3.setStyleSheet("")
        self.lblNavigation3.setText("")
        self.lblNavigation3.setObjectName("lblNavigation3")
        self.horizontalLayout.addWidget(self.lblNavigation3)
        spacerItem = QtWidgets.QSpacerItem(20, 20, QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout.addItem(spacerItem)
        self.btnRefreshMnStatus = QtWidgets.QPushButton(self.pnlNavigation)
        self.btnRefreshMnStatus.setObjectName("btnRefreshMnStatus")
        self.horizontalLayout.addWidget(self.btnRefreshMnStatus)
        self.btnMnActions = QtWidgets.QPushButton(self.pnlNavigation)
        self.btnMnActions.setObjectName("btnMnActions")
        self.horizontalLayout.addWidget(self.btnMnActions)
        self.btnMnListColumns = QtWidgets.QPushButton(self.pnlNavigation)
        self.btnMnListColumns.setObjectName("btnMnListColumns")
        self.horizontalLayout.addWidget(self.btnMnListColumns)
        self.btnMoveMnUp = QtWidgets.QPushButton(self.pnlNavigation)
        self.btnMoveMnUp.setMaximumSize(QtCore.QSize(40, 16777215))
        self.btnMoveMnUp.setText("")
        self.btnMoveMnUp.setObjectName("btnMoveMnUp")
        self.horizontalLayout.addWidget(self.btnMoveMnUp)
        self.btnMoveMnDown = QtWidgets.QPushButton(self.pnlNavigation)
        self.btnMoveMnDown.setMaximumSize(QtCore.QSize(40, 16777215))
        self.btnMoveMnDown.setText("")
        self.btnMoveMnDown.setObjectName("btnMoveMnDown")
        self.horizontalLayout.addWidget(self.btnMoveMnDown)
        self.lblMnListMessage = QtWidgets.QLabel(self.pnlNavigation)
        self.lblMnListMessage.setText("")
        self.lblMnListMessage.setObjectName("lblMnListMessage")
        self.horizontalLayout.addWidget(self.lblMnListMessage)
        spacerItem1 = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout.addItem(spacerItem1)
        self.verticalLayout_6.addWidget(self.pnlNavigation)
        self.frmMain = QtWidgets.QFrame(WdgAppMainView)
        self.frmMain.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.frmMain.setFrameShadow(QtWidgets.QFrame.Raised)
        self.frmMain.setObjectName("frmMain")
        self.verticalLayout = QtWidgets.QVBoxLayout(self.frmMain)
        self.verticalLayout.setContentsMargins(6, 6, 6, 6)
        self.verticalLayout.setSpacing(6)
        self.verticalLayout.setObjectName("verticalLayout")
        self.stackedWidget = QtWidgets.QStackedWidget(self.frmMain)
        self.stackedWidget.setObjectName("stackedWidget")
        self.pageNetworkInfo = QtWidgets.QWidget()
        self.pageNetworkInfo.setObjectName("pageNetworkInfo")
        self.verticalLayout_5 = QtWidgets.QVBoxLayout(self.pageNetworkInfo)
        self.verticalLayout_5.setContentsMargins(0, 0, 0, 0)
        self.verticalLayout_5.setSpacing(6)
        self.verticalLayout_5.setObjectName("verticalLayout_5")
        self.lblNetworkInfo = QtWidgets.QLabel(self.pageNetworkInfo)
        self.lblNetworkInfo.setText("")
        self.lblNetworkInfo.setTextInteractionFlags(QtCore.Qt.LinksAccessibleByMouse|QtCore.Qt.TextSelectableByMouse)
        self.lblNetworkInfo.setObjectName("lblNetworkInfo")
        self.verticalLayout_5.addWidget(self.lblNetworkInfo)
        spacerItem2 = QtWidgets.QSpacerItem(20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout_5.addItem(spacerItem2)
        self.stackedWidget.addWidget(self.pageNetworkInfo)
        self.pageMasternodeList = QtWidgets.QWidget()
        self.pageMasternodeList.setObjectName("pageMasternodeList")
        self.verticalLayout_4 = QtWidgets.QVBoxLayout(self.pageMasternodeList)
        self.verticalLayout_4.setContentsMargins(0, 0, 0, 0)
        self.verticalLayout_4.setSpacing(6)
        self.verticalLayout_4.setObjectName("verticalLayout_4")
        self.viewMasternodes = QtWidgets.QTableView(self.pageMasternodeList)
        self.viewMasternodes.setEditTriggers(QtWidgets.QAbstractItemView.AnyKeyPressed|QtWidgets.QAbstractItemView.EditKeyPressed)
        self.viewMasternodes.setProperty("showDropIndicator", False)
        self.viewMasternodes.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.viewMasternodes.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.viewMasternodes.setShowGrid(False)
        self.viewMasternodes.setObjectName("viewMasternodes")
        self.viewMasternodes.verticalHeader().setVisible(False)
        self.viewMasternodes.verticalHeader().setSortIndicatorShown(False)
        self.verticalLayout_4.addWidget(self.viewMasternodes)
        self.lblNoMasternodeMessage = QtWidgets.QLabel(self.pageMasternodeList)
        self.lblNoMasternodeMessage.setStyleSheet("QLabel{\n"
"  margin-top: 10px;\n"
"}")
        self.lblNoMasternodeMessage.setText("")
        self.lblNoMasternodeMessage.setAlignment(QtCore.Qt.AlignLeading|QtCore.Qt.AlignLeft|QtCore.Qt.AlignTop)
        self.lblNoMasternodeMessage.setObjectName("lblNoMasternodeMessage")
        self.verticalLayout_4.addWidget(self.lblNoMasternodeMessage)
        self.stackedWidget.addWidget(self.pageMasternodeList)
        self.pageSingleMasternode = QtWidgets.QWidget()
        self.pageSingleMasternode.setObjectName("pageSingleMasternode")
        self.verticalLayout_3 = QtWidgets.QVBoxLayout(self.pageSingleMasternode)
        self.verticalLayout_3.setContentsMargins(0, 0, 0, 0)
        self.verticalLayout_3.setSpacing(6)
        self.verticalLayout_3.setObjectName("verticalLayout_3")
        self.frmMasternodeDetails = QtWidgets.QFrame(self.pageSingleMasternode)
        self.frmMasternodeDetails.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.frmMasternodeDetails.setFrameShadow(QtWidgets.QFrame.Plain)
        self.frmMasternodeDetails.setObjectName("frmMasternodeDetails")
        self.verticalLayout_2 = QtWidgets.QVBoxLayout(self.frmMasternodeDetails)
        self.verticalLayout_2.setContentsMargins(0, 0, 0, 0)
        self.verticalLayout_2.setSpacing(6)
        self.verticalLayout_2.setObjectName("verticalLayout_2")
        self.layMasternodesControl = QtWidgets.QHBoxLayout()
        self.layMasternodesControl.setContentsMargins(0, 0, 0, 0)
        self.layMasternodesControl.setSpacing(3)
        self.layMasternodesControl.setObjectName("layMasternodesControl")
        self.btnEditMn = QtWidgets.QPushButton(self.frmMasternodeDetails)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.btnEditMn.sizePolicy().hasHeightForWidth())
        self.btnEditMn.setSizePolicy(sizePolicy)
        self.btnEditMn.setMaximumSize(QtCore.QSize(16777215, 16777215))
        self.btnEditMn.setFocusPolicy(QtCore.Qt.NoFocus)
        self.btnEditMn.setObjectName("btnEditMn")
        self.layMasternodesControl.addWidget(self.btnEditMn)
        self.btnCancelEditingMn = QtWidgets.QPushButton(self.frmMasternodeDetails)
        self.btnCancelEditingMn.setFocusPolicy(QtCore.Qt.NoFocus)
        self.btnCancelEditingMn.setObjectName("btnCancelEditingMn")
        self.layMasternodesControl.addWidget(self.btnCancelEditingMn)
        self.btnApplyMnChanges = QtWidgets.QPushButton(self.frmMasternodeDetails)
        self.btnApplyMnChanges.setFocusPolicy(QtCore.Qt.NoFocus)
        self.btnApplyMnChanges.setObjectName("btnApplyMnChanges")
        self.layMasternodesControl.addWidget(self.btnApplyMnChanges)
        spacerItem3 = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.layMasternodesControl.addItem(spacerItem3)
        self.verticalLayout_2.addLayout(self.layMasternodesControl)
        spacerItem4 = QtWidgets.QSpacerItem(20, 353, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        self.verticalLayout_2.addItem(spacerItem4)
        self.verticalLayout_3.addWidget(self.frmMasternodeDetails)
        self.stackedWidget.addWidget(self.pageSingleMasternode)
        self.verticalLayout.addWidget(self.stackedWidget)
        self.verticalLayout_6.addWidget(self.frmMain)
        self.lblMnStatusLabel = QtWidgets.QLabel(WdgAppMainView)
        self.lblMnStatusLabel.setObjectName("lblMnStatusLabel")
        self.verticalLayout_6.addWidget(self.lblMnStatusLabel)
        self.lblMnStatus = QtWidgets.QLabel(WdgAppMainView)
        self.lblMnStatus.setStyleSheet("")
        self.lblMnStatus.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.lblMnStatus.setFrameShadow(QtWidgets.QFrame.Sunken)
        self.lblMnStatus.setText("")
        self.lblMnStatus.setWordWrap(False)
        self.lblMnStatus.setOpenExternalLinks(False)
        self.lblMnStatus.setTextInteractionFlags(QtCore.Qt.LinksAccessibleByMouse|QtCore.Qt.TextSelectableByMouse)
        self.lblMnStatus.setObjectName("lblMnStatus")
        self.verticalLayout_6.addWidget(self.lblMnStatus)

        self.retranslateUi(WdgAppMainView)
        self.stackedWidget.setCurrentIndex(1)
        QtCore.QMetaObject.connectSlotsByName(WdgAppMainView)

    def retranslateUi(self, WdgAppMainView):
        _translate = QtCore.QCoreApplication.translate
        WdgAppMainView.setWindowTitle(_translate("WdgAppMainView", "Form"))
        self.btnRefreshMnStatus.setText(_translate("WdgAppMainView", "Refresh status"))
        self.btnMnActions.setText(_translate("WdgAppMainView", "MN actions"))
        self.btnMnListColumns.setText(_translate("WdgAppMainView", "Columns..."))
        self.btnMoveMnUp.setToolTip(_translate("WdgAppMainView", "Move up the selected masternode entry"))
        self.btnMoveMnDown.setToolTip(_translate("WdgAppMainView", "Move down the selected masternode entry"))
        self.btnEditMn.setToolTip(_translate("WdgAppMainView", "Edit masternode details"))
        self.btnEditMn.setText(_translate("WdgAppMainView", "Edit"))
        self.btnCancelEditingMn.setText(_translate("WdgAppMainView", "Cancel changes"))
        self.btnApplyMnChanges.setText(_translate("WdgAppMainView", "Apply changes"))
        self.lblMnStatusLabel.setText(_translate("WdgAppMainView", "Status details:"))