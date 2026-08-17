# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for UIATools - UI Automation Element Inspector
Build with: pyinstaller UIATools.spec
"""

import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Collect all submodules for packages with dynamic imports
hiddenimports = [
    # uiautomation hidden imports
    'uiautomation',
    'uiautomation.uiautomation',
    
    # pywinauto hidden imports
    'pywinauto',
    'pywinauto.controls',
    'pywinauto.controls.uiawrapper',
    'pywinauto.controls.uia_controls',
    'pywinauto.findwindows',
    'pywinauto.uia_defines',
    'pywinauto.uia_element_info',
    
    # comtypes for COM interface
    'comtypes',
    'comtypes.client',
    'comtypes.gen',
    
    # win32 modules
    'win32api',
    'win32con',
    'win32gui',
    'win32ui',
    'pywintypes',
    
    # tkinter
    'tkinter',
    'tkinter.ttk',
    'tkinter.messagebox',
    'tkinter.filedialog',
    'tkinter.simpledialog',
    
    # PIL
    'PIL',
    'PIL.Image',
    'PIL.ImageGrab',

    # Screen repository + AI script generation
    'sqlite3',
    'litellm',
    'tiktoken',
    'tiktoken_ext',
    'tiktoken_ext.openai_public',
    'keyring',
    'keyring.backends',
    'keyring.backends.Windows',

    # Standard library that may be needed
    'ctypes',
    'ctypes.wintypes',
    'json',
    'dataclasses',
    'typing',
    'enum',
    'threading',
    'queue',
    'time',
    'os',
    'sys',
]

# Add all submodules from key packages
hiddenimports += collect_submodules('comtypes')
hiddenimports += collect_submodules('pywinauto')

# litellm ships JSON data files (model costs, tokenizers) it loads at runtime
datas = []
try:
    datas += collect_data_files('litellm')
except Exception:
    pass

a = Analysis(
    ['src/main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'pytest',
        'IPython',
        'jupyter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# One-dir build: the launcher exe stays small (~2-4 MB, well under the 32 MB
# CrowdStrike certificate-extraction limit) and all libraries live next to it
# in dist/UIATools/_internal/. UPX disabled - packed exes trigger AV heuristics.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='UIATools',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # No console window - this is a GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=False,  # Set to True if you always need admin rights
    icon=None,  # Add icon path here if you have one: icon='assets/icon.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='UIATools',
)
