# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for AFV Tracker
# Run from the repo root:  pyinstaller AFV_Tracker.spec --clean
#
# The compiled exe is self-contained:
#   - GUI + tray launcher (default mode)
#   - Embedded FastAPI/uvicorn server (spawned as subprocess with --server-mode)

block_cipher = None

a = Analysis(
    ['client/launcher.py'],
    pathex=['client'],          # lets PyInstaller resolve local imports (gui, config, …)
    binaries=[
        # SimConnect.dll is loaded via __file__ path inside SimConnect.py.
        # PyInstaller doesn't detect it automatically from hiddenimports —
        # it must be explicitly placed in the SimConnect/ sub-directory so
        # the path `<_MEIPASS>/SimConnect/SimConnect.dll` resolves correctly.
        ('.venv/Lib/site-packages/SimConnect/SimConnect.dll', 'SimConnect'),
    ],
    datas=[
        # Bundle the entire server package so the frozen exe can run it
        ('server/*.py',          'server'),
        ('server/routes/*.py',   'server/routes'),
    ],
    hiddenimports=[
        # uvicorn internals (not auto-detected)
        'uvicorn.lifespan.on',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        # SQLAlchemy dialects
        'sqlalchemy.dialects.mysql',
        'sqlalchemy.dialects.mysql.pymysql',
        'sqlalchemy.dialects.postgresql',
        'sqlalchemy.dialects.postgresql.psycopg2',
        # DB drivers
        'pymysql',
        'psycopg2',
        # Networking / API
        'websockets',
        'pydantic',
        'pydantic.deprecated.class_validators',
        'pydantic_core',
        # Sim / Windows
        'SimConnect',
        'win32api',
        'win32con',
        'winsound',
        'winreg',
        # Tray / process
        'psutil',
        'pystray',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # onedir mode — no _MEI* temp extraction on every launch
    name='AFV Tracker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,          # no console window; server subprocess uses CREATE_NO_WINDOW
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AFV Tracker',
)
