# -*- mode: python -*-
import sys
import os

block_cipher = None

lib_path = os.path.join(os.path.dirname(os.path.realpath('__file__')), 'venv3/lib/python3.5/site-packages')

add_files = [
 (os.path.join(lib_path, 'bitcoin/english.txt'),'/bitcoin'),
 ('img/dash-logo.png','/img'),
 ('img/dmt.png','/img'),
 ('img/dash.ico','/img'),
 ('img/dmt.ico','/img'),
 ('img/arrow-right.ico','/img'),
 ('img/hw-lock.ico','/img'),
 ('img/hw-test.ico','/img'),
 ('version.txt', '')
]

a = Analysis(['dash_masternode_tool.py'],
             pathex=[os.path.dirname(os.path.realpath('__file__'))],
             binaries=[],
             datas=add_files,
             hiddenimports=[],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher)

pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)

exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          name='DashMasternodeTool',
          debug=False,
          strip=False,
          upx=True,
          console=False,
		  icon='img/dmt.icns' )

app = BUNDLE(exe,
             name='DashMasternodeTool.app',
             icon='img/dmt.icns',
             bundle_identifier=None)
