# -*- mode: python -*-
import sys
import os

block_cipher = None

lib_path = os.path.join(os.path.dirname(os.path.realpath('__file__')), 'venv3\\Lib\\site-packages')
qt5_path = os.path.join(lib_path, 'PyQt5\\Qt\\bin')

sys.path.append(qt5_path)
add_files = [
 (os.path.join(lib_path, 'bitcoin/english.txt'),'/bitcoin'),
 ('img/dash-logo.png','/img'),
 ('img/dmt.png','/img'),
 ('img/dmt.ico','/img'),
 ('img/arrow-right.ico','/img'),
 ('img/hw-lock.ico','/img'),
 ('img/hw-test.ico','/img'),
 ('version.txt', '')
]

# add file vcruntime140.dll manually, due to not including by pyinstaller
found = False
for p in os.environ["PATH"].split(os.pathsep):
    file_name = os.path.join(p, "vcruntime140.dll")
    if os.path.exists(file_name):
        found = True
        add_files.append((file_name, ''))
        print('Adding file ' + file_name)
        break
if not found:
    raise Exception('File vcruntime140.dll not found in the system path.')

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
          upx=False,
          console=False,
		  icon='img\\dmt.ico' )

